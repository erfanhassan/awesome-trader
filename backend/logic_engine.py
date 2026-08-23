import datetime
import math
import pandas as pd
import asyncio
import json
import os
import uuid
import numpy as np
import logging
from typing import Dict, List, Any
import copy
from deepseek_client import DeepSeekClient
from google_sheets_client import GoogleSheetsClient
from hmm_engine import HMMEngine
from risk_engine import RiskEngine

logger = logging.getLogger(__name__)

class LogicEngine:
    def __init__(self):
        # symbol -> { "1m": [...], "4h": [...], "1d": [...] }
        self.kline_data = {}
        self.active_strategies = [
            {
                "name": "SA_Level_Scalp",
                "leverage": 400,
                "fixed_tp_pct": True,
                "tp_pct": 0.0015,         # 0.15%
                "sl_pct": 0.0012,         # 0.12% hard SL
                "time_exit_minutes": 8,   # Kill if no hit in 8 min
                "htf": False, "delta": False, "rsi": False,
                "fvg": False, "pre_liq": False, "cross_margin": False,
                "scale_out": False, "no_sl": False, "auto_margin": True,
            },
            {
                "name": "SB_Level_Guardian",
                "leverage": 400,
                "fixed_tp_pct": False,    # Uses dynamic 15m swing TP
                "sl_pct": 0.0020,         # 0.20% hard SL
                "scale_out": True,        # Take half at TP1 (0.15%)
                "tp1_pct": 0.0015,        # TP1 at 0.15%
                "htf": False, "delta": False, "rsi": False,
                "fvg": False, "pre_liq": False, "cross_margin": False,
                "no_sl": False, "auto_margin": True,
            },
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
            logger.error(f"Error loading history: {e}")

    def _save_history(self):
        try:
            with open("trade_history.json", "w") as f:
                json.dump(self.signal_history, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving history: {e}")

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
                "1h_swing_high": 0,
                "1h_swing_low": 0,
                "1m_swing_highs": [],
                "1m_swing_lows": [],
                "active_sweep_level": 0.0,
                "active_sweep_type": "", 
                "sweep_wick_extreme": 0.0,
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
                
                time_limit_minutes = config.get("time_exit_minutes", 0)
                if time_limit_minutes > 0:
                    entry_time_ms = pos.get("timestamp_ms", 0)
                    current_time_ms = data.get("t", 0)
                    if entry_time_ms > 0 and current_time_ms > 0:
                        if (current_time_ms - entry_time_ms) >= (time_limit_minutes * 60 * 1000):
                            hit_time = True
                            exit_price = data["c"]
                
                if config.get("cross_margin"):
                    size = (pos["margin"] * pos["leverage"]) / pos["entry"]
                    if pos["direction"] == "LONG":
                        liq_price = pos["entry"] - (self.demo_balance / size) if size > 0 else 0
                    else:
                        liq_price = pos["entry"] + (self.demo_balance / size) if size > 0 else float('inf')
                else:
                    initial_margin = pos.get("initial_margin", pos.get("margin", 6.0))
                    total_margin = pos.get("margin", 6.0)
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
                            logger.info(f"[{symbol}] AUTO MARGIN BOOST! Added ${initial_margin:.2f} (Total adds: {pos['margin_adds']})")
                            total_margin = pos["margin"]
                            if pos["direction"] == "LONG":
                                liq_price = pos["entry"] - (total_margin / size) if size > 0 else 0
                            else:
                                liq_price = pos["entry"] + (total_margin / size) if size > 0 else float('inf')
                
                if pos["direction"] == "LONG":
                    if config.get("scale_out") and not pos.get("scaled_out") and data["h"] >= pos.get("tp1", pos["tp"]):
                        pos["scaled_out"] = True
                        pos["sl"] = pos["entry"]
                    
                    if config.get("scale_out") and pos.get("scaled_out"):
                        trail_sl = data["c"] * (1 - 0.0015)
                        if trail_sl > pos["sl"]:
                            pos["sl"] = trail_sl
                    
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
                        
                    if config.get("scale_out") and pos.get("scaled_out"):
                        trail_sl = data["c"] * (1 + 0.0015)
                        if trail_sl < pos["sl"]:
                            pos["sl"] = trail_sl
                        
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
                    
                    avg_delta = pos.get("avg_vol", 50000.0) / 60.0 # Approximate 1-minute delta scale from 15m volume
                    posterior_prob = self.risk_engine.calculate_live_bayesian_update(stats["win_rate"], rolling_delta, avg_delta, pos["direction"])
                    live_ev = self.risk_engine.calculate_ev(posterior_prob, stats["avg_win"], stats["avg_loss"])
                    if live_ev < 0:
                        bayesian_bailout = True
                        exit_price = data["c"]
                        logger.info(f"[{symbol}] DEMO BAYESIAN BAILOUT! Live EV {live_ev:.4f} < 0")
                        
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
                    logger.info(f"DEMO TRADE CLOSED: {symbol} {pos['direction']} - PnL: ${pnl:.2f} (Balance: ${self.demo_balance:.2f})")
                    
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
                
                time_limit_minutes = config.get("time_exit_minutes", 0)
                if time_limit_minutes > 0:
                    entry_time_ms = hist_pos.get("timestamp_ms", 0)
                    current_time_ms = data.get("t", 0)
                    if entry_time_ms > 0 and current_time_ms > 0:
                        if (current_time_ms - entry_time_ms) >= (time_limit_minutes * 60 * 1000):
                            hit_time = True
                            exit_price = data["c"]
                        
                if config.get("cross_margin"):
                    # For signal history simulation, assume a virtual $1000 balance to avoid early liquidation
                    virtual_balance = 1000.0
                    margin = 6.0
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
                    initial_margin = hist_pos.get("initial_margin", hist_pos.get("margin", 6.0))
                    total_margin = hist_pos.get("margin", 6.0)
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
                        
                    if config.get("scale_out") and hist_pos.get("scaled_out"):
                        trail_sl = data["c"] * (1 - 0.0015)
                        if trail_sl > hist_pos["sl"]:
                            hist_pos["sl"] = trail_sl
                        
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
                        
                    if config.get("scale_out") and hist_pos.get("scaled_out"):
                        trail_sl = data["c"] * (1 + 0.0015)
                        if trail_sl < hist_pos["sl"]:
                            hist_pos["sl"] = trail_sl
                        
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
                    
                    avg_delta = hist_pos.get("avg_vol", 50000.0) / 60.0
                    posterior_prob = self.risk_engine.calculate_live_bayesian_update(stats["win_rate"], rolling_delta, avg_delta, hist_pos["direction"])
                    live_ev = self.risk_engine.calculate_ev(posterior_prob, stats["avg_win"], stats["avg_loss"])
                    if live_ev < 0:
                        bayesian_bailout = True
                        exit_price = data["c"]
                        logger.info(f"[{symbol}] HISTORY BAYESIAN BAILOUT! Live EV {live_ev:.4f} < 0")
                        
                if hit_liq or hit_tp or hit_sl or hit_time or bayesian_bailout:
                    # Read margin/leverage from strategy config (fallback to defaults)
                    config = hist_pos.get("config", {})
                    margin = 6.0
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

        # Detect 1m, 15m, 1h swing highs and lows (2-candle pivot)
        if interval == "Min1" and len(history) >= 5:
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                if "1m_swing_highs" not in self.market_state[symbol]: self.market_state[symbol]["1m_swing_highs"] = []
                self.market_state[symbol]["1m_swing_highs"].append(history[-3]["h"])
                if len(self.market_state[symbol]["1m_swing_highs"]) > 5: self.market_state[symbol]["1m_swing_highs"].pop(0)
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                if "1m_swing_lows" not in self.market_state[symbol]: self.market_state[symbol]["1m_swing_lows"] = []
                self.market_state[symbol]["1m_swing_lows"].append(history[-3]["l"])
                if len(self.market_state[symbol]["1m_swing_lows"]) > 5: self.market_state[symbol]["1m_swing_lows"].pop(0)
        
        if interval == "Min15" and len(history) >= 5:
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                self.market_state[symbol]["15m_swing_high"] = history[-3]["h"]
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                self.market_state[symbol]["15m_swing_low"] = history[-3]["l"]
                
        if interval == "Min60" and len(history) >= 5:
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                self.market_state[symbol]["1h_swing_high"] = history[-3]["h"]
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                self.market_state[symbol]["1h_swing_low"] = history[-3]["l"]

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
            if name == "SA_Level_Scalp" and regime != "Chop":
                score += 35 * regime_conf
            if name == "SB_Level_Guardian" and regime == "Chop":
                score += 35 * regime_conf

            # ── Global context bonuses ──────────────────────────────────────
            if htf_aligned:      score += 10  # Always reward HTF alignment
            if in_prime_session: score += 8   # Prime session is higher quality

            # ── Tiebreaker: slight preference for regime-matched strategy ───
            if (regime != "Chop" and name == "SA_Level_Scalp") or \
               (regime == "Chop" and name == "SB_Level_Guardian"):
                score += 5

            scores_log[name] = round(score, 1)

            if score > best_score:
                best_score    = score
                best_strategy = strategy

        logger.info(f"[{symbol}] Strategy scores ({direction}): {scores_log}")

        # Final fallback: if everything got disqualified, use regime default
        if best_strategy is None:
            fallback_name = "SB_Level_Guardian" if regime == "Chop" else "SA_Level_Scalp"
            best_strategy = next(
                (s for s in self.active_strategies if s["name"] == fallback_name),
                self.active_strategies[0]
            )
            best_score = 0
            logger.info(f"[{symbol}] All strategies disqualified — fallback to {fallback_name}")

        logger.info(f"[{symbol}] SELECTED strategy: {best_strategy['name']} (score: {best_score:.1f})")
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

        if len(history) < 60:
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

        vol_threshold = 1.1 if in_prime_session else 1.3
        vol_surge = c_vol > (vol_threshold * avg_vol)
        state["vol_ok"] = vol_surge

        if d1_high > 0 and d1_low > 0:
            daily_range_pct = (d1_high - d1_low) / d1_low
            state["high_volatility_day"] = daily_range_pct > 0.025
        else:
            state["high_volatility_day"] = False

        # Multi-Level Liquidity Map
        valid_highs = [
            ("1D", state.get("1d_high", 0)),
            ("4H", state.get("4h_session_high", 0)),
            ("1H", state.get("1h_swing_high", 0)),
            ("15m", state.get("15m_swing_high", 0))
        ]
        valid_lows = [
            ("1D", state.get("1d_low", 0)),
            ("4H", state.get("4h_session_low", 0)),
            ("1H", state.get("1h_swing_low", 0)),
            ("15m", state.get("15m_swing_low", 0))
        ]
        
        valid_highs = [x for x in valid_highs if x[1] > 0]
        valid_lows = [x for x in valid_lows if x[1] > 0]
        
        # Sort by proximity to current price
        valid_highs.sort(key=lambda x: abs(c_close - x[1]))
        valid_lows.sort(key=lambda x: abs(c_close - x[1]))

        closest_high = valid_highs[0][1] if valid_highs else 0.0
        closest_low = valid_lows[0][1] if valid_lows else 0.0

        vol_velocity = c_vol / avg_vol if avg_vol > 0 else 1.0
        dist_high = abs(c_close - closest_high) / closest_high if closest_high > 0 else 1.0
        dist_low  = abs(c_close - closest_low)  / closest_low  if closest_low  > 0 else 1.0
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

        regime_name, regime_conf = self.hmm_engine.predict_regime(current_features)
        state["regime"] = regime_name
        state["regime_conf"] = regime_conf
        
        import time
        now = time.time()
        if (len(state["hmm_features"]) >= 1000 
                and not self.hmm_engine.is_training 
                and now - self.last_hmm_train_time > self.HMM_RETRAIN_INTERVAL):
            self.hmm_engine.retrain(state["hmm_features"])
            self.last_hmm_train_time = now
            
        state["regime_reliable"] = getattr(self.hmm_engine, "converged", False)

        last_seen_t = state.get("last_seen_candle_t")
        if last_seen_t != current_candle["t"]:
            state["intrabar_signal_taken"] = False
            state["last_seen_candle_t"] = current_candle["t"]
            
        if is_historical:
            return

        # ── Setup state machine ──
        if current_candle.get("is_closed", False):
            setup_state = state.get("setup_state", "WAITING")

            if setup_state in ["TRADED_HIGH", "SWEPT_HIGH", "SHORT_SETUP_FORMED"]:
                lvl = state.get("active_sweep_level", 0.0)
                if lvl > 0 and c_close < lvl and c_open < lvl:
                    state["setup_state"] = "WAITING"
            elif setup_state in ["TRADED_LOW", "SWEPT_LOW", "LONG_SETUP_FORMED"]:
                lvl = state.get("active_sweep_level", 0.0)
                if lvl > 0 and c_close > lvl and c_open > lvl:
                    state["setup_state"] = "WAITING"

            setup_state = state.get("setup_state", "WAITING")

            if setup_state == "WAITING":
                # Detect Sweeps against all valid levels
                for l_type, l_val in valid_highs:
                    if c_high > l_val:
                        state["setup_state"] = "SWEPT_HIGH"
                        state["active_sweep_level"] = l_val
                        state["active_sweep_type"] = l_type
                        state["sweep_wick_extreme"] = c_high
                        # Liquidity TP target = nearest valid low
                        state["target_tp"] = valid_lows[0][1] if valid_lows else c_low * 0.99
                        break

                if state["setup_state"] == "WAITING":
                    for l_type, l_val in valid_lows:
                        if c_low < l_val:
                            state["setup_state"] = "SWEPT_LOW"
                            state["active_sweep_level"] = l_val
                            state["active_sweep_type"] = l_type
                            state["sweep_wick_extreme"] = c_low
                            state["target_tp"] = valid_highs[0][1] if valid_highs else c_high * 1.01
                            break

                # EMA Pullback with Level Confluence
                ema20_15m = state.get("15m_ema20", 0)
                is_15m_bullish = state.get("15m_bullish", False)
                if ema20_15m > 0:
                    # Confluence check: is EMA near a valid level? (within 0.15%)
                    near_level_long = any(abs(ema20_15m - l_val)/ema20_15m < 0.0015 for _, l_val in valid_lows)
                    near_level_short = any(abs(ema20_15m - l_val)/ema20_15m < 0.0015 for _, l_val in valid_highs)
                    
                    if is_15m_bullish and c_low <= ema20_15m and c_high > ema20_15m and near_level_long:
                        state["setup_state"] = "LONG_SETUP_FORMED"
                        state["setup_candle"] = current_candle
                        state["ttl"] = 5
                        state["target_tp"] = valid_highs[0][1] if valid_highs else c_high * 1.002
                        state["sweep_wick_extreme"] = c_low
                    elif not is_15m_bullish and c_high >= ema20_15m and c_low < ema20_15m and near_level_short:
                        state["setup_state"] = "SHORT_SETUP_FORMED"
                        state["setup_candle"] = current_candle
                        state["ttl"] = 5
                        state["target_tp"] = valid_lows[0][1] if valid_lows else c_low * 0.998
                        state["sweep_wick_extreme"] = c_high

            setup_state = state.get("setup_state", "WAITING")

            if setup_state == "SWEPT_HIGH":
                if is_red:
                    candle_range = c_high - c_low
                    candle_body  = abs(c_close - c_open)
                    if candle_range > 0:
                        wick_size = c_high - max(c_open, c_close)
                        wick_ratio = wick_size / candle_range
                        
                        lvl = state.get("active_sweep_level", 0.0)
                        closed_below = c_close < lvl
                        
                        # Rejection criteria: wick >= 50% or body very small, closed below level, vol surge
                        if wick_ratio >= 0.5 and closed_below and vol_surge:
                            state["setup_state"] = "SHORT_SETUP_FORMED"
                            state["setup_candle"] = current_candle
                            state["ttl"] = 5
                            if c_high > state["sweep_wick_extreme"]:
                                state["sweep_wick_extreme"] = c_high
                        else:
                            if c_high > state["sweep_wick_extreme"]:
                                state["sweep_wick_extreme"] = c_high

            elif setup_state == "SWEPT_LOW":
                if is_green:
                    candle_range = c_high - c_low
                    candle_body  = abs(c_close - c_open)
                    if candle_range > 0:
                        wick_size = min(c_open, c_close) - c_low
                        wick_ratio = wick_size / candle_range
                        
                        lvl = state.get("active_sweep_level", 0.0)
                        closed_above = c_close > lvl
                        
                        if wick_ratio >= 0.5 and closed_above and vol_surge:
                            state["setup_state"] = "LONG_SETUP_FORMED"
                            state["setup_candle"] = current_candle
                            state["ttl"] = 5
                            if c_low < state["sweep_wick_extreme"]:
                                state["sweep_wick_extreme"] = c_low
                        else:
                            if c_low < state["sweep_wick_extreme"]:
                                state["sweep_wick_extreme"] = c_low

            elif setup_state == "SHORT_SETUP_FORMED":
                state["ttl"] = state.get("ttl", 5) - 1
                if state["ttl"] <= 0:
                    state["setup_state"] = "WAITING"

            elif setup_state == "LONG_SETUP_FORMED":
                state["ttl"] = state.get("ttl", 5) - 1
                if state["ttl"] <= 0:
                    state["setup_state"] = "WAITING"

        setup_state = state.get("setup_state", "WAITING")
        trigger_direction = None

        # MSS (Market Structure Shift) Execution (INTRABAR OR CLOSE)
        # We need a break of the most recent 1m swing low/high
        if setup_state == "SHORT_SETUP_FORMED" and not state.get("intrabar_signal_taken"):
            m1_lows = state.get("1m_swing_lows", [])
            recent_low = m1_lows[-1] if m1_lows else state.get("setup_candle", {}).get("l", 0) * 0.9995
            if current_candle["c"] < recent_low:
                trigger_direction = "SHORT"
                state["setup_state"] = "TRADED_HIGH"
                state["intrabar_signal_taken"] = True

        elif setup_state == "LONG_SETUP_FORMED" and not state.get("intrabar_signal_taken"):
            m1_highs = state.get("1m_swing_highs", [])
            recent_high = m1_highs[-1] if m1_highs else state.get("setup_candle", {}).get("h", float('inf')) * 1.0005
            if current_candle["c"] > recent_high:
                trigger_direction = "LONG"
                state["setup_state"] = "TRADED_LOW"
                state["intrabar_signal_taken"] = True

        if trigger_direction:
            if self.filter_killzone and not in_any_session: return
            if self.filter_volume and not vol_surge: return
            if self.filter_pressure:
                pressure = self.trade_data.get(symbol, {}).get("pressure_direction", "NEUTRAL")
                if pressure == "NEUTRAL": return

            if state.get("high_volatility_day"):
                if trigger_direction == "SHORT" and not htf_bearish: return
                if trigger_direction == "LONG" and not htf_bullish: return

            funding_rate = state.get("funding_rate", 0.0001)
            EXTREME_FUNDING = 0.0003
            if abs(funding_rate) > EXTREME_FUNDING:
                if funding_rate > 0 and trigger_direction == "LONG": return
                if funding_rate < 0 and trigger_direction == "SHORT": return

            import uuid
            setup_id = str(uuid.uuid4())
            setup_candle = state.get("setup_candle")

            regime = state.get("regime", "Chop")
            if regime == "Liquidation Cascade":
                if trigger_direction == "SHORT" and htf_bullish: return
                if trigger_direction == "LONG" and htf_bearish: return

            dist_approx = 0.001

            strategy, strategy_score = self._select_best_strategy(
                symbol, trigger_direction, state,
                self.trade_data.get(symbol, {}),
                c_high, c_low, price, dist_approx
            )
            strategy_name = strategy["name"]

            already_signaled = any(s.get("timestamp_ms") == current_candle["t"] and s.get("strategy") == strategy_name for s in self.signal_history)
            if not (already_signaled or is_historical):
                valid = True
                if trigger_direction == "SHORT":
                    if strategy["htf"] and not htf_bearish: valid = False
                    if self.filter_htf and not htf_bearish: valid = False
                    if strategy["atr_filter"] and c_high - c_low > price * 0.0015: valid = False
                    if strategy["delta"] and self.trade_data.get(symbol, {}).get("delta", 0) > 0: valid = False
                else:
                    if strategy["htf"] and not htf_bullish: valid = False
                    if self.filter_htf and not htf_bullish: valid = False
                    if strategy["atr_filter"] and c_high - c_low > price * 0.0015: valid = False
                    if strategy["delta"] and self.trade_data.get(symbol, {}).get("delta", 0) < 0: valid = False

                if valid:
                    stats = self.risk_engine.calculate_historical_stats(self.signal_history, strategy_name, trigger_direction)
                    ev = self.risk_engine.calculate_ev(stats["win_rate"], stats["avg_win"], stats["avg_loss"])
                    n_trades = stats.get("n_trades", 0)
                    if not (ev <= 0 and n_trades >= 15 and not is_historical):
                        hmm_conf = state.get("regime_conf", 0.5)
                        kelly_fraction = self.risk_engine.calculate_kelly_fraction(stats["win_rate"], stats["avg_win"], stats["avg_loss"], hmm_conf)
                        await self._trigger_signal(symbol, trigger_direction, current_candle, setup_candle, avg_vol, state["target_tp"], strategy, setup_id, kelly_fraction, entry_type="sweep")

        if current_candle.get("is_closed"):
            state["ema_cross_signal_taken"] = False
    async def _trigger_signal(self, symbol, direction, trigger_candle, setup_candle, avg_vol, target_tp, strategy=None, setup_id=None, kelly_fraction=1.0, entry_type="sweep"):
        MAX_PER_SYMBOL = 2
        MAX_TOTAL = 10
        open_symbol = sum(1 for s in self.signal_history if s.get("status") == "PENDING" and s.get("symbol") == symbol)
        open_total  = sum(1 for s in self.signal_history if s.get("status") == "PENDING")
        if open_symbol >= MAX_PER_SYMBOL or open_total >= MAX_TOTAL:
            return

        if strategy is None:
            strategy = {"name": "SA_Level_Scalp", "leverage": 400, "scale_out": False, "fixed_tp_pct": True, "tp_pct": 0.0015}
        strategy_name = strategy["name"]
        
        trade_state = self.market_state.get(symbol, {})
        BUFFER = 0.0005 # 0.05% buffer

        # Structural SL based on the wick extreme
        wick_extreme = trade_state.get("sweep_wick_extreme", 0.0)
        
        if direction == "SHORT":
            base_sl = wick_extreme * (1 + BUFFER) if wick_extreme > 0 else trigger_candle["c"] * (1 + 0.0020)
            dist_pct = (base_sl - trigger_candle["c"]) / trigger_candle["c"]
        else:
            base_sl = wick_extreme * (1 - BUFFER) if wick_extreme > 0 else trigger_candle["c"] * (1 - 0.0020)
            dist_pct = (trigger_candle["c"] - base_sl) / trigger_candle["c"]

        sl = base_sl
        
        MIN_SL_DISTANCE = 0.0008  # 0.08%
        if dist_pct < MIN_SL_DISTANCE and not strategy.get("no_sl"):
            # We don't abort, we just pad the SL so we don't get chopped by fees
            if direction == "SHORT":
                sl = trigger_candle["c"] * (1 + MIN_SL_DISTANCE)
            else:
                sl = trigger_candle["c"] * (1 - MIN_SL_DISTANCE)
            dist_pct = MIN_SL_DISTANCE

        # Dynamic TP based on Liquidity Targets
        # The target_tp passed from _evaluate_1m_logic is the nearest unswept level
        if direction == "SHORT":
            risk = sl - trigger_candle["c"]
            if strategy.get("fixed_tp_pct"):
                tp_pct = strategy.get("tp_pct", 0.0015)
                tp = trigger_candle["c"] * (1 - tp_pct)
                tp1 = trigger_candle["c"] * (1 - (tp_pct / 2.0))
            else:
                tp = min(target_tp, trigger_candle["c"] - (1.5 * risk)) # At least 1.5R or the structural target
                tp1 = trigger_candle["c"] - risk
        else:
            risk = trigger_candle["c"] - sl
            if strategy.get("fixed_tp_pct"):
                tp_pct = strategy.get("tp_pct", 0.0015)
                tp = trigger_candle["c"] * (1 + tp_pct)
                tp1 = trigger_candle["c"] * (1 + (tp_pct / 2.0))
            else:
                tp = max(target_tp, trigger_candle["c"] + (1.5 * risk))
                tp1 = trigger_candle["c"] + risk

        vol_ratio = trigger_candle.get("v", 0) / avg_vol if avg_vol > 0 else 0

        context = {
            "symbol": symbol,
            "direction": direction,
            "entry": trigger_candle["c"],
            "sl": sl,
            "tp": tp,
        }

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
        logger.info(f"SIGNAL TRIGGERED: {signal}")
        
        if strategy.get("leverage") == "auto":
            computed_leverage = max(10, min(50, int((1.0 / dist_pct) * 0.8))) if dist_pct > 0 else 50
        else:
            computed_leverage = int(strategy.get("leverage", 400))

        strategy_metric = f"{computed_leverage}x Lev | SL: {(dist_pct*100):.2f}%"

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
            "initial_margin": 6.0,
            "margin": 6.0,
            "avg_vol": avg_vol,
            "margin_adds": 0
        }
        self.signal_history.append(hist_signal)
        
        import asyncio
        import copy
        if hasattr(self, 'sheets_client'):
            asyncio.create_task(asyncio.to_thread(self.sheets_client.append_trade, copy.deepcopy(hist_signal)))
        self._save_history()
        
        if self.shihab_active and self.mexc_client:
            logger.info(f"SHIHAB AUTO-TRADER is placing order for {symbol} {direction}")
            await self.mexc_client.submit_order(symbol, direction, context["entry"], sl, tp)
            
        if self.shihab_demo_active:
            MAX_CONCURRENT_POSITIONS = 10
            if len(self.demo_positions) >= MAX_CONCURRENT_POSITIONS:
                logger.warning(f"[{symbol}] DEMO LIMIT: {len(self.demo_positions)} demo positions open >= max {MAX_CONCURRENT_POSITIONS}.")
            else:
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
                    logger.info(f"DEMO SHIHAB opened virtual {direction} on {symbol} with Margin ${invest_amount} @ {computed_leverage}x")

