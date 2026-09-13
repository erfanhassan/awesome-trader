import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, CrosshairMode } from 'lightweight-charts';
import { TrendingUp, TrendingDown, RefreshCw, Copy, Check, X, Clock } from 'lucide-react';
import DrawingToolbar from './DrawingToolbar';

const TIMEFRAMES = [
  { label: '1m', key: 'Min1', trendKey: '1m', seconds: 60 },
  { label: '15m', key: 'Min15', trendKey: '15m', seconds: 900 },
  { label: '1h', key: 'Min60', trendKey: '1h', seconds: 3600 },
  { label: '4h', key: 'Hour4', trendKey: '4h', seconds: 14400 },
  { label: '1D', key: 'Day1', trendKey: '1d', seconds: 86400 },
];

// Format timestamp into 12-hour Date + Time: e.g. "Sep 07, 2026, 04:00 PM" (or "Sep 07, 2026" for 1D)
const formatDateTime12h = (timestampSec, isDaily = false) => {
  if (!timestampSec) return '';
  const d = new Date(timestampSec * 1000);
  const dateStr = d.toLocaleDateString('en-US', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
  });
  if (isDaily) return dateStr;
  const timeStr = d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
  return `${dateStr}, ${timeStr}`;
};

// Format tick marks along bottom time scale in 12-hour format
const formatTickMark12h = (time, tickMarkType) => {
  const d = new Date(time * 1000);
  if (tickMarkType === 0) return String(d.getFullYear());
  if (tickMarkType === 1) return d.toLocaleDateString('en-US', { month: 'short' });
  if (tickMarkType === 2) return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
};

