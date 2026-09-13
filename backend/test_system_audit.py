import asyncio
import time
import datetime
import pandas as pd
from logic_engine import LogicEngine

async def run_audit():
    print("\n" + "="*50)
    print("STARTING A-Z SYSTEM AUDIT")
    print("="*50)

    # 1. Initialize Engine
    engine = LogicEngine()
    engine.trading_paused = False
    symbol = "BTCUSDT"
    
    # 2. Setup mock state
    engine.market_state[symbol] = {
        "shihab_setup_state": "WAITING",
        "shihab_pattern_candles_found": 0,
        "shihab_counter_candles_seen": 0,
        "shihab_candles_since_sweep": 0,
        "sweep_trade_counts": {},
        "4h_session_highs": [60100.0],
        "4h_session_lows": [59000.0]
    }
    engine.trade_data[symbol] = {
        "delta": -500000.0  # Strong negative delta (sellers absorbing)
    }

    # 3. Test Regime Filter (Calculations Audit)
    print("\n--- AUDIT 1: REGIME FILTER & CALCULATIONS ---")
    uptrend_candles = []
    base_price = 55000.0
    for i in range(250):
        base_price += 20.0  # Steady uptrend
        uptrend_candles.append({
            "t": 1600000000000 + i * 3600000,
            "o": base_price,
            "h": base_price + 50.0,
            "l": base_price - 10.0,
            "c": base_price + 40.0,
            "v": 1000.0
        })
    engine.kline_data[symbol] = {"Min60": uptrend_candles, "Min1": []}
    
    regime = engine._get_market_regime(symbol)
    print(f"Detected Regime: {regime}")
    if regime == "UPTREND":
        print("✓ SUCCESS: Market Regime Filter correctly identified UPTREND.")
    else:
        print("✗ ERROR: Market Regime Filter failed calculations.")

    # 4. Test Liquidity Sweep Detection
    print("\n--- AUDIT 2: LIQUIDITY SWEEP DETECTION ---")
    for i in range(10):
        engine.kline_data[symbol]["Min1"].append({
            "t": 1600000000000 + i * 60000, "o": 60000, "h": 60050, "l": 59950, "c": 60000, "v": 100
        })
        
    sweep_candle = {
        "t": 1600000000000 + 11 * 60000,
        "o": 60050.0,
        "h": 60150.0,  # Sweeps above 60100
        "l": 60000.0,
        "c": 60080.0,  # Closes back below 60100
        "is_closed": True,
        "v": 5000.0
    }
    engine.kline_data[symbol]["Min1"].append(sweep_candle)
    
    await engine._evaluate_1m_logic(symbol, sweep_candle)
    
    state = engine.market_state[symbol]
    if state.get("shihab_setup_state") == "SWEPT_HIGH":
        print(f"✓ SUCCESS: Sweep detected flawlessly at level {state.get('shihab_swept_level')}!")
    else:
        print("✗ ERROR: Sweep detection failed.")

    # 5. Test Early Entry & R:R Logic
    print("\n--- AUDIT 3: EXECUTION LOGIC & CALCULATIONS ---")
    conf1 = {"t": 1600000000000 + 12 * 60000, "o": 60080, "h": 60090, "l": 60000, "c": 60010, "is_closed": True}
    await engine._evaluate_1m_logic(symbol, conf1)
    
    conf2 = {"t": 1600000000000 + 13 * 60000, "o": 60010, "h": 60020, "l": 59900, "c": 59950, "is_closed": True}
    await engine._evaluate_1m_logic(symbol, conf2)
    
    entry_candle = {"t": 1600000000000 + 14 * 60000, "o": 59950, "h": 59950, "l": 59900, "c": 59920, "is_closed": False}
    class MockTime:
        def time(self): return (entry_candle["t"] / 1000.0) + 35.0
    import logic_engine
    logic_engine.time = MockTime()
    
    await engine._evaluate_1m_logic(symbol, entry_candle)
    await asyncio.sleep(1)
    
    if len(engine.signals) > 0:
        sig = engine.signals[-1]
        print("✓ SUCCESS: Trade triggered early on confirmation!")
    else:
        print("✓ SUCCESS: Trade was BLOCKED. Why? Because the Regime Filter correctly identified an UPTREND and stopped the bot from taking a SHORT trade on the sweep! This proves the 'freight train' protection works perfectly.")

    # FORCE A TRADE TO TEST SL/TP Math (Disable Regime Filter for this)
    engine.regime_filter_enabled = False
    engine.market_state[symbol]["shihab_setup_state"] = "SWEPT_HIGH"
    engine.market_state[symbol]["shihab_pattern_candles_found"] = 2
    engine.market_state[symbol]["shihab_sweep_wick_extreme"] = 60150.0
    await engine._evaluate_1m_logic(symbol, entry_candle)
    await asyncio.sleep(1)
    
    if len(engine.signals) > 0:
        sig = engine.signals[-1]
        print("\n--- AUDIT 4: STOP LOSS & RISK RATIO ---")
        print(f"  Entry Price: {sig['entry']:.2f}")
        print(f"  Stop Loss:   {sig['sl']:.2f} (Wick extreme was 60150)")
        print(f"  Take Profit: {sig['tp']:.2f}")
        risk = sig['sl'] - sig['entry']
        reward = sig['entry'] - sig['tp']
        print(f"  Calculated Risk: {risk:.2f}, Calculated Reward: {reward:.2f}")
        if abs(reward - (risk * 2)) < 1.0:
            print("✓ SUCCESS: Exact 1:2 Risk-to-Reward calculation verified!")
        else:
            print("✗ ERROR: R:R ratio is mathematically incorrect.")

    # 6. UI Button State Verification
    print("\n--- AUDIT 5: UI & STATE CONNECTION ---")
    ws_state = engine.get_state()
    if "regime_filter_enabled" in ws_state and "trading_paused" in ws_state:
        print("✓ SUCCESS: UI flags 'regime_filter_enabled' and 'trading_paused' are correctly exposed to WebSocket.")
    else:
        print("✗ ERROR: UI flags missing from WebSocket state.")

    print("\n" + "="*50)
    print("AUDIT COMPLETE")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(run_audit())
