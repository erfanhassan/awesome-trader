import re

with open("logic_engine.py", "r") as f:
    content = f.read()

# 1. Update state init
content = content.replace(
'''                "1d_bullish": False,
                "setup_state": "WAITING", # WAITING, CROSSED_HIGH, CROSSED_LOW, SETUP_SHORT, SETUP_LONG
                "setup_candle": None,
                "htf_ok": False,''',
'''                "1d_bullish": False,
                "setup_state": "WAITING", # WAITING, SWEPT_HIGH, SWEPT_LOW, SHORT_SETUP_FORMED, LONG_SETUP_FORMED
                "setup_candle": None,
                "target_tp": 0.0,
                "htf_ok": False,'''
)

# 2. Extract _evaluate_1m_logic
eval_logic_pattern = re.compile(r'(    async def _evaluate_1m_logic\(self, symbol, current_candle, is_historical=False\):.*?)(?=    async def _trigger_signal)', re.DOTALL)

new_eval_logic = '''    async def _evaluate_1m_logic(self, symbol, current_candle, is_historical=False):
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

        # Only evaluate on close
        if current_candle.get("is_closed", False):
            setup_state = state.get("setup_state", "WAITING")

            if setup_state == "WAITING":
                if c_high > d1_high:
                    state["setup_state"] = "SWEPT_HIGH"
                    state["target_tp"] = min([c["l"] for c in history[-61:-1]])
                elif c_low < d1_low:
                    state["setup_state"] = "SWEPT_LOW"
                    state["target_tp"] = max([c["h"] for c in history[-61:-1]])

            # Refresh setup_state variable in case it just transitioned
            setup_state = state.get("setup_state", "WAITING")
            
            trigger_direction = None

            if setup_state == "SWEPT_HIGH":
                if is_red:
                    state["setup_state"] = "SHORT_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                elif c_low < d1_low:
                    state["setup_state"] = "SWEPT_LOW"
                    state["target_tp"] = max([c["h"] for c in history[-61:-1]])
            
            elif setup_state == "SWEPT_LOW":
                if is_green:
                    state["setup_state"] = "LONG_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                elif c_high > d1_high:
                    state["setup_state"] = "SWEPT_HIGH"
                    state["target_tp"] = min([c["l"] for c in history[-61:-1]])
            
            elif setup_state == "SHORT_SETUP_FORMED":
                setup_candle = state.get("setup_candle")
                if current_candle["c"] < setup_candle["c"]:
                    trigger_direction = "SHORT"
                    state["setup_state"] = "WAITING"
                else:
                    if is_red:
                        state["setup_candle"] = current_candle
                    else:
                        state["setup_state"] = "SWEPT_HIGH"
            
            elif setup_state == "LONG_SETUP_FORMED":
                setup_candle = state.get("setup_candle")
                if current_candle["c"] > setup_candle["c"]:
                    trigger_direction = "LONG"
                    state["setup_state"] = "WAITING"
                else:
                    if is_green:
                        state["setup_candle"] = current_candle
                    else:
                        state["setup_state"] = "SWEPT_LOW"

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
                
                for strategy in getattr(self, "active_strategies", []):
                    strategy_name = strategy["name"]
                    already_signaled = any(s.get("timestamp_ms") == current_candle["t"] and s.get("strategy") == strategy_name for s in self.signal_history)
                    if already_signaled or is_historical:
                        continue
                        
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
                            await self._trigger_signal(symbol, "SHORT", current_candle, setup_candle, avg_vol, state["target_tp"], strategy, setup_id)

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
                            await self._trigger_signal(symbol, "LONG", current_candle, setup_candle, avg_vol, state["target_tp"], strategy, setup_id)
'''

content = eval_logic_pattern.sub(new_eval_logic, content)

# 3. Replace _trigger_signal signature and TP/SL logic
trigger_signal_pattern = re.compile(r'(    async def _trigger_signal\(self, symbol, direction, trigger_candle, setup_candle, avg_vol, strategy=None, setup_id=None\):.*?)(?=        context = {)', re.DOTALL)

new_trigger_signal = '''    async def _trigger_signal(self, symbol, direction, trigger_candle, setup_candle, avg_vol, target_tp, strategy=None, setup_id=None):
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
        
        tp = target_tp
        
        # Scale-out TP1 logic: Take half of the distance from entry to TP
        if direction == "SHORT":
            tp1 = trigger_candle["c"] - ((trigger_candle["c"] - target_tp) * 0.5)
        else:
            tp1 = trigger_candle["c"] + ((target_tp - trigger_candle["c"]) * 0.5)

        vol_ratio = setup_candle["v"] / avg_vol if avg_vol > 0 else 0

'''

content = trigger_signal_pattern.sub(new_trigger_signal, content)

with open("logic_engine.py", "w") as f:
    f.write(content)

print("Logic Engine updated successfully.")
