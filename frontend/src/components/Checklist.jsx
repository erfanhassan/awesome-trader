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
      <div className="mt-4 pt-3 border-t border-slate-700 text-sm text-slate-400">
        <p>State: <span className="font-mono text-slate-300">{symbolState?.setup_state || 'WAITING'}</span></p>
      </div>
    </div>
  );
}