export default function ChartArea({ symbol, state, tradeState, filterStates = {}, signals = [], signalHistory = [] }) {
  const chartContainerRef = useRef();
  const chartRef = useRef(null);
  const seriesRef = useRef({ candle: null, sessionHighLine: null, sessionLowLine: null });
  const [activeTimeframe, setActiveTimeframe] = useState(TIMEFRAMES[0]);
  const activeTimeframeRef = useRef(TIMEFRAMES[0]);
  activeTimeframeRef.current = activeTimeframe;
  const [selectedSignal, setSelectedSignal] = useState(null);
  const [hoveredCandle, setHoveredCandle] = useState(null);
  const [countdown, setCountdown] = useState({ text: '--:--', secondsLeft: 0 });
  const [currentTime, setCurrentTime] = useState(new Date());
  const pollRef = useRef(null);
  const lastCandlesRef = useRef([]); // cache last fetched candles
  const candleMapRef = useRef(new Map());
  const lastTimeframeRef = useRef(TIMEFRAMES[0].key);
  const lastSymbolRef = useRef(symbol);

  // Drawing Tools State
  const [drawMode, setDrawMode] = useState(false);
  const [drawColor, setDrawColor] = useState('#ef4444');
  const userLinesRef = useRef([]);
  const dragStateRef = useRef({ isDragging: false, lineId: null });
  const [linesVersion, setLinesVersion] = useState(0);

  const clearUserLines = useCallback(() => {
    userLinesRef.current.forEach(l => {
      try { seriesRef.current.candle.removePriceLine(l.lineRef); } catch {}
    });
    userLinesRef.current = [];
    dragStateRef.current = { isDragging: false, lineId: null };
    setLinesVersion(v => v + 1);
  }, []);

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
        timeVisible: activeTimeframeRef.current.key !== 'Day1',
        secondsVisible: false,
        tickMarkFormatter: (time, tickMarkType) => formatTickMark12h(time, tickMarkType),
      },
      localization: {
        timeFormatter: (time) => formatDateTime12h(time, activeTimeframeRef.current.key === 'Day1'),
      },
      handleScroll: {
        vertTouchDrag: false,
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
      const apiUrl = import.meta.env.DEV ? `http://${window.location.hostname}:8000` : '';
      const resp = await fetch(
        `${apiUrl}/api/klines?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(activeTimeframe.key)}`
      );
      const json = await resp.json();
      const candles = json.data || [];

      if (candles.length === 0) {
        if (lastSymbolRef.current !== symbol) {
           lastSymbolRef.current = symbol;
           lastCandlesRef.current = [];
           candleMapRef.current = new Map();
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
        candleMapRef.current = new Map(deduped.map(c => [c.time, c]));
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

  // Apply timeframe dynamic scale options (e.g. 1D vs intraday 12h format)
  useEffect(() => {
    if (!chartRef.current) return;
    const isDaily = activeTimeframe.key === 'Day1';
    chartRef.current.applyOptions({
      timeScale: {
        timeVisible: !isDaily,
        secondsVisible: false,
        tickMarkFormatter: (time, tickMarkType) => formatTickMark12h(time, tickMarkType),
      },
      localization: {
        timeFormatter: (time) => formatDateTime12h(time, isDaily),
      },
    });
  }, [activeTimeframe]);

  // Real-time clock tick every second
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Candle countdown timer updating every second for 1m, 15m, 1h, 4h, 1D
  useEffect(() => {
    const updateCountdown = () => {
      const tfSec = activeTimeframe.seconds || 60;
      const nowSec = Math.floor(Date.now() / 1000);

      // Standard MEXC calendar interval boundary
      const nextBoundary = (Math.floor(nowSec / tfSec) + 1) * tfSec;
      const lastCandles = lastCandlesRef.current;
      const lastCandleTime = lastCandles.length > 0 ? lastCandles[lastCandles.length - 1].time : 0;

      let targetEndTime = nextBoundary;
      if (lastCandleTime > 0) {
        const candleCloseTime = lastCandleTime + tfSec;
        if (candleCloseTime > nowSec) {
          targetEndTime = candleCloseTime;
        }
      }

      const secondsLeft = Math.max(0, targetEndTime - nowSec);
      const h = Math.floor(secondsLeft / 3600);
      const m = Math.floor((secondsLeft % 3600) / 60);
      const s = secondsLeft % 60;
      const pad = (n) => String(n).padStart(2, '0');

      let text;
      if (activeTimeframe.key === 'Day1' || activeTimeframe.key === 'Hour4' || h > 0) {
        text = `${pad(h)}:${pad(m)}:${pad(s)}`;
      } else {
        text = `${pad(m)}:${pad(s)}`;
      }

      setCountdown({ text, secondsLeft });

      // When countdown reaches 0, trigger fetch to get newly formed candle
      if (secondsLeft === 0) {
        fetchKlines();
      }
    };

    updateCountdown();
    const interval = setInterval(updateCountdown, 1000);
    return () => clearInterval(interval);
  }, [activeTimeframe, fetchKlines]);

  // Subscribe to crosshair move for HUD candle details
  useEffect(() => {
    if (!chartRef.current) return;

    const crosshairHandler = (param) => {
      if (!param.time || !param.point) {
        setHoveredCandle(null);
        return;
      }

      // Handle Line Dragging
      if (dragStateRef.current.isDragging && dragStateRef.current.lineId && seriesRef.current.candle) {
        const price = seriesRef.current.candle.coordinateToPrice(param.point.y);
        const lineObj = userLinesRef.current.find(l => l.id === dragStateRef.current.lineId);
        if (lineObj && lineObj.lineRef && price !== null) {
          lineObj.price = price;
          lineObj.lineRef.applyOptions({ price: price });
        }
        return; // Skip normal crosshair details while dragging
      }

      const isDaily = activeTimeframe.key === 'Day1';
      const rawCandle = candleMapRef.current.get(param.time);

      if (rawCandle) {
        setHoveredCandle({
          time: param.time,
          timeStr: formatDateTime12h(param.time, isDaily),
          open: rawCandle.open,
          high: rawCandle.high,
          low: rawCandle.low,
          close: rawCandle.close,
          volume: rawCandle.volume,
        });
      } else if (param.seriesData && seriesRef.current.candle) {
        const sData = param.seriesData.get(seriesRef.current.candle);
        if (sData) {
          setHoveredCandle({
            time: param.time,
            timeStr: formatDateTime12h(param.time, isDaily),
            open: sData.open,
            high: sData.high,
            low: sData.low,
            close: sData.close,
            volume: sData.volume,
          });
        }
      }
    };

    chartRef.current.subscribeCrosshairMove(crosshairHandler);
    return () => {
      if (chartRef.current) {
        chartRef.current.unsubscribeCrosshairMove(crosshairHandler);
      }
    };
  }, [activeTimeframe]);

  // --- Compute Markers based on actual Backend Signals ---
  useEffect(() => {
    if (!seriesRef.current.candle) return;
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
        
        const isLong = signal.direction === 'LONG';
        const isShihab = signal.strategy === 'Liquidity_Sweep_Shihab';
        
        // Base arrow color on Strategy
        let markerColor = isShihab ? '#3b82f6' : '#ffffff'; 

        markers.push({
          time: candleBucketTime,
          position: isLong ? 'belowBar' : 'aboveBar',
          color: markerColor,
          shape: isLong ? 'arrowUp' : 'arrowDown',
          text: isShihab ? 'Shihab' : 'Delta',
          id: signal.id
        });
        
        // Add sweep and liquidation markers if this signal is currently selected
        if (selectedSignal && selectedSignal.id === signal.id) {
            // Sweep Marker
            if (signal.sweep_candle_time) {
                const sweepTimeSeconds = Math.floor(signal.sweep_candle_time / 1000);
                const sweepBucketTime = Math.floor(sweepTimeSeconds / tfInSeconds) * tfInSeconds;
                
                markers.push({
                    time: sweepBucketTime,
                    position: isLong ? 'aboveBar' : 'belowBar',
                    color: '#fbbf24', // orange
                    shape: isLong ? 'arrowDown' : 'arrowUp',
                    text: `Sweep: $${signal.swept_level ? Number(signal.swept_level).toFixed(2) : 'N/A'}`,
                    id: `${signal.id}-sweep`
                });
            }

            // Liquidation Marker
            if (signal.liq_price) {
                markers.push({
                    time: candleBucketTime,
                    position: isLong ? 'aboveBar' : 'belowBar', // opposite to entry arrow
                    color: '#ef4444', // red
                    shape: isLong ? 'arrowDown' : 'arrowUp',
                    text: `Liq: $${Number(signal.liq_price).toFixed(2)}`,
                    id: `${signal.id}-liq`
                });
            }
        }

        // Add margin additions as markers ONLY if this signal is currently selected
        if (selectedSignal && selectedSignal.id === signal.id && signal.margin_add_times && Array.isArray(signal.margin_add_times)) {
            signal.margin_add_times.forEach((addTimeMs, index) => {
                const addTimeSeconds = Math.floor(addTimeMs / 1000);
                const addBucketTime = Math.floor(addTimeSeconds / tfInSeconds) * tfInSeconds;
                
                // Don't overlap exactly with entry if it happened very fast
                if (addBucketTime !== candleBucketTime || index > 0) {
                    markers.push({
                      time: addBucketTime,
                      position: isLong ? 'belowBar' : 'aboveBar', // Place margin adds on the same side
                      color: markerColor,
                      shape: 'circle',
                      text: `+$5`,
                      id: `${signal.id}-add-${index}`
                    });
                }
            });
        }
      }
    });
    // Lightweight charts requires markers to be sorted by time
    markers.sort((a, b) => a.time - b.time);

    try {
      seriesRef.current.candle.setMarkers(markers);
    } catch { /* series may be disposed */ }

  }, [state, symbol, signals, signalHistory, activeTimeframe, selectedSignal]);

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
      if (!param.point || !param.time) {
        // Do not auto-close signal card on empty click (user must click X)
        return;
      }

      if (drawMode) {
        const price = seriesRef.current.candle.coordinateToPrice(param.point.y);
        if (price !== null) {
          const newLineId = 'line_' + Date.now();
          const lineRef = seriesRef.current.candle.createPriceLine({
            price: price,
            color: drawColor,
            lineWidth: 2,
            lineStyle: 0,
            axisLabelVisible: true,
            title: 'User Line',
          });
          userLinesRef.current.push({ id: newLineId, price, color: drawColor, lineRef });
          setLinesVersion(v => v + 1);
          setDrawMode(false);
        }
        return;
      }

      const clickedPrice = seriesRef.current.candle.coordinateToPrice(param.point.y);
      if (clickedPrice !== null) {
        const priceDiff = Math.abs(seriesRef.current.candle.coordinateToPrice(param.point.y - 15) - clickedPrice);
        const hitLine = userLinesRef.current.find(l => Math.abs(l.price - clickedPrice) <= priceDiff);
        
        if (hitLine) {
          if (dragStateRef.current.isDragging && dragStateRef.current.lineId === hitLine.id) {
            dragStateRef.current = { isDragging: false, lineId: null };
          } else {
            dragStateRef.current = { isDragging: true, lineId: hitLine.id };
          }
          return;
        }
      }

      if (dragStateRef.current.isDragging) {
         dragStateRef.current = { isDragging: false, lineId: null };
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
      }
      // Do not auto-close signal card if no signal is clicked (user must click X)
    };
    
    chartRef.current.subscribeClick(clickHandler);
    return () => {
      if (chartRef.current) {
        chartRef.current.unsubscribeClick(clickHandler);
      }
    };
  }, [signals, signalHistory, symbol, activeTimeframe.key]);

  const lastCandles = lastCandlesRef.current;
  const lastCandleRaw = lastCandles.length > 0 ? lastCandles[lastCandles.length - 1] : null;
  const latestCandle = lastCandleRaw ? {
    ...lastCandleRaw,
    timeStr: formatDateTime12h(lastCandleRaw.time, activeTimeframe.key === 'Day1'),
  } : null;

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 h-full flex flex-col overflow-hidden relative">
      {/* Consolidated Chart Header & Metrics (Strict 2-Line Layout on Mobile) */}
      <div className="flex flex-col border-b border-slate-700 bg-slate-800/80">
        
        {/* Row 1: Timeframes, Timer, Drawing Tools */}
        <div className="px-1 md:px-4 py-1 flex items-center justify-between gap-1 w-full">
          {/* Timeframe selector buttons */}
          <div className="flex items-center gap-0.5 bg-slate-900/60 rounded p-0.5 shrink-0">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.key}
                onClick={() => setActiveTimeframe(tf)}
                className={`px-1.5 md:px-2.5 py-1 rounded text-[10px] md:text-xs font-medium transition-all ${
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
              className="ml-0.5 px-1 py-1 text-slate-400 hover:text-blue-400 transition-colors"
              title="Refresh Chart"
            >
              <RefreshCw size={12} />
            </button>
          </div>

          {/* Candle Timer (Ultra Compact) */}
          <div 
            className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-900/80 border border-slate-700/80 text-[9px] md:text-xs font-mono shadow-inner shrink-0"
            title="Time until candle closes"
          >
            <Clock size={10} className="text-amber-400 animate-pulse hidden md:block" />
            <span className="text-amber-300 font-bold tracking-wider">{countdown.text}</span>
          </div>

          {/* Drawing Tools (Scaled down on mobile) */}
          <div className="scale-[0.85] md:scale-100 origin-right shrink-0">
            <DrawingToolbar 
              drawMode={drawMode} 
              setDrawMode={setDrawMode} 
              drawColor={drawColor} 
              setDrawColor={setDrawColor} 
              clearLines={clearUserLines} 
            />
          </div>
        </div>

        {/* Row 2: Delta Metrics */}
        {tradeState && (
          <div className="px-1.5 md:px-4 py-1 flex items-center justify-between gap-1 bg-slate-900/30">
            <div className="flex items-center gap-2 md:gap-4 text-[9px] md:text-xs truncate">
              <span className="text-slate-400">Buy: <span className="text-emerald-400 font-mono">{tradeState.buy_vol.toFixed(0)}</span></span>
              <span className="text-slate-400">Sell: <span className="text-rose-400 font-mono">{tradeState.sell_vol.toFixed(0)}</span></span>
              <span className="text-slate-400">Δ: <span className={`font-mono font-bold ${tradeState.delta > 0 ? 'text-emerald-400' : tradeState.delta < 0 ? 'text-rose-400' : 'text-slate-400'}`}>{tradeState.delta > 0 ? '+' : ''}{tradeState.delta.toFixed(0)}</span></span>
            </div>
            <div className={`text-[8px] md:text-xs font-bold px-1.5 py-0.5 rounded shrink-0 ${tradeState.pressure_direction === 'BUYING_CONTROL' ? 'bg-emerald-500/20 text-emerald-400' : tradeState.pressure_direction === 'SELLING_CONTROL' ? 'bg-rose-500/20 text-rose-400' : 'bg-slate-700 text-slate-400'}`}>
              {tradeState.pressure_direction.replace('_', ' ')}
            </div>
          </div>
        )}
      </div>

      {/* Chart */}
      <div ref={chartContainerRef} className="flex-1 w-full relative">
        {/* Helper overlay for killzone if enabled */}
        {filterStates.killzone && activeTimeframe.key === 'Min1' && (
           <div className="absolute top-2 left-2 px-2 py-1 bg-emerald-500/20 text-emerald-400 text-xs rounded border border-emerald-500/30 z-10 pointer-events-none">
             Killzone Filter Active
           </div>
        )}

        {/* Selected Signal Detail HUD */}
        {selectedSignal && (
          <div className="absolute top-2 left-2 z-20 bg-slate-900/95 backdrop-blur-md border border-slate-600 rounded-xl shadow-2xl p-2 md:p-3.5 w-[200px] md:w-[250px] transition-all duration-150 text-[10px] md:text-xs" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-2 pb-1.5 md:pb-2 border-b border-slate-700">
              <div>
                <div className="flex items-center gap-1.5">
                  <span className={`font-bold text-xs ${selectedSignal.direction === 'LONG' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {selectedSignal.direction}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                    {selectedSignal.strategy?.replace(/S[0-9]+_/, '').replace('SA_', '').replace('SB_', '') || 'Active'}
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

      {/* Bottom Status / Time Bar (MEXC Style) */}
      <div className="px-3 py-1.5 bg-slate-900/90 border-t border-slate-700/80 flex items-center justify-between text-[11px] font-mono text-slate-400 select-none">
        {/* Left: Hovered candle or latest candle details */}
        <div className="flex items-center gap-2 overflow-hidden truncate">
          {hoveredCandle ? (
            <div className="flex items-center gap-2">
              <span className="text-sky-300 font-medium">{hoveredCandle.timeStr}</span>
              <span className="text-slate-600">|</span>
              <span>O: <span className={hoveredCandle.close >= hoveredCandle.open ? 'text-emerald-400' : 'text-rose-400'}>{hoveredCandle.open.toFixed(2)}</span></span>
              <span>H: <span className="text-slate-200">{hoveredCandle.high.toFixed(2)}</span></span>
              <span>L: <span className="text-slate-200">{hoveredCandle.low.toFixed(2)}</span></span>
              <span>C: <span className={hoveredCandle.close >= hoveredCandle.open ? 'text-emerald-400' : 'text-rose-400'}>{hoveredCandle.close.toFixed(2)}</span></span>
              {hoveredCandle.volume !== undefined && (
                <span className="hidden sm:inline">Vol: <span className="text-slate-300">{Number(hoveredCandle.volume).toFixed(1)}</span></span>
              )}
            </div>
          ) : latestCandle ? (
            <div className="flex items-center gap-2">
              <span className="text-slate-400">{latestCandle.timeStr}</span>
              <span className="text-slate-600">|</span>
              <span>O: <span className={latestCandle.close >= latestCandle.open ? 'text-emerald-400' : 'text-rose-400'}>{latestCandle.open.toFixed(2)}</span></span>
              <span>H: <span className="text-slate-200">{latestCandle.high.toFixed(2)}</span></span>
              <span>L: <span className="text-slate-200">{latestCandle.low.toFixed(2)}</span></span>
              <span>C: <span className={latestCandle.close >= latestCandle.open ? 'text-emerald-400' : 'text-rose-400'}>{latestCandle.close.toFixed(2)}</span></span>
              {latestCandle.volume !== undefined && (
                <span className="hidden sm:inline">Vol: <span className="text-slate-300">{Number(latestCandle.volume).toFixed(1)}</span></span>
              )}
            </div>
          ) : (
            <span className="text-slate-500">Tracking {symbol}</span>
          )}
        </div>

        {/* Right: Live Clock + Candle Countdown */}
        <div className="flex items-center gap-3 flex-shrink-0 ml-2">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700/60">
            <Clock size={11} className="text-amber-400 animate-pulse" />
            <span className="text-slate-400 text-[10px]">{activeTimeframe.label} Close:</span>
            <span className="text-amber-300 font-bold">{countdown.text}</span>
          </div>
          <span className="text-slate-400 text-[10px] hidden md:inline font-sans">
            {currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })}
          </span>
        </div>
      </div>
    </div>
  );
}
