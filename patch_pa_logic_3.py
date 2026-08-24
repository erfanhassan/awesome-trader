import re

with open("backend/logic_engine.py", "r") as f:
    lines = f.readlines()

out_lines = []
skip = False
for line in lines:
    if line.strip().startswith("async def _trigger_signal("):
        skip = True
        break
    out_lines.append(line)

new_trigger = """    async def _trigger_signal(self, symbol, direction, trigger_candle, setup_candle, avg_vol, target_tp, strategy=None, setup_id=None, kelly_fraction=1.0, entry_type="sweep"):
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
        print(f"SIGNAL TRIGGERED: {signal}")
        
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
            "initial_margin": 5.0,
            "margin": 5.0,
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
            print(f"SHIHAB AUTO-TRADER is placing order for {symbol} {direction}")
            await self.mexc_client.submit_order(symbol, direction, context["entry"], sl, tp)
            
        if self.shihab_demo_active:
            MAX_CONCURRENT_POSITIONS = 10
            if len(self.demo_positions) >= MAX_CONCURRENT_POSITIONS:
                print(f"[{symbol}] DEMO LIMIT: {len(self.demo_positions)} demo positions open >= max {MAX_CONCURRENT_POSITIONS}.")
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
                    print(f"DEMO SHIHAB opened virtual {direction} on {symbol} with Margin ${invest_amount} @ {computed_leverage}x")

"""

out_lines.append(new_trigger)

with open("backend/logic_engine.py", "w") as f:
    f.writelines(out_lines)

print("Patch step 4 done.")
