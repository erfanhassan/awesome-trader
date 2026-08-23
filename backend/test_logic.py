import sys
import asyncio
from logic_engine import LogicEngine

async def main():
    print("Testing logic engine initialized")
    engine = LogicEngine()
    
    symbol = "BTCUSDT"
    await engine.add_symbol(symbol)
    
    # Send some fake 1m candles
    for i in range(1, 100):
        candle = {
            "t": 1600000000000 + (i * 60000),
            "o": 60000 + i,
            "h": 60005 + i,
            "l": 59995 + i,
            "c": 60002 + i,
            "v": 10 + (i%5),
            "is_closed": True
        }
        await engine.process_kline(symbol, "Min1", candle, is_historical=False)
        
    print("Test finished without crashes.")

if __name__ == "__main__":
    asyncio.run(main())
