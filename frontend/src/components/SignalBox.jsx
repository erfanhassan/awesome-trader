import { useEffect } from 'react';
import { Target, Shield, ArrowUpRight, ArrowDownRight, TrendingUp } from 'lucide-react';

let audioCtx = null;

function playChime() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!audioCtx && AudioContext) {
      audioCtx = new AudioContext();
    }
    
    if (!audioCtx) return;

    if (audioCtx.state === 'suspended') {
      audioCtx.resume();
    }

    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    
    osc.type = 'bell'; // 'sine' is fine, but 'triangle' or 'bell' might sound better. standard types: sine, square, sawtooth, triangle
    osc.type = 'triangle';
    
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    
    osc.frequency.setValueAtTime(880, audioCtx.currentTime); 
    gain.gain.setValueAtTime(0, audioCtx.currentTime);
    gain.gain.linearRampToValueAtTime(0.5, audioCtx.currentTime + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 1.5); 
    
    osc.start(audioCtx.currentTime);
    osc.stop(audioCtx.currentTime + 1.5);
  } catch (e) {
    console.warn("AudioContext error:", e);
  }
}

export default function SignalBox({ signal }) {
  useEffect(() => {
    if (signal) {
      playChime();
    }
  }, [signal]);

  if (!signal) {
    return (
      <div className="bg-slate-800 p-8 rounded-xl border border-slate-700 flex flex-col items-center justify-center min-h-[300px] text-center transition-all duration-500">
        <Target size={64} className="text-slate-600 mb-4 opacity-50" />
        <h2 className="text-3xl font-bold text-slate-500">Scanning for Sweeps...</h2>
        <p className="text-slate-500 mt-2">Waiting for London/NY Killzone & liquidity sweep setups.</p>
      </div>
    );
  }

  const isLong = signal.direction === 'LONG';
  const bgColor = isLong ? 'bg-emerald-900/50' : 'bg-rose-900/50';
  const borderColor = isLong ? 'border-emerald-500' : 'border-rose-500';
  const textColor = isLong ? 'text-emerald-400' : 'text-rose-400';
  const Icon = isLong ? ArrowUpRight : ArrowDownRight;

  return (
    <div className={`p-4 md:p-8 rounded-xl border-2 ${bgColor} ${borderColor} shadow-[0_0_50px_rgba(0,0,0,0.3)] shadow-${isLong?'emerald':'rose'}-500/20 transition-all duration-300 min-h-[300px] flex flex-col justify-between animate-pulse`}>
      <div className="flex flex-col sm:flex-row sm:justify-between items-start gap-4">
        <div>
          <div className={`flex items-center gap-2 md:gap-3 ${textColor} mb-1 md:mb-2`}>
            <Icon className="w-6 h-6 md:w-8 md:h-8" />
            <h2 className="text-2xl md:text-4xl font-black uppercase tracking-wider">{signal.direction} TRIGGERED</h2>
          </div>
          <p className="text-slate-300 text-base md:text-xl font-medium">{signal.symbol} • 1m Timeframe</p>
        </div>
        <div className="text-left sm:text-right">
          <p className="text-slate-400 text-xs md:text-sm uppercase tracking-wider">Timestamp</p>
          <p className="text-slate-200 text-sm md:text-base font-mono">{new Date(signal.timestamp).toLocaleTimeString()}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 md:gap-6 mt-6 md:mt-8">
        <div className="bg-slate-900/60 p-3 md:p-4 rounded-lg border border-slate-700/50 min-w-0">
          <div className="flex items-center gap-2 text-slate-400 mb-1 md:mb-2 text-sm md:text-base">
            <TrendingUp size={16} className="md:w-[18px] md:h-[18px]" /> <span>Entry Price</span>
          </div>
          <div className="text-lg md:text-xl lg:text-2xl font-mono font-bold text-white break-all" title={signal.entry}>{Number(signal.entry).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 6})}</div>
        </div>
        <div className="bg-slate-900/60 p-3 md:p-4 rounded-lg border border-rose-900/50 min-w-0">
          <div className="flex items-center gap-2 text-rose-400 mb-1 md:mb-2 text-sm md:text-base">
            <Shield size={16} className="md:w-[18px] md:h-[18px]" /> <span>Stop Loss</span>
          </div>
          <div className="text-lg md:text-xl lg:text-2xl font-mono font-bold text-rose-400 break-all" title={signal.sl}>{Number(signal.sl).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 6})}</div>
        </div>
        <div className="bg-slate-900/60 p-3 md:p-4 rounded-lg border border-emerald-900/50 min-w-0">
          <div className="flex items-center gap-2 text-emerald-400 mb-1 md:mb-2 text-sm md:text-base">
            <Target size={16} className="md:w-[18px] md:h-[18px]" /> <span>Take Profit</span>
          </div>
          <div className="text-lg md:text-xl lg:text-2xl font-mono font-bold text-emerald-400 break-all" title={signal.tp}>{Number(signal.tp).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 6})}</div>
        </div>
      </div>
    </div>
  );
}
