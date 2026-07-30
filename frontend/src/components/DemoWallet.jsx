import { useState } from 'react';
import { Wallet, Settings2 } from 'lucide-react';

export default function DemoWallet({ demoState, setDemoInvest, setDemoLeverage }) {
  const [investVal, setInvestVal] = useState(demoState?.invest_amount || 10);
  const [levVal, setLevVal] = useState(demoState?.leverage || 10);

  const handleApply = () => {
    setDemoInvest(parseFloat(investVal));
    setDemoLeverage(parseInt(levVal));
  };

  const balance = demoState?.balance || 0;
  const positions = demoState?.positions || [];

  return (
    <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 space-y-6">
      <div className="flex items-center gap-3 border-b border-slate-700 pb-4">
        <Wallet className="text-purple-500" size={24} />
        <h2 className="text-lg font-bold text-slate-100">Shihab Demo Wallet</h2>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700/50">
          <p className="text-slate-400 text-xs mb-1">Demo Balance</p>
          <p className="text-2xl font-mono text-purple-400">${balance.toFixed(2)}</p>
        </div>
        <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700/50">
          <p className="text-slate-400 text-xs mb-1">Active Positions</p>
          <p className="text-2xl font-mono text-slate-200">{positions.length}</p>
        </div>
      </div>

      {/* Settings */}
      <div className="bg-slate-900 p-4 rounded-lg border border-slate-700 space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <Settings2 className="text-slate-400" size={16} />
          <h3 className="text-sm font-semibold text-slate-200">Demo Trade Settings</h3>
        </div>
        
        <div className="space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Margin per Trade (USDT)</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-purple-500"
                value={investVal}
                onChange={(e) => setInvestVal(e.target.value)}
                min="1"
              />
            </div>
          </div>
          
          <div>
            <label className="flex justify-between text-xs text-slate-400 mb-1">
              <span>Leverage</span>
              <span className="text-purple-400 font-bold">{levVal}x</span>
            </label>
            <input
              type="range"
              min="1"
              max="500"
              className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-purple-500"
              value={levVal}
              onChange={(e) => setLevVal(e.target.value)}
            />
          </div>

          <button
            onClick={handleApply}
            className="w-full mt-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold py-2 rounded transition-colors"
          >
            Apply Settings
          </button>
        </div>
      </div>

      {/* Active Positions List */}
      {positions.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Open Demo Trades</h3>
          <div className="space-y-2 max-h-[200px] overflow-y-auto pr-1">
            {positions.map((pos, idx) => (
              <div key={idx} className="bg-slate-900 p-3 rounded border border-slate-700/50 flex justify-between items-center text-sm">
                <div>
                  <div className="font-bold text-slate-200">{pos.symbol}</div>
                  <div className={`text-xs font-bold ${pos.direction === 'LONG' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {pos.direction} {pos.leverage}x
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-slate-400 text-xs">Entry: {pos.entry.toFixed(4)}</div>
                  <div className="text-slate-500 text-xs">Marg: ${pos.margin.toFixed(2)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}
