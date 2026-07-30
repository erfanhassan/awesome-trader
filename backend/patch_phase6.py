import re

with open('logic_engine.py', 'r') as f:
    content = f.read()

# 1. Update demo positions logic
demo_old = """                liq_price = pos["entry"] * (1 - 0.0015) if pos["direction"] == "LONG" else pos["entry"] * (1 + 0.0015)
                
                if pos["direction"] == "LONG":
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
                    if data["l"] <= pos["tp"]:
                        hit_tp = True
                        exit_price = pos["tp"]
                    elif data["h"] >= pos["sl"]:
                        hit_sl = True
                        exit_price = pos["sl"]
                    elif data["h"] >= liq_price:
                        hit_liq = True
                        exit_price = liq_price
                
                if hit_liq or hit_tp or hit_sl:
                    if hit_liq:"""

demo_new = """                config = pos.get("config", {})
                hit_time = False
                
                if config.get("time_exit"):
                    import datetime
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
                
                if hit_liq or hit_tp or hit_sl or hit_time:
                    if hit_liq:"""

content = content.replace(demo_old, demo_new)

# 2. Update demo positions PnL logic
demo_pnl_old = """                    else:
                        size = (pos["margin"] * pos["leverage"]) / pos["entry"]
                        if pos["direction"] == "LONG":
                            pnl = (exit_price - pos["entry"]) * size
                        else:
                            pnl = (pos["entry"] - exit_price) * size"""

demo_pnl_new = """                    else:
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
                            pnl = gross_pnl"""
content = content.replace(demo_pnl_old, demo_pnl_new)

# 3. Update signal history logic
hist_old = """                liq_price = hist_pos["entry"] * (1 - 0.0015) if hist_pos["direction"] == "LONG" else hist_pos["entry"] * (1 + 0.0015)
                
                if hist_pos["direction"] == "LONG":
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
                    if data["l"] <= hist_pos["tp"]:
                        hit_tp = True
                        exit_price = hist_pos["tp"]
                    elif data["h"] >= hist_pos["sl"]:
                        hit_sl = True
                        exit_price = hist_pos["sl"]
                    elif data["h"] >= liq_price:
                        hit_liq = True
                        exit_price = liq_price
                        
                if hit_liq or hit_tp or hit_sl:
                    # Read margin/leverage from strategy config (fallback to defaults)"""

hist_new = """                config = hist_pos.get("config", {})
                hit_time = False
                
                if config.get("time_exit"):
                    import datetime
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
                        
                if hit_liq or hit_tp or hit_sl or hit_time:
                    # Read margin/leverage from strategy config (fallback to defaults)"""
content = content.replace(hist_old, hist_new)

# 4. Update signal history PnL logic
hist_pnl_old = """                    gross_pnl = pos_size * price_diff_pct
                    if hit_liq:
                        hist_pos["status"] = "LIQUIDATED"
                        net_profit = -margin
                    elif hit_tp:
                        hist_pos["status"] = "PROFIT"
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount
                    else:
                        hist_pos["status"] = "LOSS"
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount"""

hist_pnl_new = """                    gross_pnl = pos_size * price_diff_pct
                    
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
                    elif hit_tp:
                        hist_pos["status"] = "PROFIT"
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount
                    elif hit_time:
                        hist_pos["status"] = "PROFIT" if gross_pnl > 0 else "LOSS"
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount
                    else:
                        hist_pos["status"] = "PROFIT" if gross_pnl > 0 else "LOSS" # SL could be BE (profit)
                        net_profit = gross_pnl - slippage_amount - fees_amount - funding_rate_amount"""
content = content.replace(hist_pnl_old, hist_pnl_new)

with open('logic_engine.py', 'w') as f:
    f.write(content)
