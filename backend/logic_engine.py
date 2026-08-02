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
            {"name": "S0_Baseline_400x", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S1_AutoLeverage", "leverage": "auto", "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": True, "atr_filter": False},
            {"name": "S2_PreLiq_SL", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": True, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S3_ATR_Filter", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": True},
            {"name": "S4_CrossMargin", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": True, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S5_ScaleOut_BE", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": True, "auto_lev": False, "atr_filter": False},
            {"name": "S6_HTF_Aligned", "leverage": 400, "htf": True, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S7_Delta_Div", "leverage": 400, "htf": False, "delta": True, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S8_RSI_Div", "leverage": 400, "htf": False, "delta": False, "rsi": True, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S9_TimeExit", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": True, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S10_FVG_Conf", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": True, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False},
            {"name": "S11_Fixed_Pct_TP", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False, "fixed_tp_pct": True}
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
                "vol_ok": False
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
                    liq_price = pos["entry"] * (1 - 0.0015) if pos["direction"] == "LONG" else pos["entry"] * (1 + 0.0015)
                
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
                    liq_price = hist_pos["entry"] * (1 - 0.0015) if hist_pos["direction"] == "LONG" else hist_pos["entry"] * (1 + 0.0015)
                
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
        if len(history) < 50:
            return # Not enough data
        
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


    async def _evaluate_1m_logic(self, symbol, current_candle, is_historical=False):
        state = self.market_state[symbol]
        history = self.kline_data[symbol]["Min1"]
        
        # Determine Killzone
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        in_killzone = (7 <= now_utc.hour < 10) or (13 <= now_utc.hour < 16)
        
        # Check HTF Trend conformity
        htf_bullish = state.get("4h_bullish", False) and state.get("1d_bullish", False)
        htf_bearish = not state.get("4h_bullish", True) and not state.get("1d_bullish", True)
        
        d1_high = state.get("1d_high", 0)
        d1_low = state.get("1d_low", 0)

        # If data is missing or not enough history for 60-candle pullback, return
        if d1_high == 0 or d1_low == 0 or len(history) < 60:
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
        vol_surge = c_vol > (1.5 * avg_vol)
        
        state["vol_ok"] = vol_surge

        # HMM Features
        vol_velocity = c_vol / avg_vol if avg_vol > 0 else 1.0
        dist_high = abs(c_close - d1_high) / d1_high if d1_high > 0 else 1.0
        dist_low = abs(c_close - d1_low) / d1_low if d1_low > 0 else 1.0
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
        if len(state["hmm_features"]) >= 1000 and not self.hmm_engine.is_training:
            # We can retrain periodically or just rely on a separate script.
            # We'll trigger a background retrain when buffer is full.
            self.hmm_engine.retrain(state["hmm_features"])

        # Only evaluate on close
        if current_candle.get("is_closed", False):
            setup_state = state.get("setup_state", "WAITING")

            # State Resets (if price falls back into the waiting zone)
            if setup_state in ["TRADED_HIGH", "SWEPT_HIGH", "SHORT_SETUP_FORMED"]:
                # If the entire candle body is back below the high, we can reset to WAITING
                if c_close < d1_high and c_open < d1_high:
                    state["setup_state"] = "WAITING"
                    setup_state = "WAITING"
                # New Peak Reset: if already traded, but price pushes to a new higher peak
                elif setup_state == "TRADED_HIGH":
                    setup_candle = state.get("setup_candle")
                    if setup_candle and c_high > setup_candle["h"]:
                        state["setup_state"] = "SWEPT_HIGH"
                        setup_state = "SWEPT_HIGH"
            elif setup_state in ["TRADED_LOW", "SWEPT_LOW", "LONG_SETUP_FORMED"]:
                if c_close > d1_low and c_open > d1_low:
                    state["setup_state"] = "WAITING"
                    setup_state = "WAITING"
                # New Peak Reset: if already traded, but price pushes to a new lower trough
                elif setup_state == "TRADED_LOW":
                    setup_candle = state.get("setup_candle")
                    if setup_candle and c_low < setup_candle["l"]:
                        state["setup_state"] = "SWEPT_LOW"
                        setup_state = "SWEPT_LOW"

            if setup_state == "WAITING":
                if c_high > d1_high:
                    state["setup_state"] = "SWEPT_HIGH"
                    state["target_tp"] = min([c["l"] for c in history[-61:-1]])
                    print(f"[{symbol}] SWEPT 1D HIGH ({d1_high}). State -> SWEPT_HIGH")
                elif c_low < d1_low:
                    state["setup_state"] = "SWEPT_LOW"
                    state["target_tp"] = max([c["h"] for c in history[-61:-1]])
                    print(f"[{symbol}] SWEPT 1D LOW ({d1_low}). State -> SWEPT_LOW")

            # Refresh setup_state variable in case it just transitioned
            setup_state = state.get("setup_state", "WAITING")
            
            trigger_direction = None

            if setup_state == "SWEPT_HIGH":
                if is_red:
                    state["setup_state"] = "SHORT_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    regime = state.get("regime", "Chop")
                    state["ttl"] = 3 if regime == "Liquidation Cascade" else (4 if regime == "Trend" else 5)
                    print(f"[{symbol}] Red candle closed. State -> SHORT_SETUP_FORMED (Anchor Locked, TTL: {state['ttl']})")
            
            elif setup_state == "SWEPT_LOW":
                if is_green:
                    state["setup_state"] = "LONG_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    regime = state.get("regime", "Chop")
                    state["ttl"] = 3 if regime == "Liquidation Cascade" else (4 if regime == "Trend" else 5)
                    print(f"[{symbol}] Green candle closed. State -> LONG_SETUP_FORMED (Anchor Locked, TTL: {state['ttl']})")
            
            elif setup_state == "SHORT_SETUP_FORMED":
                setup_candle = state.get("setup_candle")
                buffer_price = setup_candle["l"] * (1 - 0.0005) # 0.05% buffer below low
                
                state["ttl"] = state.get("ttl", 5) - 1
                if state["ttl"] <= 0:
                    state["setup_state"] = "WAITING"
                    print(f"[{symbol}] TTL Expired (No Volume Break). Setup invalidated. State -> WAITING.")
                else:
                    if current_candle["c"] < buffer_price:
                        if vol_surge:
                            trigger_direction = "SHORT"
                            state["setup_state"] = "TRADED_HIGH"
                            print(f"[{symbol}] SHORT TRIGGERED! Price {current_candle['c']} < Buffer {buffer_price} and Volume Surged.")
                        else:
                            print(f"[{symbol}] Failed SHORT trigger: Price broke buffer, but NO VOLUME SURGE. (Vol: {c_vol}, Avg: {avg_vol})")
                            state["setup_state"] = "WAITING"
                            print(f"[{symbol}] Setup invalidated by early break without volume. State -> WAITING.")
            
            elif setup_state == "LONG_SETUP_FORMED":
                setup_candle = state.get("setup_candle")
                buffer_price = setup_candle["h"] * (1 + 0.0005) # 0.05% buffer above high
                
                state["ttl"] = state.get("ttl", 5) - 1
                if state["ttl"] <= 0:
                    state["setup_state"] = "WAITING"
                    print(f"[{symbol}] TTL Expired (No Volume Break). Setup invalidated. State -> WAITING.")
                else:
                    if current_candle["c"] > buffer_price:
                        if vol_surge:
                            trigger_direction = "LONG"
                            state["setup_state"] = "TRADED_LOW"
                            print(f"[{symbol}] LONG TRIGGERED! Price {current_candle['c']} > Buffer {buffer_price} and Volume Surged.")
                        else:
                            print(f"[{symbol}] Failed LONG trigger: Price broke buffer, but NO VOLUME SURGE. (Vol: {c_vol}, Avg: {avg_vol})")
                            state["setup_state"] = "WAITING"
                            print(f"[{symbol}] Setup invalidated by early break without volume. State -> WAITING.")

            if trigger_direction:
                # Apply user-facing filter toggles as global gates
                if self.filter_killzone and not in_killzone: return
                if self.filter_volume and not vol_surge: return
                if self.filter_pressure:
                    pressure = self.trade_data.get(symbol, {}).get("pressure_direction", "NEUTRAL")
                    if pressure == "NEUTRAL": return

                import uuid
                setup_id = str(uuid.uuid4())
                setup_candle = state.get("setup_candle")
                
                regime = state.get("regime", "Chop")
                
                if regime == "Liquidation Cascade":
                    if trigger_direction == "SHORT" and htf_bullish:
                        print(f"[{symbol}] ORCHESTRATOR VETO: Blocked SHORT during Bullish Liquidation Cascade.")
                        return
                    if trigger_direction == "LONG" and htf_bearish:
                        print(f"[{symbol}] ORCHESTRATOR VETO: Blocked LONG during Bearish Liquidation Cascade.")
                        return
                    strategy_name = "S0_Baseline_400x"
                elif regime == "Trend":
                    strategy_name = "S6_HTF_Aligned"
                else: # Chop
                    strategy_name = "S11_Fixed_Pct_TP"
                    
                strategy = next((s for s in getattr(self, "active_strategies", []) if s["name"] == strategy_name), None)
                if not strategy:
                    return

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
                            if ev <= 0 and not is_historical:
                                print(f"[{symbol}] EV VETO: EV is {ev:.4f} <= 0. Blocking trade.")
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
                            if ev <= 0 and not is_historical:
                                print(f"[{symbol}] EV VETO: EV is {ev:.4f} <= 0. Blocking trade.")
                            else:
                                hmm_conf = state.get("regime_conf", 0.5)
                                kelly_fraction = self.risk_engine.calculate_kelly_fraction(stats["win_rate"], stats["avg_win"], stats["avg_loss"], hmm_conf)
                                await self._trigger_signal(symbol, "LONG", current_candle, setup_candle, avg_vol, state["target_tp"], strategy, setup_id, kelly_fraction)
    async def _trigger_signal(self, symbol, direction, trigger_candle, setup_candle, avg_vol, target_tp, strategy=None, setup_id=None, kelly_fraction=1.0):
        if strategy is None:
            strategy = {"name": "S0_Baseline_400x", "leverage": 400, "htf": False, "delta": False, "rsi": False, "time_exit": False, "fvg": False, "pre_liq": False, "cross_margin": False, "scale_out": False, "auto_lev": False, "atr_filter": False}
        strategy_name = strategy["name"]
        
        if direction == "SHORT":
            base_sl = setup_candle["h"]
            dist_pct = (base_sl - trigger_candle["c"]) / trigger_candle["c"]
        else:
            base_sl = setup_candle["l"]
            dist_pct = (trigger_candle["c"] - base_sl) / trigger_candle["c"]
            
        if strategy["pre_liq"]:
            # Force SL exactly 0.12% away to avoid 0.15% liquidation
            dist_pct = 0.0012
            if direction == "SHORT": base_sl = trigger_candle["c"] * (1 + 0.0012)
            else: base_sl = trigger_candle["c"] * (1 - 0.0012)
            
        sl = base_sl
        
        # Strict 1:2 Risk/Reward Take Profit
        if direction == "SHORT":
            risk = sl - trigger_candle["c"]
            if strategy.get("fixed_tp_pct"):
                tp = trigger_candle["c"] * (1 - 0.0015)
                tp1 = trigger_candle["c"] * (1 - 0.00075)
            else:
                tp = trigger_candle["c"] - (2 * risk)
                # Scale-out TP1 logic: Take half of the distance from entry to TP
                tp1 = trigger_candle["c"] - risk
        else:
            risk = trigger_candle["c"] - sl
            if strategy.get("fixed_tp_pct"):
                tp = trigger_candle["c"] * (1 + 0.0015)
                tp1 = trigger_candle["c"] * (1 + 0.00075)
            else:
                tp = trigger_candle["c"] + (2 * risk)
                # Scale-out TP1 logic: Take half of the distance from entry to TP
                tp1 = trigger_candle["c"] + risk

        vol_ratio = setup_candle["v"] / avg_vol if avg_vol > 0 else 0

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
        
        signal = {
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
        
        # For auto-leverage, compute and store the actual leverage value
        if strategy["leverage"] == "auto":
            computed_leverage = max(10, min(400, int((1.0 / dist_pct) * 0.8))) if dist_pct > 0 else 400
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
        else:
            strategy_metric = "400x Static"

        hist_signal = {
            "id": str(uuid.uuid4()),
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
                    "margin": self.demo_balance if strategy.get("cross_margin") else invest_amount,
                    "leverage": computed_leverage,
                    "strategy": strategy_name,
                    "config": strategy,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "timestamp_ms": trigger_candle["t"],
                }
                self.demo_positions.append(demo_pos)
                print(f"DEMO SHIHAB opened virtual {direction} on {symbol} with Margin ${self.demo_invest_amount} @ {computed_leverage}x")
