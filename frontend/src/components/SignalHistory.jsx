import { useState } from 'react';
import { Clock, CheckCircle2, XCircle, History, Trash2 } from 'lucide-react';

const SignalHistory = ({ history, marketData, onClearHistory }) => {
  const [selectedStrategy, setSelectedStrategy] = useState('ALL');
  
  if (!history || history.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 shadow-lg h-full flex flex-col justify-center items-center text-slate-400">
        <History size={48} className="mb-4 opacity-50" />
        <p>No trade history available yet.</p>
      </div>
    );
  }

  // Extract unique strategies
  const strategies = ['ALL', ...new Set(history.map(h => h.strategy || 'S0_Baseline_400x'))];
  
  // Filter and reverse history so newest is at the top
  const filteredHistory = history.filter(h => selectedStrategy === 'ALL' || (h.strategy || 'S0_Baseline_400x') === selectedStrategy);
  const sortedHistory = [...filteredHistory].reverse();

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 shadow-lg flex flex-col h-full max-h-[400px]">
      <div className="p-4 border-b border-slate-700 flex items-center justify-between bg-slate-800/50 rounded-t-xl">
        <div className="flex items-center gap-2 text-slate-200 font-bold">
          <History className="text-blue-500" size={20} />
          <span>Trade History</span>
        </div>
        <div className="flex items-center gap-3">
          <select 
            value={selectedStrategy} 
            onChange={(e) => setSelectedStrategy(e.target.value)}
            className="text-xs bg-slate-900 border border-slate-700 text-slate-300 rounded-md px-2 py-1 outline-none"
          >
            {strategies.map(s => <option key={s} value={s}>{s.replace('S0_', '').replace('S1_', '').replace('S2_', '').replace('S3_', '').replace('S4_', '').replace('S5_', '').replace('S6_', '').replace('S7_', '').replace('S8_', '').replace('S9_', '').replace('S10_', '')}</option>)}
          </select>
          <div className="text-xs text-slate-500 font-medium px-2 py-1 bg-slate-900 rounded-md">
            {filteredHistory.length} signals
          </div>
          {history.length > 0 && (
            <button 
              onClick={onClearHistory}
              className="text-xs text-rose-400 hover:text-rose-300 bg-rose-500/10 hover:bg-rose-500/20 px-2 py-1 rounded-md flex items-center gap-1 transition-colors"
              title="Clear all trade history"
            >
              <Trash2 size={12} />
              Clear
            </button>
          )}
        </div>
      </div>
      
      <div className="overflow-y-auto p-4 flex-1 space-y-3">
        {sortedHistory.map((trade) => {
          let displayStatus = trade.status;
          let displayPnl = trade.pnl;
          let isProfit = trade.status === "PROFIT";
          let isLoss = trade.status === "LOSS";
          const isPending = trade.status === "PENDING";
          let displayExitPrice = trade.exit_price;
          
          if (isPending && marketData?.[trade.symbol]?.price && trade.entry) {
            const currentPrice = marketData[trade.symbol].price;
            displayExitPrice = currentPrice;
            
            if (trade.direction === 'LONG') {
              displayPnl = ((currentPrice - trade.entry) / trade.entry) * 100;
            } else {
              displayPnl = ((trade.entry - currentPrice) / trade.entry) * 100;
            }
            
            if (displayPnl > 0) {
              isProfit = true;
              isLoss = false;
              displayStatus = "LIVE PROFIT";
            } else if (displayPnl < 0) {
              isProfit = false;
              isLoss = true;
              displayStatus = "LIVE LOSS";
            }
          }
          
          return (
            <div key={trade.id} className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50 hover:border-slate-600 transition-colors">
              <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2">
                  <span className={`font-bold ${trade.direction === 'LONG' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {trade.direction}
                  </span>
                  <span className="text-slate-300 font-medium">{trade.symbol}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-900 text-slate-400 border border-slate-700">
                    {trade.strategy || 'Baseline'}
                  </span>
                </div>
                <div className="text-xs text-slate-500 flex items-center gap-1">
                  {isProfit && <CheckCircle2 size={14} className="text-emerald-500" />}
                  {isLoss && <XCircle size={14} className="text-rose-500" />}
                  {isPending && displayPnl === 0 && <Clock size={14} className="text-amber-500" />}
                  <span className={`text-xs font-bold ${
                    isProfit ? 'text-emerald-500' : 
                    isLoss ? 'text-rose-500' : 
                    'text-amber-500'
                  }`}>
                    {displayStatus}
                    {displayPnl !== 0 && ` (${displayPnl > 0 ? '+' : ''}${displayPnl.toFixed(2)}%)`}
                  </span>
                </div>
              </div>
              
              <div className="grid grid-cols-3 gap-2 text-xs text-slate-400 mt-2">
                <div>
                  <span className="block text-slate-500 mb-0.5">Entry</span>
                  <span className="font-mono">{trade.entry?.toFixed(2)}</span>
                </div>
                <div>
                  <span className="block text-slate-500 mb-0.5">SL</span>
                  <span className="font-mono text-rose-400/80">{trade.sl?.toFixed(2)}</span>
                </div>
                <div>
                  <span className="block text-slate-500 mb-0.5">TP</span>
                  <span className="font-mono text-emerald-400/80">{trade.tp?.toFixed(2)}</span>
                </div>
              </div>
              <div className="mt-2 text-[10px] text-slate-500 flex justify-between">
                <span>{new Date(trade.timestamp).toLocaleString()}</span>
                {!isPending && trade.exit_price > 0 && (
                   <span>Exit: {trade.exit_price?.toFixed(2)}</span>
                )}
                {isPending && displayExitPrice > 0 && (
                   <span>Live: {displayExitPrice?.toFixed(2)}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default SignalHistory;
