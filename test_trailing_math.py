import asyncio
import os
import sys

sys.path.append(os.path.join(os.getcwd(), 'backend'))
from logic_engine import LogicEngine

async def run_unit_tests():
    print("=== TEST 1: LONG Trailing Stop Math & Safety Guard ===")
    engine = LogicEngine()
    # Mock ATR
    engine._calculate_atr = lambda sym, *args, **kwargs: 10.0 # ATR = 10 points
    engine._get_market_regime = lambda sym: "TRENDING"
    
    # Create test LONG position
    entry = 77200.0
    pos_long = {
        "id": "test-long-1",
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry": entry,
        "sl": 76900.0,
        "initial_sl": 76900.0,
        "tp": 77600.0,
        "tp1": 77220.0,
        "tp1_hit": True, # Trailing ONLY activates after TP1 is hit
        "margin": 7.0,
        "computed_leverage": 190,
        "status": "PENDING",
        "trailing_active": False,
        "margin_adds": 0,
        "timeline_events": []
    }
    engine.demo_positions = [pos_long]
    engine.signal_history = []
    
    # Step 1: Price moves up 35 points (>2.0x ATR floor of 15.0 = 30 pts) to 77235.0
    tick1 = {"t": 1000, "o": 77225.0, "h": 77236.0, "l": 77224.0, "c": 77235.0, "v": 10, "is_closed": False}
    await engine._update_open_positions("BTCUSDT", tick1)
    
    # Verify trade is STILL OPEN (didn't suicide!)
    assert len(engine.demo_positions) == 1, "Position was wrongly killed on activation tick!"
    p = engine.demo_positions[0]
    assert p["trailing_active"] == True, "Trailing should be active"
    assert p["sl"] < tick1["c"], f"Stop Loss ({p['sl']}) must be strictly LESS than live price ({tick1['c']})!"
    assert p["sl"] <= tick1["c"] - 7.5, f"Stop Loss ({p['sl']}) must respect the 0.5x ATR safety guard"
    print(f"PASS: Tick 1 (Price {tick1['c']}): SL safely moved from 76900.0 to {p['sl']:.2f} (< {tick1['c']}). Trade still alive!")

    # Step 2: Price moves up to 77270.0 (+70 pts, well past breakeven + fee buffer ~30.9 pts)
    tick2 = {"t": 2000, "o": 77260.0, "h": 77272.0, "l": 77258.0, "c": 77270.0, "v": 10, "is_closed": False}
    await engine._update_open_positions("BTCUSDT", tick2)
    assert len(engine.demo_positions) == 1, "Position should still be open"
    p = engine.demo_positions[0]
    fee_buffer = entry * (engine.taker_fee_rate + engine.slippage_pct + 0.0001)
    assert p["sl"] >= entry + fee_buffer, f"SL ({p['sl']}) should now be at or above fee-protected breakeven ({entry + fee_buffer})"
    assert p["sl"] < tick2["c"], f"SL ({p['sl']}) must still be less than live price ({tick2['c']})"
    print(f"PASS: Tick 2 (Price {tick2['c']}): SL safely trailed up to {p['sl']:.2f} (above breakeven {entry + fee_buffer:.2f})")

    # Step 3: Auto-Margin Add check while in profit
    assert p["margin_adds"] == 0, "Margin adds should NOT have triggered while trade was in profit!"
    print(f"PASS: Margin adds count = {p['margin_adds']} (no margin wasted on winning trade)")

    print("\n=== TEST 2: SHORT Trailing Stop Math & Safety Guard ===")
    pos_short = {
        "id": "test-short-1",
        "symbol": "BTCUSDT",
        "direction": "SHORT",
        "entry": 77200.0,
        "sl": 77500.0,
        "initial_sl": 77500.0,
        "tp": 76600.0,
        "tp1": 77180.0,
        "tp1_hit": True, # Trailing ONLY activates after TP1 is hit
        "margin": 7.0,
        "computed_leverage": 190,
        "status": "PENDING",
        "trailing_active": False,
        "margin_adds": 0,
        "timeline_events": []
    }
    engine.demo_positions = [pos_short]
    
    # Price drops 35 points to 77165.0
    tick_s1 = {"t": 3000, "o": 77175.0, "h": 77176.0, "l": 77164.0, "c": 77165.0, "v": 10, "is_closed": False}
    await engine._update_open_positions("BTCUSDT", tick_s1)
    assert len(engine.demo_positions) == 1, "SHORT was wrongly killed on activation tick!"
    ps = engine.demo_positions[0]
    assert ps["trailing_active"] == True, "SHORT trailing should be active"
    assert ps["sl"] > tick_s1["c"], f"Stop Loss ({ps['sl']}) must be strictly GREATER than live price ({tick_s1['c']})!"
    assert ps["sl"] >= tick_s1["c"] + 7.5, f"Stop Loss ({ps['sl']}) must respect the 0.5x ATR safety guard"
    print(f"PASS: Tick 1 (Price {tick_s1['c']}): SL safely moved from 77500.0 down to {ps['sl']:.2f} (> {tick_s1['c']}). Trade still alive!")

    print("\n=== TEST 3: Multi-Strategy Signal Deduplication ===")
    engine.circuit_breaker_enabled = False
    engine.daily_loss_tracker["realized_loss"] = 0.0
    engine.market_state["BTCUSDT"] = {"fired_strategy_candles": set()}
    candle = {"t": 1789000000, "o": 77200, "h": 77210, "l": 77190, "c": 77205, "v": 50}
    
    # Strategy 1 fires
    await engine._trigger_signal("BTCUSDT", "LONG", candle, "Delta_Sweep", swept_level=77200.0)
    sig_count_1 = len(engine.signals)
    assert sig_count_1 == 1, "Delta_Sweep should have fired"
    
    # Strategy 1 fires AGAIN on the same candle (ghost duplicate)
    await engine._trigger_signal("BTCUSDT", "LONG", candle, "Delta_Sweep", swept_level=77200.0)
    sig_count_2 = len(engine.signals)
    assert sig_count_2 == 1, "Delta_Sweep ghost duplicate should be blocked!"
    print("PASS: Identical strategy duplicate on same candle successfully blocked!")

    # Strategy 2 fires on the SAME candle (different strategy!)
    await engine._trigger_signal("BTCUSDT", "LONG", candle, "Mean_Reversion_Sweep", swept_level=77200.0)
    sig_count_3 = len(engine.signals)
    assert sig_count_3 == 2, "Mean_Reversion_Sweep should be allowed to fire on the same candle!"
    print("PASS: Different strategy (Mean_Reversion_Sweep) successfully allowed to fire on same candle!")

    print("\n=== ALL UNIT TESTS PASSED PERFECTLY ===")

if __name__ == "__main__":
    asyncio.run(run_unit_tests())
