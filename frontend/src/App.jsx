import { useState, useEffect, useRef, useMemo } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import SymbolSelector from './components/SymbolSelector';
import Checklist from './components/Checklist';
import SignalBox from './components/SignalBox';
import AIConsole from './components/AIConsole';
import ChartArea from './components/ChartArea';
import DemoWallet from './components/DemoWallet';
import SignalHistory from './components/SignalHistory';
import { Activity, Bot, FlaskConical } from 'lucide-react';

function SystemClock() {
  const [time, setTime] = useState(new Date().toISOString().substring(11, 19));
  useEffect(() => {
    const interval = setInterval(() => {
      setTime(new Date().toISOString().substring(11, 19));
    }, 1000);
    return () => clearInterval(interval);
  }, []);
  return <p className="text-2xl font-mono text-slate-200">{time} UTC</p>;
}

function App() {
  const wsUrl = import.meta.env.DEV 
    ? "ws://localhost:8000/ws" 
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
  const { state, readyState, addSymbol, removeSymbol, activeSymbol, setActiveSymbol, setFilter, toggleShihab, toggleDemoShihab, setDemoInvest, setDemoLeverage, clearHistory } = useWebSocket(wsUrl);
  const [activeSignal, setActiveSignal] = useState(null);
  const prevSignalsLength = useRef(0);

  const playNotificationSound = () => {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gainNode = ctx.createGain();
      
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime); // A5 note
      osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.1); // Drop to A4
      
      gainNode.gain.setValueAtTime(0.1, ctx.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1);
      
      osc.connect(gainNode);
      gainNode.connect(ctx.destination);
      
      osc.start();
      osc.stop(ctx.currentTime + 0.1);
    } catch (err) {
      console.warn("Audio play failed", err);
    }
  };

  // Derive symbols list from state without cascading renders
  const symbolsList = useMemo(() => {
    return state.market_data ? Object.keys(state.market_data) : [];
  }, [state.market_data]);

  useEffect(() => {
    if (symbolsList.length > 0 && !activeSymbol) {
      setActiveSymbol(symbolsList[0]);
    }
  }, [symbolsList, activeSymbol, setActiveSymbol]);

  useEffect(() => {
    if (state.signals && state.signals.length > 0) {
      const latest = state.signals[state.signals.length - 1];
      if (latest.symbol === activeSymbol) {
        setActiveSignal(latest);
      }
      
      // Play sound if there's a new signal
      if (state.signals.length > prevSignalsLength.current) {
        if (prevSignalsLength.current > 0) {
          playNotificationSound();
        }
        prevSignalsLength.current = state.signals.length;
      }
    }
  }, [state.signals, activeSymbol]);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <header className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <Activity className="text-blue-500" size={28} />
            <h1 className="text-2xl font-bold tracking-tight">Liquidity Sweep Scanner</h1>
          </div>
          <div className="flex items-center gap-6">
            <div className="flex gap-2">
              <button
                onClick={() => toggleDemoShihab(!state.shihab_demo_active)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg font-bold transition-all duration-300 text-sm ${
                  state.shihab_demo_active
                    ? 'bg-purple-600 hover:bg-purple-700 text-white shadow-[0_0_15px_rgba(147,51,234,0.5)] animate-pulse'
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-400 border border-slate-700'
                }`}
                title="Simulate trades with Demo Money"
              >
                <FlaskConical size={18} className={state.shihab_demo_active ? 'text-white' : 'text-slate-500'} />
                Demo Shihab: {state.shihab_demo_active ? 'ON' : 'OFF'}
              </button>
              
              <button
                onClick={() => toggleShihab(!state.shihab_active)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg font-bold transition-all duration-300 text-sm ${
                  state.shihab_active
                    ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-[0_0_15px_rgba(37,99,235,0.5)] animate-pulse'
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-400 border border-slate-700'
                }`}
                title="Execute LIVE trades with Real Money"
              >
                <Bot size={18} className={state.shihab_active ? 'text-white' : 'text-slate-500'} />
                Live Shihab: {state.shihab_active ? 'ON' : 'OFF'}
              </button>
            </div>
            
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full ${readyState === 1 ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
              <span className="text-sm font-medium text-slate-400">
                {readyState === 1 ? 'WS Connected' : 'Disconnected'}
              </span>
            </div>
          </div>
        </header>

        {/* Top Controls */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="md:col-span-2">
            <SymbolSelector 
              activeSymbol={activeSymbol}
              setActiveSymbol={setActiveSymbol} 
              addSymbol={addSymbol}
              removeSymbol={removeSymbol}
              symbolsList={symbolsList}
            />
          </div>
          <div className="md:col-span-1">
             {/* Some stats could go here */}
             <div className="bg-slate-800 p-4 rounded-xl border border-slate-700 h-full flex flex-col justify-center">
                <p className="text-slate-400 text-sm">System Time</p>
                <SystemClock />
             </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Left Column (Signal Box + Checklist) */}
          <div className="lg:col-span-1 space-y-6">
            <SignalBox signal={activeSignal} />
              <Checklist 
                killzoneActive={state.killzone_active} 
                symbolState={state.market_data?.[activeSymbol]}
                tradeState={state.trade_data?.[activeSymbol]}
                filterStates={{
                  killzone: state.filter_killzone,
                  htf: state.filter_htf,
                  volume: state.filter_volume,
                  pressure: state.filter_pressure,
                }}
                onSetFilter={setFilter}
              />
          </div>

          {/* Right Column (Chart + AI Console) */}
          <div className="lg:col-span-2 space-y-6 flex flex-col">
            <div className="flex-none">
              <ChartArea 
                symbol={activeSymbol} 
                state={state.market_data} 
                filterStates={{
                  killzone: state.filter_killzone,
                  htf: state.filter_htf,
                  volume: state.filter_volume,
                  pressure: state.filter_pressure,
                }}
                tradeState={state.trade_data?.[activeSymbol]}
                signals={state.signals}
                signalHistory={state.signal_history}
              />
            </div>
            <div className="flex-1 min-h-[200px]">
              <AIConsole signal={activeSignal} />
            </div>
            <div className="flex-1">
              <DemoWallet 
                demoState={state.demo_state} 
                setDemoInvest={setDemoInvest} 
                setDemoLeverage={setDemoLeverage} 
              />
            </div>
            <div className="flex-1">
              <SignalHistory history={state.signal_history || []} marketData={state.market_data || {}} onClearHistory={clearHistory} />
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}

export default App;
