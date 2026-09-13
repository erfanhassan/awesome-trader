import asyncio
import json
import os
import sys

sys.path.append(os.path.join(os.getcwd(), 'backend'))
from logic_engine import LogicEngine

async def run_replay():
    with open("mexc_1m_candles.json") as f:
        candles = json.load(f)
        
    candles = sorted(candles, key=lambda c: c["t"])
    print(f"Replaying {len(candles)} candles through fixed LogicEngine...")
    
    engine = LogicEngine()
    engine.circuit_breaker_enabled = False
    engine.demo_balance = 10000.0
    engine.sheets_client = None # Disable sheets network calls for fast replay
    
    # Let us simulate the exact trade from 11:02 AM (Trade 9/10):
    # Entry at 77189.75, TP at 77288.80, Initial SL at 76866.96
    # Let's seed this trade right at 05:02 UTC candle (t=1789189320)
    t_entry_ms = 1789189320 * 1000 # around 05:02 UTC
    
    # Filter candles starting from 05:02 UTC
    test_candles = [c for c in candles if c["t"] >= 1789189320]
    
    pos = {
        "id": "replay-trade-1",
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry": 77189.75,
        "sl": 76866.96,
        "initial_sl": 76866.96,
        "tp": 77288.80,
        "tp1": 77240.0,
        "margin": 7.0,
        "computed_leverage": 190,
        "status": "PENDING",
        "trailing_active": False,
        "margin_adds": 0,
        "timeline_events": []
    }
    engine.demo_positions = [pos]
    engine.signal_history = [pos]
    
    closed_pos = None
    
    for idx, c in enumerate(test_candles):
        # Pass candle to _update_open_positions
        await engine._update_open_positions("BTCUSDT", c)
        
        if pos.get("status") in ("PROFIT", "LOSS", "BREAKEVEN"):
            closed_pos = pos
            print(f"Trade CLOSED at candle {idx} (timestamp {c['t']}):")
            print(f"  Close Reason: {pos.get('close_reason')}")
            print(f"  Status: {pos.get('status')}")
            print(f"  Exit Price: {pos.get('exit_price'):.2f}")
            print(f"  Net PnL: ${pos.get('net_profit'):.4f}")
            print(f"  Raw Profit: ${pos.get('raw_profit'):.4f}")
            print(f"  Fees: ${pos.get('fees'):.4f}")
            print(f"  Margin Adds Used: {pos.get('margin_adds')}")
            break
            
    if closed_pos is None:
        p = engine.demo_positions[0]
        print(f"Trade remained OPEN through entire window! Current SL: {p['sl']:.2f}, Trailing Active: {p['trailing_active']}")
    else:
        assert closed_pos["close_reason"] == "Take Profit", f"Expected Take Profit, got {closed_pos['close_reason']}"
        assert closed_pos["net_profit"] > 0, "Expected positive Net PnL"
        print("\nPASS: Replay trade survived all volatility and successfully hit TAKE PROFIT!")

if __name__ == "__main__":
    asyncio.run(run_replay())
