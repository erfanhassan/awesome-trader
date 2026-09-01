import datetime
import asyncio
import json
import os
import uuid
import logging
import copy
from google_sheets_client import GoogleSheetsClient

logger = logging.getLogger(__name__)


class LogicEngine:
    def __init__(self):
        # symbol -> { "Min1": [...], "Min15": [...], etc. }
        self.kline_data = {}

        # Strategy config
        self.strategy = {
            "name": "LiquiditySweep_v2",
            "leverage": 400,
            "initial_margin": 7.0,              # $7 to open a trade
            "margin_add_amount": 5.0,            # Add $5 each time trade goes against us
            "max_margin_adds": 3,                # Max 3 adds
            "margin_add_drawdown_pct": 0.0010,   # Trigger add at 0.10% drawdown
            "candle_window": 10,                 # Look for 3-candle pattern within 10 candles
            "breakeven_roe_trigger": 0.20,       # Move SL to breakeven at 20% ROE
        }

        # symbol -> state dict
        self.market_state = {}
        # symbol -> live trade volume data
        self.trade_data = {}

        self.shihab_active = False
        self.shihab_demo_active = False
        self.demo_balance = 100.0
        self.demo_invest_amount = 7.0
        self.demo_leverage = 400
        self.demo_positions = []
        self.mexc_client = None
        self.sheets_client = GoogleSheetsClient()
        self.signals = []
        self.signal_history = []
        self._load_history()

    # ─────────────────────────────────────────────────────────────────────────
    # History persistence
    # ─────────────────────────────────────────────────────────────────────────

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
        return {
            "shihab_active": self.shihab_active,
            "shihab_demo_active": self.shihab_demo_active,
            "demo_state": {
                "balance": self.demo_balance,
                "invest_amount": self.demo_invest_amount,
                "leverage": self.demo_leverage,
                "positions": self.demo_positions,
            },
            "market_data": self.market_state,
            "trade_data": self.trade_data,
            "signal_history": self.signal_history,
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
                "1d_high": 0,
                "1d_low": 0,
                "4h_session_high": 0,
                "4h_session_low": 0,
                "1h_swing_high": 0,
                "1h_swing_low": 0,
                "15m_swing_high": 0,
                "15m_swing_low": 0,
                # ── Sweep State Machine ──
                "setup_state": "WAITING",
                "sweep_wick_extreme": 0.0,
                "swept_level": 0.0,
                "swept_level_label": "",
                "candles_since_sweep": 0,
                # ── 3-Candle Pattern Tracking ──
                "pattern_candles_found": 0,
                "pattern_candle_1": None,
                # ── Misc ──
                "funding_rate": 0.0001,
                "intrabar_signal_taken": False,
                "last_seen_candle_t": None,
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
        """Update swing highs/lows for each timeframe as new candles arrive."""
        state = self.market_state[symbol]

        if interval == "Day1" and len(history) >= 2:
            prev = history[-2]
            state["1d_high"] = prev["h"]
            state["1d_low"] = prev["l"]

        elif interval == "Hour4" and len(history) >= 3:
            state["4h_session_high"] = max(history[-3]["h"], history[-2]["h"])
            state["4h_session_low"] = min(history[-3]["l"], history[-2]["l"])

        elif interval == "Min60" and len(history) >= 5:
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                state["1h_swing_high"] = history[-3]["h"]
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                state["1h_swing_low"] = history[-3]["l"]

        elif interval == "Min15" and len(history) >= 5:
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                state["15m_swing_high"] = history[-3]["h"]
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                state["15m_swing_low"] = history[-3]["l"]

    def _get_all_levels(self, symbol):
        """Returns all tracked liquidity levels as two lists: highs and lows."""
        state = self.market_state[symbol]
        highs, lows = [], []
        for label, h, l in [
            ("1D",  state.get("1d_high", 0),          state.get("1d_low", 0)),
            ("4H",  state.get("4h_session_high", 0),   state.get("4h_session_low", 0)),
            ("1H",  state.get("1h_swing_high", 0),     state.get("1h_swing_low", 0)),
            ("15m", state.get("15m_swing_high", 0),    state.get("15m_swing_low", 0)),
        ]:
            if h > 0:
                highs.append((label, h))
            if l > 0:
                lows.append((label, l))
        return highs, lows

    def _find_tp(self, symbol, direction, entry_price):
        """Find the nearest liquidity level in the trade direction as TP.
        Falls back to 40% ROE target if no level is found."""
        highs, lows = self._get_all_levels(symbol)
        leverage = self.strategy["leverage"]
        tp_fallback_pct = 0.40 / leverage  # 40% ROE = 0.10% price move at 400x

        if direction == "LONG":
            candidates = [(lbl, h) for lbl, h in highs if h > entry_price]
            if candidates:
                candidates.sort(key=lambda x: x[1])  # Nearest first
                return candidates[0][1]
            return entry_price * (1 + tp_fallback_pct)
        else:
            candidates = [(lbl, l) for lbl, l in lows if l < entry_price]
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)  # Nearest first
                return candidates[0][1]
            return entry_price * (1 - tp_fallback_pct)

    # ─────────────────────────────────────────────────────────────────────────
    # Core 1-Minute Logic — Pure Liquidity Sweep State Machine
    # ─────────────────────────────────────────────────────────────────────────

    async def _evaluate_1m_logic(self, symbol, current_candle, is_historical=False):
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

        highs, lows = self._get_all_levels(symbol)
        setup_state = state.get("setup_state", "WAITING")

        # ══════════════════════════════════════════════════════════════════════
        # STATE: WAITING — scan for a liquidity sweep
        # ══════════════════════════════════════════════════════════════════════
        if setup_state == "WAITING":
            # Sweep of a HIGH level (wick pierces above)
            for label, lvl in sorted(highs, key=lambda x: x[1]):
                if c_high > lvl:
                    state["setup_state"]        = "SWEPT_HIGH"
                    state["sweep_wick_extreme"]  = c_high   # Wick tip = SL for shorts
                    state["swept_level"]         = lvl
                    state["swept_level_label"]   = label
                    state["candles_since_sweep"] = 0
                    state["pattern_candles_found"] = 0
                    state["pattern_candle_1"]    = None
                    logger.info(f"[{symbol}] SWEPT HIGH @ {lvl:.4f} ({label}), wick={c_high:.4f}")
                    break

            # Sweep of a LOW level (wick pierces below)
            if state["setup_state"] == "WAITING":
                for label, lvl in sorted(lows, key=lambda x: x[1], reverse=True):
                    if c_low < lvl:
                        state["setup_state"]        = "SWEPT_LOW"
                        state["sweep_wick_extreme"]  = c_low    # Wick tip = SL for longs
                        state["swept_level"]         = lvl
                        state["swept_level_label"]   = label
                        state["candles_since_sweep"] = 0
                        state["pattern_candles_found"] = 0
                        state["pattern_candle_1"]    = None
                        logger.info(f"[{symbol}] SWEPT LOW @ {lvl:.4f} ({label}), wick={c_low:.4f}")
                        break

        # ══════════════════════════════════════════════════════════════════════
        # STATE: SWEPT_LOW — look for 3 consecutive GREEN candles
        #
        #   C1: green
        #   C2: green AND C2.close > C1.close  (body break)
        #   C3: green → TRIGGER LONG
        # ══════════════════════════════════════════════════════════════════════
        elif setup_state == "SWEPT_LOW":
            if not is_closed:
                return  # Only process on closed candles

            state["candles_since_sweep"] += 1

            # Timeout — give up if pattern not found in time
            if state["candles_since_sweep"] > self.strategy["candle_window"]:
                logger.info(f"[{symbol}] SWEPT_LOW timeout after {self.strategy['candle_window']} candles — resetting")
                state["setup_state"] = "WAITING"
                return

            # Invalidation — price makes a new low, thesis is broken
            if c_low < state["sweep_wick_extreme"]:
                logger.info(f"[{symbol}] SWEPT_LOW invalidated (new lower low) — resetting")
                state["setup_state"] = "WAITING"
                return

            if is_green:
                pf = state["pattern_candles_found"]
                if pf == 0:
                    state["pattern_candle_1"]      = current_candle
                    state["pattern_candles_found"] = 1
                    logger.info(f"[{symbol}] LONG C1 found, close={c_close:.4f}")

                elif pf == 1:
                    c1 = state["pattern_candle_1"]
                    if c_close > c1["c"]:
                        # C2 breaks C1's body — valid, FIRE LONG at start of C3
                        logger.info(f"[{symbol}] LONG C2 (body break) close={c_close:.4f} > C1={c1['c']:.4f}")
                        if not is_historical:
                            state["setup_state"]           = "WAITING"
                            state["pattern_candles_found"] = 0
                            logger.info(
                                f"[{symbol}] ✅ LONG SIGNAL after LOW sweep "
                                f"({state['swept_level_label']} @ {state['swept_level']:.4f})"
                            )
                            await self._trigger_signal(symbol, "LONG", current_candle)
                    else:
                        # Same color but no body break — becomes new C1
                        state["pattern_candle_1"] = current_candle
                        logger.info(f"[{symbol}] LONG C2 no body break — reset C1")
            else:
                # Red candle — reset pattern, keep counting window
                state["pattern_candles_found"] = 0
                state["pattern_candle_1"]      = None

        # ══════════════════════════════════════════════════════════════════════
        # STATE: SWEPT_HIGH — look for 3 consecutive RED candles
        #
        #   C1: red
        #   C2: red AND C2.close < C1.close  (body break)
        #   C3: red → TRIGGER SHORT
        # ══════════════════════════════════════════════════════════════════════
        elif setup_state == "SWEPT_HIGH":
            if not is_closed:
                return

            state["candles_since_sweep"] += 1

            if state["candles_since_sweep"] > self.strategy["candle_window"]:
                logger.info(f"[{symbol}] SWEPT_HIGH timeout after {self.strategy['candle_window']} candles — resetting")
                state["setup_state"] = "WAITING"
                return

            # Invalidation — price makes a new high, thesis is broken
            if c_high > state["sweep_wick_extreme"]:
                logger.info(f"[{symbol}] SWEPT_HIGH invalidated (new higher high) — resetting")
                state["setup_state"] = "WAITING"
                return

            if is_red:
                pf = state["pattern_candles_found"]
                if pf == 0:
                    state["pattern_candle_1"]      = current_candle
                    state["pattern_candles_found"] = 1
                    logger.info(f"[{symbol}] SHORT C1 found, close={c_close:.4f}")

                elif pf == 1:
                    c1 = state["pattern_candle_1"]
                    if c_close < c1["c"]:
                        # C2 breaks C1's body — valid, FIRE SHORT at start of C3
                        logger.info(f"[{symbol}] SHORT C2 (body break) close={c_close:.4f} < C1={c1['c']:.4f}")
                        if not is_historical:
                            state["setup_state"]           = "WAITING"
                            state["pattern_candles_found"] = 0
                            logger.info(
                                f"[{symbol}] ✅ SHORT SIGNAL after HIGH sweep "
                                f"({state['swept_level_label']} @ {state['swept_level']:.4f})"
                            )
                            await self._trigger_signal(symbol, "SHORT", current_candle)
                    else:
                        state["pattern_candle_1"] = current_candle
                        logger.info(f"[{symbol}] SHORT C2 no body break — reset C1")
            else:
                state["pattern_candles_found"] = 0
                state["pattern_candle_1"]      = None

    # ─────────────────────────────────────────────────────────────────────────
    # Signal Trigger
    # ─────────────────────────────────────────────────────────────────────────

    async def _trigger_signal(self, symbol, direction, trigger_candle):
        MAX_PER_SYMBOL = 2
        MAX_TOTAL      = 10
        open_symbol = sum(1 for s in self.signal_history if s.get("status") == "PENDING" and s.get("symbol") == symbol)
        open_total  = sum(1 for s in self.signal_history if s.get("status") == "PENDING")
        if open_symbol >= MAX_PER_SYMBOL or open_total >= MAX_TOTAL:
            logger.info(f"[{symbol}] Skipping signal — position limit reached")
            return

        state    = self.market_state[symbol]
        strategy = self.strategy
        leverage = strategy["leverage"]
        initial_margin = strategy["initial_margin"]

        entry_price = trigger_candle["c"]
        sl = state["sweep_wick_extreme"]   # Wick tip of the sweep candle
        tp = self._find_tp(symbol, direction, entry_price)

        # Sanity checks — ensure SL/TP are on the correct side
        if direction == "LONG":
            if sl >= entry_price:
                sl = entry_price * (1 - (1.0 / leverage) * 0.9)
            if tp <= entry_price:
                tp = entry_price * (1 + 0.40 / leverage)
        else:
            if sl <= entry_price:
                sl = entry_price * (1 + (1.0 / leverage) * 0.9)
            if tp >= entry_price:
                tp = entry_price * (1 - 0.40 / leverage)

        trade_id = str(uuid.uuid4())
        now_iso  = datetime.datetime.now(datetime.timezone.utc).isoformat()

        signal = {
            "id":               trade_id,
            "symbol":           symbol,
            "direction":        direction,
            "entry":            entry_price,
            "sl":               sl,
            "tp":               tp,
            "timestamp":        now_iso,
            "timestamp_ms":     trigger_candle["t"],
            "swept_level":      state.get("swept_level", 0.0),
            "swept_level_label": state.get("swept_level_label", ""),
        }
        self.signals.append(signal)

        hist_signal = {
            **signal,
            "status":           "PENDING",
            "pnl":              0.0,
            "net_profit":       0.0,
            "exit_price":       0.0,
            "close_reason":     "",
            "strategy":         strategy["name"],
            "config":           strategy,
            "computed_leverage": leverage,
            "initial_margin":   initial_margin,
            "margin":           initial_margin,
            "margin_adds":      0,
            "last_add_t":       0,
        }
        self.signal_history.append(hist_signal)
        self._save_history()

        logger.info(
            f"SIGNAL: {direction} {symbol} | entry={entry_price:.4f} "
            f"SL={sl:.4f} TP={tp:.4f} | swept {state.get('swept_level_label')} @ {state.get('swept_level', 0):.4f}"
        )

        if hasattr(self, "sheets_client"):
            asyncio.create_task(
                asyncio.to_thread(self.sheets_client.append_trade, copy.deepcopy(hist_signal))
            )

        if self.shihab_active and self.mexc_client:
            await self.mexc_client.submit_order(symbol, direction, entry_price, sl, tp)

        if self.shihab_demo_active:
            if len(self.demo_positions) >= 10:
                logger.warning(f"[{symbol}] DEMO LIMIT reached")
            elif self.demo_balance >= initial_margin:
                self.demo_balance -= initial_margin
                self.demo_positions.append({
                    **hist_signal,
                    "margin":         initial_margin,
                    "initial_margin": initial_margin,
                    "margin_adds":    0,
                    "last_add_t":     0,
                })

    # ─────────────────────────────────────────────────────────────────────────
    # Open Position Management — P&L, auto-margin, trailing stop
    # ─────────────────────────────────────────────────────────────────────────

    async def _update_open_positions(self, symbol, data):
        """Called on every live 1m tick. Manages open position lifecycle."""
        strategy         = self.strategy
        leverage         = strategy["leverage"]
        margin_add_pct   = strategy["margin_add_drawdown_pct"]
        margin_add_amt   = strategy["margin_add_amount"]
        max_adds         = strategy["max_margin_adds"]
        be_trigger       = strategy["breakeven_roe_trigger"]  # 20% ROE

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
                lev       = float(pos.get("computed_leverage", leverage))

                if direction == "LONG":
                    price_move_pct = (data["c"] - entry) / entry
                    drawdown_pct   = (entry - data["l"]) / entry
                else:
                    price_move_pct = (entry - data["c"]) / entry
                    drawdown_pct   = (data["h"] - entry) / entry

                current_roe = price_move_pct * lev

                # ── Trailing Stop: Move SL to breakeven at 20% ROE ──
                if current_roe >= be_trigger:
                    if direction == "LONG" and pos["sl"] < entry:
                        pos["sl"] = entry
                        logger.info(f"[{symbol}] Breakeven SL set @ {entry:.4f}")
                    elif direction == "SHORT" and pos["sl"] > entry:
                        pos["sl"] = entry
                        logger.info(f"[{symbol}] Breakeven SL set @ {entry:.4f}")

                # ── Auto-Margin Add ──
                if drawdown_pct >= margin_add_pct:
                    adds       = pos.get("margin_adds", 0)
                    last_add_t = pos.get("last_add_t", 0)
                    if adds < max_adds and data["t"] > last_add_t:
                        if positions_list is self.demo_positions and self.demo_balance >= margin_add_amt:
                            self.demo_balance  -= margin_add_amt
                            pos["margin"]      += margin_add_amt
                            pos["margin_adds"]  = adds + 1
                            pos["last_add_t"]   = data["t"]
                            logger.info(f"[{symbol}] DEMO MARGIN ADD #{adds+1} +${margin_add_amt} → total ${pos['margin']:.2f}")
                        elif positions_list is self.signal_history:
                            pos["margin"]      += margin_add_amt
                            pos["margin_adds"]  = adds + 1
                            pos["last_add_t"]   = data["t"]
                            logger.info(f"[{symbol}] MARGIN ADD #{adds+1} +${margin_add_amt} → total ${pos['margin']:.2f}")

                # ── TP / SL Hit ──
                hit_tp = (direction == "LONG"  and data["h"] >= tp) or \
                         (direction == "SHORT" and data["l"] <= tp)
                hit_sl = (direction == "LONG"  and data["l"] <= pos["sl"]) or \
                         (direction == "SHORT" and data["h"] >= pos["sl"])

                if hit_tp or hit_sl:
                    exit_price = tp if hit_tp else pos["sl"]
                    size = (pos["margin"] * lev) / entry
                    
                    # Raw PnL
                    raw_pnl = (exit_price - entry) * size if direction == "LONG" else (entry - exit_price) * size
                    
                    # Calculate Exchange Fees (0.01% Taker open + 0.01% Taker close)
                    open_fee = (entry * size) * 0.0001
                    close_fee = (exit_price * size) * 0.0001
                    total_fees = open_fee + close_fee
                    
                    # Net PnL after fees
                    net_pnl = raw_pnl - total_fees

                    pos["status"]       = "PROFIT" if net_pnl > 0 else "LOSS"
                    pos["exit_price"]   = exit_price
                    pos["raw_profit"]   = raw_pnl
                    pos["fees"]         = total_fees
                    pos["net_profit"]   = net_pnl
                    pos["close_reason"] = "Take Profit" if hit_tp else "Stop Loss"

                    if positions_list is self.demo_positions:
                        self.demo_balance += pos["margin"] + net_pnl

                    closed.append(pos)
                    logger.info(f"TRADE CLOSED: {symbol} {direction} | Net PnL=${net_pnl:.2f} | {pos['close_reason']}")

                    if hasattr(self, "sheets_client"):
                        asyncio.create_task(
                            asyncio.to_thread(self.sheets_client.update_trade, copy.deepcopy(pos))
                        )

            if positions_list is self.demo_positions:
                self.demo_positions = [p for p in self.demo_positions if p not in closed]

        if len(self.signal_history) > 2000:
            self.signal_history = self.signal_history[-2000:]

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
                size          = (pos["margin"] * lev) / entry
                pnl           = (current_price - entry) * size if direction == "LONG" else (entry - current_price) * size

                pos["status"]       = "CLOSED"
                pos["exit_price"]   = current_price
                pos["net_profit"]   = pnl
                pos["close_reason"] = "Manual Close"
                self._save_history()

                logger.info(f"MANUAL CLOSE: {trade_id} {symbol} {direction} @ {current_price:.4f} | PnL=${pnl:.2f}")

                if hasattr(self, "sheets_client"):
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
                size          = (pos["margin"] * lev) / entry
                pnl           = (current_price - entry) * size if direction == "LONG" else (entry - current_price) * size

                self.demo_balance += pos["margin"] + pnl
                self.demo_positions.remove(pos)
                logger.info(f"DEMO MANUAL CLOSE: {trade_id} {symbol} @ {current_price:.4f} | PnL=${pnl:.2f}")
                return True

        return False

