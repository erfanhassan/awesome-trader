import { Pencil, Trash2, ChevronDown } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';

const COLORS = [
  { id: 'red', value: '#ef4444', name: 'Red' },
  { id: 'green', value: '#10b981', name: 'Green' },
  { id: 'blue', value: '#3b82f6', name: 'Blue' },
  { id: 'yellow', value: '#eab308', name: 'Yellow' },
  { id: 'white', value: '#ffffff', name: 'White' },
  { id: 'orange', value: '#f97316', name: 'Orange' },
];

export default function DrawingToolbar({ drawMode, setDrawMode, drawColor, setDrawColor, clearLines }) {
  const [showPalette, setShowPalette] = useState(false);
  const paletteRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (paletteRef.current && !paletteRef.current.contains(event.target)) {
        setShowPalette(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="flex items-center gap-2 bg-slate-800 rounded-lg p-1 border border-slate-700">
      {/* Draw Toggle */}
      <button
        onClick={() => setDrawMode(!drawMode)}
        className={`p-1.5 rounded-md transition-colors flex items-center gap-1 ${
          drawMode ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700'
        }`}
        title="Draw Horizontal Line (Click chart to place)"
      >
        <Pencil size={16} />
      </button>

      {/* Color Picker Dropdown */}
      <div className="relative" ref={paletteRef}>
        <button
          onClick={() => setShowPalette(!showPalette)}
          className="p-1.5 rounded-md hover:bg-slate-700 flex items-center gap-1 transition-colors"
          title="Select Line Color"
        >
          <div className="w-4 h-4 rounded-full border border-slate-600" style={{ backgroundColor: drawColor }}></div>
          <ChevronDown size={14} className="text-slate-400" />
        </button>
        
        {showPalette && (
          <div className="absolute top-full mt-1 right-0 bg-slate-800 border border-slate-700 rounded-lg p-2 shadow-xl z-50 flex gap-2">
            {COLORS.map(color => (
              <button
                key={color.id}
                onClick={() => {
                  setDrawColor(color.value);
                  setShowPalette(false);
                }}
                className={`w-6 h-6 rounded-full border-2 transition-transform hover:scale-110 ${
                  drawColor === color.value ? 'border-white' : 'border-transparent'
                }`}
                style={{ backgroundColor: color.value }}
                title={color.name}
              />
            ))}
          </div>
        )}
      </div>

      <div className="w-px h-4 bg-slate-700 mx-1"></div>

      {/* Clear Lines */}
      <button
        onClick={() => {
          if (confirm('Clear all drawn lines?')) {
            clearLines();
          }
        }}
        className="p-1.5 rounded-md text-slate-400 hover:text-rose-400 hover:bg-slate-700 transition-colors"
        title="Clear All Lines"
      >
        <Trash2 size={16} />
      </button>
    </div>
  );
}
