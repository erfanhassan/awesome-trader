import re

with open("backend/logic_engine.py", "r") as f:
    code = f.read()

# Update leverage
code = re.sub(r'"name": "SA_Level_Scalp",\s*"leverage": 50,', '"name": "SA_Level_Scalp",\n                "leverage": 400,', code)
code = re.sub(r'"name": "SB_Level_Guardian",\s*"leverage": 75,', '"name": "SB_Level_Guardian",\n                "leverage": 400,', code)

# Enable auto margin for 400x scaling
code = re.sub(r'"auto_margin": False,', '"auto_margin": True,', code)

# Add 15m EMA pullback logic to the state in process_kline for 15m
# Actually let's just insert the logic into _evaluate_1m_logic

# Find the WAITING state in _evaluate_1m_logic
waiting_state_pattern = r'if setup_state == "WAITING":\n(\s+)# Wick Rejection \(Touch and Trade\)'

new_waiting_logic = """if setup_state == "WAITING":
                # --- HIGH FREQUENCY MID-RANGE EMA PULLBACK ---
                ema20_15m = state.get("15m_ema20", 0)
                is_15m_bullish = state.get("15m_bullish", False)
                # If price pulls back and touches EMA 20 in an uptrend (LONG)
                if ema20_15m > 0 and is_15m_bullish and c_low <= ema20_15m and c_high > ema20_15m:
                    state["setup_state"] = "LONG_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    state["ttl"] = 5
                    state["target_tp"] = c_high * 1.002 # 0.2% default target
                    print(f"[{symbol}] HFT EMA PULLBACK LONG: touched {ema20_15m:.4f}. State -> LONG_SETUP_FORMED")
                    
                # If price pulls back and touches EMA 20 in a downtrend (SHORT)
                elif ema20_15m > 0 and not is_15m_bullish and c_high >= ema20_15m and c_low < ema20_15m:
                    state["setup_state"] = "SHORT_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    state["ttl"] = 5
                    state["target_tp"] = c_low * 0.998
                    print(f"[{symbol}] HFT EMA PULLBACK SHORT: touched {ema20_15m:.4f}. State -> SHORT_SETUP_FORMED")
                    
                # --- HIGH FREQUENCY BREAKOUT CONTINUATION ---
                # Break and close above 4H high = LONG Continuation
                elif c_close > sweep_high and sweep_high > 0 and is_green:
                    state["setup_state"] = "LONG_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    state["ttl"] = 4
                    state["target_tp"] = c_close * 1.005 # Target 0.5% breakout extension
                    print(f"[{symbol}] HFT BREAKOUT LONG: Closed above 4H High {sweep_high:.4f}. State -> LONG_SETUP_FORMED")
                    
                # Break and close below 4H low = SHORT Continuation
                elif c_close < sweep_low and sweep_low > 0 and is_red:
                    state["setup_state"] = "SHORT_SETUP_FORMED"
                    state["setup_candle"] = current_candle
                    state["ttl"] = 4
                    state["target_tp"] = c_close * 0.995
                    print(f"[{symbol}] HFT BREAKOUT SHORT: Closed below 4H Low {sweep_low:.4f}. State -> SHORT_SETUP_FORMED")

                # Wick Rejection (Touch and Trade)"""

code = re.sub(waiting_state_pattern, new_waiting_logic, code)

with open("backend/logic_engine.py", "w") as f:
    f.write(code)

print("Patched logic_engine.py successfully.")
