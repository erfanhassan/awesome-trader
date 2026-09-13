import asyncio
import os
import sys

sys.path.append(os.path.join(os.getcwd(), 'backend'))
from logic_engine import LogicEngine

async def run_test():
    engine = LogicEngine()
    engine.trading_paused = False
    engine.regime_filter_enabled = False
    engine.circuit_breaker_enabled = False
    engine.signal_history = []
    engine.demo_positions = []
    
    # 1. Verify Default Strategy Config
    print("Testing Strategy Config Defaults...")
    assert engine.strategy.get("max_margin_adds") == 0, f"Expected 0, got {engine.strategy.get('max_margin_adds')}"
    print(" Strategy Config: PASSED")

    # 2. Simulate Signal Trigger
    print("\nTesting Signal Trigger Sizing & Geometry...")
    symbol = "BTCUSDT"
    trigger_candle = {
        "t": 1789150000000,
        "o": 77460.0,
        "h": 77480.0,
        "l": 77450.0,
        "c": 77468.0,
        "v": 100.0,
        "is_closed": True
    }
    engine.market_state[symbol] = {
        "price": 77468.0,
        "levels": {"1H": [77468.0], "4H": [77468.0]},
        "delta": -6000
    }
    engine.kline_data[symbol] = {"Min1": [trigger_candle] * 20}
    
    # Mock VWAP to ensure TP1 is far enough to pass Friction Gatekeeper
    engine._calculate_vwap = lambda sym: 77000.0  # 468 points away for a SHORT
    
    await engine._trigger_signal(
        symbol=symbol,
        direction="SHORT",
        trigger_candle=trigger_candle,
        strategy_name="Delta_Sweep",
        swept_level=77468.0,
        swept_level_label="4H",
        sweep_wick_extreme=77480.0,
        sweep_candle_time=trigger_candle["t"]
    )
    
    assert len(engine.signal_history) == 1, "Signal not added to signal_history"
    trade = engine.signal_history[0]
    
    print(f"  Trade ID: {trade['id']}")
    print(f"  Entry: {trade['entry']}")
    print(f"  Leverage: {trade['leverage']}x")
    print(f"  Initial Margin: ${trade['initial_margin']:.2f}")
    print(f"  Liquidation Price: ${trade['liq_price']:.2f}")
    print(f"  Stop Loss: ${trade['sl']:.2f}")
    print(f"  Take Profit: ${trade['tp']:.2f}")
    
    assert trade["liq_price"] > trade["entry"], "SHORT liquidation must be above entry"
    assert trade["sl"] < trade["liq_price"], "SHORT Stop Loss must be safely below liquidation"
    assert trade["sl"] > trade["entry"], "SHORT Stop Loss must be above entry"
    print(" Sizing & SL/Liq Placement: PASSED")

    # 4. Simulate Stop Out and Verify PnL & Fee Math
    print("\nTesting PnL, Fees, and Narrative Calculation on Close...")
    close_tick = {"c": trade["sl"] + 2.0, "h": trade["sl"] + 5.0, "l": trade["sl"]}
    await engine._update_open_positions(symbol, close_tick)
    
    assert trade["status"] == "LOSS", f"Expected LOSS, got {trade['status']}"
    assert trade["close_reason"] == "Stop Loss", f"Expected Stop Loss, got {trade['close_reason']}"
    assert trade["raw_profit"] < 0, "Raw profit must be negative on SL"
    assert trade["exchange_fees"] > 0, "Exchange taker fees must be calculated"
    assert trade["slippage"] > 0, "Slippage must be calculated"
    assert trade["net_profit"] < trade["raw_profit"], "Net profit must include fees + slippage"
    
    print(f"  Close Status: {trade['status']}")
    print(f"  Exit Price: {trade['exit_price']:.2f}")
    print(f"  Raw PnL: ${trade['raw_profit']:.2f}")
    print(f"  Exchange Fees: ${trade['exchange_fees']:.4f}")
    print(f"  Slippage: ${trade['slippage']:.4f}")
    print(f"  Total Fees & Costs: ${trade['fees']:.4f}")
    print(f"  Actual Net Loss: ${trade['net_profit']:.2f}")
    print(f"  Total Committed Margin: ${trade['margin']:.2f}")
    
    timeline = trade.get("timeline_events", [])
    close_event = [e for e in timeline if e["type"] == "CLOSE"]
    assert len(close_event) > 0, "CLOSE timeline event missing"
    assert f"Total capital committed: ${trade['margin']:.2f}" in close_event[0]["message"], "Committed capital mismatch in narrative"
    print(" PnL & Fee Math: PASSED")

    print("\nALL TESTS PASSED SUCCESSFULLY! ")

if __name__ == "__main__":
    asyncio.run(run_test())
