import pytest
import asyncio
import time
from logic_engine import LogicEngine
from mexc_client import MEXCClient

@pytest.mark.asyncio
async def test_concurrent_symbols_stress():
    engine = LogicEngine()
    symbols = [f"COIN{i}USDT" for i in range(10)]
    
    # Initialize all symbols
    for s in symbols:
        await engine.add_symbol(s)
        
    start_time = time.time()
    
    # Simulate high frequency data for 10 symbols concurrently
    # 1000 candles per symbol = 10,000 processed events
    async def feed_symbol(sym):
        for i in range(1000):
            candle = {
                "t": 1600000000000 + i*60000,
                "o": 1000 + i%10,
                "h": 1010 + i%10,
                "l": 990 - i%10,
                "c": 1005 + i%10,
                "v": 100,
                "is_closed": True
            }
            await engine.process_kline(sym, "Min1", candle, is_historical=False)
            
    tasks = [feed_symbol(sym) for sym in symbols]
    await asyncio.gather(*tasks)
    
    duration = time.time() - start_time
    print(f"Processed 10,000 events across 10 symbols in {duration:.2f} seconds")
    
    # Check that it didn't take excessively long (should be very fast)
    assert duration < 15.0

@pytest.mark.asyncio
async def test_websocket_payload_generation():
    engine = LogicEngine()
    await engine.add_symbol("BTCUSDT")
    
    # Get state should not crash and return proper keys
    state = engine.get_state()
    assert "market_data" in state
    assert "demo_state" in state
    assert "shihab_active" in state
    
    # Check if a symbol is in the market_data
    assert "BTCUSDT" in state["market_data"]
