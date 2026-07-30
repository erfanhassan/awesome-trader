import { useState, useEffect } from 'react';
import { Plus, X } from 'lucide-react';

export default function SymbolSelector({ activeSymbol, setActiveSymbol, addSymbol, removeSymbol, symbolsList }) {
  const [newSymbol, setNewSymbol] = useState('');
  const [availableSymbols, setAvailableSymbols] = useState([]);

  useEffect(() => {
    const apiUrl = import.meta.env.DEV ? 'http://localhost:8000' : '';
    fetch(`${apiUrl}/api/symbols`)
      .then(res => res.json())
      .then(data => {
        if (data.symbols) {
          setAvailableSymbols(data.symbols);
        }
      })
      .catch(err => console.error('Error fetching symbols:', err));
  }, []);

  const SYMBOL_MAP = {
    'GOLD': 'XAUUSDT',
    'SILVER': 'XAGUSDT'
  };

  const handleAdd = (e) => {
    e.preventDefault();
    if (newSymbol.trim()) {
      let sym = newSymbol.trim().toUpperCase();
      if (SYMBOL_MAP[sym]) {
        sym = SYMBOL_MAP[sym];
      }
      addSymbol(sym);
      setNewSymbol('');
    }
  };

  return (
    <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">Pairs</h2>
      <div className="flex flex-wrap gap-2 mb-4">
        {symbolsList.map(sym => (
          <div 
            key={sym} 
            onClick={() => setActiveSymbol(sym)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg cursor-pointer transition-colors ${activeSymbol === sym ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}
          >
            <span className="font-medium text-sm">{sym}</span>
            <button 
              onClick={(e) => { e.stopPropagation(); removeSymbol(sym); }}
              className="text-slate-400 hover:text-white"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      <form onSubmit={handleAdd} className="flex gap-2">
        <input 
          type="text" 
          value={newSymbol}
          onChange={(e) => setNewSymbol(e.target.value)}
          placeholder="e.g. BTCUSDT"
          list="mexc-symbols"
          className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        <datalist id="mexc-symbols">
          {availableSymbols.map(sym => (
            <option key={sym} value={sym} />
          ))}
        </datalist>
        <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white p-2 rounded-lg transition-colors">
          <Plus size={18} />
        </button>
      </form>
    </div>
  );
}
