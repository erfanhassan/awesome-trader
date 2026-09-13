import asyncio
import json
import os
import sys
import pandas as pd
import numpy as np

sys.path.append(os.path.join(os.getcwd(), 'backend'))
import logic_engine
from logic_engine import LogicEngine
import datetime

class MockSheets:
    enabled = False
    def append_trade(self, *args, **kwargs): pass
    def update_trade(self, *args, **kwargs): pass

class MockDeepSeek:
    async def generate_mentor_review(self, *args, **kwargs):
        return "Simulated AI review"
    async def generate_hourly_report(self, *args, **kwargs):
        return "Simulated hourly report"

logic_engine.GoogleSheetsClient = MockSheets
logic_engine.DeepSeekClient = MockDeepSeek

def create_base_engine():
    engine = LogicEngine()
    engine.circuit_breaker_enabled = False
    engine.daily_loss_tracker = {
        "date": datetime.date.today().isoformat(),
        "realized_loss": 0.0,
        "realized_pnl": 0.0,
        "trades_count": 0,
        "circuit_breaker_tripped": False,
        "loss_exceeded_notified": False,
    }
    engine.shihab_demo_active = True
    engine.demo_balance = 10000.0
    engine.demo_positions = []
    engine.signals = []
    engine.signal_history = []
    engine.sheets_client = MockSheets()
    engine.deepseek = MockDeepSeek()
    return engine

def generate_base_history(start_p=77200.0, num_candles=100, trend="FLAT"):
    candles = []
    p = start_p
    base_t = 1789200000000
    for i in range(num_candles):
        t = base_t + i * 60000
        if trend == "UP":
            drift = 1.5
        elif trend == "DOWN":
            drift = -1.5
        else:
            drift = 0.0
        step = np.random.normal(drift, 4.0)
        c = p + step
        h = max(p, c) + abs(np.random.normal(2.0, 1.5))
        l = min(p, c) - abs(np.random.normal(2.0, 1.5))
        v = np.random.uniform(50, 150)
        candles.append({
            "t": t, "o": round(p, 1), "h": round(h, 1), "l": round(l, 1), "c": round(c, 1), "v": round(v, 1), "is_closed": True
        })
        p = c
    return candles

async def run_scenario(scenario_id, name, setup_fn):
    engine = create_base_engine()
    symbol = "BTCUSDT"
    await engine.add_symbol(symbol)
    
    # Custom scenario setup
    setup_result = await setup_fn(engine, symbol)
    
    # Analyze outcome
    signals = engine.signals
    trades = engine.signal_history
    positions = engine.demo_positions
    
    return {
        "scenario_id": scenario_id,
        "name": name,
        "description": setup_result.get("description", ""),
        "category": setup_result.get("category", ""),
        "signal_fired": len(signals) > 0,
        "signals_count": len(signals),
        "signals_detail": [{
            "strategy": s.get("strategy"),
            "direction": s.get("direction"),
            "entry": s.get("entry"),
            "sl": s.get("sl"),
            "tp": s.get("tp"),
            "swept_level": s.get("swept_level"),
            "swept_label": s.get("swept_level_label")
        } for s in signals],
        "trades_count": len(trades),
        "trades_detail": [{
            "strategy": t.get("strategy"),
            "direction": t.get("direction"),
            "entry": t.get("entry"),
            "exit_price": t.get("exit_price"),
            "close_reason": t.get("close_reason"),
            "status": t.get("status"),
            "raw_pnl": t.get("raw_profit"),
            "net_pnl": t.get("net_profit"),
            "margin_adds": t.get("margin_adds", 0),
            "trailing_active": t.get("trailing_active", False),
            "events_count": len(t.get("timeline_events", []))
        } for t in trades],
        "vetoed": setup_result.get("expected_veto", False) and len(signals) == 0,
        "notes": setup_result.get("notes", "")
    }

