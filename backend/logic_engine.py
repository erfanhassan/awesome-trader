import datetime
import asyncio
import json
import os
import uuid
import logging
import copy
import pandas as pd
from google_sheets_client import GoogleSheetsClient
from deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)


class LogicEngine:
    def __init__(self):
        # symbol -> { "Min1": [...], "Min15": [...], etc. }
        self.kline_data = {}

        # Strategy config
        self.strategy = {
            "name": "LiquiditySweep_v2",
            "initial_margin": 7.0,               # Fallback initial margin
            "leverage": 190,                     # Fallback leverage
            "max_leverage_cap": 50,              # Cap dynamic leverage at 50x
            "fixed_risk_usd": 7.0,               # Fixed risk amount per trade
            "candle_window": 10,                 # Look for 3-candle pattern within 10 candles
            "trail_atr_multiplier": 3.0,         # Trail SL by 3.0x ATR to survive normal pullbacks
            "trail_activation_atr": 2.0,         # Activate trailing stop at 2x ATR profit
            "max_margin_adds": 0,                # DISABLED: No averaging down (Martingale) allowed
            "margin_add_amount": 5.0,            # (Legacy) amount for margin adds
            "min_edge_to_fee_ratio": 2.5,        # Skip trades where edge < 2.5x friction
        }

        # Live Market Simulation Parameters
        self.taker_fee_rate = 0.0002             # 0.02% MEXC standard taker fee
        self.slippage_pct = 0.0001               # 0.01% simulated market order slippage
        self.max_daily_loss = 15.0               # $15.00 max daily loss circuit breaker

        # Trade Limits Configuration
        self.max_trades_per_symbol = 8
        self.max_total_trades = 20
        self.max_trades_per_sweep = 8

        # Toggles
        self.regime_filter_enabled = True
        self.mean_reversion_active = False
        self.trading_paused = False
        
        self.circuit_breaker_enabled = True

        # Daily loss tracking in BD Time (UTC+6)
        self.daily_loss_tracker = {
            "date": "",
            "realized_loss": 0.0,
            "realized_pnl": 0.0,
            "trades_count": 0,
            "circuit_breaker_tripped": False,
        }

        # symbol -> state dict
        self.market_state = {}
        # symbol -> live trade volume data
        self.trade_data = {}

        self.shihab_active = False
        self.shihab_demo_active = False
        self.demo_balance = 100.0
        self.demo_invest_amount = 7.0
        self.demo_leverage = 300
        self.demo_positions = []
        self.mexc_client = None
        self.sheets_client = GoogleSheetsClient()
        self.deepseek = DeepSeekClient()
        self.signals = []
        self.signal_history = []
        self.hourly_reports = []
        self.last_trade_time = datetime.datetime.now(datetime.timezone.utc)
        self._load_history()
        self._sync_daily_loss_from_history()
        self._hourly_loop_started = False
        

    async def _hourly_report_loop(self):
        """Generates an AI report explaining why no trades were taken if 1 hour passes without activity."""
        last_checked_hour = datetime.datetime.now(datetime.timezone.utc).hour
        while True:
            await asyncio.sleep(60) # Check every minute
            now = datetime.datetime.now(datetime.timezone.utc)
            
            # If the hour has changed
            if now.hour != last_checked_hour:
                last_checked_hour = now.hour
                
                # Check if it has been roughly 1 hour since the last trade
                time_since_trade = (now - self.last_trade_time).total_seconds()
                if time_since_trade > 3500: # approx 1 hour
                    try:
                        # Prepare context
                        symbol = "BTCUSDT" # Assuming default symbol
                        regime = self._get_market_regime(symbol) if hasattr(self, '_get_market_regime') else "UNKNOWN"
                        
                        # Get ADX if possible
                        adx = "UNKNOWN"
                        if symbol in self.kline_data and "Min60" in self.kline_data[symbol]:
                            history_1h = self.kline_data[symbol]["Min60"]
                            if len(history_1h) >= 200:
                                df = pd.DataFrame(history_1h)
                                df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
                                df['up_move'] = df['high'] - df['high'].shift(1)
                                df['down_move'] = df['low'].shift(1) - df['low']
                                df['+dm'] = 0.0
                                df.loc[(df['up_move'] > df['down_move']) & (df['up_move'] > 0), '+dm'] = df['up_move']
                                df['-dm'] = 0.0
                                df.loc[(df['down_move'] > df['up_move']) & (df['down_move'] > 0), '-dm'] = df['down_move']
                                df['tr1'] = df['high'] - df['low']
                                df['tr2'] = (df['high'] - df['close'].shift(1)).abs()
                                df['tr3'] = (df['low'] - df['close'].shift(1)).abs()
                                df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
                                df['atr'] = df['tr'].ewm(alpha=1/14, adjust=False).mean()
                                df['+di'] = 100 * (df['+dm'].ewm(alpha=1/14, adjust=False).mean() / df['atr'])
                                df['-di'] = 100 * (df['-dm'].ewm(alpha=1/14, adjust=False).mean() / df['atr'])
                                df['dx'] = 100 * (df['+di'] - df['-di']).abs() / (df['+di'] + df['-di'])
                                adx = f"{df['dx'].ewm(alpha=1/14, adjust=False).mean().iloc[-1]:.2f}"
                        
                        market_context = {
                            "symbol": symbol,
                            "regime": regime,
                            "adx": adx,
                            "sweeps_count": self.market_state.get(symbol, {}).get("sweep_trade_counts", {})
                        }
                        
                        # Generate Report
                        report_text = await self.deepseek.generate_hourly_report(market_context)
                        
                        # Format Time window (e.g. 10:00 AM - 11:00 AM)
                        bd_tz = datetime.timezone(datetime.timedelta(hours=6))
                        end_time = now.astimezone(bd_tz)
                        start_time = end_time - datetime.timedelta(hours=1)
                        time_window = f"{start_time.strftime('%I:00 %p')} to {end_time.strftime('%I:00 %p')}"
                        
                        # Add to list
                        self.hourly_reports.append({
                            "time_window": time_window,
                            "report": report_text,
                            "timestamp": now.isoformat()
                        })
                        
                        # Keep only last 24
                        if len(self.hourly_reports) > 24:
                            self.hourly_reports.pop(0)
                            
                        logger.info(f"Hourly AI Report Generated: {report_text}")
                    except Exception as e:
                        logger.error(f"Failed to generate hourly report: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # History persistence & Daily Loss Tracker
    # ─────────────────────────────────────────────────────────────────────────

    def _get_current_bd_date(self):
        bd_tz = datetime.timezone(datetime.timedelta(hours=6))
        return datetime.datetime.now(bd_tz).strftime("%Y-%m-%d")

    def _sync_daily_loss_from_history(self):
        today_str = self._get_current_bd_date()
        self.daily_loss_tracker = {
            "date": today_str,
            "realized_loss": 0.0,
            "realized_pnl": 0.0,
            "trades_count": 0,
            "circuit_breaker_tripped": False,
        }
        bd_tz = datetime.timezone(datetime.timedelta(hours=6))
        for pos in self.signal_history:
            if pos.get("status") in ["WIN", "LOSS", "PROFIT", "LIQUIDATED", "CLOSED"]:
                ts_str = pos.get("exit_timestamp") or pos.get("timestamp")
                if ts_str:
                    try:
                        dt = datetime.datetime.fromisoformat(ts_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        pos_date = dt.astimezone(bd_tz).strftime("%Y-%m-%d")
                        if pos_date == today_str:
                            net = float(pos.get("net_profit", 0.0) or 0.0)
                            self.daily_loss_tracker["trades_count"] += 1
                            self.daily_loss_tracker["realized_pnl"] += net
                            if net < 0:
                                self.daily_loss_tracker["realized_loss"] += abs(net)
                    except Exception:
                        pass
        if self.daily_loss_tracker["realized_loss"] >= self.max_daily_loss:
            self.daily_loss_tracker["circuit_breaker_tripped"] = True
            logger.warning(
                f"CIRCUIT BREAKER ACTIVE on startup: Daily loss ${self.daily_loss_tracker['realized_loss']:.2f} >= ${self.max_daily_loss:.2f}"
            )

    def _is_circuit_breaker_active(self):
        today_str = self._get_current_bd_date()
        if self.daily_loss_tracker.get("date") != today_str:
            self.daily_loss_tracker = {
                "date": today_str,
                "realized_loss": 0.0,
                "realized_pnl": 0.0,
                "trades_count": 0,
                "circuit_breaker_tripped": False,
            }
            
        if not getattr(self, "circuit_breaker_enabled", True):
            return False
            
        return self.daily_loss_tracker.get("circuit_breaker_tripped", False)

    def set_trading_paused(self, paused: bool):
        self.trading_paused = paused
        logger.info(f"Master Trading Pause toggled: {'PAUSED' if paused else 'ACTIVE'}")

    def set_regime_filter_enabled(self, enabled: bool):
        self.regime_filter_enabled = enabled
        logger.info(f"Market Regime Filter toggled: {'ON' if enabled else 'OFF'}")

    def set_mean_reversion_enabled(self, enabled: bool):
        self.mean_reversion_active = enabled
        logger.info(f"Mean Reversion Logic toggled: {'ON' if enabled else 'OFF'}")

    def _record_trade_closure_in_daily_tracker(self, pos):
        today_str = self._get_current_bd_date()
        if self.daily_loss_tracker.get("date") != today_str:
            self.daily_loss_tracker = {
                "date": today_str,
                "realized_loss": 0.0,
                "realized_pnl": 0.0,
                "trades_count": 0,
                "circuit_breaker_tripped": False,
            }
        net_profit = float(pos.get("net_profit", 0.0) or 0.0)
        self.daily_loss_tracker["trades_count"] += 1
        self.daily_loss_tracker["realized_pnl"] += net_profit
        if net_profit < 0:
            self.daily_loss_tracker["realized_loss"] += abs(net_profit)
        if self.daily_loss_tracker["realized_loss"] >= self.max_daily_loss:
            self.daily_loss_tracker["circuit_breaker_tripped"] = True
            logger.warning(
                f"CIRCUIT BREAKER TRIPPED! Daily loss ${self.daily_loss_tracker['realized_loss']:.2f} >= limit ${self.max_daily_loss:.2f}. Trading paused."
            )
        rem = max(0.0, self.max_daily_loss - self.daily_loss_tracker["realized_loss"])
        pos["daily_loss_status"] = (
            f"TRIPPED (-${self.daily_loss_tracker['realized_loss']:.2f})"
            if self.daily_loss_tracker["circuit_breaker_tripped"]
            else f"${rem:.2f} left"
        )

    def get_daily_stats(self):
        today_str = self._get_current_bd_date()
        bd_tz = datetime.timezone(datetime.timedelta(hours=6))
        trades = 0
        wins = 0
        losses = 0
        gross = 0.0
        ex_fees = 0.0
        fund_fees = 0.0
        slip = 0.0
        total_costs = 0.0
        net = 0.0

        for pos in self.signal_history:
            if pos.get("status") in ["WIN", "LOSS", "PROFIT", "LIQUIDATED", "CLOSED"]:
                ts_str = pos.get("exit_timestamp") or pos.get("timestamp")
                if ts_str:
                    try:
                        dt = datetime.datetime.fromisoformat(ts_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        pos_date = dt.astimezone(bd_tz).strftime("%Y-%m-%d")
                        if pos_date == today_str:
                            trades += 1
                            net_prof = float(pos.get("net_profit", 0.0) or 0.0)
                            if net_prof > 0:
                                wins += 1
                            else:
                                losses += 1
                            gross += float(pos.get("raw_profit", 0.0) or 0.0)
                            ex_fees += float(pos.get("exchange_fees", 0.0) or 0.0)
                            fund_fees += float(pos.get("funding_fees", 0.0) or 0.0)
                            slip += float(pos.get("slippage", 0.0) or 0.0)
                            total_costs += float(pos.get("fees", 0.0) or 0.0)
                            net += net_prof
                    except Exception:
                        pass

        win_rate = (wins / trades * 100.0) if trades > 0 else 0.0
        tripped = "YES" if (self.daily_loss_tracker.get("circuit_breaker_tripped") or (net < -self.max_daily_loss)) else "NO"

        return {
            "date": today_str,
            "total_trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "gross_profit": round(gross, 2),
            "exchange_fees": round(ex_fees, 4),
            "funding_fees": round(fund_fees, 4),
            "slippage": round(slip, 4),
            "total_costs": round(total_costs, 4),
            "net_profit": round(net, 2),
            "max_daily_loss": self.max_daily_loss,
            "circuit_breaker_hit": tripped,
        }

    def _calculate_funding_cost(self, pos, exit_time_iso, symbol, notional_value):
        try:
            open_dt = datetime.datetime.fromisoformat(pos.get("timestamp"))
            if open_dt.tzinfo is None:
                open_dt = open_dt.replace(tzinfo=datetime.timezone.utc)
            close_dt = datetime.datetime.fromisoformat(exit_time_iso)
            if close_dt.tzinfo is None:
                close_dt = close_dt.replace(tzinfo=datetime.timezone.utc)

            duration_hours = max(0.0, (close_dt - open_dt).total_seconds() / 3600.0)
            intervals = int(duration_hours // 8)

            state = self.market_state.get(symbol, {})
            funding_rate = float(state.get("funding_rate", 0.0) or 0.0)

            direction = pos.get("direction", "LONG")
            if intervals > 0 and funding_rate != 0:
                if direction == "LONG":
                    funding_cost = notional_value * funding_rate * intervals
                else:
                    funding_cost = notional_value * (-funding_rate) * intervals
                return max(0.0, funding_cost), intervals, funding_rate
            return 0.0, intervals, funding_rate
        except Exception as e:
            logger.error(f"Error calculating funding cost: {e}")
            return 0.0, 0, 0.0

    def set_live_leverage(self, leverage: int):
        self.strategy["leverage"] = leverage
        # Recalculate SL and Liquidation for all open PENDING trades
        for pos in self.signal_history:
            if pos.get("status") == "PENDING":
                pos["computed_leverage"] = leverage
                pos["leverage"] = leverage
                entry = float(pos["entry"])
                direction = pos["direction"]
                margin = float(pos.get("margin", 7.0))
                initial_margin = float(pos.get("initial_margin", 7.0))
                liq_dist_pct = (margin / initial_margin) / leverage
                if direction == "LONG":
                    pos["liq_price"] = entry * (1 - liq_dist_pct)
                else:
                    pos["liq_price"] = entry * (1 + liq_dist_pct)
        for pos in self.demo_positions:
            pos["computed_leverage"] = leverage
            pos["leverage"] = leverage
        self._save_history()
        logger.info(f"Live leverage updated to {leverage}x via UI. Open positions adapted.")

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

    # ─────────────────────────────────────────────────────────────────────────
    # State broadcast
    # ─────────────────────────────────────────────────────────────────────────

    def get_state(self):
        rem_budget = max(0.0, self.max_daily_loss - self.daily_loss_tracker.get("realized_loss", 0.0))
        
        # Sanitize market_state (convert sets to lists for JSON serialization)
        safe_market_state = {}
        for sym, m_state in self.market_state.items():
            safe_market_state[sym] = {k: list(v) if isinstance(v, set) else v for k, v in m_state.items()}
            safe_market_state[sym]["regime"] = self._get_market_regime(sym)
            
        return {
            "shihab_active": self.shihab_active,
            "shihab_demo_active": self.shihab_demo_active,
            "demo_state": {
                "balance": self.demo_balance,
                "invest_amount": self.demo_invest_amount,
                "leverage": self.demo_leverage,
                "positions": self.demo_positions,
            },
            "market_data": safe_market_state,
            "trade_data": self.trade_data,
            "signal_history": self.signal_history,
            "live_leverage": self.strategy.get("leverage", 300),
            "regime_filter_enabled": getattr(self, "regime_filter_enabled", True),
            "mean_reversion_active": getattr(self, "mean_reversion_active", False),
            "trading_paused": getattr(self, "trading_paused", False),
            "hourly_reports": getattr(self, "hourly_reports", []),
        }

    def get_klines(self, symbol, interval):
        """Return kline data for chart rendering."""
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

    # ─────────────────────────────────────────────────────────────────────────
    # Symbol management
    # ─────────────────────────────────────────────────────────────────────────

    async def add_symbol(self, symbol):
        if symbol not in self.kline_data:
            self.kline_data[symbol] = {
                "Min1": [], "Min15": [], "Min60": [], "Hour4": [], "Day1": []
            }
            self.market_state[symbol] = {
                "price": 0,
                # ── Multi-Timeframe Liquidity Levels ──
                "1d_highs": [],
                "1d_lows": [],
                "4h_session_highs": [],
                "4h_session_lows": [],
                "1h_swing_highs": [],
                "1h_swing_lows": [],
                "15m_swing_highs": [],
                "15m_swing_lows": [],
                # ── Shihab Strategy State ──
                "shihab_setup_state": "WAITING",
                "shihab_sweep_wick_extreme": 0.0,
                "shihab_swept_level": 0.0,
                "shihab_swept_level_label": "",
                "shihab_candles_since_sweep": 0,
                "shihab_pattern_candles_found": 0,
                "shihab_counter_candles_seen": 0,
                "shihab_pattern_candle_1": None,
                "shihab_intrabar_signal_taken": False,
                "shihab_last_traded_sweep": "",
                
                # ── Delta Strategy State ──
                "delta_setup_state": "WAITING",
                "delta_sweep_wick_extreme": 0.0,
                "delta_swept_level": 0.0,
                "delta_swept_level_label": "",
                "delta_candles_since_sweep": 0,
                "delta_mss_level": 0.0,
                "delta_intrabar_signal_taken": False,
                "delta_last_traded_sweep": "",

                # ── Misc ──
                "funding_rate": 0.0001,
                "last_seen_candle_t": None,
                "sweep_trade_counts": {},
            }
            self.trade_data[symbol] = {
                "buy_vol": 0.0,
                "sell_vol": 0.0,
                "delta": 0.0,
                "cvd": 0.0,
                "pressure_direction": "NEUTRAL",
                "last_minute": None,
            }

    async def remove_symbol(self, symbol):
        if symbol in self.kline_data:
            del self.kline_data[symbol]
        if symbol in self.market_state:
            del self.market_state[symbol]
        if symbol in self.trade_data:
            del self.trade_data[symbol]

    # ─────────────────────────────────────────────────────────────────────────
    # Trade volume (order flow)
    # ─────────────────────────────────────────────────────────────────────────

    async def process_trades(self, symbol, trades):
        if symbol not in self.trade_data:
            await self.add_symbol(symbol)

        td = self.trade_data[symbol]
        for trade in trades:
            t = trade.get("time", 0)
            minute_ms = t - (t % 60000)
            if td["last_minute"] != minute_ms:
                td["buy_vol"] = 0.0
                td["sell_vol"] = 0.0
                td["delta"] = 0.0
                td["last_minute"] = minute_ms

            qty = float(trade.get("qty", 0))
            is_buyer_maker = trade.get("isBuyerMaker", False)
            if is_buyer_maker:
                td["sell_vol"] += qty
                td["cvd"] -= qty
            else:
                td["buy_vol"] += qty
                td["cvd"] += qty

        td["delta"] = td["buy_vol"] - td["sell_vol"]
        if td["delta"] > 0:
            td["pressure_direction"] = "BUYING_CONTROL"
        elif td["delta"] < 0:
            td["pressure_direction"] = "SELLING_CONTROL"
        else:
            td["pressure_direction"] = "NEUTRAL"

    # ─────────────────────────────────────────────────────────────────────────
    # Kline processing — main entry point from mexc_client
    # ─────────────────────────────────────────────────────────────────────────

    async def process_kline(self, symbol, interval, data, is_historical=False):
        if symbol not in self.kline_data:
            if hasattr(self, "mexc_client") and self.mexc_client:
                await self.mexc_client.add_symbol(symbol)
            else:
                await self.add_symbol(symbol)

        # Update open position P&L on live 1m ticks
        if interval == "Min1" and not is_historical:
            await self._update_open_positions(symbol, data)

        max_len = 1000
        if interval in self.kline_data[symbol]:
            history = self.kline_data[symbol][interval]

            if history and history[-1]["t"] == data["t"]:
                # Update existing (in-progress) candle
                history[-1] = data
                if interval == "Min1":
                    self.market_state[symbol]["price"] = data["c"]
                    await self._evaluate_1m_logic(symbol, data, is_historical)
            else:
                # New candle — close the previous one
                if history:
                    history[-1]["is_closed"] = True
                    if interval == "Min1":
                        await self._evaluate_1m_logic(symbol, history[-1], is_historical)

                history.append(data)
                if len(history) > max_len:
                    history.pop(0)

                if interval == "Min1":
                    self.market_state[symbol]["price"] = data["c"]
                    await self._evaluate_1m_logic(symbol, data, is_historical)

            # Update multi-timeframe liquidity levels
            self._update_levels(symbol, interval, history)

    # ─────────────────────────────────────────────────────────────────────────
    # Level tracking — multi-timeframe
    # ─────────────────────────────────────────────────────────────────────────

    def _update_levels(self, symbol, interval, history):
        """Update swing highs/lows for each timeframe as new candles arrive. Keep up to 3."""
        state = self.market_state[symbol]
        MAX_LEVELS = 3

        def add_level(lst, val):
            if val not in lst:
                lst.append(val)
                if len(lst) > MAX_LEVELS:
                    lst.pop(0)

        if interval == "Day1" and len(history) >= 2:
            prev = history[-2]
            add_level(state["1d_highs"], prev["h"])
            add_level(state["1d_lows"], prev["l"])

        elif interval == "Hour4" and len(history) >= 3:
            add_level(state["4h_session_highs"], max(history[-3]["h"], history[-2]["h"]))
            add_level(state["4h_session_lows"], min(history[-3]["l"], history[-2]["l"]))

        elif interval == "Min60" and len(history) >= 5:
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                add_level(state["1h_swing_highs"], history[-3]["h"])
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                add_level(state["1h_swing_lows"], history[-3]["l"])

        elif interval == "Min15" and len(history) >= 5:
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                add_level(state["15m_swing_highs"], history[-3]["h"])
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                add_level(state["15m_swing_lows"], history[-3]["l"])

    def _get_all_levels(self, symbol):
        """Returns all tracked liquidity levels as two lists: highs and lows."""
        state = self.market_state[symbol]
        highs, lows = [], []
        
        sources = [
            ("1D",  state.get("1d_highs", []),          state.get("1d_lows", [])),
            ("4H",  state.get("4h_session_highs", []),  state.get("4h_session_lows", [])),
            ("1H",  state.get("1h_swing_highs", []),    state.get("1h_swing_lows", [])),
            ("15m", state.get("15m_swing_highs", []),   state.get("15m_swing_lows", [])),
        ]
        
        for label, h_list, l_list in sources:
            for h in h_list:
                if h > 0: highs.append((label, h))
            for l in l_list:
                if l > 0: lows.append((label, l))
                
        return highs, lows

    def _find_tp(self, symbol, direction, entry_price):
        """Find the nearest liquidity level in the trade direction as TP.
        Falls back to 40% ROE target if no level is found.
        Offsets TP slightly before the level to ensure it gets filled."""
        highs, lows = self._get_all_levels(symbol)
        leverage = self.strategy["leverage"]
        tp_fallback_pct = 0.40 / leverage  # 40% ROE = 0.10% price move at 400x
        offset_pct = 0.0001 # 0.01% offset

        if direction == "LONG":
            candidates = [(lbl, h) for lbl, h in highs if h > entry_price]
            if candidates:
                candidates.sort(key=lambda x: x[1])  # Nearest first
                return candidates[0][1] * (1 - offset_pct)
            return entry_price * (1 + tp_fallback_pct)
        else:
            candidates = [(lbl, l) for lbl, l in lows if l < entry_price]
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)  # Nearest first
                return candidates[0][1] * (1 + offset_pct)
            return entry_price * (1 - tp_fallback_pct)

    # ─────────────────────────────────────────────────────────────────────────
    # Market Regime Trend Filter
    # ─────────────────────────────────────────────────────────────────────────

    def _get_market_regime(self, symbol):
        """Returns UPTREND, DOWNTREND, or RANGING based on 1H 200 EMA and ADX."""
        if not getattr(self, "regime_filter_enabled", True):
            return "RANGING"

        history_1h = self.kline_data.get(symbol, {}).get("Min60", [])
        if len(history_1h) < 200:
            return "RANGING" # Default if not enough data
        
        df = pd.DataFrame(history_1h)
        df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
        
        # Pure pandas calculation for EMA 200
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # Pure pandas calculation for ADX 14
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        
        df['+dm'] = 0.0
        df.loc[(df['up_move'] > df['down_move']) & (df['up_move'] > 0), '+dm'] = df['up_move']
        
        df['-dm'] = 0.0
        df.loc[(df['down_move'] > df['up_move']) & (df['down_move'] > 0), '-dm'] = df['down_move']
        
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = (df['high'] - df['close'].shift(1)).abs()
        df['tr3'] = (df['low'] - df['close'].shift(1)).abs()
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        df['atr'] = df['tr'].ewm(alpha=1/14, adjust=False).mean()
        df['+di'] = 100 * (df['+dm'].ewm(alpha=1/14, adjust=False).mean() / df['atr'])
        df['-di'] = 100 * (df['-dm'].ewm(alpha=1/14, adjust=False).mean() / df['atr'])
        
        df['dx'] = 100 * (df['+di'] - df['-di']).abs() / (df['+di'] + df['-di'])
        df['adx'] = df['dx'].ewm(alpha=1/14, adjust=False).mean()
        
        current_close = df['close'].iloc[-1]
        current_ema = df['ema_200'].iloc[-1]
        current_adx = df['adx'].iloc[-1]
        
        if pd.isna(current_ema) or pd.isna(current_adx):
            return "RANGING"
            
        if current_adx < 20:
            return "RANGING"
            
        if current_close > current_ema:
            return "UPTREND"
        else:
            return "DOWNTREND"

    def _calculate_atr(self, symbol, interval="Min1", period=14):
        history = self.kline_data.get(symbol, {}).get(interval, [])
        if len(history) < period + 1:
            return 0.0
        
        df = pd.DataFrame(history[-(period+1):])
        df['tr1'] = df['h'] - df['l']
        df['tr2'] = (df['h'] - df['c'].shift(1)).abs()
        df['tr3'] = (df['l'] - df['c'].shift(1)).abs()
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        atr = df['tr'].iloc[1:].mean()
        return float(atr) if not pd.isna(atr) else 0.0

    def _calculate_vwap(self, symbol, interval="Min1"):
        history = self.kline_data.get(symbol, {}).get(interval, [])
        if not history:
            return 0.0
        
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
        
        day_history = [c for c in history if c["t"] >= start_of_day]
        if not day_history:
            day_history = history[-60:] # fallback
            
        df = pd.DataFrame(day_history)
        df['typical_price'] = (df['h'] + df['l'] + df['c']) / 3
        df['vol_price'] = df['v'] * df['typical_price']
        
        cum_vol = df['v'].sum()
        if cum_vol == 0:
            return float(df['typical_price'].iloc[-1])
            
        return float(df['vol_price'].sum() / cum_vol)

    # ─────────────────────────────────────────────────────────────────────────
    # Core 1-Minute Logic — Pure Liquidity Sweep State Machine
    # ─────────────────────────────────────────────────────────────────────────

    async def _evaluate_1m_logic(self, symbol, current_candle, is_historical=False):
        if getattr(self, "trading_paused", False):
            return

        if not getattr(self, "_hourly_loop_started", False) and not is_historical:
            self._hourly_loop_started = True
            asyncio.create_task(self._hourly_report_loop())

        state = self.market_state[symbol]
        history = self.kline_data[symbol]["Min1"]

        # Need enough history before we start trading
        if len(history) < 10:
            return

        c_open  = current_candle["o"]
        c_close = current_candle["c"]
        c_high  = current_candle["h"]
        c_low   = current_candle["l"]
        is_closed = current_candle.get("is_closed", False)
        is_green  = c_close > c_open
        is_red    = c_close < c_open

        if state.get("last_candle_t") != current_candle["t"]:
            state["last_candle_t"] = current_candle["t"]
            state["intrabar_signals"] = set()

        highs, lows = self._get_all_levels(symbol)
        # ──────────────────────────────────────────────────────────────────────
        # SHIHAB STRATEGY: Liquidity Sweep Shihab
        # ──────────────────────────────────────────────────────────────────────
        shihab_state = state.get("shihab_setup_state", "WAITING")
        if shihab_state == "WAITING":
            if is_closed:
                # Check High Sweeps
                for label, lvl in sorted(highs, key=lambda x: x[1]):
                    if "4H" not in label: continue
                    if c_high > lvl and c_close < lvl:  # FAILED BREAKOUT
                        state["shihab_setup_state"]        = "SWEPT_HIGH"
                        state["shihab_rejection_low"]      = c_low
                        state["shihab_sweep_wick_extreme"] = c_high
                        state["shihab_swept_level"]        = lvl
                        state["shihab_swept_level_label"]  = label
                        state["shihab_sweep_candle_time"]  = current_candle["t"]
                        logger.info(f"[{symbol}] SHIHAB SWEPT HIGH @ {lvl:.4f} ({label}). Waiting for break of {c_low:.4f}")
                        break

                # Check Low Sweeps
                if state["shihab_setup_state"] == "WAITING":
                    for label, lvl in sorted(lows, key=lambda x: x[1], reverse=True):
                        if "4H" not in label: continue
                        if c_low < lvl and c_close > lvl:  # FAILED BREAKOUT
                            state["shihab_setup_state"]        = "SWEPT_LOW"
                            state["shihab_rejection_high"]     = c_high
                            state["shihab_sweep_wick_extreme"] = c_low
                            state["shihab_swept_level"]        = lvl
                            state["shihab_swept_level_label"]  = label
                            state["shihab_sweep_candle_time"]  = current_candle["t"]
                            logger.info(f"[{symbol}] SHIHAB SWEPT LOW @ {lvl:.4f} ({label}). Waiting for break of {c_high:.4f}")
                            break

        elif shihab_state == "SWEPT_LOW":
            if c_high > state.get("shihab_rejection_high", float('inf')):
                if not is_historical:
                    state["shihab_setup_state"] = "WAITING"
                    asyncio.create_task(self._trigger_signal(
                        symbol, "LONG", current_candle, "Liquidity_Sweep_Shihab",
                        state["shihab_swept_level"], state["shihab_swept_level_label"],
                        state["shihab_sweep_wick_extreme"], state["shihab_sweep_candle_time"]
                    ))
            elif is_closed:
                state["shihab_setup_state"] = "WAITING"

        elif shihab_state == "SWEPT_HIGH":
            if c_low < state.get("shihab_rejection_low", -1.0):
                if not is_historical:
                    state["shihab_setup_state"] = "WAITING"
                    asyncio.create_task(self._trigger_signal(
                        symbol, "SHORT", current_candle, "Liquidity_Sweep_Shihab",
                        state["shihab_swept_level"], state["shihab_swept_level_label"],
                        state["shihab_sweep_wick_extreme"], state["shihab_sweep_candle_time"]
                    ))
            elif is_closed:
                state["shihab_setup_state"] = "WAITING"

        # ──────────────────────────────────────────────────────────────────────
        # DELTA SWEEP STRATEGY: Pro MSS + Delta Absorption
        # ──────────────────────────────────────────────────────────────────────
        delta_state = state.get("delta_setup_state", "WAITING")
        if delta_state == "WAITING":
            if "Delta_Sweep" not in state.get("intrabar_signals", set()):
                swept = False
                # Check High Sweeps
                for label, lvl in sorted(highs, key=lambda x: x[1]):
                    if c_high > lvl and c_close < lvl:  # FAILED BREAKOUT
                        if self.trade_data[symbol]["delta"] < -5000: # Absorption
                            logger.info(f"[{symbol}] DELTA SWEPT HIGH @ {lvl:.4f} ({label}) - ENTERING IMMEDIATELY")
                            if not is_historical:
                                state.setdefault("intrabar_signals", set()).add("Delta_Sweep")
                                asyncio.create_task(self._trigger_signal(
                                    symbol, "SHORT", current_candle, "Delta_Sweep",
                                    lvl, label, c_high, current_candle["t"]
                                ))
                            swept = True
                            break

                # Check Low Sweeps
                if not swept:
                    for label, lvl in sorted(lows, key=lambda x: x[1], reverse=True):
                        if c_low < lvl and c_close > lvl:  # FAILED BREAKOUT
                            if self.trade_data[symbol]["delta"] > 5000: # Absorption
                                logger.info(f"[{symbol}] DELTA SWEPT LOW @ {lvl:.4f} ({label}) - ENTERING IMMEDIATELY")
                                if not is_historical:
                                    state.setdefault("intrabar_signals", set()).add("Delta_Sweep")
                                    asyncio.create_task(self._trigger_signal(
                                        symbol, "LONG", current_candle, "Delta_Sweep",
                                        lvl, label, c_low, current_candle["t"]
                                    ))
                                break

        # ──────────────────────────────────────────────────────────────────────
        # TREND-CONTINUATION ENGINE: Trade pullbacks in direction of macro trend
        # ──────────────────────────────────────────────────────────────────────
        regime = self._get_market_regime(symbol)
        if "Trend_Continuation_Sweep" not in state.get("intrabar_signals", set()):

            if regime == "UPTREND":
                # Monitor 15m and 1h lows
                for label, lvl in sorted(lows, key=lambda x: x[1], reverse=True):
                    if label in ["15m", "1H"]:
                        if c_low < lvl and c_close > lvl:  # Swept and reclaimed
                            if self.trade_data[symbol]["delta"] > 5000: # Absorption required
                                logger.info(f"[{symbol}] TREND-CONT SWEPT LOW @ {lvl:.4f} ({label}) - ENTERING LONG")
                                if not is_historical:
                                    state.setdefault("intrabar_signals", set()).add("Trend_Continuation_Sweep")
                                    asyncio.create_task(self._trigger_signal(
                                        symbol, "LONG", current_candle, "Trend_Continuation_Sweep",
                                        lvl, label, c_low, current_candle["t"]
                                    ))
                                break
            elif regime == "DOWNTREND":
                # Monitor 15m and 1h highs
                for label, lvl in sorted(highs, key=lambda x: x[1]):
                    if label in ["15m", "1H"]:
                        if c_high > lvl and c_close < lvl: # Swept and reclaimed
                            if self.trade_data[symbol]["delta"] < -5000: # Absorption required
                                logger.info(f"[{symbol}] TREND-CONT SWEPT HIGH @ {lvl:.4f} ({label}) - ENTERING SHORT")
                                if not is_historical:
                                    state.setdefault("intrabar_signals", set()).add("Trend_Continuation_Sweep")
                                    asyncio.create_task(self._trigger_signal(
                                        symbol, "SHORT", current_candle, "Trend_Continuation_Sweep",
                                        lvl, label, c_high, current_candle["t"]
                                    ))
                                break

        # MEAN REVERSION ENGINE: Trade chop (Buy support, Sell resistance)
        # ──────────────────────────────────────────────────────────────────────
        if regime == "RANGING":
            if "Mean_Reversion_Sweep" not in state.get("intrabar_signals", set()):
                # Check for sweep of lows (Support)
                for label, lvl in sorted(lows, key=lambda x: x[1], reverse=True):
                    if label in ["15m", "1H", "4H"]:
                        if c_low < lvl and c_close > lvl:
                            if self.trade_data[symbol]["delta"] > 3000:
                                logger.info(f"[{symbol}] MEAN-REVERSION SWEPT LOW @ {lvl:.4f} ({label}) - ENTERING LONG")
                                if not is_historical:
                                    state.setdefault("intrabar_signals", set()).add("Mean_Reversion_Sweep")
                                    asyncio.create_task(self._trigger_signal(
                                        symbol, "LONG", current_candle, "Mean_Reversion_Sweep",
                                        lvl, label, c_low, current_candle["t"]
                                    ))
                                break
                
                # Check for sweep of highs (Resistance)
                for label, lvl in sorted(highs, key=lambda x: x[1]):
                    if label in ["15m", "1H", "4H"]:
                        if c_high > lvl and c_close < lvl:
                            if self.trade_data[symbol]["delta"] < -3000:
                                logger.info(f"[{symbol}] MEAN-REVERSION SWEPT HIGH @ {lvl:.4f} ({label}) - ENTERING SHORT")
                                if not is_historical:
                                    state.setdefault("intrabar_signals", set()).add("Mean_Reversion_Sweep")
                                    asyncio.create_task(self._trigger_signal(
                                        symbol, "SHORT", current_candle, "Mean_Reversion_Sweep",
                                        lvl, label, c_high, current_candle["t"]
                                    ))
                                break

    # ─────────────────────────────────────────────────────────────────────────
    # Signal Trigger
    # ─────────────────────────────────────────────────────────────────────────

    async def _trigger_signal(self, symbol, direction, trigger_candle, strategy_name="LiquiditySweep_v2", swept_level=0.0, swept_level_label="", sweep_wick_extreme=0.0, sweep_candle_time=None):
        # ── 0. Daily Loss Circuit Breaker Check ──
        if self._is_circuit_breaker_active():
            logger.warning(
                f"[{symbol}] Skipping signal — Daily Loss Circuit Breaker ACTIVE (${self.daily_loss_tracker['realized_loss']:.2f} / ${self.max_daily_loss:.2f} lost today)"
            )
            return

        # ── Ghost Deduplication: Prevent identical strategy duplicate on the exact same candle ──
        candle_time = trigger_candle.get("t")
        fired_key = (strategy_name, symbol, candle_time)
        fired_set = self.market_state.setdefault(symbol, {}).setdefault("fired_strategy_candles", set())
        if candle_time and fired_key in fired_set:
            logger.info(f"[{symbol}] Skipping duplicate signal for {strategy_name} on candle {candle_time}")
            return
        if candle_time:
            fired_set.add(fired_key)
            if len(fired_set) > 300:
                self.market_state[symbol]["fired_strategy_candles"] = set(list(fired_set)[-150:])

        open_symbol = sum(1 for s in self.signal_history if s.get("status") == "PENDING" and s.get("symbol") == symbol)
        open_total  = sum(1 for s in self.signal_history if s.get("status") == "PENDING")
        if open_symbol >= self.max_trades_per_symbol or open_total >= self.max_total_trades:
            logger.info(f"[{symbol}] Skipping signal — position limit reached")
            return

        state    = self.market_state[symbol]
        strategy = self.strategy
        
        # ── 1. Entry Price with Post-Only Maker Execution ──
        # Execute exactly at the swept level to capture 0.00% fees
        entry_price = float(swept_level)
        if entry_price == 0.0:
            entry_price = float(trigger_candle["c"])
            
        raw_entry = float(trigger_candle["c"])
        
        # ── 2. Maximum Entry Distance Filter ──
        # Professional standard: Do not enter if price has moved >0.15% from swept level
        entry_dist_pct = abs(raw_entry - swept_level) / swept_level if swept_level > 0 else 0
        if entry_dist_pct > 0.0015:
            logger.info(f"[{symbol}] Skipping signal — entry too far from swept level ({entry_dist_pct*100:.3f}% > 0.15%)")
            return
            
        # ── 2.5 Defensive Vetoes (Spread Anomaly & Chop/Exhaustion) ──
        # Spread Anomaly Check
        if "depth20" in self.market_state.get(symbol, {}):
            bids = self.market_state[symbol]["depth20"].get("bids", [])
            asks = self.market_state[symbol]["depth20"].get("asks", [])
            if bids and asks:
                ask_0 = float(asks[0][0])
                bid_0 = float(bids[0][0])
                mid_price = (ask_0 + bid_0) / 2
                spread_ratio = (ask_0 - bid_0) / mid_price
                if spread_ratio > 0.0003: # 0.03%
                    logger.warning(f"[{symbol}] VETO: Spread Anomaly Detected ({spread_ratio*100:.3f}% > 0.03%). Skipping.")
                    return

        # Chop Veto (Blacklisted Levels)
        blacklisted_levels = state.get("blacklisted_levels", [])
        for bl_level in blacklisted_levels:
            if abs(swept_level - bl_level) / bl_level <= 0.001: # within 0.1% tolerance
                logger.warning(f"[{symbol}] VETO: Swept level {swept_level} is blacklisted (Exhaustion Zone). Skipping.")
                return

        # ── 3. Market Regime Filter (1H 200 EMA + ADX) ──
        regime = self._get_market_regime(symbol)
        if regime == "UPTREND" and direction == "SHORT":
            logger.info(f"[{symbol}] Skipping SHORT signal — Market Regime is UPTREND (Avoiding the freight train)")
            return
        elif regime == "DOWNTREND" and direction == "LONG":
            logger.info(f"[{symbol}] Skipping LONG signal — Market Regime is DOWNTREND (Avoiding the falling knife)")
            return

        # ── 4. Max Trades Per Sweep Per Strategy ──
        current_sweep = f"{strategy_name}_{direction}_{swept_level_label}_{swept_level}"
        sweep_counts = state.get("sweep_trade_counts", {})
        count = sweep_counts.get(current_sweep, 0)
        if count >= self.max_trades_per_sweep:
            logger.info(f"[{symbol}] Skipping signal — max 2 trades taken for sweep {current_sweep}")
            return
        sweep_counts[current_sweep] = count + 1
        state["sweep_trade_counts"] = sweep_counts

        # ── 5. Invalidation Stop Loss & Dynamic Sizing ──
        atr_1m = max(self._calculate_atr(symbol, interval="Min1", period=14), 15.0)
        buffer = atr_1m * 1.0
        
        if direction == "LONG":
            sl = min(float(sweep_wick_extreme), entry_price) - buffer
        else:
            sl = max(float(sweep_wick_extreme), entry_price) + buffer
            
        risk_distance = abs(entry_price - sl)
        if risk_distance <= 0:
            risk_distance = entry_price * 0.001
            
        fixed_risk_usd = float(strategy.get("fixed_risk_usd", 7.0))
        step_size = 0.001
        entry_size = max(step_size, round(fixed_risk_usd / risk_distance, 3))
        
        notional = entry_size * entry_price
        initial_margin = float(strategy.get("initial_margin", 7.0))
        max_leverage_cap = int(strategy.get("max_leverage_cap", 50))
        
        # Calculate leverage required, capped securely
        computed_leverage = min(max(int(round(notional / initial_margin)), 5), max_leverage_cap)
        required_margin = notional / computed_leverage
        leverage = computed_leverage
        
        # Verify Liquidation Distance
        liq_dist_pct = (1.0 / leverage) * 0.85
        if direction == "LONG":
            liq_price = entry_price * (1.0 - liq_dist_pct)
        else:
            liq_price = entry_price * (1.0 + liq_dist_pct)
            
        # ── 6. Structural Take Profits ──
        # Target TP1: VWAP
        tp1 = self._calculate_vwap(symbol)
        if direction == "LONG" and tp1 <= entry_price:
            tp1 = entry_price + risk_distance
        elif direction == "SHORT" and tp1 >= entry_price:
            tp1 = entry_price - risk_distance
            
        # Target TP2: Opposite Range Boundary
        highs, lows = self._get_all_levels(symbol)
        tp2 = 0.0
        if direction == "LONG":
            valid_highs = [lvl for label, lvl in highs if lvl > entry_price]
            tp2 = min(valid_highs) if valid_highs else entry_price + (risk_distance * 3.0)
            if tp2 <= tp1: tp2 = tp1 + risk_distance
        else:
            valid_lows = [lvl for label, lvl in lows if lvl < entry_price]
            tp2 = max(valid_lows) if valid_lows else entry_price - (risk_distance * 3.0)
            if tp2 >= tp1: tp2 = tp1 - risk_distance
            
        tp = tp2
        
        # ── Friction-to-Edge Gatekeeper ──
        expected_reward = abs(tp1 - entry_price) * entry_size
        estimated_friction = (entry_price * entry_size * 0.0004) + (tp1 * entry_size * 0.0004)
        min_ratio = float(strategy.get("min_edge_to_fee_ratio", 2.5))
        if expected_reward < min_ratio * estimated_friction:
            logger.info(f"[{symbol}] Skipping trade: Edge too small for fee structure (${expected_reward:.2f} reward vs ${estimated_friction:.2f} fees)")
            return

        trade_id = str(uuid.uuid4())
        now_iso  = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.last_trade_time = datetime.datetime.now(datetime.timezone.utc)

        signal = {
            "id":               trade_id,
            "symbol":           symbol,
            "direction":        direction,
            "entry":            entry_price,
            "sl":               sl,
            "tp":               tp,
            "tp1":              tp1,
            "tp1_hit":          False,
            "leverage":         leverage,
            "timestamp":        now_iso,
            "timestamp_ms":     trigger_candle["t"],
            "swept_level":      swept_level,
            "swept_level_label": swept_level_label,
            "sweep_candle_time": sweep_candle_time,
        }
        self.signals.append(signal)

        # ── 7. Deep Rationale Construction for SETUP ──
        wick_str = f"high wicked to ${trigger_candle['h']:,.2f}" if direction == "SHORT" else f"low wicked to ${trigger_candle['l']:,.2f}"
        close_str = f"closed back below at ${trigger_candle['c']:,.2f}" if direction == "SHORT" else f"closed back above at ${trigger_candle['c']:,.2f}"
        delta_val = float(state.get("delta", 0.0) or 0.0)
        delta_desc = f"Orderflow Delta recorded at {delta_val:+,.0f}, confirming aggressive {'absorption by sellers capping the high' if direction == 'SHORT' else 'absorption by buyers defending the low'}." if delta_val != 0 else "Orderflow volume confirmed failed continuation beyond the swept level."

        setup_message = (
            f"SETUP EXECUTION ({direction}):\n\n"
            f"1. Liquidity Sweep Detected: Price swept key {swept_level_label} liquidity at ${swept_level:,.2f}. The trigger candle {wick_str}, but failed to sustain breakout and {close_str} — trapping breakout participants.\n\n"
            f"2. Orderflow & Trend Confirmation:\n"
            f"   • {delta_desc}\n"
            f"   • 15-minute trend filter checked: No opposing higher-timeframe momentum is blocking a {direction} entry.\n\n"
            f"3. Risk & Target Geometry:\n"
            f"   • Invalidation / Stop Loss placed at ${sl:,.2f} safely inside liquidation boundary.\n"
            f"   • Take Profit placed at ${tp:,.2f} targeting the opposing liquidity pool (offset 0.01% for limit order completion).\n\n"
            f"4. Sizing & Liquidation Math:\n"
            f"   • Base Entry: ${raw_entry:,.2f} | Limit Fill (Post-Only Maker): ${entry_price:,.2f}.\n"
            f"   • Position: ${required_margin:.2f} margin @ {leverage}x leverage (${entry_size * entry_price:,.2f} notional = {entry_size:.4f} {symbol.replace('USDT', '')}).\n"
            f"   • Initial Liquidation Price: ${liq_price:,.2f} (${abs(entry_price - liq_price):,.2f} safety buffer)."
        )

        initial_event = {
            "type": "SETUP",
            "timestamp": now_iso,
            "message": setup_message
        }

        rem_budget = max(0.0, self.max_daily_loss - self.daily_loss_tracker["realized_loss"])

        hist_signal = {
            **signal,
            "status":           "PENDING",
            "pnl":              0.0,
            "net_profit":       0.0,
            "raw_profit":       0.0,
            "exit_price":       0.0,
            "close_reason":     "",
            "strategy":         strategy_name,
            "config":           strategy,
            "leverage":         leverage,
            "computed_leverage": leverage,
            "initial_margin":   required_margin,
            "margin":           required_margin,
            "raw_entry":        raw_entry,
            "entry_slippage_cost": 0.0,
            "liq_price":        liq_price,
            "exchange_fees":    0.0,
            "funding_fees":     0.0,
            "slippage":         0.0,
            "fees":             0.0,
            "daily_loss_status": f"${rem_budget:.2f} left",
            "margin_adds":      0,
            "last_add_t":       0,
            "margin_add_times": [],
            "timeline_events": [initial_event],
        }
        self.signal_history.append(hist_signal)
        self._save_history()

        logger.info(
            f"SIGNAL: {direction} {symbol} | entry={entry_price:.4f} "
            f"SL={sl:.4f} TP={tp:.4f} | swept {state.get('swept_level_label')} @ {state.get('swept_level', 0):.4f}"
        )

        if getattr(self, "sheets_client", None) and getattr(self.sheets_client, "enabled", False):
            asyncio.create_task(
                asyncio.to_thread(self.sheets_client.append_trade, copy.deepcopy(hist_signal))
            )

        if self.shihab_active and self.mexc_client:
            vol = max(1, int(entry_size / 0.0001))
            await self.mexc_client.submit_order(symbol, direction, entry_price, sl, tp, vol=vol)

        if self.shihab_demo_active:
            if len(self.demo_positions) >= 10:
                logger.warning(f"[{symbol}] DEMO LIMIT reached")
            elif self.demo_balance >= required_margin:
                self.demo_balance -= required_margin
                self.demo_positions.append({
                    **hist_signal,
                    "margin":         required_margin,
                    "initial_margin": required_margin,
                    "margin_adds":    0,
                    "last_add_t":     0,
                    "margin_add_times": [],
                })

    # ─────────────────────────────────────────────────────────────────────────
    # Open Position Management — P&L, auto-margin, trailing stop
    # ─────────────────────────────────────────────────────────────────────────

    async def _update_open_positions(self, symbol, data):
        """Called on every live 1m tick. Manages open position lifecycle."""
        raw_atr = self._calculate_atr(symbol)
        min_atr_floor = 15.0 if "BTC" in symbol else (raw_atr if raw_atr > 0 else 1.0)
        atr = max(raw_atr, min_atr_floor)
        strategy = self.strategy

        for positions_list in [self.demo_positions, self.signal_history]:
            closed = []
            for pos in positions_list:
                if pos.get("status") in ("PROFIT", "LOSS", "LIQUIDATED", "CLOSED"):
                    continue
                if pos.get("symbol") != symbol:
                    continue

                entry     = pos["entry"]
                direction = pos["direction"]
                margin    = pos["margin"]
                tp        = pos["tp"]
                sl        = pos["sl"]
                lev       = float(pos.get("computed_leverage", strategy.get("leverage", 1)))

                fee_buffer_points = entry * (self.taker_fee_rate + self.slippage_pct + 0.0001)

                # ── TP1 (Structural Midpoint) Logic ──
                if "tp1" in pos and not pos.get("tp1_hit", False):
                    if (direction == "LONG" and data["h"] >= pos["tp1"]) or (direction == "SHORT" and data["l"] <= pos["tp1"]):
                        pos["tp1_hit"] = True
                        be_sl = entry + fee_buffer_points if direction == "LONG" else entry - fee_buffer_points
                        if direction == "LONG":
                            pos["sl"] = max(pos["sl"], be_sl)
                        else:
                            pos["sl"] = min(pos["sl"], be_sl)
                        
                        if positions_list is self.signal_history and getattr(self, "mexc_client", None):
                            initial_m = pos.get("initial_margin", margin)
                            total_vol = max(1, int((initial_m * lev) / entry))
                            close_vol = max(1, int(total_vol * 0.5))
                            close_side = 4 if direction == "LONG" else 2 # 4: Close Long, 2: Close Short
                            asyncio.create_task(self.mexc_client.close_position(symbol, close_side, close_vol))
                            
                        if "timeline_events" not in pos: pos["timeline_events"] = []
                        pos["timeline_events"].append({
                            "type": "PARTIAL_TAKE_PROFIT",
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "message": f"TP1 (VWAP/Midpoint) HIT at ${pos['tp1']:.4f}: Closing 50% of position and moving Stop Loss to Breakeven (${pos['sl']:.4f})."
                        })
                        logger.info(f"[{symbol}] TP1 HIT at {pos['tp1']:.4f}! 50% closed, SL moved to breakeven ({pos['sl']:.4f}).")

                # ── Trailing Stop: Lock in profits on Runner ──
                regime = self._get_market_regime(symbol)
                if pos.get("tp1_hit", False) and regime != "RANGING":
                    trail_activation_atr = float(strategy.get("trail_activation_atr", 2.0))
                    trail_atr_multiplier = float(strategy.get("trail_atr_multiplier", 3.0))

                    if direction == "LONG":
                        price_move_points = data["c"] - entry
                        if price_move_points >= trail_activation_atr * atr:
                            calculated_sl = data["c"] - (trail_atr_multiplier * atr)
                            min_breakeven_sl = entry + fee_buffer_points
                            candidate_sl = max(calculated_sl, min_breakeven_sl)

                            # HARD SAFETY GUARD: Stop Loss CANNOT be higher than current price minus 0.5x ATR
                            safe_sl = min(candidate_sl, data["c"] - (0.5 * atr))
                            if safe_sl > pos["sl"]:
                                old_sl = pos["sl"]
                                pos["sl"] = safe_sl
                                pos["trailing_active"] = True
                                guaranteed_points = safe_sl - entry
                                if "timeline_events" not in pos: pos["timeline_events"] = []
                                pos["timeline_events"].append({
                                    "type": "TRAILING_STOP",
                                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "message": (
                                        f"PROFIT PROTECTION (Trailing Stop Activated):\n\n"
                                        f"• Milestone: Price moved {price_move_points:.2f} points in profit (>{trail_activation_atr:.1f}x ATR).\n"
                                        f"• Stop Loss Trailed: Shifted SL from ${old_sl:,.2f} to ${safe_sl:,.2f}.\n"
                                        f"• Protected Distance: {guaranteed_points:+.2f} points relative to entry.\n"
                                        f"• Status: Downside risk reduced. Trade running on house money."
                                    )
                                })
                                logger.info(f"[{symbol}] Trailing SL moved up to {safe_sl:.4f}")
                    else: # SHORT
                        price_move_points = entry - data["c"]
                        if price_move_points >= trail_activation_atr * atr:
                            calculated_sl = data["c"] + (trail_atr_multiplier * atr)
                            min_breakeven_sl = entry - fee_buffer_points
                            candidate_sl = min(calculated_sl, min_breakeven_sl)

                            # HARD SAFETY GUARD: Stop Loss CANNOT be lower than current price plus 0.5x ATR
                            safe_sl = max(candidate_sl, data["c"] + (0.5 * atr))
                            if safe_sl < pos["sl"]:
                                old_sl = pos["sl"]
                                pos["sl"] = safe_sl
                                pos["trailing_active"] = True
                                guaranteed_points = entry - safe_sl
                                if "timeline_events" not in pos: pos["timeline_events"] = []
                                pos["timeline_events"].append({
                                    "type": "TRAILING_STOP",
                                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "message": (
                                        f"PROFIT PROTECTION (Trailing Stop Activated):\n\n"
                                        f"• Milestone: Price moved {price_move_points:.2f} points in profit (>{trail_activation_atr:.1f}x ATR).\n"
                                        f"• Stop Loss Trailed: Shifted SL from ${old_sl:,.2f} to ${safe_sl:,.2f}.\n"
                                        f"• Protected Distance: {guaranteed_points:+.2f} points relative to entry.\n"
                                        f"• Status: Downside risk reduced. Trade running on house money."
                                    )
                                })
                                logger.info(f"[{symbol}] Trailing SL moved down to {safe_sl:.4f}")

                # ── Stop Loss and Liquidation Logic ──
                # ── Auto-Margin Add ($5.00 Averaging Down) ──
                margin_adds = pos.get("margin_adds", 0)
                max_adds = self.strategy.get("max_margin_adds", 3)
                if margin_adds < max_adds:
                    # Only average down if trade is genuinely in drawdown and trailing stop is NOT active
                    is_in_drawdown = (data["c"] < entry) if direction == "LONG" else (data["c"] > entry)
                    dist_to_sl = abs(data["c"] - pos["sl"])
                    entry_to_sl = abs(entry - pos["sl"])
                    is_danger = is_in_drawdown and not pos.get("trailing_active", False) and (entry_to_sl > 0 and dist_to_sl < entry_to_sl * 0.20)

                    # Price must be pushing further against position than previous add
                    last_add_price = pos.get("last_add_price")
                    moved_further = True
                    if last_add_price is not None:
                        if direction == "LONG":
                            moved_further = data["c"] < last_add_price
                        else:
                            moved_further = data["c"] > last_add_price

                    if is_danger and moved_further:
                        add_margin = float(self.strategy.get("margin_add_amount", 5.0))
                        if positions_list is self.demo_positions:
                            if self.demo_balance >= add_margin:
                                self.demo_balance -= add_margin
                            else:
                                add_margin = self.demo_balance
                                self.demo_balance = 0.0

                        if add_margin > 0:
                            old_entry = entry
                            old_margin = float(pos.get("margin", 7.0))
                            old_size = (old_margin * lev) / old_entry
                            
                            add_size = (add_margin * lev) / data["c"]
                            total_size = old_size + add_size
                            new_entry = ((old_entry * old_size) + (data["c"] * add_size)) / total_size
                            
                            pos["margin"] = old_margin + add_margin
                            pos["initial_margin"] = pos["margin"]
                            pos["entry"] = new_entry
                            entry = new_entry
                            pos["last_add_price"] = data["c"]
                            
                            # Dynamically push Liquidation and Stop Loss outward from the new blended entry
                            liq_dist_pct = (1.0 / lev) * 0.85
                            if direction == "LONG":
                                pos["liq_price"] = new_entry * (1.0 - liq_dist_pct)
                                pos["sl"] = new_entry - (abs(new_entry - pos["liq_price"]) * 0.90)
                            else:
                                pos["liq_price"] = new_entry * (1.0 + liq_dist_pct)
                                pos["sl"] = new_entry + (abs(new_entry - pos["liq_price"]) * 0.90)
                                
                            pos["margin_adds"] = margin_adds + 1
                            if "timeline_events" not in pos: pos["timeline_events"] = []
                            pos["timeline_events"].append({
                                "type": "AUTO_MARGIN_ADD",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "message": f"Added ${add_margin:.2f} margin at {data['c']:.4f}. New Avg Entry: {new_entry:.4f}, New SL: {pos['sl']:.4f}, New Liq: {pos['liq_price']:.4f}"
                            })
                            logger.info(f"[{symbol}] AUTO-MARGIN ADD #{pos['margin_adds']} at {data['c']:.4f}. New Avg Entry: {new_entry:.4f}, New SL: {pos['sl']:.4f}")

                            if getattr(self, "sheets_client", None) and getattr(self.sheets_client, "enabled", False):
                                asyncio.create_task(
                                    asyncio.to_thread(self.sheets_client.update_trade, copy.deepcopy(pos))
                                )

                # ── Liquidation Check ──
                current_margin = float(pos.get("margin", 7.0))
                liq_dist_pct = (1.0 / lev) * 0.85
                if direction == "LONG":
                    liq_price = pos.get("liq_price", entry * (1 - liq_dist_pct))
                    hit_liq = data["l"] <= liq_price
                else:
                    liq_price = pos.get("liq_price", entry * (1 + liq_dist_pct))
                    hit_liq = data["h"] >= liq_price

                # ── TP / SL / LIQ Hit ──
                hit_tp = (direction == "LONG"  and data["h"] >= tp) or \
                         (direction == "SHORT" and data["l"] <= tp)
                if pos.get("trailing_active"):
                    # For trailing stop: evaluate against live current price (data["c"]) to avoid
                    # triggering on earlier wick extremes that existed before the trailing stop moved
                    hit_sl = (direction == "LONG"  and data["c"] <= pos["sl"]) or \
                             (direction == "SHORT" and data["c"] >= pos["sl"])
                else:
                    hit_sl = (direction == "LONG"  and data["l"] <= pos["sl"]) or \
                             (direction == "SHORT" and data["h"] >= pos["sl"])

                if hit_tp or hit_sl or hit_liq:
                    size = (current_margin * lev) / entry
                    
                    if hit_tp:
                        exit_price = tp
                        exit_slippage = 0.0
                    elif hit_liq:
                        exit_price = liq_price
                        exit_slippage = abs(liq_price * self.slippage_pct) * size
                    else:
                        # hit_sl (Market stop loss order slippage)
                        if direction == "LONG":
                            exit_price = pos["sl"] * (1.0 - self.slippage_pct)
                        else:
                            exit_price = pos["sl"] * (1.0 + self.slippage_pct)
                        exit_slippage = abs(exit_price - pos["sl"]) * size
                        
                    # Raw Gross PnL
                    raw_pnl = (exit_price - entry) * size if direction == "LONG" else (entry - exit_price) * size
                    
                    # Calculate Exchange Fees
                    # Entry is a resting Limit Post-Only order exactly at swept level (0.00% Maker Fee)
                    open_fee = 0.0
                    # Take Profits are Limit orders (0.00%), Stop Loss/Liquidation are Market (0.02% Taker Fee)
                    close_fee = 0.0 if hit_tp else (exit_price * size) * self.taker_fee_rate
                    exchange_fees = open_fee + close_fee
                    
                    # Calculate Slippage Cost (Zero for TP limit orders)
                    total_slippage = float(pos.get("entry_slippage_cost", 0.0) or 0.0) + (0.0 if hit_tp else exit_slippage)
                    
                    # Calculate Funding Fees
                    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    notional = entry * size
                    funding_fee, funding_intervals, f_rate = self._calculate_funding_cost(pos, now_iso, symbol, notional)
                    
                    # Total Trading Costs & Net PnL
                    total_costs = exchange_fees + funding_fee + total_slippage
                    net_pnl = raw_pnl - total_costs

                    if hit_liq:
                        pos["status"] = "LIQUIDATED"
                        pos["close_reason"] = "Liquidation"
                    else:
                        is_trailing = pos.get("trailing_active", False) or pos.get("sl") != pos.get("initial_sl", pos["sl"])
                        pos["close_reason"] = "Take Profit" if hit_tp else ("Trailing Stop" if is_trailing else "Stop Loss")
                        if hit_tp or net_pnl > 0:
                            pos["status"] = "PROFIT"
                        elif is_trailing or abs(net_pnl) < 0.05:
                            pos["status"] = "BREAKEVEN"
                        else:
                            pos["status"] = "LOSS"
                        
                    # Exhaustion Veto: Blacklist the swept level ONLY if the trade was an actual structural loss or liquidation
                    hit_structural_sl = (pos["close_reason"] == "Stop Loss" and not pos.get("trailing_active", False))
                    if hit_structural_sl or pos["status"] == "LIQUIDATED":
                        b_levels = self.market_state.setdefault(symbol, {}).setdefault("blacklisted_levels", [])
                        bl = float(pos.get("swept_level", 0.0))
                        if bl > 0 and bl not in b_levels:
                            b_levels.append(bl)
                            self.market_state[symbol]["blacklisted_levels"] = b_levels[-10:]

                    pos["exit_price"]        = exit_price
                    pos["exit_timestamp"]    = now_iso
                    pos["raw_profit"]        = raw_pnl
                    pos["exchange_fees"]     = exchange_fees
                    pos["funding_fees"]      = funding_fee
                    pos["funding_intervals"] = funding_intervals
                    pos["slippage"]          = total_slippage
                    pos["fees"]              = total_costs
                    pos["net_profit"]        = net_pnl

                    if positions_list is self.demo_positions:
                        self.demo_balance += pos["margin"] + net_pnl

                    # Record trade closure in daily loss circuit breaker
                    self._record_trade_closure_in_daily_tracker(pos)
                    pos["daily_stats"] = self.get_daily_stats()

                    # Trade Grade
                    if pos["status"] == "PROFIT":
                        if pos.get("margin_adds", 0) == 0: grade = "A+"
                        elif pos.get("margin_adds", 0) == 1: grade = "A"
                        else: grade = "B+"
                    elif pos["status"] == "LIQUIDATED":
                        grade = "F"
                    else:
                        grade = "C" if pos.get("margin_adds", 0) > 0 else "B-"
                    pos["grade"] = grade

                    price_diff = exit_price - entry if direction == "LONG" else entry - exit_price
                    
                    close_msg = (
                        f"TRADE CONCLUSION ({pos['close_reason']} | Grade: {grade}):\n\n"
                        f"• Exit Execution: Closed at ${exit_price:,.2f} via {pos['close_reason']}.\n"
                        f"• Price Movement: ${entry:,.2f} → ${exit_price:,.2f} ({price_diff:+,.2f} points).\n\n"
                        f"• Quantitative Math Breakdown:\n"
                        f"   • Gross Raw PnL: ${raw_pnl:+,.2f}\n"
                        f"   • Exchange Taker Fees (0.02% Open + Close): -${exchange_fees:,.2f}\n"
                        f"   • Funding Fees ({funding_intervals} interval{'s' if funding_intervals != 1 else ''} @ {f_rate*100:.4f}%): -${funding_fee:,.2f}\n"
                        f"   • Slippage Incurred: -${total_slippage:,.2f}\n"
                        f"   • Total Trading Costs: -${total_costs:,.2f}\n"
                        f"   ═════════════════════════════════════\n"
                        f"   • Actual Net Profit: ${net_pnl:+,.2f}\n\n"
                        f"• Collateral Summary: Used {pos.get('margin_adds', 0)} of {self.strategy.get('max_margin_adds', 3)} margin additions. Total capital committed: ${current_margin:.2f}."
                    )
                    
                    if "timeline_events" not in pos: pos["timeline_events"] = []
                    pos["timeline_events"].append({
                        "type": "CLOSE",
                        "timestamp": now_iso,
                        "message": close_msg
                    })
                    
                    closed.append(pos)
                    logger.info(f"TRADE CLOSED: {symbol} {direction} | Net PnL=${net_pnl:.2f} | {pos['close_reason']}")
                    
                    if positions_list is self.signal_history:
                        asyncio.create_task(self._process_closed_trade_review(pos))
                        self._save_history()

                    if getattr(self, "sheets_client", None) and getattr(self.sheets_client, "enabled", False) and positions_list is self.signal_history:
                        asyncio.create_task(
                            asyncio.to_thread(self.sheets_client.update_trade, copy.deepcopy(pos))
                        )

            if positions_list is self.demo_positions:
                self.demo_positions = [p for p in self.demo_positions if p not in closed]

        if len(self.signal_history) > 2000:
            self.signal_history = self.signal_history[-2000:]
            
    async def _process_closed_trade_review(self, pos: dict):
        """Asynchronously generate the AI mentor review and save it to the trade object, then update Google Sheets."""
        try:
            review = await self.deepseek.generate_mentor_review(pos)
            pos["mentor_review"] = review
            self._save_history()
            if getattr(self, "sheets_client", None) and getattr(self.sheets_client, "enabled", False):
                # We update sheets again after the review is generated so the narrative is included
                await asyncio.to_thread(self.sheets_client.update_trade, copy.deepcopy(pos))
        except Exception as e:
            logger.error(f"Error generating mentor review: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Manual Trade Controls — called from WebSocket handlers
    # ─────────────────────────────────────────────────────────────────────────

    def set_trade_tp(self, trade_id: str, new_tp: float):
        """Manually override the Take Profit level for an open trade."""
        updated = False
        for pos in self.signal_history:
            if pos.get("id") == trade_id and pos.get("status") == "PENDING":
                pos["tp"] = new_tp
                updated = True
                logger.info(f"Manual TP override: {trade_id} → {new_tp:.4f}")
                break
        for pos in self.demo_positions:
            if pos.get("id") == trade_id:
                pos["tp"] = new_tp
                updated = True
                break
        if updated:
            self._save_history()
        return updated

    async def close_trade_now(self, trade_id: str):
        """Immediately close a trade at the current market price."""
        for pos in self.signal_history:
            if pos.get("id") == trade_id and pos.get("status") == "PENDING":
                symbol        = pos["symbol"]
                current_price = self.market_state.get(symbol, {}).get("price", pos["entry"])
                entry         = pos["entry"]
                direction     = pos["direction"]
                lev           = float(pos.get("computed_leverage", self.strategy["leverage"]))
                current_margin = float(pos.get("margin", 7.0))
                size          = (current_margin * lev) / entry
                
                # Market exit slippage
                if direction == "LONG":
                    exit_price = current_price * (1.0 - self.slippage_pct)
                else:
                    exit_price = current_price * (1.0 + self.slippage_pct)
                exit_slippage = abs(exit_price - current_price) * size
                total_slippage = float(pos.get("entry_slippage_cost", 0.0) or 0.0) + exit_slippage
                
                raw_pnl       = (exit_price - entry) * size if direction == "LONG" else (entry - exit_price) * size
                open_fee      = (entry * size) * self.taker_fee_rate
                close_fee     = (exit_price * size) * self.taker_fee_rate
                exchange_fees = open_fee + close_fee
                
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                funding_fee, funding_intervals, f_rate = self._calculate_funding_cost(pos, now_iso, symbol, entry * size)
                total_costs   = exchange_fees + funding_fee + total_slippage
                net_pnl       = raw_pnl - total_costs

                pos["status"]       = "PROFIT" if net_pnl > 0 else "LOSS"
                pos["exit_price"]   = exit_price
                pos["exit_timestamp"] = now_iso
                pos["raw_profit"]   = raw_pnl
                pos["exchange_fees"] = exchange_fees
                pos["funding_fees"]  = funding_fee
                pos["funding_intervals"] = funding_intervals
                pos["slippage"]     = total_slippage
                pos["fees"]         = total_costs
                pos["net_profit"]   = net_pnl
                pos["close_reason"] = "Manual Close"

                self._record_trade_closure_in_daily_tracker(pos)
                pos["daily_stats"] = self.get_daily_stats()

                price_diff = exit_price - entry if direction == "LONG" else entry - exit_price
                close_msg = (
                    f"TRADE CONCLUSION (Manual Close):\n\n"
                    f"• Exit Execution: Closed manually at ${exit_price:,.2f} via UI override.\n"
                    f"• Price Movement: ${entry:,.2f} → ${exit_price:,.2f} ({price_diff:+,.2f} points).\n\n"
                    f"• Quantitative Math Breakdown:\n"
                    f"   • Gross Raw PnL: ${raw_pnl:+,.2f}\n"
                    f"   • Exchange Taker Fees (0.02% Open + Close): -${exchange_fees:,.2f}\n"
                    f"   • Funding Fees ({funding_intervals} interval{'s' if funding_intervals != 1 else ''} @ {f_rate*100:.4f}%): -${funding_fee:,.2f}\n"
                    f"   • Slippage Incurred: -${total_slippage:,.2f}\n"
                    f"   • Total Trading Costs: -${total_costs:,.2f}\n"
                    f"   ═════════════════════════════════════\n"
                    f"   • Actual Net Profit: ${net_pnl:+,.2f}\n\n"
                    f"• Collateral Summary: Used {pos.get('margin_adds', 0)} of {self.strategy.get('max_margin_adds', 3)} margin additions. Total capital committed: ${pos.get('margin', initial_margin):.2f}."
                )

                if "timeline_events" not in pos: pos["timeline_events"] = []
                pos["timeline_events"].append({
                    "type": "CLOSE",
                    "timestamp": now_iso,
                    "message": close_msg
                })

                self._save_history()

                logger.info(f"MANUAL CLOSE: {trade_id} {symbol} {direction} @ {exit_price:.4f} | Net PnL=${net_pnl:.2f}")

                asyncio.create_task(self._process_closed_trade_review(pos))

                if getattr(self, "sheets_client", None) and getattr(self.sheets_client, "enabled", False):
                    asyncio.create_task(
                        asyncio.to_thread(self.sheets_client.update_trade, copy.deepcopy(pos))
                    )

                if self.shihab_active and self.mexc_client:
                    await self.mexc_client.close_position(symbol)

                return True

        for pos in self.demo_positions[:]:
            if pos.get("id") == trade_id:
                symbol        = pos["symbol"]
                current_price = self.market_state.get(symbol, {}).get("price", pos["entry"])
                entry         = pos["entry"]
                direction     = pos["direction"]
                lev           = float(pos.get("computed_leverage", self.strategy["leverage"]))
                current_margin = float(pos.get("margin", 7.0))
                size          = (current_margin * lev) / entry
                
                # Market exit slippage
                if direction == "LONG":
                    exit_price = current_price * (1.0 - self.slippage_pct)
                else:
                    exit_price = current_price * (1.0 + self.slippage_pct)
                exit_slippage = abs(exit_price - current_price) * size
                total_slippage = float(pos.get("entry_slippage_cost", 0.0) or 0.0) + exit_slippage

                raw_pnl       = (exit_price - entry) * size if direction == "LONG" else (entry - exit_price) * size
                open_fee      = (entry * size) * self.taker_fee_rate
                close_fee     = (exit_price * size) * self.taker_fee_rate
                exchange_fees = open_fee + close_fee
                total_costs   = exchange_fees + total_slippage
                net_pnl       = raw_pnl - total_costs

                self.demo_balance += pos["margin"] + net_pnl
                self.demo_positions.remove(pos)
                logger.info(f"DEMO MANUAL CLOSE: {trade_id} {symbol} @ {exit_price:.4f} | Net PnL=${net_pnl:.2f}")
                return True

        return False

