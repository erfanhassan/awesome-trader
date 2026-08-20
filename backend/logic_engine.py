import datetime
import math
import pandas as pd
import asyncio
import json
import os
import uuid
import numpy as np
from deepseek_client import DeepSeekClient
from google_sheets_client import GoogleSheetsClient
from hmm_engine import HMMEngine
from risk_engine import RiskEngine

class LogicEngine:
    def __init__(self):
        # symbol -> { "1m": [...], "4h": [...], "1d": [...] }
        self.kline_data = {}
        self.active_strategies = [
            {"name": "S11_Fixed_Pct_TP", "leverage": 50, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False, "fixed_tp_pct": True},
            {"name": "S12_NoSL_MarginBoost", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False, "fixed_tp_pct": True, "no_sl": True, "auto_margin": True, "max_margin_adds": 1},
            {"name": "S13_EMA_Cross_Scalp", "leverage": 25, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False, "fixed_tp_pct": True, "ema_cross": True}
        ]

        # symbol -> state dict
        self.market_state = {}
        # symbol -> current minute trade metrics
        self.trade_data = {}
        # Individual filter toggles
        self.filter_killzone = False
        self.filter_htf = False
        self.filter_volume = False
        self.filter_pressure = False
        self.shihab_active = False
        self.shihab_demo_active = False
        self.demo_balance = 100.0
        self.demo_invest_amount = 10.0
        self.demo_leverage = 10
        self.demo_positions = []
        self.mexc_client = None
        self.deepseek = DeepSeekClient()
        self.sheets_client = GoogleSheetsClient()
        self.hmm_engine = HMMEngine()
        self.risk_engine = RiskEngine()
        self.signals = []
        self.signal_history = []
        self.last_hmm_train_time = 0
        self.HMM_RETRAIN_INTERVAL = 900
        self._load_history()

    def _load_history(self):
        try:
            if os.path.exists("trade_history.json"):
                with open("trade_history.json", "r") as f:
                    self.signal_history = json.load(f)
        except Exception as e:
            print(f"Error loading history: {e}")

    def _save_history(self):
        try:
            with open("trade_history.json", "w") as f:
                json.dump(self.signal_history, f, indent=2)
        except Exception as e:
            print(f"Error saving history: {e}")

    def clear_history(self):
        self.signal_history = []
        self._save_history()

    def get_state(self):
        # We also need to evaluate killzone dynamically
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        hour = now_utc.hour
        in_london = 7 <= hour < 10
        in_ny = 13 <= hour < 16
        in_killzone = in_london or in_ny

        return {
            "killzone_active": in_killzone,
            "filter_killzone": self.filter_killzone,
            "filter_htf": self.filter_htf,
            "filter_volume": self.filter_volume,
            "filter_pressure": self.filter_pressure,
            "shihab_active": self.shihab_active,
            "shihab_demo_active": self.shihab_demo_active,
            "demo_state": {
                "balance": self.demo_balance,
                "invest_amount": self.demo_invest_amount,
                "leverage": self.demo_leverage,
                "positions": self.demo_positions
            },
            "market_data": self.market_state,
            "trade_data": self.trade_data,
            "signal_history": self.signal_history,
        }

    def get_klines(self, symbol, interval):
        """Return kline data for a specific symbol and interval, formatted for frontend charts."""
        candles = self.kline_data.get(symbol, {}).get(interval, [])
        return [
            {
                "time": int(c["t"] / 1000) if c["t"] > 1e12 else int(c["t"]),
                "open": c["o"],
                "high": c["h"],
                "low": c["l"],
                "close": c["c"],
                "volume": c["v"],
            }
            for c in candles
        ]

    def get_and_clear_signals(self):
        sigs = self.signals[:]
        self.signals.clear()
        return sigs

    async def add_symbol(self, symbol):
        if symbol not in self.kline_data:
            self.kline_data[symbol] = {"Min1": [], "Min15": [], "Min60": [], "Hour4": [], "Day1": []}
            self.market_state[symbol] = {
                "price": 0,
                "1d_high": 0,
                "1d_low": 0,
                "1m_bullish": False,
                "15m_bullish": False,
                "1h_bullish": False,
                "4h_bullish": False,
                "1d_bullish": False,
                "setup_state": "WAITING", # WAITING, SWEPT_HIGH, SWEPT_LOW, SHORT_SETUP_FORMED, LONG_SETUP_FORMED, TRADED_HIGH, TRADED_LOW
                "setup_candle": None,
                "target_tp": 0.0,
                "htf_ok": False,
                "vol_ok": False,
                # Fix 5: 4H session sweep levels (primary, updated every 4h)
                "4h_session_high": 0,
                "4h_session_low": 0,
                "sweep_is_premium": False,  # True if sweep also hits 1D level
                # Fix 8: 15m swing structure pivots
                "15m_swing_high": 0,
                "15m_swing_low": 0,
                # Fix 7: Live funding rate from MEXC
                "funding_rate": 0.0001,
                # Fix 6: Daily volatility flag
                "high_volatility_day": False,
                # Fix 2: Intrabar signal deduplication
                "intrabar_signal_taken": False,
                "last_seen_candle_t": None,
                # Fix 9: Session precision
                "in_prime_session": False,
                "in_any_session": False,
                "swept_level_cooldown": {},
                "ema_cross_signal_taken": False,
            }
            self.trade_data[symbol] = {
                "buy_vol": 0.0,
                "sell_vol": 0.0,
                "delta": 0.0,
                "cvd": 0.0,
                "pressure_direction": "NEUTRAL",
                "last_minute": None
            }

    async def remove_symbol(self, symbol):
        if symbol in self.kline_data:
            del self.kline_data[symbol]
        if symbol in self.market_state:
            del self.market_state[symbol]
        if symbol in self.trade_data:
            del self.trade_data[symbol]

    async def process_trades(self, symbol, trades):
        if symbol not in self.trade_data:
            await self.add_symbol(symbol)
            
        td = self.trade_data[symbol]
        
        for trade in trades:
            # trade time in ms
            t = trade.get("time", 0)
            # Find the start of the current minute in ms
            minute_ms = t - (t % 60000)
            
            # Reset minute accumulator if a new minute started
            if td["last_minute"] != minute_ms:
                if "delta_history" not in td:
                    td["delta_history"] = []
                td["delta_history"].append(td.get("delta", 0.0))
                if len(td["delta_history"]) > 3:
                    td["delta_history"].pop(0)
                    
                td["buy_vol"] = 0.0
                td["sell_vol"] = 0.0
                td["delta"] = 0.0
                td["last_minute"] = minute_ms
                
            qty = float(trade.get("qty", 0))
            # isBuyerMaker: true means seller is taker (SELL VOLUME), false means buyer is taker (BUY VOLUME)
            is_buyer_maker = trade.get("isBuyerMaker", False)
            
            if is_buyer_maker:
                td["sell_vol"] += qty
                td["cvd"] -= qty
            else:
                td["buy_vol"] += qty
                td["cvd"] += qty
                
        # Calculate Delta and Pressure Direction
        td["delta"] = td["buy_vol"] - td["sell_vol"]
        if td["delta"] > 0:
            td["pressure_direction"] = "BUYING_CONTROL"
        elif td["delta"] < 0:
            td["pressure_direction"] = "SELLING_CONTROL"
        else:
            td["pressure_direction"] = "NEUTRAL"

    async def process_kline(self, symbol, interval, data, is_historical=False):
        if symbol not in self.kline_data:
            if hasattr(self, "mexc_client") and self.mexc_client:
                await self.mexc_client.add_symbol(symbol)
            else:
                await self.add_symbol(symbol)

        # Process Demo Positions and Signal History against 1-minute live price ticks only
        if interval == "Min1" and not is_historical:
            closed_positions = []
            for pos in self.demo_positions:
                if pos["symbol"] != symbol:
                    continue
                
                hit_tp = False
                hit_sl = False
                hit_liq = False
                exit_price = 0.0
                
                config = pos.get("config", {})
                hit_time = False
                
                if config.get("time_exit"):
                    entry_time = datetime.datetime.fromisoformat(pos["timestamp"])
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if (now - entry_time).total_seconds() >= 900:
                        hit_time = True
                        exit_price = data["c"]
                
                if config.get("cross_margin"):
                    size = (pos["margin"] * pos["leverage"]) / pos["entry"]
                    if pos["direction"] == "LONG":
                        liq_price = pos["entry"] - (self.demo_balance / size) if size > 0 else 0
                    else:
                        liq_price = pos["entry"] + (self.demo_balance / size) if size > 0 else float('inf')
                else:
                    initial_margin = pos.get("initial_margin", pos.get("margin", 5.0))
                    total_margin = pos.get("margin", 5.0)
                    size = (initial_margin * pos.get("leverage", 50)) / pos["entry"]
                    
                    if pos["direction"] == "LONG":
                        liq_price = pos["entry"] - (total_margin / size) if size > 0 else 0
                    else:
                        liq_price = pos["entry"] + (total_margin / size) if size > 0 else float('inf')
                        
                    if config.get("auto_margin") and pos.get("margin_adds", 0) < config.get("max_margin_adds", 3):
                        liq_buffer = 0.0005
                        needs_margin = False
                        if pos["direction"] == "LONG" and data["l"] <= liq_price * (1 + liq_buffer):
                            needs_margin = True
                        elif pos["direction"] == "SHORT" and data["h"] >= liq_price * (1 - liq_buffer):
                            needs_margin = True
                            
                        if needs_margin and self.demo_balance >= initial_margin:
                            pos["margin"] += initial_margin
                            pos["margin_adds"] = pos.get("margin_adds", 0) + 1
                            print(f"[{symbol}] AUTO MARGIN BOOST! Added ${initial_margin:.2f} (Total adds: {pos['margin_adds']})")
                            total_margin = pos["margin"]
                            if pos["direction"] == "LONG":
                                liq_price = pos["entry"] - (total_margin / size) if size > 0 else 0
                            else:
                                liq_price = pos["entry"] + (total_margin / size) if size > 0 else float('inf')
                
                if pos["direction"] == "LONG":
                    if config.get("scale_out") and not pos.get("scaled_out") and data["h"] >= pos.get("tp1", pos["tp"]):
                        pos["scaled_out"] = True
                        pos["sl"] = pos["entry"]
                    
                    if not hit_time:
                        if data["h"] >= pos["tp"]:
                            hit_tp = True
                            exit_price = pos["tp"]
                        elif data["l"] <= pos["sl"]:
                            hit_sl = True
                            exit_price = pos["sl"]
                        elif data["l"] <= liq_price:
                            hit_liq = True
                            exit_price = liq_price
                else: # SHORT
                    if config.get("scale_out") and not pos.get("scaled_out") and data["l"] <= pos.get("tp1", pos["tp"]):
                        pos["scaled_out"] = True
                        pos["sl"] = pos["entry"]
                        
                    if not hit_time:
                        if data["l"] <= pos["tp"]:
                            hit_tp = True
                            exit_price = pos["tp"]
                        elif data["h"] >= pos["sl"]:
                            hit_sl = True
                            exit_price = pos["sl"]
                        elif data["h"] >= liq_price:
                            hit_liq = True
                            exit_price = liq_price
                
                bayesian_bailout = False
                if not (hit_tp or hit_sl or hit_liq or hit_time):
                    stats = self.risk_engine.calculate_historical_stats(self.signal_history, pos["strategy"], pos["direction"])
                    current_delta = self.trade_data.get(symbol, {}).get("delta", 0)
                    delta_history = self.trade_data.get(symbol, {}).get("delta_history", [])
                    all_deltas = delta_history + [current_delta]
                    rolling_delta = sum(all_deltas) / len(all_deltas) if all_deltas else 0
                    
                    avg_delta = 50000.0 # Standardize volume scale
                    posterior_prob = self.risk_engine.calculate_live_bayesian_update(stats["win_rate"], rolling_delta, avg_delta, pos["direction"])
                    live_ev = self.risk_engine.calculate_ev(posterior_prob, stats["avg_win"], stats["avg_loss"])
                    if live_ev < 0:
                        bayesian_bailout = True
                        exit_price = data["c"]
                        print(f"[{symbol}] DEMO BAYESIAN BAILOUT! Live EV {live_ev:.4f} < 0")
                        
                if hit_liq or hit_tp or hit_sl or hit_time or bayesian_bailout:
                    if hit_liq:
                        pnl = -pos["margin"]
                    else:
                        size = (pos["margin"] * pos["leverage"]) / pos["entry"]
                        if pos["direction"] == "LONG":
                            price_diff = exit_price - pos["entry"]
                        else:
                            price_diff = pos["entry"] - exit_price
                            
                        gross_pnl = price_diff * size
                        
                        # Apply scale-out math if applicable
                        if pos.get("scaled_out"):
                            if hit_tp:
                                pnl = gross_pnl * 0.75 # (0.5R + 1.0R) / 2R = 0.75 of original gross TP profit
                            elif hit_sl:
                                # SL was at entry, exit_price = entry, gross_pnl = 0
                                # But we already took 0.5R at TP1
                                original_risk_amount = size * abs(pos["entry"] - (pos["entry"] - pos["entry"]*0.001)) # approximated buffer
                                pnl = gross_pnl + (original_risk_amount * 0.5) # simplify to just flat PnL math
                                # Actually, better: if hit_sl and scaled_out, price_diff is 0, but we secured half profit
                                # The profit taken was 50% size * distance to TP1
                                tp1_dist = abs(pos["entry"] - pos.get("tp1", pos["entry"]))
                                pnl = (size * 0.5) * tp1_dist
                            else:
                                pnl = gross_pnl
                        else:
                            pnl = gross_pnl
                    
                    self.demo_balance += pnl
                    closed_positions.append(pos)
                    print(f"DEMO TRADE CLOSED: {symbol} {pos['direction']} - PnL: ${pnl:.2f} (Balance: ${self.demo_balance:.2f})")
                    
            # Remove closed positions
            self.demo_positions = [p for p in self.demo_positions if p not in closed_positions]
            
            # Process Signal History for pending trades
            history_updated = False
            for hist_pos in self.signal_history:
                if hist_pos["status"] != "PENDING" or hist_pos["symbol"] != symbol:
                    continue
                    
                # Update Max Drawdown Price live
                if "max_drawdown_price" not in hist_pos:
                    hist_pos["max_drawdown_price"] = hist_pos["entry"]
                    
                if hist_pos["direction"] == "LONG":
                    hist_pos["max_drawdown_price"] = min(hist_pos["max_drawdown_price"], data["l"])
                else: # SHORT
                    hist_pos["max_drawdown_price"] = max(hist_pos["max_drawdown_price"], data["h"])
                    
                hit_tp = False
                hit_sl = False
                hit_liq = False
                exit_price = 0.0
                
                config = hist_pos.get("config", {})
                hit_time = False
                
                if config.get("time_exit"):
                    entry_time = datetime.datetime.fromisoformat(hist_pos["timestamp"])
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if (now - entry_time).total_seconds() >= 900:
                        hit_time = True
                        exit_price = data["c"]
                        
                if config.get("cross_margin"):
                    # For signal history simulation, assume a virtual $1000 balance to avoid early liquidation
                    virtual_balance = 1000.0
                    margin = 5.0
                    config_lev = config.get("leverage", 400)
                    leverage = float(hist_pos.get("computed_leverage", config_lev if config_lev != "auto" else 400))
                    size = (margin * leverage) / hist_pos["entry"]
                    
                    if hist_pos["direction"] == "LONG":
                        liq_price = hist_pos["entry"] - (virtual_balance / size) if size > 0 else 0
                    else:
                        liq_price = hist_pos["entry"] + (virtual_balance / size) if size > 0 else float('inf')
                else:
                    config_lev = config.get("leverage", 400)
                    leverage = float(hist_pos.get("computed_leverage", config_lev if config_lev != "auto" else 400))
                    initial_margin = hist_pos.get("initial_margin", hist_pos.get("margin", 5.0))
                    total_margin = hist_pos.get("margin", 5.0)
                    size = (initial_margin * leverage) / hist_pos["entry"]
                    
                    if hist_pos["direction"] == "LONG":
                        liq_price = hist_pos["entry"] - (total_margin / size) if size > 0 else 0
                    else:
                        liq_price = hist_pos["entry"] + (total_margin / size) if size > 0 else float('inf')
                        
                    if config.get("auto_margin") and hist_pos.get("margin_adds", 0) < config.get("max_margin_adds", 3):
                        liq_buffer = 0.0005
                        needs_margin = False
                        if hist_pos["direction"] == "LONG" and data["l"] <= liq_price * (1 + liq_buffer):
                            needs_margin = True
                        elif hist_pos["direction"] == "SHORT" and data["h"] >= liq_price * (1 - liq_buffer):
                            needs_margin = True
                            
                        if needs_margin:
                            hist_pos["margin"] = total_margin + initial_margin
                            hist_pos["margin_adds"] = hist_pos.get("margin_adds", 0) + 1
                            total_margin = hist_pos["margin"]
                            if hist_pos["direction"] == "LONG":
                                liq_price = hist_pos["entry"] - (total_margin / size) if size > 0 else 0
                            else:
                                liq_price = hist_pos["entry"] + (total_margin / size) if size > 0 else float('inf')
                
                if hist_pos["direction"] == "LONG":
                    if config.get("scale_out") and not hist_pos.get("scaled_out") and data["h"] >= hist_pos.get("tp1", hist_pos["tp"]):
                        hist_pos["scaled_out"] = True
                        hist_pos["sl"] = hist_pos["entry"]
                        
                    if not hit_time:
                        if data["h"] >= hist_pos["tp"]:
                            hit_tp = True
                            exit_price = hist_pos["tp"]
                        elif data["l"] <= hist_pos["sl"]:
                            hit_sl = True
                            exit_price = hist_pos["sl"]
                        elif data["l"] <= liq_price:
                            hit_liq = True
                            exit_price = liq_price
                else: # SHORT
                    if config.get("scale_out") and not hist_pos.get("scaled_out") and data["l"] <= hist_pos.get("tp1", hist_pos["tp"]):
                        hist_pos["scaled_out"] = True
                        hist_pos["sl"] = hist_pos["entry"]
                        
                    if not hit_time:
                        if data["l"] <= hist_pos["tp"]:
                            hit_tp = True
                            exit_price = hist_pos["tp"]
                        elif data["h"] >= hist_pos["sl"]:
                            hit_sl = True
                            exit_price = hist_pos["sl"]
                        elif data["h"] >= liq_price:
                            hit_liq = True
                            exit_price = liq_price
                        
                bayesian_bailout = False
                if not (hit_tp or hit_sl or hit_liq or hit_time):
                    stats = self.risk_engine.calculate_historical_stats(self.signal_history, hist_pos["strategy"], hist_pos["direction"])
                    current_delta = self.trade_data.get(symbol, {}).get("delta", 0)
                    delta_history = self.trade_data.get(symbol, {}).get("delta_history", [])
                    all_deltas = delta_history + [current_delta]
                    rolling_delta = sum(all_deltas) / len(all_deltas) if all_deltas else 0
                    
                    avg_delta = 50000.0
                    posterior_prob = self.risk_engine.calculate_live_bayesian_update(stats["win_rate"], rolling_delta, avg_delta, hist_pos["direction"])
                    live_ev = self.risk_engine.calculate_ev(posterior_prob, stats["avg_win"], stats["avg_loss"])
                    if live_ev < 0:
                        bayesian_bailout = True
                        exit_price = data["c"]
                        print(f"[{symbol}] HISTORY BAYESIAN BAILOUT! Live EV {live_ev:.4f} < 0")
                        
                if hit_liq or hit_tp or hit_sl or hit_time or bayesian_bailout:
                    # Read margin/leverage from strategy config (fallback to defaults)
                    config = hist_pos.get("config", {})
                    margin = 5.0
                    config_lev = config.get("leverage", 400)
                    leverage = float(hist_pos.get("computed_leverage", config_lev if config_lev != "auto" else 400))
                    pos_size = margin * leverage
                    
                    # Fees: 0.02% entry, 0.02% exit
                    fee_pct = 0.0002
                    fees_amount = pos_size * fee_pct * 2
                    
                    # Slippage: Estimated at 0.01% of pos size per trade (entry + exit)
                    slippage_pct = 0.0001
                    slippage_amount = pos_size * slippage_pct * 2
                    
                    # Real-Time Funding Rate from MEXC
                    try:
                        entry_time = datetime.datetime.fromisoformat(hist_pos["timestamp"])
                        exit_time = datetime.datetime.now(datetime.timezone.utc)
                        hours_held = (exit_time - entry_time).total_seconds() / 3600.0
                        funding_intervals = max(0, hours_held / 8.0)
                        
                        real_funding_rate = 0.0001
                        if hasattr(self, "mexc_client") and self.mexc_client:
                            real_funding_rate = await self.mexc_client.get_funding_rate(symbol)
                            
                        # If you are long, you pay if rate is positive.
                        # If you are short, you receive if rate is positive (pay if negative).
                        funding_cost_pct = real_funding_rate * funding_intervals
                        if hist_pos["direction"] == "LONG":
                            funding_rate_amount = pos_size * funding_cost_pct
                        else:
                            funding_rate_amount = pos_size * (-funding_cost_pct)
                        
                        duration_secs = (exit_time - entry_time).total_seconds()
                        duration_mins = duration_secs / 60.0
                        if duration_mins < 60:
                            duration_str = f"{int(duration_mins)} mins"
                        elif duration_mins < 1440:
                            duration_str = f"{duration_mins / 60:.1f} hrs"
                        else:
                            duration_str = f"{duration_mins / 1440:.1f} days"
                    except Exception as e:
                        funding_rate_amount = 0.0
                        duration_str = "0 mins"
                        
                    # Calculate Max Drawdown in USD
                    if "max_drawdown_price" not in hist_pos:
                        hist_pos["max_drawdown_price"] = hist_pos["entry"]
                        
                    if hist_pos["direction"] == "LONG":
                        dd_pct = (hist_pos["entry"] - hist_pos["max_drawdown_price"]) / hist_pos["entry"]
                    else:
                        dd_pct = (hist_pos["max_drawdown_price"] - hist_pos["entry"]) / hist_pos["entry"]
                        
                    dd_pct = max(0.0, dd_pct) # avoid negative drawdown
                    max_drawdown_usd = pos_size * dd_pct
                    max_drawdown_str = f"-${max_drawdown_usd:.2f}"
                        
                    if hist_pos["direction"] == "LONG":
                        price_diff_pct = (exit_price - hist_pos["entry"]) / hist_pos["entry"]
                        pnl_pct = price_diff_pct * 100
                    else:
                        price_diff_pct = (hist_pos["entry"] - exit_price) / hist_pos["entry"]
                        pnl_pct = price_diff_pct * 100
                        
                    gross_pnl = pos_size * price_diff_pct
                    
                    if hist_pos.get("scaled_out"):
                        if hit_tp:
                            gross_pnl = gross_pnl * 0.75 # 0.5R + 1.0R
                        elif hit_sl:
                            # SL is BE. price_diff is 0, but we made 0.5R
                            tp1_dist_pct = abs(hist_pos.get("tp1", hist_pos["entry"]) - hist_pos["entry"]) / hist_pos["entry"]
                            gross_pnl = pos_size * tp1_dist_pct * 0.5
                            pnl_pct = tp1_dist_pct * 50 # adjust visual %
                            
                    if hit_liq:
                        hist_pos["status"] = "LIQUIDATED"
                        net_profit = -margin
                        hist_pos["close_reason"] = "Liquidated"
                    elif hit_tp:
                        hist_pos["status"] = "PROFIT"
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount
                        hist_pos["close_reason"] = "Take Profit"
                    elif hit_time:
                        hist_pos["status"] = "PROFIT" if gross_pnl > 0 else "LOSS"
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount
                        hist_pos["close_reason"] = "Time Exit"
                    elif bayesian_bailout:
                        hist_pos["status"] = "PROFIT" if gross_pnl > 0 else "LOSS"
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount
                        hist_pos["close_reason"] = "Bayesian Bailout"
                    else:
                        hist_pos["status"] = "PROFIT" if gross_pnl > 0 else "LOSS" # SL could be BE (profit)
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount
                        hist_pos["close_reason"] = "Stop Loss"
                        
                    hist_pos["raw_profit"] = round(gross_pnl, 4)
                        
                    hist_pos["net_profit"] = round(net_profit, 4)
                    hist_pos["pnl"] = round(pnl_pct, 4)
                    hist_pos["exit_price"] = exit_price
                    hist_pos["close_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    hist_pos["slippage"] = round(slippage_amount, 4)
                    hist_pos["fees"] = round(fees_amount, 4)
                    hist_pos["funding_rate"] = round(funding_rate_amount, 4)
                    hist_pos["net_profit"] = round(net_profit, 4)
                    hist_pos["duration"] = duration_str
                    hist_pos["max_drawdown"] = max_drawdown_str
                    
                    
                    import asyncio
                    import copy
                    asyncio.create_task(asyncio.to_thread(self.sheets_client.update_trade, copy.deepcopy(hist_pos)))
                    history_updated = True
                    
            if history_updated:
                self._save_history()

        # Keep lists bounded
        max_len = 1000
        
        if interval in self.kline_data[symbol]:
            history = self.kline_data[symbol][interval]
            
            # Update last candle if same timestamp, else append
            if history and history[-1]["t"] == data["t"]:
                history[-1] = data
                if interval == "Min1":
                    self.market_state[symbol]["price"] = data["c"]
                    self._evaluate_ema(symbol, interval)
                    await self._evaluate_1m_logic(symbol, data, is_historical)
            else:
                # New candle arrived: mark the previous one as closed
                if history:
                    history[-1]["is_closed"] = True
                    if interval == "Min1":
                        await self._evaluate_1m_logic(symbol, history[-1], is_historical)
                        
                history.append(data)
                if len(history) > max_len:
                    history.pop(0)

                # Evaluate new candle
                if interval == "Min1":
                    self.market_state[symbol]["price"] = data["c"]
                    self._evaluate_ema(symbol, interval)
                    await self._evaluate_1m_logic(symbol, data, is_historical)

            if interval in ["Min15", "Min60", "Hour4", "Day1"]:
                self._evaluate_ema(symbol, interval)

            # For 1D, update high and low of the *previous* completed day. 
            if interval == "Day1" and len(history) > 1:
                prev_day = history[-2]
                self.market_state[symbol]["1d_high"] = prev_day["h"]
                self.market_state[symbol]["1d_low"] = prev_day["l"]

    def _evaluate_ema(self, symbol, interval):
        history = self.kline_data[symbol].get(interval, [])
        if not history:
            return

        if len(history) >= 50:
            ema20 = history[0]["c"]
            ema50 = history[0]["c"]
            k20 = 2 / (20 + 1)
            k50 = 2 / (50 + 1)
            
            for c in history[1:]:
                price = c["c"]
                ema20 = (price * k20) + (ema20 * (1 - k20))
                ema50 = (price * k50) + (ema50 * (1 - k50))
                
            last_ema20 = ema20
            last_ema50 = ema50
            
            is_bullish = bool(last_ema20 > last_ema50)
            
            interval_map = {
                "Min1": "1m",
                "Min15": "15m",
                "Min60": "1h",
                "Hour4": "4h",
                "Day1": "1d",
            }
            prefix = interval_map.get(interval, interval)
            
            self.market_state[symbol][f"{prefix}_bullish"] = is_bullish
            self.market_state[symbol][f"{prefix}_ema20"] = float(last_ema20)
            self.market_state[symbol][f"{prefix}_ema50"] = float(last_ema50)
            
        # Calculate RSI 14 for 1m (using last 14 candles)
        if interval == "Min1" and len(history) >= 15:
            gains = 0
            losses = 0
            start_idx = len(history) - 14
            for i in range(start_idx, len(history)):
                change = history[i]["c"] - history[i-1]["c"]
                if change > 0: gains += change
                else: losses -= change
            rs = (gains/14) / (losses/14) if losses > 0 else 100
            rsi = 100 - (100 / (1 + rs))
            self.market_state[symbol]["rsi_14"] = rsi
            
        # Calculate FVG for 15m
        if interval == "Min15" and len(history) >= 3:
            c1 = history[-3]
            c3 = history[-1]
            if c1["h"] < c3["l"]: # Bullish FVG
                self.market_state[symbol]["15m_fvg_bullish"] = (c1["h"], c3["l"])
            elif c1["l"] > c3["h"]: # Bearish FVG
                self.market_state[symbol]["15m_fvg_bearish"] = (c3["h"], c1["l"])

        # Fix 8: Detect 15m swing highs and lows (2-candle pivot)
        # Used for: confluence requirement and dynamic TP targeting
        if interval == "Min15" and len(history) >= 5:
            # A swing high: middle candle is higher than both neighbors
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                self.market_state[symbol]["15m_swing_high"] = history[-3]["h"]
            # A swing low: middle candle is lower than both neighbors
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                self.market_state[symbol]["15m_swing_low"] = history[-3]["l"]

        # Fix 5: Compute 4H session high/low from the 2 most recent completed 4H candles
        # This gives a fresh, actionable sweep level that updates every 4 hours (much more frequent than 1D)
        if interval == "Hour4":
            if len(history) >= 3:
                self.market_state[symbol]["4h_session_high"] = max(history[-3]["h"], history[-2]["h"])
                self.market_state[symbol]["4h_session_low"]  = min(history[-3]["l"], history[-2]["l"])
            elif len(history) >= 1:
                self.market_state[symbol]["4h_session_high"] = max(c["h"] for c in history)
                self.market_state[symbol]["4h_session_low"]  = min(c["l"] for c in history)



    def _select_best_strategy(self, symbol, direction, state, trade_data_symbol, c_high, c_low, price, dist_approx):
        """
        Multi-factor strategy scorer. Scores every active strategy against current
        market conditions and historical EV, then returns the best fit.

        Score breakdown:
          - Historical EV (only counted if >= 15 past trades for that strategy)
          - Condition bonuses: regime match, RSI extreme, delta confirm, FVG, etc.
          - Hard disqualification: strategies that require a condition that isn't met
        """
        regime      = state.get("regime", "Chop")
        regime_conf = state.get("regime_conf", 0.5)
        htf_bullish = state.get("4h_bullish", False) and state.get("1d_bullish", False)
        htf_bearish = not state.get("4h_bullish", True) and not state.get("1d_bullish", True)
        htf_aligned = htf_bearish if direction == "SHORT" else htf_bullish

        rsi         = state.get("rsi_14", 50)
        rsi_extreme = (rsi > 68 and direction == "SHORT") or (rsi < 32 and direction == "LONG")

        delta          = trade_data_symbol.get("delta", 0)
        delta_confirms = (delta < 0 and direction == "SHORT") or (delta > 0 and direction == "LONG")

        fvg_bearish = state.get("15m_fvg_bearish")
        fvg_bullish = state.get("15m_fvg_bullish")
        fvg_present = (fvg_bearish is not None and direction == "SHORT") or \
                      (fvg_bullish is not None and direction == "LONG")

        candle_range_pct = (c_high - c_low) / price if price > 0 else 0
        atr_small        = candle_range_pct < 0.0015

        premium_level    = state.get("sweep_is_premium", False)
        in_prime_session = state.get("in_prime_session", False)
        high_vol_day     = state.get("high_volatility_day", False)

        MIN_HISTORY = 15  # Minimum trades before trusting historical EV

        best_strategy = None
        best_score    = -99999
        scores_log    = {}

        for strategy in self.active_strategies:
            name  = strategy["name"]
            score = 0

            # ── Hard disqualifications ──────────────────────────────────────
            if strategy.get("htf")      and not htf_aligned:    continue
            if strategy.get("delta")    and not delta_confirms:  continue
            if strategy.get("rsi")      and not rsi_extreme:     continue
            if strategy.get("fvg")      and not fvg_present:     continue
            if strategy.get("atr_filter") and not atr_small:     continue

            # ── Historical EV (trust only with enough data) ─────────────────
            stats   = self.risk_engine.calculate_historical_stats(self.signal_history, name, direction)
            n_trades = stats.get("n_trades", 0)
            ev = self.risk_engine.calculate_ev(stats["win_rate"], stats["avg_win"], stats["avg_loss"])
            if n_trades >= MIN_HISTORY:
                score += ev * 150
                # Confidence bonus: more trades = more reliable signal
                score += min(n_trades / 50.0, 1.0) * 20
            # (no penalty if not enough history — condition bonuses carry it)

            # ── Regime match bonuses ────────────────────────────────────────
            if name == "S11_Fixed_Pct_TP" and regime != "Chop":
                score += 35 * regime_conf
            if name == "S12_NoSL_MarginBoost" and regime == "Chop":
                score += 35 * regime_conf

            # ── Global context bonuses ──────────────────────────────────────
            if htf_aligned:      score += 10  # Always reward HTF alignment
            if in_prime_session: score += 8   # Prime session is higher quality

            # ── Tiebreaker: slight preference for regime-matched strategy ───
            if (regime != "Chop" and name == "S11_Fixed_Pct_TP") or \
               (regime == "Chop" and name == "S12_NoSL_MarginBoost"):
                score += 5

            scores_log[name] = round(score, 1)

            if score > best_score:
                best_score    = score
                best_strategy = strategy

        print(f"[{symbol}] Strategy scores ({direction}): {scores_log}")

        # Final fallback: if everything got disqualified, use regime default
        if best_strategy is None:
            fallback_name = "S12_NoSL_MarginBoost" if regime == "Chop" else "S11_Fixed_Pct_TP"
            best_strategy = next(
                (s for s in self.active_strategies if s["name"] == fallback_name),
                self.active_strategies[0]
            )
            best_score = 0
            print(f"[{symbol}] All strategies disqualified — fallback to {fallback_name}")

        print(f"[{symbol}] SELECTED strategy: {best_strategy['name']} (score: {best_score:.1f})")
        return best_strategy, best_score

    async def _evaluate_1m_logic(self, symbol, current_candle, is_historical=False):
        state = self.market_state[symbol]
        history = self.kline_data[symbol]["Min1"]

        # Fix 9: Precision session timing
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        london_prime_start = now_utc.replace(hour=7,  minute=0,  second=0, microsecond=0)
        london_prime_end   = now_utc.replace(hour=7,  minute=30, second=0, microsecond=0)
        ny_prime_start     = now_utc.replace(hour=12, minute=30, second=0, microsecond=0)
        ny_prime_end       = now_utc.replace(hour=13, minute=30, second=0, microsecond=0)
        london_sec_start   = london_prime_end
        london_sec_end     = now_utc.replace(hour=9,  minute=0,  second=0, microsecond=0)
        ny_sec_start       = ny_prime_end
        ny_sec_end         = now_utc.replace(hour=15, minute=0,  second=0, microsecond=0)

        in_prime_session     = (london_prime_start <= now_utc < london_prime_end) or \
                               (ny_prime_start <= now_utc < ny_prime_end)
        in_secondary_session = (london_sec_start <= now_utc < london_sec_end) or \
                               (ny_sec_start <= now_utc < ny_sec_end)
        in_any_session       = in_prime_session or in_secondary_session
        in_killzone          = in_any_session  # backward-compat alias

        state["in_prime_session"] = in_prime_session
        state["in_any_session"]   = in_any_session

        # HTF Trend conformity
        htf_bullish = state.get("4h_bullish", False) and state.get("1d_bullish", False)
        htf_bearish = not state.get("4h_bullish", True) and not state.get("1d_bullish", True)

        d1_high = state.get("1d_high", 0)
        d1_low  = state.get("1d_low", 0)

        # Fix 5: Use 4H session levels as primary sweep targets, fall back to 1D
        sweep_high = state.get("4h_session_high") or d1_high
        sweep_low  = state.get("4h_session_low")  or d1_low

        # Need enough history and at least one sweep level defined
        if sweep_high == 0 or sweep_low == 0 or len(history) < 60:
            return

        price = current_candle["c"]
        c_open = current_candle["o"]
        c_close = current_candle["c"]
        c_high = current_candle["h"]
        c_low = current_candle["l"]
        c_vol = current_candle["v"]

        # Calculate avg volume of prev 10 candles
        prev_10 = history[-11:-1]
        if len(prev_10) == 10:
            avg_vol = sum(c["v"] for c in prev_10) / 10
        else:
            avg_vol = 1

        is_red = c_close < c_open
        is_green = c_close > c_open

        # Fix 9: Lower volume threshold during prime sessions (institutional flow is more organic)
        vol_threshold = 1.3 if in_prime_session else 1.5
        vol_surge = c_vol > (vol_threshold * avg_vol)

        state["vol_ok"] = vol_surge

        # Fix 6: Daily volatility flag — on big trend days, counter-trend sweeps are dangerous
        if d1_high > 0 and d1_low > 0:
            daily_range_pct = (d1_high - d1_low) / d1_low
            state["high_volatility_day"] = daily_range_pct > 0.025  # > 2.5% = strong trend day
        else:
            state["high_volatility_day"] = False

        # HMM Features — use 4H sweep levels for proximity calculation
        vol_velocity = c_vol / avg_vol if avg_vol > 0 else 1.0
        dist_high = abs(c_close - sweep_high) / sweep_high if sweep_high > 0 else 1.0
        dist_low  = abs(c_close - sweep_low)  / sweep_low  if sweep_low  > 0 else 1.0
        liq_proximity = min(dist_high, dist_low)
        
        if len(history) >= 14:
            recent_closes = [c["c"] for c in history[-14:]]
            volatility_std = float(np.std(recent_closes)) / price
        else:
            volatility_std = 0.0

        current_features = [vol_velocity, liq_proximity, volatility_std]
        
        if "hmm_features" not in state:
            state["hmm_features"] = []
        state["hmm_features"].append(current_features)
        
        if len(state["hmm_features"]) > 1000:
            state["hmm_features"].pop(0)

        # Predict current regime
        regime_name, regime_conf = self.hmm_engine.predict_regime(current_features)
        state["regime"] = regime_name
        state["regime_conf"] = regime_conf
        
        # Periodic Retrain (e.g. if we reach 1000 candles and not training)
        import time
        now = time.time()
        if (len(state["hmm_features"]) >= 1000 
                and not self.hmm_engine.is_training 
                and now - self.last_hmm_train_time > self.HMM_RETRAIN_INTERVAL):
            self.hmm_engine.retrain(state["hmm_features"])
            self.last_hmm_train_time = now
            
        state["regime_reliable"] = getattr(self.hmm_engine, "converged", False)

        # Fix 2: Reset intrabar signal flag when a brand-new candle starts
        last_seen_t = state.get("last_seen_candle_t")
        if last_seen_t != current_candle["t"]:
            state["intrabar_signal_taken"] = False
            state["last_seen_candle_t"] = current_candle["t"]
            
        if is_historical:
            return
            
        def _get_regime_thresholds(st):
            r = st.get("regime", "Chop")
            reliable = st.get("regime_reliable", False)
            if not reliable:
                return {"min_body": 0.20, "require_vol": False, "ttl": 8}
            if r == "Liquidation Cascade":
                return {"min_body": 0.00, "require_vol": False, "ttl": 6}
            elif r == "Trend":
                return {"min_body": 0.20, "require_vol": False, "ttl": 10}
            else:  # Chop
                return {"min_body": 0.30, "require_vol": True, "ttl": 5}

        # ── CLOSE-ONLY: Setup state machine (sweep detection + anchor locking + TTL) ──
        if current_candle.get("is_closed", False):
            setup_state = state.get("setup_state", "WAITING")

            # State Resets (if price falls back into the waiting zone)
            if setup_state in ["TRADED_HIGH", "SWEPT_HIGH", "SHORT_SETUP_FORMED"]:
                if c_close < sweep_high and c_open < sweep_high:
                    state["setup_state"] = "WAITING"
                    setup_state = "WAITING"
                elif setup_state == "TRADED_HIGH":
                    setup_candle = state.get("setup_candle")
                    if setup_candle and c_high > setup_candle["h"]:
                        state["setup_state"] = "SWEPT_HIGH"
                        setup_state = "SWEPT_HIGH"
            elif setup_state in ["TRADED_LOW", "SWEPT_LOW", "LONG_SETUP_FORMED"]:
                if c_close > sweep_low and c_open > sweep_low:
                    state["setup_state"] = "WAITING"
                    setup_state = "WAITING"
                elif setup_state == "TRADED_LOW":
                    setup_candle = state.get("setup_candle")
                    if setup_candle and c_low < setup_candle["l"]:
                        state["setup_state"] = "SWEPT_LOW"
                        setup_state = "SWEPT_LOW"

            if setup_state == "WAITING":
                # Wick Rejection (Touch and Trade)
                is_short_rejection = c_high >= sweep_high and c_close < sweep_high and (sweep_high - c_close)/sweep_high >= 0.0005
                is_long_rejection = c_low <= sweep_low and c_close > sweep_low and (c_close - sweep_low)/sweep_low >= 0.0005
                
                if is_short_rejection:
                    state["setup_state"] = "SHORT_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    regime = state.get("regime", "Chop")
                    state["ttl"] = 3 if regime == "Liquidation Cascade" else (4 if regime == "Trend" else 5)
                    state["target_tp"] = min([c["l"] for c in history[-61:-1]]) if len(history) >= 61 else c_low
                    print(f"[{symbol}] WICK REJECTION SHORT: touched {sweep_high:.4f}, closed {c_close:.4f}. State -> SHORT_SETUP_FORMED")
                elif is_long_rejection:
                    state["setup_state"] = "LONG_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    regime = state.get("regime", "Chop")
                    state["ttl"] = 3 if regime == "Liquidation Cascade" else (4 if regime == "Trend" else 5)
                    state["target_tp"] = max([c["h"] for c in history[-61:-1]]) if len(history) >= 61 else c_high
                    print(f"[{symbol}] WICK REJECTION LONG: touched {sweep_low:.4f}, closed {c_close:.4f}. State -> LONG_SETUP_FORMED")
                # Fix 5: Detect sweep of 4H session level (premium if also breaking 1D level)
                elif c_high > sweep_high:
                    cooldown = state.get("swept_level_cooldown", {})
                    level_key = round(sweep_high, 1)
                    if level_key not in cooldown or len(history) - cooldown[level_key] >= 10:
                        state["setup_state"] = "SWEPT_HIGH"
                        state["target_tp"] = min([c["l"] for c in history[-61:-1]]) if len(history) >= 61 else c_low
                        state["sweep_is_premium"] = d1_high > 0 and c_high > d1_high
                        label = " [PREMIUM — also 1D HIGH!]" if state["sweep_is_premium"] else ""
                        print(f"[{symbol}] SWEPT 4H HIGH ({sweep_high:.4f}).{label} State -> SWEPT_HIGH")
                elif c_low < sweep_low:
                    cooldown = state.get("swept_level_cooldown", {})
                    level_key = round(sweep_low, 1)
                    if level_key not in cooldown or len(history) - cooldown[level_key] >= 10:
                        state["setup_state"] = "SWEPT_LOW"
                        state["target_tp"] = max([c["h"] for c in history[-61:-1]]) if len(history) >= 61 else c_high
                        state["sweep_is_premium"] = d1_low > 0 and c_low < d1_low
                        label = " [PREMIUM — also 1D LOW!]" if state["sweep_is_premium"] else ""
                        print(f"[{symbol}] SWEPT 4H LOW ({sweep_low:.4f}).{label} State -> SWEPT_LOW")
                elif state.get("15m_swing_high", 0) > 0 and c_high > state["15m_swing_high"]:
                    cooldown = state.get("swept_level_cooldown", {})
                    level_key = round(state["15m_swing_high"], 1)
                    if level_key not in cooldown or len(history) - cooldown[level_key] >= 10:
                        state["setup_state"] = "SWEPT_HIGH"
                        state["target_tp"] = min([c["l"] for c in history[-15:-1]]) if len(history) >= 15 else c_low
                        state["sweep_is_premium"] = False
                        print(f"[{symbol}] SWEPT 15m HIGH ({state['15m_swing_high']:.4f}). State -> SWEPT_HIGH")
                elif state.get("15m_swing_low", 0) > 0 and c_low < state["15m_swing_low"]:
                    cooldown = state.get("swept_level_cooldown", {})
                    level_key = round(state["15m_swing_low"], 1)
                    if level_key not in cooldown or len(history) - cooldown[level_key] >= 10:
                        state["setup_state"] = "SWEPT_LOW"
                        state["target_tp"] = max([c["h"] for c in history[-15:-1]]) if len(history) >= 15 else c_high
                        state["sweep_is_premium"] = False
                        print(f"[{symbol}] SWEPT 15m LOW ({state['15m_swing_low']:.4f}). State -> SWEPT_LOW")

            # Refresh setup_state variable in case it just transitioned
            setup_state = state.get("setup_state", "WAITING")

            if setup_state == "SWEPT_HIGH":
                if is_red:
                    # Fix 3: Setup candle quality check — body must be >= threshold
                    candle_range = c_high - c_low
                    candle_body  = abs(c_close - c_open)
                    body_ratio   = candle_body / candle_range if candle_range > 0 else 0
                    thresholds = _get_regime_thresholds(state)
                    if body_ratio < thresholds["min_body"]:
                        print(f"[{symbol}] Setup candle REJECTED: body ratio {body_ratio:.2f} < {thresholds['min_body']:.2f} (weak/doji). State -> WAITING.")
                        state["setup_state"] = "WAITING"
                    else:
                        state["setup_state"] = "SHORT_SETUP_FORMED"
                        state["setup_candle"] = current_candle
                        state["ttl"] = thresholds["ttl"]
                        print(f"[{symbol}] Red candle locked (body {body_ratio:.2f}). State -> SHORT_SETUP_FORMED (TTL: {state['ttl']})")

            elif setup_state == "SWEPT_LOW":
                if is_green:
                    # Fix 3: Setup candle quality check
                    candle_range = c_high - c_low
                    candle_body  = abs(c_close - c_open)
                    body_ratio   = candle_body / candle_range if candle_range > 0 else 0
                    thresholds = _get_regime_thresholds(state)
                    if body_ratio < thresholds["min_body"]:
                        print(f"[{symbol}] Setup candle REJECTED: body ratio {body_ratio:.2f} < {thresholds['min_body']:.2f} (weak/doji). State -> WAITING.")
                        state["setup_state"] = "WAITING"
                    else:
                        state["setup_state"] = "LONG_SETUP_FORMED"
                        state["setup_candle"] = current_candle
                        state["ttl"] = thresholds["ttl"]
                        print(f"[{symbol}] Green candle locked (body {body_ratio:.2f}). State -> LONG_SETUP_FORMED (TTL: {state['ttl']})")

            elif setup_state == "SHORT_SETUP_FORMED":
                # Decrement TTL on each closed candle (the trigger check itself is intrabar below)
                state["ttl"] = state.get("ttl", 5) - 1
                if state["ttl"] <= 0:
                    state["setup_state"] = "WAITING"
                    state["swept_level_cooldown"][round(sweep_high, 1)] = len(history)
                    print(f"[{symbol}] TTL Expired. No break occurred. State -> WAITING.")

            elif setup_state == "LONG_SETUP_FORMED":
                state["ttl"] = state.get("ttl", 5) - 1
                if state["ttl"] <= 0:
                    state["setup_state"] = "WAITING"
                    state["swept_level_cooldown"][round(sweep_low, 1)] = len(history)
                    print(f"[{symbol}] TTL Expired. No break occurred. State -> WAITING.")

        # ── INTRABAR: Trigger check (Fix 2 — runs every tick, not just on candle close) ──
        setup_state     = state.get("setup_state", "WAITING")
        trigger_direction = None

        if setup_state == "SHORT_SETUP_FORMED" and not state.get("intrabar_signal_taken"):
            setup_candle = state.get("setup_candle")
            if setup_candle:
                buffer_price = setup_candle["l"] * (1 - 0.0005)
                thresholds = _get_regime_thresholds(state)
                if current_candle["c"] < buffer_price:
                    if not thresholds["require_vol"] or vol_surge:
                        trigger_direction = "SHORT"
                        state["setup_state"] = "TRADED_HIGH"
                        state["intrabar_signal_taken"] = True
                        print(f"[{symbol}] SHORT TRIGGERED INTRABAR! Price {current_candle['c']:.4f} < Buffer {buffer_price:.4f}")
                    elif current_candle.get("is_closed", False):
                        # Only invalidate on candle close — intrabar the candle may still develop volume
                        print(f"[{symbol}] Failed SHORT: buffer broken but NO VOLUME SURGE at candle close. State -> WAITING.")
                        state["setup_state"] = "WAITING"

        elif setup_state == "LONG_SETUP_FORMED" and not state.get("intrabar_signal_taken"):
            setup_candle = state.get("setup_candle")
            if setup_candle:
                buffer_price = setup_candle["h"] * (1 + 0.0005)
                thresholds = _get_regime_thresholds(state)
                if current_candle["c"] > buffer_price:
                    if not thresholds["require_vol"] or vol_surge:
                        trigger_direction = "LONG"
                        state["setup_state"] = "TRADED_LOW"
                        state["intrabar_signal_taken"] = True
                        print(f"[{symbol}] LONG TRIGGERED INTRABAR! Price {current_candle['c']:.4f} > Buffer {buffer_price:.4f}")
                    elif current_candle.get("is_closed", False):
                        print(f"[{symbol}] Failed LONG: buffer broken but NO VOLUME SURGE at candle close. State -> WAITING.")
                        state["setup_state"] = "WAITING"

        if trigger_direction:
            # Apply user-facing filter toggles as global gates
            if self.filter_killzone and not in_any_session: return
            if self.filter_volume and not vol_surge: return
            if self.filter_pressure:
                pressure = self.trade_data.get(symbol, {}).get("pressure_direction", "NEUTRAL")
                if pressure == "NEUTRAL": return

            # Fix 6: Daily volatility veto — on strong trend days, only trade WITH the trend
            if state.get("high_volatility_day"):
                if trigger_direction == "SHORT" and not htf_bearish:
                    print(f"[{symbol}] VETO: High-volatility day + counter-trend SHORT blocked.")
                    return
                if trigger_direction == "LONG" and not htf_bullish:
                    print(f"[{symbol}] VETO: High-volatility day + counter-trend LONG blocked.")
                    return

            # Fix 7: Funding rate directional bias — skip trades against the overcrowded side
            funding_rate = state.get("funding_rate", 0.0001)
            EXTREME_FUNDING = 0.0003  # 0.03% per 8h is extreme
            if abs(funding_rate) > EXTREME_FUNDING:
                if funding_rate > 0 and trigger_direction == "LONG":
                    print(f"[{symbol}] FUNDING BIAS: Extreme positive rate ({funding_rate:.5f}). Skipping LONG.")
                    return
                if funding_rate < 0 and trigger_direction == "SHORT":
                    print(f"[{symbol}] FUNDING BIAS: Extreme negative rate ({funding_rate:.5f}). Skipping SHORT.")
                    return

            # Fix 8: 15m structure break confluence — require price to have broken a 15m swing
            if trigger_direction == "SHORT":
                m15_swing_low = state.get("15m_swing_low", 0)
                if m15_swing_low > 0 and current_candle["c"] > m15_swing_low:
                    print(f"[{symbol}] CONFLUENCE FAIL: Price {current_candle['c']:.4f} still above 15m swing low {m15_swing_low:.4f}. Skipping SHORT.")
                    return
            if trigger_direction == "LONG":
                m15_swing_high = state.get("15m_swing_high", 0)
                if m15_swing_high > 0 and current_candle["c"] < m15_swing_high:
                    print(f"[{symbol}] CONFLUENCE FAIL: Price {current_candle['c']:.4f} still below 15m swing high {m15_swing_high:.4f}. Skipping LONG.")
                    return

            import uuid
            setup_id = str(uuid.uuid4())
            setup_candle = state.get("setup_candle")

            regime = state.get("regime", "Chop")

            # Orchestrator veto: block counter-cascade trades during strong liquidations
            if regime == "Liquidation Cascade":
                if trigger_direction == "SHORT" and htf_bullish:
                    print(f"[{symbol}] ORCHESTRATOR VETO: Blocked SHORT during Bullish Liquidation Cascade.")
                    return
                if trigger_direction == "LONG" and htf_bearish:
                    print(f"[{symbol}] ORCHESTRATOR VETO: Blocked LONG during Bearish Liquidation Cascade.")
                    return

            # Estimate SL distance for strategy scoring (approx from setup candle)
            setup_candle_for_score = state.get("setup_candle")
            if setup_candle_for_score and current_candle["c"] > 0:
                if trigger_direction == "SHORT":
                    dist_approx = (setup_candle_for_score["h"] - current_candle["c"]) / current_candle["c"]
                else:
                    dist_approx = (current_candle["c"] - setup_candle_for_score["l"]) / current_candle["c"]
                dist_approx = max(dist_approx, 0.0001)
            else:
                dist_approx = 0.001

            # Smart strategy selection: score all strategies, pick best
            strategy, strategy_score = self._select_best_strategy(
                symbol, trigger_direction, state,
                self.trade_data.get(symbol, {}),
                c_high, c_low, price, dist_approx
            )
            strategy_name = strategy["name"]

            already_signaled = any(s.get("timestamp_ms") == current_candle["t"] and s.get("strategy") == strategy_name for s in self.signal_history)
            if not (already_signaled or is_historical):
                if trigger_direction == "SHORT":
                    valid = True
                    if strategy["htf"] and not htf_bearish: valid = False
                    if self.filter_htf and not htf_bearish: valid = False
                    if strategy["atr_filter"] and c_high - c_low > price * 0.0015: valid = False
                    if strategy["delta"]:
                        current_delta = self.trade_data.get(symbol, {}).get("delta", 0)
                        if current_delta > 0: valid = False
                    if strategy["rsi"]:
                        rsi = state.get("rsi_14", 50)
                        if rsi > 60: valid = False
                    if strategy["fvg"]:
                        fvg = state.get("15m_fvg_bearish")
                        if not fvg or not (fvg[0] <= c_high <= fvg[1]): valid = False

                    if valid:
                        stats = self.risk_engine.calculate_historical_stats(self.signal_history, strategy_name, "SHORT")
                        ev = self.risk_engine.calculate_ev(stats["win_rate"], stats["avg_win"], stats["avg_loss"])
                        n_trades = stats.get("n_trades", 0)
                        if ev <= 0 and n_trades >= 15 and not is_historical:
                            print(f"[{symbol}] EV VETO: EV is {ev:.4f} <= 0 (n={n_trades}). Blocking trade.")
                        else:
                            hmm_conf = state.get("regime_conf", 0.5)
                            kelly_fraction = self.risk_engine.calculate_kelly_fraction(stats["win_rate"], stats["avg_win"], stats["avg_loss"], hmm_conf)
                            await self._trigger_signal(symbol, "SHORT", current_candle, setup_candle, avg_vol, state["target_tp"], strategy, setup_id, kelly_fraction)

                elif trigger_direction == "LONG":
                    valid = True
                    if strategy["htf"] and not htf_bullish: valid = False
                    if self.filter_htf and not htf_bullish: valid = False
                    if strategy["atr_filter"] and c_high - c_low > price * 0.0015: valid = False
                    if strategy["delta"]:
                        current_delta = self.trade_data.get(symbol, {}).get("delta", 0)
                        if current_delta < 0: valid = False
                    if strategy["rsi"]:
                        rsi = state.get("rsi_14", 50)
                        if rsi < 40: valid = False
                    if strategy["fvg"]:
                        fvg = state.get("15m_fvg_bullish")
                        if not fvg or not (fvg[0] <= c_low <= fvg[1]): valid = False

                    if valid:
                        stats = self.risk_engine.calculate_historical_stats(self.signal_history, strategy_name, "LONG")
                        ev = self.risk_engine.calculate_ev(stats["win_rate"], stats["avg_win"], stats["avg_loss"])
                        n_trades = stats.get("n_trades", 0)
                        if ev <= 0 and n_trades >= 15 and not is_historical:
                            print(f"[{symbol}] EV VETO: EV is {ev:.4f} <= 0 (n={n_trades}). Blocking trade.")
                        else:
                            hmm_conf = state.get("regime_conf", 0.5)
                            kelly_fraction = self.risk_engine.calculate_kelly_fraction(stats["win_rate"], stats["avg_win"], stats["avg_loss"], hmm_conf)
                            await self._trigger_signal(symbol, "LONG", current_candle, setup_candle, avg_vol, state["target_tp"], strategy, setup_id, kelly_fraction)

        # ── S13: 1m EMA Cross Scalp ───────────────────────────────────────────
        # Independent of the sweep state machine — fires on momentum crosses
        if not is_historical and not state.get("ema_cross_signal_taken"):
            ema20 = state.get("1m_ema20", 0)
            ema50 = state.get("1m_ema50", 0)
            rsi   = state.get("rsi_14", 50)

            if ema20 > 0 and ema50 > 0 and len(history) >= 3:
                # Need EMA from previous candle to detect cross
                prev_closes = [c["c"] for c in history[-52:]]
                if len(prev_closes) >= 52:
                    # Simple EMA helper
                    def _calc_ema(prices, period):
                        k = 2 / (period + 1)
                        ema = prices[0]
                        for p in prices[1:]:
                            ema = (p * k) + (ema * (1 - k))
                        return ema
                        
                    prev_ema20 = _calc_ema(prev_closes[:-1], 20)
                    prev_ema50 = _calc_ema(prev_closes[:-1], 50)

                    ema_cross_direction = None
                    if ema20 > ema50 and prev_ema20 <= prev_ema50 and rsi < 65:
                        ema_cross_direction = "LONG"
                        state["ema_cross_signal_taken"] = True
                    elif ema20 < ema50 and prev_ema20 >= prev_ema50 and rsi > 35:
                        ema_cross_direction = "SHORT"
                        state["ema_cross_signal_taken"] = True

                    if ema_cross_direction:
                        s13 = next((s for s in self.active_strategies if s["name"] == "S13_EMA_Cross_Scalp"), None)
                        if s13:
                            setup_id_s13 = str(uuid.uuid4())
                            await self._trigger_signal(
                                symbol, ema_cross_direction, current_candle,
                                current_candle, avg_vol, 0, s13, setup_id_s13, 1.0
                            )

        # Reset EMA cross signal taken on new candle
        if current_candle.get("is_closed"):
            state["ema_cross_signal_taken"] = False

    async def _trigger_signal(self, symbol, direction, trigger_candle, setup_candle, avg_vol, target_tp, strategy=None, setup_id=None, kelly_fraction=1.0):
        # Fix 10: Max concurrent positions limit — avoid over-exposure
        MAX_CONCURRENT_POSITIONS = 5
        open_count = sum(1 for s in self.signal_history if s.get("status") == "PENDING")
        if open_count >= MAX_CONCURRENT_POSITIONS:
            print(f"[{symbol}] POSITION LIMIT: {open_count} open positions >= max {MAX_CONCURRENT_POSITIONS}. Skipping signal.")
            return

        if strategy is None:
            strategy = {"name": "S0_Baseline_400x", "leverage": 50, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False}
        strategy_name = strategy["name"]
        
        trade_state = self.market_state.get(symbol, {})
        BUFFER = 0.0005 # 0.05% buffer

        if strategy.get("no_sl"):
            if direction == "SHORT":
                base_sl = trigger_candle["c"] * 1.5
            else:
                base_sl = trigger_candle["c"] * 0.5
            dist_pct = abs(trigger_candle["c"] - base_sl) / trigger_candle["c"]
        else:
            if direction == "SHORT":
                four_h_high = trade_state.get("4h_session_high", 0)
                structure_sl = four_h_high * (1 + BUFFER) if four_h_high > 0 else setup_candle["h"]
                base_sl = max(setup_candle["h"], structure_sl)
                dist_pct = (base_sl - trigger_candle["c"]) / trigger_candle["c"]
            else:
                four_h_low = trade_state.get("4h_session_low", 0)
                structure_sl = four_h_low * (1 - BUFFER) if four_h_low > 0 else setup_candle["l"]
                base_sl = min(setup_candle["l"], structure_sl)
                dist_pct = (trigger_candle["c"] - base_sl) / trigger_candle["c"]
            
        if strategy.get("pre_liq"):
            # Force SL exactly 0.12% away to avoid 0.15% liquidation
            dist_pct = 0.0012
            if direction == "SHORT": base_sl = trigger_candle["c"] * (1 + 0.0012)
            else: base_sl = trigger_candle["c"] * (1 - 0.0012)
            
        sl = base_sl

        # Fix 4: Minimum SL distance filter — fees eat trades with tight SL
        # At 50x with 0.04% round-trip fees, need at least 0.08% to break even
        MIN_SL_DISTANCE = 0.0008  # 0.08%
        if dist_pct < MIN_SL_DISTANCE and not strategy.get("no_sl"):
            print(f"[{symbol}] TRADE REJECTED: SL distance {dist_pct*100:.4f}% < minimum 0.08%. Fees would consume profit.")
            return

        # Fix 11: Dynamic TP based on 15m swing structure — captures more on momentum days
        trade_state = self.market_state.get(symbol, {})

        # Fix 1: Apply 1:2 R:R as base, try to target 15m swing for a higher payout
        if direction == "SHORT":
            risk = sl - trigger_candle["c"]
            if strategy.get("fixed_tp_pct"):
                tp = trigger_candle["c"] * (1 - 0.0015)
                tp1 = trigger_candle["c"] * (1 - 0.00075)
            else:
                fixed_2R_tp = trigger_candle["c"] - (2 * risk)
                m15_target  = trade_state.get("15m_swing_low", 0)
                if m15_target > 0 and m15_target < trigger_candle["c"] and risk > 0:
                    potential_rr = (trigger_candle["c"] - m15_target) / risk
                    if potential_rr >= 1.0:
                        tp = m15_target
                        print(f"[{symbol}] Dynamic TP: 15m swing low {tp:.4f} ({potential_rr:.1f}R)")
                    else:
                        tp = fixed_2R_tp
                else:
                    tp = fixed_2R_tp
                tp1 = trigger_candle["c"] - risk  # Scale-out TP1 at 1R
        else:
            risk = trigger_candle["c"] - sl
            if strategy.get("fixed_tp_pct"):
                tp = trigger_candle["c"] * (1 + 0.0015)
                tp1 = trigger_candle["c"] * (1 + 0.00075)
            else:
                fixed_2R_tp = trigger_candle["c"] + (2 * risk)
                m15_target  = trade_state.get("15m_swing_high", 0)
                if m15_target > 0 and m15_target > trigger_candle["c"] and risk > 0:
                    potential_rr = (m15_target - trigger_candle["c"]) / risk
                    if potential_rr >= 1.0:
                        tp = m15_target
                        print(f"[{symbol}] Dynamic TP: 15m swing high {tp:.4f} ({potential_rr:.1f}R)")
                    else:
                        tp = fixed_2R_tp
                else:
                    tp = fixed_2R_tp
                tp1 = trigger_candle["c"] + risk  # Scale-out TP1 at 1R

        vol_ratio = setup_candle.get("v", 0) / avg_vol if (avg_vol > 0 and setup_candle) else 0

        context = {
            "symbol": symbol,
            "direction": direction,
            "price": trigger_candle["c"],
            "entry": trigger_candle["c"],
            "sl": sl,
            "tp": tp,
            "1d_high": self.market_state[symbol].get("1d_high"),
            "1d_low": self.market_state[symbol].get("1d_low"),
            "4h_bullish": self.market_state[symbol].get("4h_bullish"),
            "1d_bullish": self.market_state[symbol].get("1d_bullish"),
            "vol_ratio": round(vol_ratio, 2)
        }

        # Insight removed per user request
        
        import uuid
        trade_id = str(uuid.uuid4())

        signal = {
            "id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry": context["entry"],
            "sl": sl,
            "tp": tp,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "timestamp_ms": trigger_candle["t"]
        }
        
        self.signals.append(signal)
        print(f"SIGNAL TRIGGERED: {signal}")
        
        # For auto-leverage, compute actual leverage — capped at 50x (Fix 1)
        if strategy["leverage"] == "auto":
            computed_leverage = max(10, min(50, int((1.0 / dist_pct) * 0.8))) if dist_pct > 0 else 50
        else:
            computed_leverage = int(strategy["leverage"])

        # Build strategy metric string
        if strategy['name'] == 'S1_AutoLeverage':
            strategy_metric = f"{computed_leverage}x Lev | SL: {(dist_pct*100):.2f}%"
        elif strategy['name'] == 'S2_PreLiq_SL':
            strategy_metric = f"SL: {(dist_pct*100):.2f}%"
        elif strategy['name'] == 'S3_ATR_Filter':
            strategy_metric = "Volatility Checked"
        elif strategy['name'] == 'S4_CrossMargin':
            strategy_metric = "Balance Protected"
        elif strategy['name'] == 'S5_ScaleOut_BE':
            strategy_metric = "ScaleOut Enabled"
        elif strategy['name'] == 'S6_HTF_Aligned':
            strategy_metric = "Trend Verified"
        elif strategy['name'] == 'S7_Delta_Div':
            strategy_metric = "Delta Confirmed"
        elif strategy['name'] == 'S8_RSI_Div':
            strategy_metric = "RSI Momentum Checked"
        elif strategy['name'] == 'S9_TimeExit':
            strategy_metric = "15m Timer Enabled"
        elif strategy['name'] == 'S10_FVG_Conf':
            strategy_metric = "FVG Confirmed"
        elif strategy['name'] == 'S11_Fixed_Pct_TP':
            strategy_metric = "0.15% Fixed TP"
        elif strategy['name'] == 'S12_NoSL_MarginBoost':
            strategy_metric = "400x Auto-Margin"
        else:
            strategy_metric = "50x Static"

        hist_signal = {
            "id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry": context["entry"],
            "sl": sl,
            "tp": tp,
            "tp1": tp1,
            "scaled_out": False,
            "timestamp": signal["timestamp"],
            "status": "PENDING",
            "pnl": 0.0,
            "exit_price": 0.0,
            "close_time": "",
            "slippage": 0.0,
            "fees": 0.0,
            "funding_rate": 0.0,
            "net_profit": 0.0,
            "raw_profit": 0.0,
            "close_reason": "",
            "duration": "",
            "max_drawdown_price": context["entry"],
            "max_drawdown": "",
            "strategy": strategy_name,
            "setup_id": setup_id,
            "config": strategy,
            "computed_leverage": computed_leverage,
            "strategy_metric": strategy_metric,
            "initial_margin": 5.0,
            "margin": 5.0,
            "margin_adds": 0
        }
        self.signal_history.append(hist_signal)
        
        import asyncio
        import copy
        asyncio.create_task(asyncio.to_thread(self.sheets_client.append_trade, copy.deepcopy(hist_signal)))
        self._save_history()
        
        if self.shihab_active and self.mexc_client:
            print(f"SHIHAB AUTO-TRADER is placing order for {symbol} {direction}")
            await self.mexc_client.submit_order(symbol, direction, context["entry"], sl, tp)
            
        if self.shihab_demo_active:
            # Fix 10: Enforce demo position limit before opening a new virtual trade
            if len(self.demo_positions) >= MAX_CONCURRENT_POSITIONS:
                print(f"[{symbol}] DEMO LIMIT: {len(self.demo_positions)} demo positions open >= max {MAX_CONCURRENT_POSITIONS}. Skipping demo entry.")
            else:
                # Prevent opening if not enough balance
                invest_amount = self.demo_invest_amount * kelly_fraction if kelly_fraction < 1.0 else self.demo_invest_amount
                if self.demo_balance >= invest_amount:
                    demo_pos = {
                        "symbol": symbol,
                        "direction": direction,
                        "entry": context["entry"],
                        "sl": sl,
                        "tp": tp,
                        "tp1": tp1,
                        "scaled_out": False,
                        "initial_margin": invest_amount,
                        "margin": self.demo_balance if strategy.get("cross_margin") else invest_amount,
                        "margin_adds": 0,
                        "leverage": computed_leverage,
                        "strategy": strategy_name,
                        "config": strategy,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "timestamp_ms": trigger_candle["t"],
                    }
                    self.demo_positions.append(demo_pos)
                    print(f"DEMO SHIHAB opened virtual {direction} on {symbol} with Margin ${self.demo_invest_amount} @ {computed_leverage}x")
