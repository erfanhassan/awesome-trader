import React from 'react';
import { X, Clock, Target, TrendingUp, TrendingDown, BookOpen, Brain, Activity, ShieldAlert, CheckCircle2, XCircle } from 'lucide-react';

const ExplainerModal = ({ trade, onClose }) => {
  if (!trade) return null;

  const isProfit = trade.net_profit > 0;
  const isPending = trade.status === "PENDING";
  
  const getEventIcon = (type) => {
    switch (type) {
      case 'SETUP': return <Target size={16} className="text-sky-400" />;
      case 'MARGIN_ADD': return <ShieldAlert size={16} className="text-amber-400" />;
      case 'TRAILING_STOP': return <Activity size={16} className="text-purple-400" />;
      case 'CLOSE': return <CheckCircle2 size={16} className="text-emerald-400" />;
      default: return <Clock size={16} className="text-slate-400" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden">
        
        {/* Header */}
        <div className="p-4 border-b border-slate-700 bg-slate-800/50 flex justify-between items-center sticky top-0">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${trade.direction === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'}`}>
              {trade.direction === 'LONG' ? <TrendingUp size={24} /> : <TrendingDown size={24} />}
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                {trade.symbol} <span className="text-sm font-normal text-slate-400">Trade Explainer</span>
              </h2>
              <div className="text-xs text-slate-400 font-mono mt-0.5">
                ID: {trade.id}
              </div>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          
          {/* Status Banner */}
          <div className={`p-4 rounded-lg border flex flex-wrap justify-between items-center gap-4 ${
            isPending ? 'bg-amber-500/10 border-amber-500/30' : 
            isProfit ? 'bg-emerald-500/10 border-emerald-500/30' : 
            'bg-rose-500/10 border-rose-500/30'
          }`}>
            <div className="flex items-center gap-6">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Status</div>
                <div className={`font-bold text-sm ${isPending ? 'text-amber-400' : isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {trade.status}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Leverage</div>
                <div className="font-bold text-sm text-amber-400">
                  {trade.computed_leverage || trade.leverage || 300}x
                </div>
              </div>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Collateral</div>
                <div className="font-bold text-sm text-slate-200">
                  ${(trade.margin || 7).toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Margin Adds</div>
                <div className="font-bold text-sm text-slate-200">
                  {trade.margin_adds || 0}/3
                </div>
              </div>
            </div>

            {!isPending && (
              <div className="text-right">
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Net PnL</div>
                <div className={`font-bold text-lg ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {isProfit ? '+' : ''}${trade.net_profit?.toFixed(2)}
                </div>
              </div>
            )}
          </div>

          {/* Sweep Execution Details */}
          {trade.sweep_candle_time && (
            <div className="bg-slate-800/50 border border-amber-500/30 p-4 rounded-lg">
              <h3 className="text-amber-400 font-bold flex items-center gap-2 mb-3 text-sm">
                <Target size={16} />
                Liquidity Sweep Triggers
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Swept Level</div>
                  <div className="font-mono text-sm text-slate-200">${trade.swept_level?.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Target Type</div>
                  <div className="font-bold text-sm text-slate-200">{trade.swept_level_label}</div>
                </div>
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">Sweep Execution Time</div>
                  <div className="font-mono text-sm text-amber-400">
                    {new Date(trade.sweep_candle_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second:'2-digit' })}
                  </div>
                </div>
              </div>
              <p className="text-xs text-slate-400 mt-3 italic">
                * The bot entered exactly upon the close of this sweep candle to secure the optimal execution price.
              </p>
            </div>
          )}

          {/* Timeline Feed */}
          <div>
            <h3 className="text-slate-200 font-bold flex items-center gap-2 mb-4">
              <Clock size={18} className="text-blue-400" />
              Live Strategic Timeline
            </h3>
            
            <div className="space-y-6 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-slate-700">
              {(trade.timeline_events || []).map((event, idx) => (
                <div key={idx} className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                  <div className="flex items-center justify-center w-10 h-10 rounded-full border-4 border-slate-900 bg-slate-800 text-slate-400 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10">
                    {getEventIcon(event.type)}
                  </div>
                  <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-lg border border-slate-700 bg-slate-800/60 shadow-md">
                    <div className="flex items-center justify-between mb-2 pb-1 border-b border-slate-700/50">
                      <span className="font-bold text-slate-200 text-xs tracking-wider uppercase">{event.type.replace('_', ' ')}</span>
                      <time className="font-mono text-[10px] text-slate-400">
                        {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second:'2-digit' })}
                      </time>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap font-sans">
                      {event.message}
                    </p>
                  </div>
                </div>
              ))}
            </div>
            
            {(!trade.timeline_events || trade.timeline_events.length === 0) && (
              <div className="text-center text-slate-500 text-sm p-4 border border-dashed border-slate-700 rounded-lg">
                No timeline events recorded for this trade.
              </div>
            )}
          </div>

          {/* AI Mentor Review */}
          {trade.mentor_review && (
            <div className="mt-8">
              <h3 className="text-slate-200 font-bold flex items-center gap-2 mb-4">
                <Brain size={18} className="text-purple-400" />
                AI Mentor Review
              </h3>
              <div className="bg-gradient-to-br from-purple-500/10 to-blue-500/10 border border-purple-500/30 p-5 rounded-xl shadow-inner">
                <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">
                  {trade.mentor_review}
                </p>
              </div>
            </div>
          )}
          
        </div>
      </div>
    </div>
  );
};

export default ExplainerModal;