async def main():
    print("Beginning execution of 30 comprehensive market scenarios...\n")
    results = []

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 1: Textbook 15m High Sweep (SHORT) with Bearish Delta Absorption
    # ─────────────────────────────────────────────────────────────────────────
    async def s1(engine, sym):
        history = generate_base_history(77150, 60, "UP")
        engine.kline_data[sym]["Min1"] = history
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.market_state[sym]["15m_swing_lows"] = [77050.0]
        engine.trade_data[sym]["delta"] = -6200 # Absorption capping high
        
        # Trigger candle sweeps 77250 and closes back below
        sweep_c = {"t": history[-1]["t"] + 60000, "o": 77245.0, "h": 77255.0, "l": 77238.0, "c": 77242.0, "v": 120, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Subsequent price moves down to TP
        for i in range(1, 20):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77242.0 - i*10, "h": 77245.0 - i*10, "l": 77230.0 - i*10, "c": 77232.0 - i*10, "v": 80, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "High-Volatility Sweeps & Traps",
            "description": "15m key resistance at $77,250 swept with -$6,200 delta absorption, followed by a clean drop.",
            "notes": "Tests Delta_Sweep entry, maker execution, and downward trailing stop."
        }
    results.append(await run_scenario(1, "Textbook 15m Resistance Sweep (SHORT)", s1))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 2: Textbook 15m Low Sweep (LONG) with Bullish Delta Absorption
    # ─────────────────────────────────────────────────────────────────────────
    async def s2(engine, sym):
        history = generate_base_history(77250, 60, "DOWN")
        engine.kline_data[sym]["Min1"] = history
        engine.market_state[sym]["15m_swing_highs"] = [77350.0]
        engine.market_state[sym]["15m_swing_lows"] = [77150.0]
        engine.trade_data[sym]["delta"] = +6800 # Buyers defending low
        
        sweep_c = {"t": history[-1]["t"] + 60000, "o": 77155.0, "h": 77160.0, "l": 77142.0, "c": 77158.0, "v": 150, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Subsequent price moves up
        for i in range(1, 20):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77158.0 + i*10, "h": 77168.0 + i*10, "l": 77155.0 + i*10, "c": 77165.0 + i*10, "v": 90, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "High-Volatility Sweeps & Traps",
            "description": "15m key support at $77,150 swept with +$6,800 delta absorption, followed by clean rally.",
            "notes": "Tests Delta_Sweep LONG entry and upward trailing stop protection."
        }
    results.append(await run_scenario(2, "Textbook 15m Support Sweep (LONG)", s2))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 3: Trend Continuation Pullback Sweep (Macro UPTREND)
    # ─────────────────────────────────────────────────────────────────────────
    async def s3(engine, sym):
        # 1H candles configured in strong uptrend (EMA 200 below price, ADX > 25)
        h1 = []
        for i in range(250):
            h1.append({"t": i*3600000, "o": 70000 + i*30, "h": 70010 + i*30, "l": 69990 + i*30, "c": 70005 + i*30, "v": 100})
        engine.kline_data[sym]["Min60"] = h1
        engine.kline_data[sym]["Min1"] = generate_base_history(77500, 60, "FLAT")
        engine.market_state[sym]["1h_swing_lows"] = [77450.0]
        engine.market_state[sym]["1h_swing_highs"] = [77800.0]
        engine.trade_data[sym]["delta"] = +5800
        
        sweep_c = {"t": 1789300000, "o": 77455.0, "h": 77460.0, "l": 77442.0, "c": 77458.0, "v": 110, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        for i in range(1, 15):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77458.0 + i*15, "h": 77465.0 + i*15, "l": 77452.0 + i*15, "c": 77462.0 + i*15, "v": 80, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Trending Regimes",
            "description": "Macro UPTREND (ADX > 25) pullbacks into 1H swing low at $77,450, sweeps & reclaims with positive delta.",
            "notes": "Tests Trend_Continuation_Sweep engine and alignment with higher-timeframe regime."
        }
    results.append(await run_scenario(3, "Trend-Continuation Pullback Sweep (UPTREND)", s3))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 4: Trend Continuation Relief Rally Sweep (Macro DOWNTREND)
    # ─────────────────────────────────────────────────────────────────────────
    async def s4(engine, sym):
        h1 = []
        for i in range(250):
            h1.append({"t": i*3600000, "o": 85000 - i*30, "h": 85010 - i*30, "l": 84990 - i*30, "c": 84995 - i*30, "v": 100})
        engine.kline_data[sym]["Min60"] = h1
        engine.kline_data[sym]["Min1"] = generate_base_history(77000, 60, "FLAT")
        engine.market_state[sym]["1h_swing_highs"] = [77100.0]
        engine.market_state[sym]["1h_swing_lows"] = [76500.0]
        engine.trade_data[sym]["delta"] = -5900
        
        sweep_c = {"t": 1789350000, "o": 77095.0, "h": 77112.0, "l": 77090.0, "c": 77092.0, "v": 130, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        for i in range(1, 15):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77092.0 - i*15, "h": 77095.0 - i*15, "l": 77080.0 - i*15, "c": 77082.0 - i*15, "v": 80, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Trending Regimes",
            "description": "Macro DOWNTREND relief rally into 1H swing high at $77,100, sweeps & reclaims with negative delta.",
            "notes": "Tests Trend_Continuation_Sweep SHORT execution in strong macro bear market."
        }
    results.append(await run_scenario(4, "Trend-Continuation Relief Rally Sweep (DOWNTREND)", s4))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 5: Mean Reversion Range-High Resistance Sweep (RANGING)
    # ─────────────────────────────────────────────────────────────────────────
    async def s5(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["4h_session_highs"] = [77300.0]
        engine.market_state[sym]["4h_session_lows"] = [76800.0]
        engine.trade_data[sym]["delta"] = -3500
        
        sweep_c = {"t": 1789400000, "o": 77295.0, "h": 77312.0, "l": 77290.0, "c": 77294.0, "v": 90, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        for i in range(1, 15):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77294.0 - i*12, "h": 77298.0 - i*12, "l": 77285.0 - i*12, "c": 77288.0 - i*12, "v": 70, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Ranging & Compression Regimes",
            "description": "ADX < 20 (RANGING regime). Sweeps 4H range resistance at $77,300 with -$3,500 delta.",
            "notes": "Tests Mean_Reversion_Sweep fading range boundaries."
        }
    results.append(await run_scenario(5, "Mean Reversion Range-High Resistance Sweep", s5))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 6: Mean Reversion Range-Low Support Sweep (RANGING)
    # ─────────────────────────────────────────────────────────────────────────
    async def s6(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(76900, 60, "FLAT")
        engine.market_state[sym]["4h_session_lows"] = [76800.0]
        engine.market_state[sym]["4h_session_highs"] = [77300.0]
        engine.trade_data[sym]["delta"] = +3600
        
        sweep_c = {"t": 1789450000, "o": 76805.0, "h": 76810.0, "l": 76788.0, "c": 76806.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        for i in range(1, 15):
            tick = {"t": sweep_c["t"] + i*60000, "o": 76806.0 + i*12, "h": 76815.0 + i*12, "l": 76802.0 + i*12, "c": 76810.0 + i*12, "v": 70, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Ranging & Compression Regimes",
            "description": "ADX < 20 (RANGING regime). Sweeps 4H range support at $76,800 with +$3,600 delta.",
            "notes": "Tests Mean_Reversion_Sweep buying support in quiet chop."
        }
    results.append(await run_scenario(6, "Mean Reversion Range-Low Support Sweep", s6))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 7: Shihab 4H High Sweep & Break of Rejection Low
    # ─────────────────────────────────────────────────────────────────────────
    async def s7(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77400, 60, "FLAT")
        engine.market_state[sym]["4h_session_highs"] = [77500.0]
        engine.market_state[sym]["4h_session_lows"] = [77000.0]
        
        # Candle 1 sweeps 4H high and closes below -> SWEPT_HIGH
        c1 = {"t": 1789500000, "o": 77490.0, "h": 77515.0, "l": 77470.0, "c": 77485.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, c1)
        
        # Candle 2 breaks rejection low (77470.0) -> triggers SHORT
        c2 = {"t": 1789500000 + 60000, "o": 77485.0, "h": 77488.0, "l": 77465.0, "c": 77468.0, "v": 120, "is_closed": False}
        await engine._evaluate_1m_logic(sym, c2)
        await asyncio.sleep(0.01)
        
        for i in range(1, 15):
            tick = {"t": c2["t"] + i*60000, "o": 77468.0 - i*15, "h": 77472.0 - i*15, "l": 77455.0 - i*15, "c": 77460.0 - i*15, "v": 70, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "High-Volatility Sweeps & Traps",
            "description": "Shihab strategy: 4H session high ($77,500) swept, rejection low at $77,470 broken by candle 2.",
            "notes": "Tests Liquidity_Sweep_Shihab 2-candle confirmation sequence."
        }
    results.append(await run_scenario(7, "Shihab 4H High Sweep & Rejection Breakdown", s7))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 8: Shihab 4H Low Sweep & Break of Rejection High
    # ─────────────────────────────────────────────────────────────────────────
    async def s8(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77100, 60, "FLAT")
        engine.market_state[sym]["4h_session_lows"] = [77000.0]
        engine.market_state[sym]["4h_session_highs"] = [77500.0]
        
        c1 = {"t": 1789550000, "o": 77010.0, "h": 77025.0, "l": 76985.0, "c": 77015.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, c1)
        
        # Candle 2 breaks rejection high (77025.0) -> triggers LONG
        c2 = {"t": 1789550000 + 60000, "o": 77015.0, "h": 77030.0, "l": 77010.0, "c": 77028.0, "v": 120, "is_closed": False}
        await engine._evaluate_1m_logic(sym, c2)
        await asyncio.sleep(0.01)
        
        for i in range(1, 15):
            tick = {"t": c2["t"] + i*60000, "o": 77028.0 + i*15, "h": 77035.0 + i*15, "l": 77022.0 + i*15, "c": 77030.0 + i*15, "v": 70, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "High-Volatility Sweeps & Traps",
            "description": "Shihab strategy: 4H session low ($77,000) swept, rejection high at $77,025 broken by candle 2.",
            "notes": "Tests Liquidity_Sweep_Shihab LONG confirmation sequence."
        }
    results.append(await run_scenario(8, "Shihab 4H Low Sweep & Rejection Breakout", s8))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 9: Flash Wick with Violent V-Reversal
    # ─────────────────────────────────────────────────────────────────────────
    async def s9(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.market_state[sym]["15m_swing_highs"] = [77400.0]
        engine.trade_data[sym]["delta"] = +8500
        
        # Massive 100-point lower wick
        sweep_c = {"t": 1789600000, "o": 77185.0, "h": 77195.0, "l": 77080.0, "c": 77192.0, "v": 350, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Immediate 150-point rocket up
        for i in range(1, 15):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77192.0 + i*15, "h": 77205.0 + i*15, "l": 77190.0 + i*15, "c": 77202.0 + i*15, "v": 150, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Extreme Stress & Black Swan Events",
            "description": "100-point flash wick down to $77,080 instantly absorbed with +8,500 delta and rockets +150 points.",
            "notes": "Tests wide wick extreme calculation and Take Profit geometry on violent spikes."
        }
    results.append(await run_scenario(9, "Flash Wick With Instant V-Reversal", s9))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 10: Deep Drawdown Testing Auto-Margin Averaging Down
    # ─────────────────────────────────────────────────────────────────────────
    async def s10(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.market_state[sym]["15m_swing_highs"] = [77500.0]
        engine.trade_data[sym]["delta"] = +5500
        
        sweep_c = {"t": 1789650000, "o": 77182.0, "h": 77185.0, "l": 77170.0, "c": 77182.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Price drops deeply into danger zone (<20% of SL distance)
        # Entry = 77180, Initial SL = ~76870 (diff ~310 pts). Danger zone is below 76930
        for i in range(1, 6):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77180.0 - i*50, "h": 77185.0 - i*50, "l": 77120.0 - i*50, "c": 77130.0 - i*50, "v": 100, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        # Then price bounces strongly
        for i in range(6, 20):
            tick = {"t": sweep_c["t"] + i*60000, "o": 76930.0 + (i-6)*30, "h": 76940.0 + (i-6)*30, "l": 76920.0 + (i-6)*30, "c": 76935.0 + (i-6)*30, "v": 100, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Structural Edge Cases",
            "description": "Deep adverse move pushing into the 20% danger zone to verify auto-margin averaging down.",
            "notes": "Verifies that $5.00 auto-margin addition executes properly when genuinely in drawdown."
        }
    results.append(await run_scenario(10, "Deep Drawdown Auto-Margin Averaging Down", s10))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 11: Multi-Strategy Concurrency (Delta_Sweep + Mean_Reversion)
    # ─────────────────────────────────────────────────────────────────────────
    async def s11(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.market_state[sym]["4h_session_lows"] = [77180.0]
        engine.market_state[sym]["4h_session_highs"] = [77400.0]
        # Delta > 5000 satisfies Delta_Sweep, and ADX < 20 satisfies Mean_Reversion_Sweep
        engine.trade_data[sym]["delta"] = +6500
        
        sweep_c = {"t": 1789700000, "o": 77185.0, "h": 77190.0, "l": 77172.0, "c": 77184.0, "v": 120, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Structural Edge Cases",
            "description": "Ranging market + strong delta absorption causes both Delta_Sweep and Mean_Reversion_Sweep to trigger.",
            "notes": "Tests multi-strategy independence: both strategies take their trades concurrently."
        }
    results.append(await run_scenario(11, "Multi-Strategy Concurrency (Dual Entry)", s11))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 12: Premature Retrace (+25 pts then -15 pts pullback then Rally)
    # ─────────────────────────────────────────────────────────────────────────
    async def s12(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77180, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.market_state[sym]["15m_swing_highs"] = [77320.0]
        engine.trade_data[sym]["delta"] = +6000
        
        sweep_c = {"t": 1789750000, "o": 77182.0, "h": 77185.0, "l": 77174.0, "c": 77181.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Moves up 25 pts (old code suicided here)
        t1 = {"t": sweep_c["t"] + 60000, "o": 77181.0, "h": 77206.0, "l": 77180.0, "c": 77205.0, "v": 80, "is_closed": False}
        await engine._update_open_positions(sym, t1)
        
        # Pulls back 15 pts
        t2 = {"t": sweep_c["t"] + 120000, "o": 77205.0, "h": 77206.0, "l": 77190.0, "c": 77192.0, "v": 60, "is_closed": False}
        await engine._update_open_positions(sym, t2)
        
        # Rockets up to Take Profit
        for i in range(3, 15):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77192.0 + (i-2)*15, "h": 77200.0 + (i-2)*15, "l": 77190.0 + (i-2)*15, "c": 77198.0 + (i-2)*15, "v": 90, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Structural Edge Cases",
            "description": "Exact replay of September 12 11:00 AM dynamic: early +25 pt move, -15 pt pullback, then full run to TP.",
            "notes": "Verifies that our new Trailing Stop / Breakeven math does NOT suicide on the early pullback."
        }
    results.append(await run_scenario(12, "Early Retrace Resilience (The Sep 12 Bug Fix)", s12))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 13: Parabolic Breakout With Zero Reversal (Opposing Delta Veto)
    # ─────────────────────────────────────────────────────────────────────────
    async def s13(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77300, 60, "UP")
        engine.market_state[sym]["15m_swing_highs"] = [77350.0]
        # Delta is heavily POSITIVE (+18,000) - buyers in complete control, breakout is REAL
        engine.trade_data[sym]["delta"] = +18000
        
        # Candle breaks out and stays above level
        breakout_c = {"t": 1789800000, "o": 77340.0, "h": 77390.0, "l": 77338.0, "c": 77385.0, "v": 450, "is_closed": True}
        await engine._evaluate_1m_logic(sym, breakout_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Trending Regimes",
            "description": "Parabolic breakout through $77,350 with +18,000 buyer delta. No failed breakout printed.",
            "expected_veto": True,
            "notes": "Tests that bot correctly refuses to short against strong momentum continuation."
        }
    results.append(await run_scenario(13, "Parabolic Breakout (Opposing Delta Veto)", s13))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 14: Failed Setup Hitting Structural Stop Loss
    # ─────────────────────────────────────────────────────────────────────────
    async def s14(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.market_state[sym]["15m_swing_lows"] = [77000.0]
        engine.trade_data[sym]["delta"] = -5500
        
        sweep_c = {"t": 1789850000, "o": 77245.0, "h": 77255.0, "l": 77240.0, "c": 77244.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Market violently inverses and spikes through structural SL (~77550)
        for i in range(1, 10):
            tick = {"t": sweep_c["t"] + i*60000, "o": 77244.0 + i*40, "h": 77250.0 + i*40, "l": 77240.0 + i*40, "c": 77248.0 + i*40, "v": 120, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Structural Edge Cases",
            "description": "Valid sweep setup that gets overpowered by sudden institutional breakout, hitting structural SL.",
            "notes": "Tests structural SL triggering, taker fee/slippage calculation, and level blacklisting."
        }
    results.append(await run_scenario(14, "Structural Stop Loss & Exhaustion Blacklist", s14))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 15: Low-Volatility Micro-ATR Squeeze (ATR Floor Test)
    # ─────────────────────────────────────────────────────────────────────────
    async def s15(engine, sym):
        # Generate candles with tiny 2-point ranges (ATR drops to 2.5)
        history = []
        base_t = 1789900000000
        for i in range(60):
            history.append({"t": base_t + i*60000, "o": 77200.0, "h": 77201.5, "l": 77199.5, "c": 77200.5, "v": 10, "is_closed": True})
        engine.kline_data[sym]["Min1"] = history
        engine.market_state[sym]["15m_swing_lows"] = [77195.0]
        engine.market_state[sym]["15m_swing_highs"] = [77300.0]
        engine.trade_data[sym]["delta"] = +5200
        
        sweep_c = {"t": base_t + 61*60000, "o": 77196.0, "h": 77198.0, "l": 77192.0, "c": 77196.0, "v": 50, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Price moves up 20 points
        tick = {"t": sweep_c["t"] + 60000, "o": 77196.0, "h": 77218.0, "l": 77195.0, "c": 77216.0, "v": 40, "is_closed": False}
        await engine._update_open_positions(sym, tick)
        
        return {
            "category": "Ranging & Compression Regimes",
            "description": "Asian session dead volatility where 1m ATR drops to 2.5 points.",
            "notes": "Verifies that our 15.0 ATR floor prevents setting a suicidal 3-point trailing stop."
        }
    results.append(await run_scenario(15, "Low-Volatility Micro-ATR Squeeze", s15))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 16: Spread Anomaly & Liquidity Vacuum (Defensive Veto)
    # ─────────────────────────────────────────────────────────────────────────
    async def s16(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.trade_data[sym]["delta"] = -6000
        
        # Orderbook spread widens to 0.15% (115 points)
        engine.market_state[sym]["depth20"] = {
            "bids": [["77180.0", "1.0"]],
            "asks": [["77295.0", "1.0"]] # Spread = (77295-77180)/77295 = 0.15% > 0.08% limit
        }
        
        sweep_c = {"t": 1789950000, "o": 77245.0, "h": 77255.0, "l": 77240.0, "c": 77244.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Extreme Stress & Black Swan Events",
            "description": "Orderbook liquidity dries up; spread blows out to 115 points (0.15%).",
            "expected_veto": True,
            "notes": "Tests spread anomaly defense filter in _trigger_signal."
        }
    results.append(await run_scenario(16, "Spread Anomaly & Liquidity Vacuum Veto", s16))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 17: Maximum Entry Distance Filter Veto (>0.15% Chase)
    # ─────────────────────────────────────────────────────────────────────────
    async def s17(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77000.0] # Swept level at 77000
        engine.trade_data[sym]["delta"] = +6500
        
        # Candle closed at 77180 (+180 pts above level, 0.23% > 0.15% allowed)
        sweep_c = {"t": 1790000000, "o": 77010.0, "h": 77185.0, "l": 76990.0, "c": 77180.0, "v": 150, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Structural Edge Cases",
            "description": "Sweep of $77,000 occurs, but trigger candle closes 180 points away (0.23% distance).",
            "expected_veto": True,
            "notes": "Verifies that bot refuses to chase extended entries (>0.15% from swept level)."
        }
    results.append(await run_scenario(17, "Entry Distance Filter Veto (Anti-FOMO)", s17))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 18: TP1 Partial Take Profit + Breakeven Exit
    # ─────────────────────────────────────────────────────────────────────────
    async def s18(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.market_state[sym]["15m_swing_highs"] = [77500.0]
        engine.trade_data[sym]["delta"] = +6000
        
        sweep_c = {"t": 1790050000, "o": 77182.0, "h": 77185.0, "l": 77174.0, "c": 77181.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Override TP1 to 77240 for clear test
        if engine.demo_positions:
            engine.demo_positions[0]["tp1"] = 77240.0
            
        # Tick reaches TP1 (77240)
        t1 = {"t": sweep_c["t"] + 60000, "o": 77181.0, "h": 77245.0, "l": 77180.0, "c": 77242.0, "v": 100, "is_closed": False}
        await engine._update_open_positions(sym, t1)
        
        # Price retraces back to entry/breakeven
        t2 = {"t": sweep_c["t"] + 120000, "o": 77242.0, "h": 77242.0, "l": 77200.0, "c": 77205.0, "v": 100, "is_closed": False}
        await engine._update_open_positions(sym, t2)
        
        return {
            "category": "High-Volatility Sweeps & Traps",
            "description": "Trade hits TP1 (locks in 50% profit), moves SL to breakeven, then gets taken out risk-free.",
            "notes": "Tests partial close and fee-protected breakeven execution."
        }
    results.append(await run_scenario(18, "TP1 Hit & Risk-Free Breakeven Conclusion", s18))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 19: Double Bottom Liquidity Sweep (Secondary Re-Entry)
    # ─────────────────────────────────────────────────────────────────────────
    async def s19(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77150.0]
        engine.market_state[sym]["15m_swing_highs"] = [77350.0]
        engine.trade_data[sym]["delta"] = +6500
        
        # First sweep
        c1 = {"t": 1790100000, "o": 77155.0, "h": 77160.0, "l": 77144.0, "c": 77154.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, c1)
        await asyncio.sleep(0.01)
        
        # Close trade 1 cleanly at TP
        t_close = {"t": 1790100060, "o": 77350.0, "h": 77360.0, "l": 77340.0, "c": 77355.0, "v": 100, "is_closed": False}
        await engine._update_open_positions(sym, t_close)
        
        # Second deeper sweep of 77144 on subsequent candle
        engine.market_state[sym]["15m_swing_lows"] = [77144.0]
        c2 = {"t": 1790100120, "o": 77148.0, "h": 77152.0, "l": 77135.0, "c": 77146.0, "v": 120, "is_closed": True}
        await engine._evaluate_1m_logic(sym, c2)
        await asyncio.sleep(0.01)
        
        return {
            "category": "High-Volatility Sweeps & Traps",
            "description": "Double bottom: First sweep at $77,150, followed by a second sweep of the wick at $77,144.",
            "notes": "Verifies that level state machine resets and accepts consecutive valid setups."
        }
    results.append(await run_scenario(19, "Double Bottom Liquidity Sweep Re-Entry", s19))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 20: Slow-Bleed Breakdown with Zero Absorption (No Entry)
    # ─────────────────────────────────────────────────────────────────────────
    async def s20(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "DOWN")
        engine.market_state[sym]["15m_swing_lows"] = [77150.0]
        # Delta is NEGATIVE (-4500) - sellers pushing, no buyer defense
        engine.trade_data[sym]["delta"] = -4500
        
        # Drops below 77150 and closes at 77145 (no reclaim)
        c = {"t": 1790150000, "o": 77155.0, "h": 77156.0, "l": 77140.0, "c": 77145.0, "v": 80, "is_closed": True}
        await engine._evaluate_1m_logic(sym, c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Trending Regimes",
            "description": "Price bleeds below $77,150 with negative delta (-4,500). No absorption, no failed breakdown.",
            "expected_veto": True,
            "notes": "Tests that bot does not catch falling knives when buyers are absent."
        }
    results.append(await run_scenario(20, "Slow-Bleed Breakdown (No Absorption Filter)", s20))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 21: News Spike Pump & Instant Dump
    # ─────────────────────────────────────────────────────────────────────────
    async def s21(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77100, 60, "FLAT")
        engine.market_state[sym]["1h_swing_highs"] = [77300.0]
        engine.market_state[sym]["1h_swing_lows"] = [76900.0]
        engine.trade_data[sym]["delta"] = -12000 # Aggressive selling absorption
        
        # 1-minute candle spikes 220 points, sweeps 77300, and dumps back to 77280
        c = {"t": 1790200000, "o": 77120.0, "h": 77340.0, "l": 77115.0, "c": 77280.0, "v": 500, "is_closed": True}
        await engine._evaluate_1m_logic(sym, c)
        await asyncio.sleep(0.01)
        
        for i in range(1, 10):
            tick = {"t": c["t"] + i*60000, "o": 77280.0 - i*35, "h": 77285.0 - i*35, "l": 77240.0 - i*35, "c": 77245.0 - i*35, "v": 200, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Extreme Stress & Black Swan Events",
            "description": "CPI/FOMC style news wick: 220-point spike above $77,300 absorbed with -12,000 delta.",
            "notes": "Tests speed and resilience under extreme news volatility."
        }
    results.append(await run_scenario(21, "News Spike Pump & Immediate Liquidation Dump", s21))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 22: Daily Loss Circuit Breaker Tripping
    # ─────────────────────────────────────────────────────────────────────────
    async def s22(engine, sym):
        # Trip daily circuit breaker
        engine.circuit_breaker_enabled = True
        engine.daily_loss_tracker["realized_loss"] = 16.50 # > $15.00 limit
        engine.daily_loss_tracker["circuit_breaker_tripped"] = True
        
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.trade_data[sym]["delta"] = -7000
        
        sweep_c = {"t": 1790250000, "o": 77245.0, "h": 77255.0, "l": 77240.0, "c": 77244.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Extreme Stress & Black Swan Events",
            "description": "Daily loss exceeds $15.00 threshold ($16.50). Setup triggers on chart.",
            "expected_veto": True,
            "notes": "Tests circuit breaker enforcement blocking capital destruction."
        }
    results.append(await run_scenario(22, "Daily Loss Circuit Breaker Tripping", s22))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 23: Ghost Duplicate Inflow (Rapid Duplicate Tick Ingestion)
    # ─────────────────────────────────────────────────────────────────────────
    async def s23(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.trade_data[sym]["delta"] = -6000
        
        sweep_c = {"t": 1790300000, "o": 77245.0, "h": 77255.0, "l": 77240.0, "c": 77244.0, "v": 100, "is_closed": True}
        
        # Simulate websocket packet burst sending same closed candle 4 times
        for _ in range(4):
            await engine._evaluate_1m_logic(sym, sweep_c)
            await asyncio.sleep(0.002)
            
        return {
            "category": "Structural Edge Cases",
            "description": "Network buffer burst sending 4 duplicate candle packets in 10ms.",
            "notes": "Tests ghost deduplication guard: exactly 1 trade must be created."
        }
    results.append(await run_scenario(23, "Rapid Duplicate Packet Burst (Ghost Suppression)", s23))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 24: High-Leverage Liquidation Proximity Survival
    # ─────────────────────────────────────────────────────────────────────────
    async def s24(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.trade_data[sym]["delta"] = +6000
        
        sweep_c = {"t": 1790350000, "o": 77182.0, "h": 77185.0, "l": 77174.0, "c": 77181.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        if engine.demo_positions:
            p = engine.demo_positions[0]
            liq_p = p.get("liq_price", 76840.0)
            
            # Price drops to $3 above liquidation price, but does not cross it
            danger_tick = {"t": sweep_c["t"] + 60000, "o": 77180.0, "h": 77180.0, "l": liq_p + 3.0, "c": liq_p + 5.0, "v": 200, "is_closed": False}
            await engine._update_open_positions(sym, danger_tick)
        
        return {
            "category": "Extreme Stress & Black Swan Events",
            "description": "Adverse wick drops within $3.00 of liquidation price without touching it.",
            "notes": "Tests liquidation price calculation and survival boundary."
        }
    results.append(await run_scenario(24, "High-Leverage Liquidation Proximity Survival", s24))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 25: Funding Rate Bias Filter
    # ─────────────────────────────────────────────────────────────────────────
    async def s25(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.market_state[sym]["funding_rate"] = 0.0008 # Heavily overleveraged LONG
        engine.trade_data[sym]["delta"] = -6500
        
        sweep_c = {"t": 1790400000, "o": 77245.0, "h": 77255.0, "l": 77240.0, "c": 77244.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Extreme Stress & Black Swan Events",
            "description": "Extreme positive funding rate (+0.08%) favoring institutional short squeeze.",
            "notes": "Tests funding fee calculation and contrarian short bias."
        }
    results.append(await run_scenario(25, "Extreme Funding Rate Bias Filter", s25))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 26: Exhaustion Veto Level Blacklist Enforcement
    # ─────────────────────────────────────────────────────────────────────────
    async def s26(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        # Pre-blacklist level 77250 due to previous true structural failure
        engine.market_state[sym]["blacklisted_levels"] = [77250.0]
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.trade_data[sym]["delta"] = -6000
        
        sweep_c = {"t": 1790450000, "o": 77245.0, "h": 77255.0, "l": 77240.0, "c": 77244.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Structural Edge Cases",
            "description": "Level at $77,250 previously failed and is blacklisted in market_state.",
            "expected_veto": True,
            "notes": "Verifies that blacklisted levels are rejected to prevent repeat losses."
        }
    results.append(await run_scenario(26, "Exhaustion Veto Blacklist Enforcement", s26))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 27: Multi-Timeframe Confluence Sweep (15m + 1H + 4H)
    # ─────────────────────────────────────────────────────────────────────────
    async def s27(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        # Level 77300 aligns on 15m, 1H, and 4H
        engine.market_state[sym]["15m_swing_highs"] = [77300.0]
        engine.market_state[sym]["1h_swing_highs"] = [77300.0]
        engine.market_state[sym]["4h_session_highs"] = [77300.0]
        engine.market_state[sym]["15m_swing_lows"] = [76950.0]
        engine.trade_data[sym]["delta"] = -7500
        
        sweep_c = {"t": 1790500000, "o": 77295.0, "h": 77310.0, "l": 77290.0, "c": 77292.0, "v": 150, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        return {
            "category": "Structural Edge Cases",
            "description": "Macro confluence level: $77,300 aligns across 15m, 1H, and 4H timeframes.",
            "notes": "Tests liquidity priority and Take Profit targeting on multi-timeframe confluence."
        }
    results.append(await run_scenario(27, "Multi-Timeframe Confluence Sweep (15m/1H/4H)", s27))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 28: Staircase Bull Run With Dynamic Trailing Stop Lock-Ins
    # ─────────────────────────────────────────────────────────────────────────
    async def s28(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77180, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.market_state[sym]["15m_swing_highs"] = [77500.0]
        engine.trade_data[sym]["delta"] = +6000
        
        sweep_c = {"t": 1790550000, "o": 77182.0, "h": 77185.0, "l": 77174.0, "c": 77181.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Staircase advance: +35 pts, +60 pts, +90 pts, +130 pts
        steps = [35, 60, 90, 130]
        for idx, s in enumerate(steps):
            tick = {"t": sweep_c["t"] + (idx+1)*60000, "o": 77180.0 + s, "h": 77185.0 + s, "l": 77175.0 + s, "c": 77180.0 + s, "v": 100, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Trending Regimes",
            "description": "Staircase bull advance progressing through +35, +60, +90, +130 points.",
            "notes": "Verifies step-by-step upward trailing stop progression without premature exit."
        }
    results.append(await run_scenario(28, "Staircase Bull Run Dynamic Trailing Lock-In", s28))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 29: Staircase Bear Run With Short Trailing Stop Progression
    # ─────────────────────────────────────────────────────────────────────────
    async def s29(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77250, 60, "FLAT")
        engine.market_state[sym]["15m_swing_highs"] = [77250.0]
        engine.market_state[sym]["15m_swing_lows"] = [76900.0]
        engine.trade_data[sym]["delta"] = -6000
        
        sweep_c = {"t": 1790600000, "o": 77245.0, "h": 77255.0, "l": 77240.0, "c": 77242.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        steps = [35, 60, 90, 130]
        for idx, s in enumerate(steps):
            tick = {"t": sweep_c["t"] + (idx+1)*60000, "o": 77250.0 - s, "h": 77255.0 - s, "l": 77245.0 - s, "c": 77250.0 - s, "v": 100, "is_closed": False}
            await engine._update_open_positions(sym, tick)
            
        return {
            "category": "Trending Regimes",
            "description": "Staircase bear decline cascading through -35, -60, -90, -130 points.",
            "notes": "Verifies downward trailing stop ratchet and locked value on short positions."
        }
    results.append(await run_scenario(29, "Staircase Bear Run Dynamic Trailing Lock-In", s29))

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 30: Violent Liquidation Cascade Through Structural SL
    # ─────────────────────────────────────────────────────────────────────────
    async def s30(engine, sym):
        engine.kline_data[sym]["Min1"] = generate_base_history(77200, 60, "FLAT")
        engine.market_state[sym]["15m_swing_lows"] = [77180.0]
        engine.trade_data[sym]["delta"] = +5500
        
        sweep_c = {"t": 1790650000, "o": 77182.0, "h": 77185.0, "l": 77174.0, "c": 77181.0, "v": 100, "is_closed": True}
        await engine._evaluate_1m_logic(sym, sweep_c)
        await asyncio.sleep(0.01)
        
        # Massive 400-point dump straight through liquidation price
        dump_tick = {"t": sweep_c["t"] + 60000, "o": 77180.0, "h": 77180.0, "l": 76700.0, "c": 76750.0, "v": 1000, "is_closed": False}
        await engine._update_open_positions(sym, dump_tick)
        
        return {
            "category": "Extreme Stress & Black Swan Events",
            "description": "Institutional liquidation cascade dumps 450 points straight through SL and Liq.",
            "notes": "Tests emergency liquidation handling, margin balance adjustment, and daily tracker recording."
        }
    results.append(await run_scenario(30, "Liquidation Cascade Emergency Handling", s30))

    with open("results_30_scenarios.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Successfully simulated all {len(results)} market scenarios!")
    print(f"Results saved to results_30_scenarios.json")

if __name__ == "__main__":
    asyncio.run(main())
