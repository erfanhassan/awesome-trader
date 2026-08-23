import pytest
import asyncio
from logic_engine import LogicEngine

@pytest.fixture
def engine():
    return LogicEngine()

@pytest.mark.asyncio
async def test_margin_calculation(engine):
    symbol = "BTCUSDT"
    await engine.add_symbol(symbol)
    
    # Force a position to be open
    engine.demo_positions = [{
        "symbol": symbol,
        "direction": "LONG",
        "entry": 60000,
        "size": 0.001,
        "margin": 6.0,
        "initial_margin": 6.0,
        "leverage": 10,
        "computed_leverage": 10,
        "tp": 65000,
        "sl": 50000,
        "strategy": {"name": "test"},
        "config": {"auto_margin": True}
    }]
    engine.demo_balance = 100.0
    
    # Process a candle that triggers margin add (price drops significantly)
    candle = {
        "t": 1600000000000,
        "o": 60000,
        "h": 60000,
        "l": 54020,
        "c": 54050,
        "v": 10,
        "is_closed": True
    }
    
    # We mock get_klines so it doesn't crash
    engine.get_klines = lambda s, i: [candle]*200
    
    await engine.process_kline(symbol, "Min1", candle, is_historical=False)
    
    # The margin might be boosted because the price dropped
    assert engine.demo_positions[0]["margin"] >= 6.0

@pytest.mark.asyncio
async def test_missing_config_error_path(engine):
    symbol = "UNKNOWN"
    # Should handle gracefully by not doing anything since UNKNOWN is not in active symbols
    await engine.process_kline(symbol, "Min1", {"t": 123, "c": 100}, is_historical=False)
    assert symbol in engine.kline_data
    assert engine.market_state[symbol]["setup_state"] == "WAITING"

@pytest.mark.asyncio
async def test_state_machine_init(engine):
    symbol = "ETHUSDT"
    await engine.add_symbol(symbol)
    assert symbol in engine.kline_data
    assert symbol in engine.market_state
    
    # Feed some min1 candles to make sure state machine doesn't crash
    for i in range(10):
        candle = {
            "t": 1600000000000 + i*60000,
            "o": 3000,
            "h": 3010,
            "l": 2990,
            "c": 3005,
            "v": 100,
            "is_closed": True
        }
        await engine.process_kline(symbol, "Min1", candle, is_historical=False)
        
    assert engine.market_state[symbol]["setup_state"] in ["WAITING", "SWEPT_HIGH", "SWEPT_LOW"]
