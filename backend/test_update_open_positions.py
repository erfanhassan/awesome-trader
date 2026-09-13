import asyncio
import json
from logic_engine import LogicEngine

async def main():
    engine = LogicEngine()
    engine._load_history()
    # Mock data for current 1m candle (price dropped to 79542)
    data = {
        "t": 1788613140000,
        "o": 79545.0,
        "h": 79545.0,
        "l": 79542.0,
        "c": 79542.0,
        "v": 100,
        "is_closed": False
    }
    
    try:
        await engine._update_open_positions("BTCUSDT", data)
        print("Update successful. PENDING count:", len([p for p in engine.signal_history if p["status"] == "PENDING"]))
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
