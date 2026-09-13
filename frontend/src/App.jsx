import { useState, useEffect, useRef, useMemo } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import SymbolSelector from './components/SymbolSelector';
import SignalBox from './components/SignalBox';
import ChartArea from './components/ChartArea';
import DemoWallet from './components/DemoWallet';
import SignalHistory from './components/SignalHistory';
import { Activity, Bot, FlaskConical, ShieldAlert, Sliders, TrendingUp, TrendingDown, ArrowRight, PauseCircle, Info, X, Menu } from 'lucide-react';

function SystemClock() {
  const [times, setTimes] = useState({ bd: '', tokyo: '', london: '', ny: '' });
  useEffect(() => {
    const interval = setInterval(() => {
      const now = new Date();
      setTimes({
        bd: now.toLocaleTimeString('en-US', { timeZone: 'Asia/Dhaka', hour12: false }),
        tokyo: now.toLocaleTimeString('en-US', { timeZone: 'Asia/Tokyo', hour12: false }),
        london: now.toLocaleTimeString('en-US', { timeZone: 'Europe/London', hour12: false }),
        ny: now.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false })
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);
  return (
    <div className="flex overflow-x-auto whitespace-nowrap max-w-full gap-2 md:gap-3 text-[9px] md:text-[10px] font-mono text-slate-300 items-center scrollbar-hide">
      <div>BD {times.bd}</div>
      <div>TYO {times.tokyo}</div>
      <div>LON {times.london}</div>
      <div>NY {times.ny}</div>
    </div>
  );
}

function App() {
  const wsUrl = import.meta.env.DEV 
    ? `ws://${window.location.hostname}:8000/ws` 
    : `ws://${window.location.host}/ws`;
  const { state, readyState, addSymbol, removeSymbol, activeSymbol, setActiveSymbol, setFilter, toggleShihab, toggleDemoShihab, toggleCircuitBreaker, toggleRegimeFilter, toggleMeanReversion, setDemoInvest, setDemoLeverage, setLiveLeverage, clearHistory, sendMessage } = useWebSocket(wsUrl);
  const [activeSignal, setActiveSignal] = useState(null);
  const prevSignalsLength = useRef(0);

  // Leverage input state
  const [leverageInput, setLeverageInput] = useState('300');
  const [isEditingLeverage, setIsEditingLeverage] = useState(false);

  // Bot Status Modal & Menu State
  const [isBotStatusOpen, setIsBotStatusOpen] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  useEffect(() => {
    if (state.live_leverage !== undefined && !isEditingLeverage) {
      setLeverageInput(String(state.live_leverage));
    }
  }, [state.live_leverage, isEditingLeverage]);

  const handleLeverageSubmit = () => {
    const val = parseInt(leverageInput);
    if (!isNaN(val) && val >= 1 && val <= 500) {
      setLiveLeverage(val);
    } else {
      setLeverageInput(String(state.live_leverage || 300));
    }
    setIsEditingLeverage(false);
  };

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
    <div className="min-h-screen bg-[#0a0f1c] text-slate-200 font-sans pb-12">
      
      {/* Bot Status Modal */}
      {isBotStatusOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 rounded-lg shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col animate-in fade-in zoom-in duration-200">
            <div className="flex items-center justify-between p-4 border-b border-slate-800">
              <h2 className="text-lg font-bold flex items-center gap-2 text-indigo-400">
                <Bot size={20} />
                AI Bot Status & Logic Reports
              </h2>
              <button 
                onClick={() => setIsBotStatusOpen(false)}
                className="p-1 hover:bg-slate-800 rounded text-slate-400 hover:text-white transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            
            <div className="p-4 overflow-y-auto flex-1 space-y-4 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
              {(!state.hourly_reports || state.hourly_reports.length === 0) ? (
                <div className="text-center text-slate-500 py-8">
                  <Bot size={32} className="mx-auto mb-2 opacity-50" />
                  <p>No hourly reports yet.</p>
                  <p className="text-xs mt-1">The AI will generate a report if it stays out of the market for a full hour.</p>
                </div>
              ) : (
                [...state.hourly_reports].reverse().map((report, idx) => (
                  <div key={idx} className="bg-slate-800/50 border border-slate-700/50 rounded p-3">
                    <div className="text-xs font-mono text-slate-400 mb-1 flex items-center gap-1.5">
                      <div className="w-1.5 h-1.5 rounded-full bg-indigo-500"></div>
                      {report.time_window}
                    </div>
                    <p className="text-sm text-slate-300 leading-relaxed">
                      {report.report}
                    </p>
                  </div>
                ))
              )}
            </div>
            <div className="p-3 border-t border-slate-800 bg-slate-900/50 text-xs text-slate-500 text-center">
              Reports are generated hourly when no trades are taken to prevent FOMO and ensure transparency.
            </div>
          </div>
        </div>
      )}

      {/* Clean Header with Hamburger Menu */}
      <header className="sticky top-0 z-40 bg-slate-900/95 backdrop-blur-md border-b border-slate-800 px-2 md:px-4 py-1 md:py-2 flex items-center justify-between shadow-xl">
        <div className="flex items-center gap-1.5 md:gap-3 shrink-0">
          <Activity className="text-blue-500" size={16} md:size={18} />
          <h1 className="text-sm md:text-base font-bold tracking-tight hidden sm:block">Awesome Trader</h1>
          <div className="h-4 md:h-5 w-px bg-slate-700 mx-1 hidden sm:block"></div>
          
          <div className="scale-90 origin-left md:scale-100">
            <SymbolSelector 
              activeSymbol={activeSymbol}
              setActiveSymbol={setActiveSymbol} 
              addSymbol={addSymbol}
              removeSymbol={removeSymbol}
              symbolsList={symbolsList}
            />
          </div>
        </div>

        <div className="flex items-center gap-1 md:gap-3 shrink-0">
          <div className="scale-90 origin-right md:scale-100 hidden sm:block">
            <SystemClock />
          </div>
          <div className="h-4 md:h-5 w-px bg-slate-700 mx-1 hidden sm:block"></div>

          {/* Connection Indicator */}
          <div className="flex items-center justify-center min-w-[20px]">
            <div className={`w-2.5 h-2.5 rounded-full ${readyState === 1 ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)] animate-pulse' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]'}`}></div>
          </div>

          {/* Hamburger Menu Toggle */}
          <div className="relative ml-1">
            <button
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              className="p-1.5 rounded-md text-slate-300 hover:text-white hover:bg-slate-800 transition-colors focus:outline-none"
            >
              {isMenuOpen ? <X size={22} /> : <Menu size={22} />}
            </button>

            {/* Dropdown Control Panel */}
            {isMenuOpen && (
              <div className="absolute top-full right-0 mt-2 w-64 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
                <div className="p-3 border-b border-slate-800 flex items-center justify-between bg-slate-800/50">
                  <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Control Panel</span>
                </div>
                
                <div className="p-2 space-y-1">
                  {/* Leverage Input */}
                  <div className="flex items-center justify-between p-2 hover:bg-slate-800/50 rounded-md transition-colors">
                    <div className="flex items-center gap-2">
                      <Sliders size={14} className="text-amber-400" />
                      <span className="text-sm font-medium text-slate-300">Live Leverage</span>
                    </div>
                    <div className="flex items-center gap-1 bg-slate-950 border border-slate-700 rounded px-2 py-1">
                      <input
                        type="number"
                        min="1"
                        max="500"
                        value={leverageInput}
                        onFocus={() => setIsEditingLeverage(true)}
                        onChange={(e) => setLeverageInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.target.blur();
                          }
                        }}
                        onBlur={handleLeverageSubmit}
                        className="w-10 bg-transparent text-xs font-bold text-amber-400 text-center focus:outline-none"
                      />
                      <span className="text-[10px] font-bold text-slate-500">x</span>
                    </div>
                  </div>

                  {/* Market Regime Toggle */}
                  {state.regime_filter_enabled !== undefined && (
                    <div className="flex items-center justify-between p-2 hover:bg-slate-800/50 rounded-md transition-colors">
                      <div className="flex items-center gap-2">
                        <TrendingUp size={14} className={state.regime_filter_enabled ? "text-blue-400" : "text-slate-500"} />
                        <span className="text-sm font-medium text-slate-300">Market Regime</span>
                      </div>
                      <button
                        onClick={() => toggleRegimeFilter(!state.regime_filter_enabled)}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${state.regime_filter_enabled ? 'bg-blue-500' : 'bg-slate-700'}`}
                      >
                        <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${state.regime_filter_enabled ? 'translate-x-5' : 'translate-x-1'}`} />
                      </button>
                    </div>
                  )}

                  {/* Market Regime Indicator */}
                  {state.market_data && state.market_data[activeSymbol] && state.market_data[activeSymbol].regime && (
                    <div className="flex items-center justify-between p-2 bg-slate-800/30 rounded-md">
                      <div className="flex items-center gap-2">
                        {state.market_data[activeSymbol].regime === 'UPTREND' && <TrendingUp size={16} className="text-emerald-400" />}
                        {state.market_data[activeSymbol].regime === 'DOWNTREND' && <TrendingDown size={16} className="text-rose-400" />}
                        {state.market_data[activeSymbol].regime === 'RANGING' && <ArrowRight size={16} className="text-amber-400" />}
                        <span className="text-sm font-medium text-slate-300">Live Trend</span>
                      </div>
                      <span className={`text-xs font-bold px-2 py-1 rounded-full ${
                        state.market_data[activeSymbol].regime === 'UPTREND' ? 'bg-emerald-900/50 text-emerald-400' :
                        state.market_data[activeSymbol].regime === 'DOWNTREND' ? 'bg-rose-900/50 text-rose-400' :
                        'bg-amber-900/50 text-amber-400'
                      }`}>
                        {state.market_data[activeSymbol].regime}
                      </span>
                    </div>
                  )}

                  {/* Master Pause Toggle */}
                  {state.trading_paused !== undefined && (
                    <div className="flex items-center justify-between p-2 hover:bg-slate-800/50 rounded-md transition-colors">
                      <div className="flex items-center gap-2">
                        <PauseCircle size={14} className={state.trading_paused ? "text-rose-400" : "text-emerald-400"} />
                        <span className="text-sm font-medium text-slate-300">Trading Paused</span>
                      </div>
                      <button
                        onClick={() => toggleCircuitBreaker(!state.trading_paused)}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${state.trading_paused ? 'bg-rose-500 shadow-[0_0_8px_rgba(225,29,72,0.4)] animate-pulse' : 'bg-emerald-500'}`}
                      >
                        <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${state.trading_paused ? 'translate-x-5' : 'translate-x-1'}`} />
                      </button>
                    </div>
                  )}

                  {/* Demo Trading Toggle */}
                  <div className="flex items-center justify-between p-2 hover:bg-slate-800/50 rounded-md transition-colors">
                    <div className="flex items-center gap-2">
                      <FlaskConical size={14} className={state.shihab_demo_active ? 'text-purple-400' : 'text-slate-500'} />
                      <span className="text-sm font-medium text-slate-300">Demo Mode</span>
                    </div>
                    <button
                      onClick={() => toggleDemoShihab(!state.shihab_demo_active)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${state.shihab_demo_active ? 'bg-purple-500 shadow-[0_0_8px_rgba(168,85,247,0.4)]' : 'bg-slate-700'}`}
                    >
                      <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${state.shihab_demo_active ? 'translate-x-5' : 'translate-x-1'}`} />
                    </button>
                  </div>

                  {/* Live Trading Toggle */}
                  <div className="flex items-center justify-between p-2 hover:bg-slate-800/50 rounded-md transition-colors">
                    <div className="flex items-center gap-2">
                      <Bot size={14} className={state.shihab_active ? 'text-blue-400' : 'text-slate-500'} />
                      <span className="text-sm font-medium text-slate-300">Live Trade Eng.</span>
                    </div>
                    <button
                      onClick={() => toggleShihab(!state.shihab_active)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${state.shihab_active ? 'bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.4)]' : 'bg-slate-700'}`}
                    >
                      <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${state.shihab_active ? 'translate-x-5' : 'translate-x-1'}`} />
                    </button>
                  </div>
                </div>

                {/* AI Bot Status Button (Bottom of dropdown) */}
                <div className="p-2 border-t border-slate-800 bg-slate-900/50">
                  <button
                    onClick={() => {
                      setIsMenuOpen(false);
                      setIsBotStatusOpen(true);
                    }}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 border border-indigo-500/30 transition-colors text-sm font-bold"
                  >
                    <Info size={16} />
                    View AI Bot Status
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

        {/* Chart Area - 90vh full width */}
        <div className="w-full h-[90vh] bg-slate-900 border-b border-slate-800">
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

        {/* Bottom content sections */}
        <div className="max-w-[1600px] mx-auto px-4 mt-8 space-y-8">
          <div className="w-full">
            <SignalBox signal={activeSignal} />
          </div>

          <div className="w-full max-w-4xl mx-auto">
            <DemoWallet 
              demoState={state.demo_state} 
              setDemoInvest={setDemoInvest} 
              setDemoLeverage={setDemoLeverage} 
            />
          </div>

          <div className="w-full">
            <SignalHistory history={state.signal_history || []} marketData={state.market_data || {}} onClearHistory={clearHistory} sendMessage={sendMessage} />
          </div>
        </div>
    </div>
  );
}

export default App;
