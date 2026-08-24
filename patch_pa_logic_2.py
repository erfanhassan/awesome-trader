import re

with open("backend/logic_engine.py", "r") as f:
    lines = f.readlines()

out_lines = []
skip = False
for line in lines:
    if line.strip().startswith("def _evaluate_1m_logic("):
        pass # we will manually replace it
    if line.strip().startswith("async def _evaluate_1m_logic("):
        skip = True
    
    if skip and line.strip().startswith("async def _trigger_signal("):
        skip = False
        
    if not skip:
        out_lines.append(line)

# Let's insert our new _evaluate_1m_logic before _trigger_signal
new_evaluate_1m = """    async def _evaluate_1m_logic(self, symbol, current_candle, is_historical=False):
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

        in_prime_session     = (london_prime_start <= now_utc < london_prime_end) or \\
                               (ny_prime_start <= now_utc < ny_prime_end)
        in_secondary_session = (london_sec_start <= now_utc < london_sec_end) or \\
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
"""

# Let's find index to insert
idx = 0
for i, line in enumerate(out_lines):
    if line.strip().startswith("async def _trigger_signal("):
        idx = i
        break

out_lines.insert(idx, new_evaluate_1m)

with open("backend/logic_engine.py", "w") as f:
    f.writelines(out_lines)

print("Patch step 3 done.")
