import re

with open("backend/logic_engine.py", "r") as f:
    code = f.read()

# Make sure we import time if not imported
if "import time" not in code:
    code = "import time\n" + code

pattern = r'(if setup_state == "WAITING":)'

new_logic = """if setup_state == "WAITING":
                # --- HIGH FREQUENCY 25-SECOND INTRABAR MOMENTUM ---
                import time
                current_time_ms = time.time() * 1000
                candle_start_t = current_candle.get("t", 0)
                elapsed_ms = current_time_ms - candle_start_t
                
                # Check if we are in the 25-30 second window and have enough history
                if not is_historical and 25000 <= elapsed_ms <= 30000 and len(history) >= 2:
                    c1 = history[-2]
                    c2 = history[-1]
                    
                    c1_green = c1["c"] > c1["o"]
                    c1_red = c1["c"] < c1["o"]
                    c2_green = c2["c"] > c2["o"]
                    c2_red = c2["c"] < c2["o"]
                    
                    # LONG INTRABAR: C1 Green, C2 Green (body breaks C1 body), Live Green
                    if c1_green and c2_green and c2["c"] > c1["c"] and is_green:
                        state["setup_state"] = "LONG_SETUP_FORMED"
                        state["setup_candle"] = current_candle
                        state["ttl"] = 4
                        state["target_tp"] = c_close * 1.002
                        print(f"[{symbol}] HFT INTRABAR MOMENTUM LONG: 25s elapsed, 3 consecutive greens. State -> LONG_SETUP_FORMED")
                        
                    # SHORT INTRABAR: C1 Red, C2 Red (body breaks C1 body), Live Red
                    elif c1_red and c2_red and c2["c"] < c1["c"] and is_red:
                        state["setup_state"] = "SHORT_SETUP_FORMED"
                        state["setup_candle"] = current_candle
                        state["ttl"] = 4
                        state["target_tp"] = c_close * 0.998
                        print(f"[{symbol}] HFT INTRABAR MOMENTUM SHORT: 25s elapsed, 3 consecutive reds. State -> SHORT_SETUP_FORMED")

"""

code = re.sub(pattern, new_logic, code)

with open("backend/logic_engine.py", "w") as f:
    f.write(code)

print("Patched logic_engine.py with Intrabar Momentum.")
