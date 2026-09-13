import { useState } from 'react';
import { Clock, CheckCircle2, XCircle, History, Trash2, Copy, Check, Target, LogOut, BookOpen } from 'lucide-react';
import ExplainerModal from './ExplainerModal';

const SignalHistory = ({ history, marketData, onClearHistory, sendMessage }) => {
  const [selectedStrategy, setSelectedStrategy] = useState('ALL');
  const [copiedId, setCopiedId] = useState(null);
  const [tpInputs, setTpInputs] = useState({});     // trade_id -> string input value
  const [tpEditing, setTpEditing] = useState({});   // trade_id -> bool
  const [closingId, setClosingId] = useState(null);  // trade being confirmed for close
  const [explainerTrade, setExplainerTrade] = useState(null); // trade being explained

  const handleSetTp = (tradeId) => {
    const val = parseFloat(tpInputs[tradeId]);
    if (!val || val <= 0) return;
    sendMessage({ type: 'set_tp', trade_id: tradeId, tp: val });
    setTpEditing(e => ({ ...e, [tradeId]: false }));
  };

  const handleCloseTrade = (tradeId) => {
    sendMessage({ type: 'close_trade', trade_id: tradeId });
    setClosingId(null);
  };

  const handleCopyId = (id) => {
    if (!id) return;
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };
  
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
    <>
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
            {strategies.map(s => <option key={s} value={s}>{s.replace(/S[0-9]+_/, '').replace('SA_', '').replace('SB_', '')}</option>)}
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
            
            const lev = trade.computed_leverage || 400;
            const initialMargin = trade.initial_margin || trade.margin || 5.0;
            const size = (initialMargin * lev) / trade.entry;
            
            if (trade.direction === 'LONG') {
              displayPnl = (currentPrice - trade.entry) * size;
            } else {
              displayPnl = (trade.entry - currentPrice) * size;
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
          } else if (!isPending) {
             // For closed trades, use net_profit if available
             displayPnl = trade.net_profit !== undefined ? trade.net_profit : displayPnl;
          }
          
          return (
            <div key={trade.id} className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50 hover:border-slate-600 transition-colors">
              <div className="flex justify-between items-start mb-1.5">
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
                    {displayPnl !== 0 && ` (${displayPnl > 0 ? '+$' : '-$'}${Math.abs(displayPnl).toFixed(2)})`}
                  </span>
                </div>
              </div>
              
              <div className="mb-2">
                <button
                  onClick={() => setExplainerTrade(trade)}
                  className="w-full flex items-center justify-center gap-1.5 py-1.5 px-3 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/20 rounded-md transition-colors text-xs font-bold uppercase tracking-wider"
                >
                  <BookOpen size={14} />
                  Explain Me
                </button>
              </div>

              {/* Sheet ID Match Banner */}
              {trade.id && (
                <div className="flex items-center justify-between bg-slate-950/60 px-2 py-1 rounded border border-slate-800/80 mb-2">
                  <div className="flex items-center gap-1.5 overflow-hidden">
                    <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Sheet ID:</span>
                    <span className="font-mono text-[10px] text-sky-400 truncate select-all">{trade.id}</span>
                  </div>
                  <button
                    onClick={() => handleCopyId(trade.id)}
                    className="text-slate-400 hover:text-sky-400 p-0.5 rounded ml-2 flex-shrink-0 transition-colors"
                    title="Copy Google Sheet ID"
                  >
                    {copiedId === trade.id ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
                  </button>
                </div>
              )}
              
              <div className="grid grid-cols-3 gap-2 text-xs text-slate-400">
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

              {/* Manual Controls — only for PENDING trades */}
              {isPending && sendMessage && (
                <div className="mt-2 pt-2 border-t border-slate-700/60 flex items-center gap-2 flex-wrap">
                  {/* Set TP */}
                  {tpEditing[trade.id] ? (
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        step="any"
                        placeholder="New TP price"
                        value={tpInputs[trade.id] || ''}
                        onChange={e => setTpInputs(v => ({ ...v, [trade.id]: e.target.value }))}
                        className="text-[10px] w-28 bg-slate-950 border border-emerald-700 text-emerald-300 rounded px-2 py-0.5 outline-none font-mono"
                        autoFocus
                      />
                      <button
                        onClick={() => handleSetTp(trade.id)}
                        className="text-[10px] px-2 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded transition-colors"
                      >Set</button>
                      <button
                        onClick={() => setTpEditing(e => ({ ...e, [trade.id]: false }))}
                        className="text-[10px] px-2 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded transition-colors"
                      >Cancel</button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setTpEditing(e => ({ ...e, [trade.id]: true }))}
                      className="text-[10px] flex items-center gap-1 px-2 py-0.5 bg-emerald-900/40 hover:bg-emerald-900/70 border border-emerald-700/50 text-emerald-400 rounded transition-colors"
                      title="Override Take Profit"
                    >
                      <Target size={10} /> Set TP
                    </button>
                  )}

                  {/* Exit Now */}
                  {closingId === trade.id ? (
                    <div className="flex items-center gap-1">
                      <span className="text-[10px] text-rose-400">Sure?</span>
                      <button
                        onClick={() => handleCloseTrade(trade.id)}
                        className="text-[10px] px-2 py-0.5 bg-rose-600 hover:bg-rose-500 text-white rounded transition-colors"
                      >Yes, Exit</button>
                      <button
                        onClick={() => setClosingId(null)}
                        className="text-[10px] px-2 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded transition-colors"
                      >No</button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setClosingId(trade.id)}
                      className="text-[10px] flex items-center gap-1 px-2 py-0.5 bg-rose-900/40 hover:bg-rose-900/70 border border-rose-700/50 text-rose-400 rounded transition-colors"
                      title="Close trade at market price now"
                    >
                      <LogOut size={10} /> Exit Now
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {filteredHistory.length === 0 && (
          <div className="text-center text-slate-500 text-sm py-4">
            No trades match the selected strategy.
          </div>
        )}
      </div>
    </div>
    {explainerTrade && (
      <ExplainerModal trade={explainerTrade} onClose={() => setExplainerTrade(null)} />
    )}
    </>
  );
};

export default SignalHistory;
