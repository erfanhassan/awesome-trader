import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, CrosshairMode } from 'lightweight-charts';
import { TrendingUp, TrendingDown, RefreshCw } from 'lucide-react';

const TIMEFRAMES = [
  { label: '1m', key: 'Min1', trendKey: '1m' },
  { label: '15m', key: 'Min15', trendKey: '15m' },
  { label: '1h', key: 'Min60', trendKey: '1h' },
  { label: '4h', key: 'Hour4', trendKey: '4h' },
  { label: '1D', key: 'Day1', trendKey: '1d' },
];

export default function ChartArea({ symbol, state, tradeState, filterStates = {}, signals = [], signalHistory = [] }) {
  const chartContainerRef = useRef();
  const chartRef = useRef(null);
  const seriesRef = useRef({ candle: null, d1HighLine: null, d1LowLine: null });
  const [activeTimeframe, setActiveTimeframe] = useState(TIMEFRAMES[0]);
  const [selectedSignal, setSelectedSignal] = useState(null);
  const pollRef = useRef(null);
  const lastCandlesRef = useRef([]); // cache last fetched candles
  const lastTimeframeRef = useRef(TIMEFRAMES[0].key);
  const lastSymbolRef = useRef(symbol);

  // Create chart once on mount
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chartOptions = {
      layout: {
        background: { type: 'solid', color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#1e293b',
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
      },
      localization: {
        timeFormatter: (time) => {
          const date = new Date(time * 1000);
          return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
      },
      autoSize: true,
    };

    const chart = createChart(chartContainerRef.current, chartOptions);
    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    seriesRef.current = {
      candle: candleSeries,
      d1HighLine: null,
      d1LowLine: null,
    };

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Fetch klines from REST API
  const fetchKlines = useCallback(async () => {
    if (!symbol || !seriesRef.current.candle) return;

    try {
      const apiUrl = import.meta.env.DEV ? 'http://localhost:8000' : '';
      const resp = await fetch(
        `${apiUrl}/api/klines?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(activeTimeframe.key)}`
      );
      const json = await resp.json();
      const candles = json.data || [];

      if (candles.length === 0) {
        if (lastSymbolRef.current !== symbol) {
           lastSymbolRef.current = symbol;
           lastCandlesRef.current = [];
           try {
             if (seriesRef.current.candle) seriesRef.current.candle.setData([]);
            } catch { /* series may not exist yet */ }
        }
        return;
      }

      // Deduplicate by time, keeping last occurrence
      const seen = new Map();
      for (const c of candles) {
        seen.set(c.time, c);
      }
      const deduped = Array.from(seen.values()).sort((a, b) => a.time - b.time);
      
      // Only set data if it changed to avoid destroying markers/zoom state unnecessarily
      const prev = lastCandlesRef.current;
      const tfChanged = lastTimeframeRef.current !== activeTimeframe.key;
      const symbolChanged = lastSymbolRef.current !== symbol;
      const changed = symbolChanged || tfChanged || prev.length !== deduped.length || prev[prev.length-1]?.time !== deduped[deduped.length-1]?.time || prev[prev.length-1]?.close !== deduped[deduped.length-1]?.close;
      
      if (changed) {
        lastCandlesRef.current = deduped;
        lastTimeframeRef.current = activeTimeframe.key;
        lastSymbolRef.current = symbol;
        try {
          seriesRef.current.candle.setData(deduped);
          if ((tfChanged || symbolChanged) && chartRef.current) {
            chartRef.current.timeScale().fitContent();
          }
        } catch (e) {
          console.warn('Chart setData error:', e);
        }
      }
    } catch (err) {
      console.error('Error fetching klines:', err);
    }
  }, [symbol, activeTimeframe]);

  // Poll klines every 3 seconds
  useEffect(() => {
    fetchKlines();
    pollRef.current = setInterval(fetchKlines, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchKlines]);

  // Evaluate markers and 1D lines based on current state + filters
  useEffect(() => {
    if (!state || !state[symbol] || !seriesRef.current.candle) return;

    const symbolState = state[symbol];
    const deduped = lastCandlesRef.current;
    if (deduped.length < 2) return;

    const d1High = symbolState['1d_high'];
    const d1Low = symbolState['1d_low'];

    if (d1High) {
      if (!seriesRef.current.d1HighLine) {
        seriesRef.current.d1HighLine = seriesRef.current.candle.createPriceLine({
          price: d1High,
          color: '#ef4444',
          lineWidth: 1,
          lineStyle: 2, // Dashed
          axisLabelVisible: true,
          title: '1D High',
        });
      } else {
        seriesRef.current.d1HighLine.applyOptions({ price: d1High });
      }
    }

    if (d1Low) {
      if (!seriesRef.current.d1LowLine) {
        seriesRef.current.d1LowLine = seriesRef.current.candle.createPriceLine({
          price: d1Low,
          color: '#10b981',
          lineWidth: 1,
          lineStyle: 2, // Dashed
          axisLabelVisible: true,
          title: '1D Low',
        });
      } else {
        seriesRef.current.d1LowLine.applyOptions({ price: d1Low });
      }
    }

    // --- Compute Markers based on actual Backend Signals ---
    if (activeTimeframe.key === 'Min1') {
      const markers = [];
      const allSignals = [...(signals || []), ...(signalHistory || [])].filter(s => s.symbol === symbol);
      
      const uniqueSignalTimes = new Set();
      
      allSignals.forEach(signal => {
        if (!signal.timestamp_ms) return;
        
        const timeInSeconds = Math.floor(signal.timestamp_ms / 1000);
        const markerKey = `${timeInSeconds}-${signal.direction}`;
        
        if (!uniqueSignalTimes.has(markerKey)) {
          uniqueSignalTimes.add(markerKey);
          
          markers.push({
            time: timeInSeconds,
            position: signal.direction === 'LONG' ? 'belowBar' : 'aboveBar',
            color: signal.direction === 'LONG' ? '#10b981' : '#ef4444',
            shape: signal.direction === 'LONG' ? 'arrowUp' : 'arrowDown',
            text: signal.direction,
          });
        }
      });
      
      // Lightweight charts requires markers to be sorted by time
      markers.sort((a, b) => a.time - b.time);

      try {
        seriesRef.current.candle.setMarkers(markers);
      } catch { /* series may be disposed */ }
    } else {
      // Clear markers if not 1m timeframe
      try {
        seriesRef.current.candle.setMarkers([]);
        } catch { /* series may be disposed */ }
    }

  }, [state, symbol, signals, signalHistory, activeTimeframe]);

  // Apply dynamic background color based on Volume Delta Pressure
  useEffect(() => {
    if (!chartRef.current) return;
    
    let bgColor = '#0f172a'; // Default slate-900
    if (filterStates.pressure && tradeState) {
      if (tradeState.pressure_direction === 'BUYING_CONTROL') {
        bgColor = '#064e3b'; // Dark emerald
      } else if (tradeState.pressure_direction === 'SELLING_CONTROL') {
        bgColor = '#450a0a'; // Dark rose
      }
    }

    chartRef.current.applyOptions({
      layout: {
        background: { type: 'solid', color: bgColor },
      }
    });
  }, [filterStates.pressure, tradeState]);

  // Click subscription for Signal details
  useEffect(() => {
    if (!chartRef.current) return;
    
    const clickHandler = (param) => {
      // If we clicked outside the chart plot or clicked without time, dismiss widget
      if (!param.point || !param.time) {
        setSelectedSignal(null);
        return;
      }
      
      const allSignals = [...(signals || []), ...(signalHistory || [])].filter(s => s.symbol === symbol);
      
      const tfInSeconds = {
        'Min1': 60,
        'Min15': 900,
        'Min60': 3600,
        'Hour4': 14400,
        'Day1': 86400
      }[activeTimeframe.key] || 60;
      
      const candleStartTime = param.time;
      const candleEndTime = param.time + tfInSeconds;
      
      // Find the first signal that falls within this candlestick's time range
      const clickedSignal = allSignals.find(s => {
        if (!s.timestamp) return false;
        const sTime = Math.floor(new Date(s.timestamp).getTime() / 1000);
        return sTime >= candleStartTime && sTime < candleEndTime;
      });
      
      if (clickedSignal) {
        const containerWidth = chartContainerRef.current?.clientWidth || 0;
        const containerHeight = chartContainerRef.current?.clientHeight || 0;
        
        let x = param.point.x;
        let y = param.point.y;
        
        // Widget is ~200px wide, ~130px tall. Adjust so it doesn't get clipped.
        if (x + 220 > containerWidth) x -= 220;
        else x += 15;
        
        if (y + 140 > containerHeight) y -= 140;
        else y += 15;

        setSelectedSignal({
          ...clickedSignal,
          x,
          y
        });
      } else {
        setSelectedSignal(null);
      }
    };
    
    chartRef.current.subscribeClick(clickHandler);
    return () => {
      if (chartRef.current) {
        chartRef.current.unsubscribeClick(clickHandler);
      }
    };
  }, [signals, signalHistory, symbol, activeTimeframe.key]);

  const symbolState = state && state[symbol] ? state[symbol] : {};

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 h-[400px] flex flex-col overflow-hidden">
      {/* Header with timeframe selector and trend badges */}
      <div className="px-4 py-2.5 flex items-center justify-between border-b border-slate-700">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-slate-200">{symbol} / USDT</span>
          {/* Timeframe selector buttons */}
          <div className="flex items-center gap-1 bg-slate-900/60 rounded-lg p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.key}
                onClick={() => setActiveTimeframe(tf)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                  activeTimeframe.key === tf.key
                    ? 'bg-blue-500/20 text-blue-400 shadow-sm'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-slate-700/50'
                }`}
              >
                {tf.label}
              </button>
            ))}
            <button
              onClick={() => {
                fetchKlines();
                if (chartRef.current) chartRef.current.timeScale().fitContent();
              }}
              className="ml-1 px-2 py-1 text-slate-400 hover:text-blue-400 transition-colors"
              title="Refresh Chart"
            >
              <RefreshCw size={14} />
            </button>
          </div>
          {/* Display 1D High and 1D Low Values clearly */}
          {symbolState['1d_high'] > 0 && (
            <div className="flex items-center gap-2 ml-4 text-[11px] font-mono">
               <div className="flex items-center gap-1 text-red-400">
                 <span className="text-slate-500">1D High:</span>
                 {symbolState['1d_high'].toFixed(1)}
               </div>
               <div className="flex items-center gap-1 text-emerald-400">
                 <span className="text-slate-500">1D Low:</span>
                 {symbolState['1d_low'].toFixed(1)}
               </div>
            </div>
          )}
        </div>

        {/* Bullish/Bearish trend badges */}
        <div className="flex items-center gap-1.5">
          {TIMEFRAMES.map((tf) => {
            const isBullish = symbolState[`${tf.trendKey}_bullish`];
            const hasData = symbolState[`${tf.trendKey}_bullish`] !== undefined;
            if (!hasData) {
              return (
                <div
                  key={tf.key}
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold bg-slate-700/40 text-slate-500 border border-slate-700/50"
                  title={`${tf.label} — No data`}
                >
                  <span>{tf.label}</span>
                  <span>—</span>
                </div>
              );
            }
            return (
              <div
                key={tf.key}
                className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold border transition-colors ${
                  isBullish
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                }`}
                title={`${tf.label} ${isBullish ? 'Bullish' : 'Bearish'} (EMA 20/50)`}
              >
                <span>{tf.label}</span>
                {isBullish ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              </div>
            );
          })}
        </div>
      </div>

      {/* Delta Pressure Metrics Row */}
      {tradeState && (
        <div className="px-4 py-1.5 flex items-center justify-between border-b border-slate-700 bg-slate-800/50">
          <div className="flex items-center gap-4 text-xs">
            <span className="text-slate-400">1m Buy Vol: <span className="text-emerald-400 font-mono">{tradeState.buy_vol.toFixed(2)}</span></span>
            <span className="text-slate-400">1m Sell Vol: <span className="text-rose-400 font-mono">{tradeState.sell_vol.toFixed(2)}</span></span>
            <span className="text-slate-400">Delta: <span className={`font-mono font-bold ${tradeState.delta > 0 ? 'text-emerald-400' : tradeState.delta < 0 ? 'text-rose-400' : 'text-slate-400'}`}>{tradeState.delta > 0 ? '+' : ''}{tradeState.delta.toFixed(2)}</span></span>
          </div>
          <div className={`text-xs font-bold px-2 py-0.5 rounded ${tradeState.pressure_direction === 'BUYING_CONTROL' ? 'bg-emerald-500/20 text-emerald-400' : tradeState.pressure_direction === 'SELLING_CONTROL' ? 'bg-rose-500/20 text-rose-400' : 'bg-slate-700 text-slate-400'}`}>
            {tradeState.pressure_direction.replace('_', ' ')}
          </div>
        </div>
      )}

      {/* Chart */}
      <div ref={chartContainerRef} className="flex-1 w-full relative">
        {/* Helper overlay for killzone if enabled */}
        {filterStates.killzone && activeTimeframe.key === 'Min1' && (
           <div className="absolute top-2 left-2 px-2 py-1 bg-emerald-500/20 text-emerald-400 text-xs rounded border border-emerald-500/30 z-10 pointer-events-none">
             Killzone Filter Active
           </div>
        )}

        {/* Signal Details Widget */}
        {selectedSignal && (
          <div 
            className="absolute z-20 bg-slate-900 border border-slate-600 rounded-lg shadow-2xl p-3 w-[200px] transition-all duration-150"
            style={{ left: selectedSignal.x, top: selectedSignal.y }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-2 pb-2 border-b border-slate-700/50">
              <span className={`text-xs font-bold ${selectedSignal.direction === 'LONG' ? 'text-emerald-400' : 'text-rose-400'}`}>
                {selectedSignal.direction} SIGNAL
              </span>
              <span className="text-[10px] text-slate-500 font-mono">
                {selectedSignal.id?.substring(0, 8) || 'No ID'}
              </span>
            </div>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-400">Entry</span>
                <span className="font-mono text-slate-200">{Number(selectedSignal.entry).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 6})}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Stop Loss</span>
                <span className="font-mono text-rose-400">{Number(selectedSignal.sl).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 6})}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Take Profit</span>
                <span className="font-mono text-emerald-400">{Number(selectedSignal.tp).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 6})}</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
