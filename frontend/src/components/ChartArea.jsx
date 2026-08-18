import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, CrosshairMode } from 'lightweight-charts';
import { TrendingUp, TrendingDown, RefreshCw, Copy, Check, X } from 'lucide-react';

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
    const markers = [];
    const allSignals = [...(signals || []), ...(signalHistory || [])].filter(s => s.symbol === symbol);
    
    const tfInSeconds = {
      'Min1': 60,
      'Min15': 900,
      'Min60': 3600,
      'Hour4': 14400,
      'Day1': 86400
    }[activeTimeframe.key] || 60;
    
    const uniqueSignalTimes = new Set();
    
    allSignals.forEach(signal => {
      if (!signal.timestamp_ms && !signal.timestamp) return;
      
      const rawTimeSeconds = signal.timestamp_ms 
        ? Math.floor(signal.timestamp_ms / 1000)
        : Math.floor(new Date(signal.timestamp).getTime() / 1000);
      
      // Align marker time to candle boundary of active timeframe
      const candleBucketTime = Math.floor(rawTimeSeconds / tfInSeconds) * tfInSeconds;
      const markerKey = `${candleBucketTime}-${signal.id || signal.direction}`;
      
      if (!uniqueSignalTimes.has(markerKey)) {
        uniqueSignalTimes.add(markerKey);
        
        const shortId = signal.id ? signal.id.substring(0, 8) : 'TRADE';
        const isLong = signal.direction === 'LONG';
        const isPending = signal.status === 'PENDING';
        const isWin = signal.status === 'PROFIT' || signal.status === 'WIN';
        const isLoss = signal.status === 'LOSS';
        
        let markerColor = isLong ? '#10b981' : '#f43f5e';
        if (isPending) markerColor = '#f59e0b';
        else if (isWin) markerColor = '#10b981';
        else if (isLoss) markerColor = '#f43f5e';

        markers.push({
          time: candleBucketTime,
          position: isLong ? 'belowBar' : 'aboveBar',
          color: markerColor,
          shape: isLong ? 'arrowUp' : 'arrowDown',
          text: `${signal.direction} #${shortId}`,
          id: signal.id
        });
      }
    });
    
    // Lightweight charts requires markers to be sorted by time
    markers.sort((a, b) => a.time - b.time);

    try {
      seriesRef.current.candle.setMarkers(markers);
    } catch { /* series may be disposed */ }

  }, [state, symbol, signals, signalHistory, activeTimeframe]);

  // Manage dynamic Entry/SL/TP lines when a trade signal is selected
  const activeTradeLinesRef = useRef({ entry: null, sl: null, tp: null });

  useEffect(() => {
    if (!seriesRef.current.candle) return;

    // Clear previous trade lines
    if (activeTradeLinesRef.current.entry) {
      try { seriesRef.current.candle.removePriceLine(activeTradeLinesRef.current.entry); } catch {}
      activeTradeLinesRef.current.entry = null;
    }
    if (activeTradeLinesRef.current.sl) {
      try { seriesRef.current.candle.removePriceLine(activeTradeLinesRef.current.sl); } catch {}
      activeTradeLinesRef.current.sl = null;
    }
    if (activeTradeLinesRef.current.tp) {
      try { seriesRef.current.candle.removePriceLine(activeTradeLinesRef.current.tp); } catch {}
      activeTradeLinesRef.current.tp = null;
    }

    // If a signal is selected, draw its Entry, SL, and TP lines
    if (selectedSignal) {
      try {
        if (selectedSignal.entry) {
          activeTradeLinesRef.current.entry = seriesRef.current.candle.createPriceLine({
            price: Number(selectedSignal.entry),
            color: '#38bdf8',
            lineWidth: 1,
            lineStyle: 0, // Solid
            axisLabelVisible: true,
            title: `Entry #${selectedSignal.id?.substring(0, 6) || ''}`,
          });
        }
        if (selectedSignal.sl) {
          activeTradeLinesRef.current.sl = seriesRef.current.candle.createPriceLine({
            price: Number(selectedSignal.sl),
            color: '#f43f5e',
            lineWidth: 1,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: 'SL',
          });
        }
        if (selectedSignal.tp) {
          activeTradeLinesRef.current.tp = seriesRef.current.candle.createPriceLine({
            price: Number(selectedSignal.tp),
            color: '#10b981',
            lineWidth: 1,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: 'TP',
          });
        }
      } catch (e) {
        console.warn('Error drawing trade price lines:', e);
      }
    }
  }, [selectedSignal]);

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
        const sTime = s.timestamp_ms 
          ? Math.floor(s.timestamp_ms / 1000) 
          : (s.timestamp ? Math.floor(new Date(s.timestamp).getTime() / 1000) : 0);
        return sTime >= candleStartTime && sTime < candleEndTime;
      });
      
      if (clickedSignal) {
        const containerWidth = chartContainerRef.current?.clientWidth || 0;
        const containerHeight = chartContainerRef.current?.clientHeight || 0;
        
        let x = param.point.x;
        let y = param.point.y;
        
        if (x + 240 > containerWidth) x -= 240;
        else x += 15;
        
        if (y + 180 > containerHeight) y -= 180;
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
            className="absolute z-20 bg-slate-900/95 backdrop-blur-md border border-slate-600 rounded-xl shadow-2xl p-3.5 w-[250px] transition-all duration-150 text-xs"
            style={{ left: selectedSignal.x, top: selectedSignal.y }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-start mb-2 pb-2 border-b border-slate-700">
              <div>
                <div className="flex items-center gap-1.5">
                  <span className={`font-bold text-xs ${selectedSignal.direction === 'LONG' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {selectedSignal.direction}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                    {selectedSignal.strategy?.replace('S0_', '').replace('S1_', '').replace('S2_', '').replace('S3_', '').replace('S4_', '').replace('S5_', '').replace('S6_', '').replace('S7_', '').replace('S8_', '').replace('S9_', '').replace('S10_', '') || 'Active'}
                  </span>
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">
                  {selectedSignal.status || 'PENDING'} {selectedSignal.pnl ? `(${selectedSignal.pnl > 0 ? '+' : ''}${selectedSignal.pnl.toFixed(2)}%)` : ''}
                </div>
              </div>
              <button 
                onClick={() => setSelectedSignal(null)}
                className="text-slate-500 hover:text-slate-300 p-0.5 rounded"
              >
                <X size={14} />
              </button>
            </div>

            {/* Google Sheet ID Match Row */}
            <div className="bg-slate-950/80 p-1.5 rounded-lg border border-slate-800 mb-2 flex items-center justify-between">
              <div className="overflow-hidden">
                <span className="text-[9px] text-slate-500 block uppercase font-bold tracking-wider">Sheet ID</span>
                <span className="font-mono text-[10px] text-sky-400 truncate block select-all">
                  {selectedSignal.id || 'N/A'}
                </span>
              </div>
              {selectedSignal.id && (
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(selectedSignal.id);
                  }}
                  className="p-1 text-slate-400 hover:text-sky-400 hover:bg-slate-800 rounded transition-colors ml-1 flex-shrink-0"
                  title="Copy Google Sheet ID"
                >
                  <Copy size={12} />
                </button>
              )}
            </div>

            <div className="space-y-1.5 text-[11px]">
              <div className="flex justify-between">
                <span className="text-slate-400">Entry Price</span>
                <span className="font-mono text-slate-200 font-bold">{Number(selectedSignal.entry).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Stop Loss</span>
                <span className="font-mono text-rose-400">{Number(selectedSignal.sl).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Take Profit</span>
                <span className="font-mono text-emerald-400">{Number(selectedSignal.tp).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</span>
              </div>
              {selectedSignal.exit_price > 0 && (
                <div className="flex justify-between pt-1 border-t border-slate-800">
                  <span className="text-slate-400">Exit Price</span>
                  <span className="font-mono text-slate-300">{Number(selectedSignal.exit_price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</span>
                </div>
              )}
              {selectedSignal.net_profit !== undefined && selectedSignal.net_profit !== '' && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Net Profit</span>
                  <span className={`font-mono font-bold ${Number(selectedSignal.net_profit) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    ${Number(selectedSignal.net_profit).toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
