// React import not needed with JSX transform
import { CheckCircle2, Circle, ToggleLeft, ToggleRight } from 'lucide-react';

export default function Checklist({ killzoneActive, symbolState, tradeState, filterStates, onSetFilter }) {
  const htfOk = symbolState?.htf_ok || false;
  const volOk = symbolState?.vol_ok || false;
  const volDeltaOk = tradeState?.pressure_direction === 'BUYING_CONTROL' || tradeState?.pressure_direction === 'SELLING_CONTROL';

  const filters = [
    {
      key: 'killzone',
      label: 'Killzone Active (Lon/NY)',
      active: killzoneActive,
      enabled: filterStates.killzone,
    },
    {
      key: 'htf',
      label: 'HTF Trend Conformity',
      active: htfOk,
      enabled: filterStates.htf,
    },
    {
      key: 'volume',
      label: 'Volume & Sweep Setup',
      active: volOk,
      enabled: filterStates.volume,
    },
    {
      key: 'pressure',
      label: 'Volume Delta Pressure',
      active: volDeltaOk,
      enabled: filterStates.pressure,
    },
  ];

  return (
    <div className="bg-slate-800 p-5 rounded-xl border border-slate-700 h-full flex flex-col">
      <h2 className="text-lg font-bold text-slate-100 mb-4">Filter Checklist</h2>
      <div className="space-y-3 flex-1">
        {filters.map((f) => (
          <div key={f.key} className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5 min-w-0">
              {f.active
                ? <CheckCircle2 size={18} className="text-emerald-500 flex-shrink-0" />
                : <Circle size={18} className="text-slate-500 flex-shrink-0" />
              }
              <span className={`text-sm ${f.active ? 'text-emerald-400' : 'text-slate-400'}`}>
                {f.label}
              </span>
            </div>
            <button
              onClick={() => onSetFilter(f.key, !f.enabled)}
              className={`flex-shrink-0 transition-colors ${
                f.enabled ? 'text-blue-400' : 'text-slate-600 hover:text-slate-400'
              }`}
              title={f.enabled ? `Disable ${f.label} filter` : `Enable ${f.label} filter`}
            >
              {f.enabled
                ? <ToggleRight size={28} />
                : <ToggleLeft size={28} />
              }
            </button>
          </div>
        ))}
      </div>
      <div className="mt-4 pt-3 border-t border-slate-700 text-sm text-slate-400 space-y-1">
        <p>State: <span className="font-mono text-slate-300">{symbolState?.setup_state || 'WAITING'}</span></p>
        <div className="flex justify-between items-center text-xs">
          <span>Active Sweep: {symbolState?.active_sweep_type ? <span className="text-amber-400">{symbolState.active_sweep_type}</span> : 'None'}</span>
          <span className="font-mono text-slate-300">{symbolState?.active_sweep_level ? `$${symbolState.active_sweep_level}` : '-'}</span>
        </div>
        
        {/* ML & Probability Data */}
        <div className="mt-2 pt-2 border-t border-slate-700/50 space-y-1">
          <div className="flex justify-between items-center text-xs">
            <span>Regime (HMM):</span>
            <span className={`font-mono ${symbolState?.regime_reliable ? 'text-blue-400' : 'text-slate-500'}`}>
               {symbolState?.regime || 'Unknown'} 
               {symbolState?.regime_conf ? ` (${(symbolState.regime_conf * 100).toFixed(0)}%)` : ''}
            </span>
          </div>
          
          <div className="flex flex-col gap-1 mt-2 text-xs">
            <div className="flex justify-between items-center">
              <span>Next Candle Prob:</span>
              <span className={symbolState?.prob_model_trained ? 'text-emerald-400' : 'text-amber-500'}>
                 {symbolState?.prob_model_trained ? 'Trained' : 'Training...'}
              </span>
            </div>
            {symbolState?.prob_up !== undefined && (
              <div className="grid grid-cols-3 gap-1 text-[10px] text-center font-mono mt-1">
                <div className="bg-emerald-950/50 text-emerald-400 py-1 rounded">UP: {(symbolState.prob_up * 100).toFixed(1)}%</div>
                <div className="bg-slate-800 text-slate-400 py-1 rounded">FLAT: {(symbolState.prob_flat * 100).toFixed(1)}%</div>
                <div className="bg-rose-950/50 text-rose-400 py-1 rounded">DN: {(symbolState.prob_down * 100).toFixed(1)}%</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
