import { useState, useEffect, useRef } from 'react';
import { Plus, X, ChevronDown } from 'lucide-react';

export default function SymbolSelector({ activeSymbol, setActiveSymbol, addSymbol, removeSymbol, symbolsList }) {
  const [isOpen, setIsOpen] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const [availableSymbols, setAvailableSymbols] = useState([]);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const apiUrl = import.meta.env.DEV ? `http://${window.location.hostname}:8000` : '';
    fetch(`${apiUrl}/api/symbols`)
      .then(res => res.json())
      .then(data => {
        if (data.symbols) {
          setAvailableSymbols(data.symbols);
        }
      })
      .catch(err => console.error('Error fetching symbols:', err));
  }, []);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
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
      setActiveSymbol(sym);
    }
  };

  return (
    <div className="relative inline-block" ref={dropdownRef}>
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded-md px-3 py-1.5 transition-colors text-sm font-semibold text-slate-200"
      >
        <span>{activeSymbol || 'Select Pair'}</span>
        <ChevronDown size={14} className="text-slate-400" />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 w-64 bg-slate-800 border border-slate-600 rounded-lg shadow-xl z-50 p-2">
          <div className="max-h-48 overflow-y-auto mb-2 space-y-1 pr-1">
            {symbolsList.length === 0 ? (
              <div className="text-xs text-slate-500 italic p-2">No pairs tracked</div>
            ) : (
              symbolsList.map(sym => (
                <div 
                  key={sym}
                  onClick={() => { setActiveSymbol(sym); setIsOpen(false); }}
                  className={`flex items-center justify-between px-2 py-1.5 rounded cursor-pointer text-sm ${activeSymbol === sym ? 'bg-blue-600/20 text-blue-400' : 'text-slate-300 hover:bg-slate-700'}`}
                >
                  <span className="font-medium">{sym}</span>
                  <button 
                    onClick={(e) => { e.stopPropagation(); removeSymbol(sym); }}
                    className="text-slate-500 hover:text-rose-400 p-0.5 rounded transition-colors"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
          <form onSubmit={handleAdd} className="flex gap-1.5 border-t border-slate-700 pt-2">
            <input 
              type="text" 
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value)}
              placeholder="Add BTCUSDT"
              list="mexc-symbols-dropdown"
              className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
            <datalist id="mexc-symbols-dropdown">
              {availableSymbols.map(sym => (
                <option key={sym} value={sym} />
              ))}
            </datalist>
            <button type="submit" className="bg-blue-600 hover:bg-blue-500 text-white p-1 rounded transition-colors">
              <Plus size={14} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
