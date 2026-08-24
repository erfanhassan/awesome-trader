import re
import sys

with open("backend/logic_engine.py", "r") as f:
    content = f.read()

# 1. Update add_symbol
old_add_symbol = """                # Fix 5: 4H session sweep levels (primary, updated every 4h)
                "4h_session_high": 0,
                "4h_session_low": 0,
                "sweep_is_premium": False,  # True if sweep also hits 1D level
                # Fix 8: 15m swing structure pivots
                "15m_swing_high": 0,
                "15m_swing_low": 0,
                # Fix 7: Live funding rate from MEXC"""

new_add_symbol = """                # Fix 5: 4H session sweep levels (primary, updated every 4h)
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
                # Fix 7: Live funding rate from MEXC"""
content = content.replace(old_add_symbol, new_add_symbol)

# 2. Update _evaluate_ema for 1h and 1m swings
old_ema = """        # Fix 8: Detect 15m swing highs and lows (2-candle pivot)
        # Used for: confluence requirement and dynamic TP targeting
        if interval == "Min15" and len(history) >= 5:
            # A swing high: middle candle is higher than both neighbors
            if history[-3]["h"] > history[-4]["h"] and history[-3]["h"] > history[-2]["h"]:
                self.market_state[symbol]["15m_swing_high"] = history[-3]["h"]
            # A swing low: middle candle is lower than both neighbors
            if history[-3]["l"] < history[-4]["l"] and history[-3]["l"] < history[-2]["l"]:
                self.market_state[symbol]["15m_swing_low"] = history[-3]["l"]"""

new_ema = """        # Detect 1m, 15m, 1h swing highs and lows (2-candle pivot)
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
                self.market_state[symbol]["1h_swing_low"] = history[-3]["l"]"""
content = content.replace(old_ema, new_ema)


with open("backend/logic_engine.py", "w") as f:
    f.write(content)

print("Patch step 1 and 2 done.")
