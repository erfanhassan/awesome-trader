import { useState, useEffect } from 'react';
import useWebSocketLib from 'react-use-websocket';

export function useWebSocket(url) {
  const [state, setState] = useState({
    shihab_active: false,
    shihab_demo_active: false,
    demo_state: {
      balance: 100,
      invest_amount: 7,
      leverage: 400,
      positions: []
    },
    market_data: {},
    trade_data: {},
    signals: [],
    signal_history: [],
    live_leverage: 400,
  });
  const [activeSymbol, setActiveSymbol] = useState("BTCUSDT");

  const useWs = typeof useWebSocketLib === 'function' ? useWebSocketLib : useWebSocketLib.default || useWebSocketLib;
  const { sendMessage, lastMessage, readyState } = useWs(url, {
    shouldReconnect: (closeEvent) => true,
    reconnectInterval: 3000,
  });

  useEffect(() => {
    if (lastMessage !== null) {
      try {
        const data = JSON.parse(lastMessage.data);
        if (data.market_data) {
          setState(prev => ({
            ...prev,
            shihab_active: data.shihab_active ?? prev.shihab_active,
            shihab_demo_active: data.shihab_demo_active ?? prev.shihab_demo_active,
            demo_state: data.demo_state ?? prev.demo_state,
            market_data: data.market_data,
            trade_data: data.trade_data,
            signal_history: data.signal_history ?? prev.signal_history,
            live_leverage: data.live_leverage ?? prev.live_leverage,
            regime_filter_enabled: data.regime_filter_enabled ?? prev.regime_filter_enabled,
            mean_reversion_active: data.mean_reversion_active ?? prev.mean_reversion_active,
            trading_paused: data.trading_paused ?? prev.trading_paused,
            hourly_reports: data.hourly_reports ?? prev.hourly_reports,
            signals: data.signals && data.signals.length > 0 ? [...prev.signals, ...data.signals].slice(-100) : prev.signals,
          }));
        }
      } catch (e) {
        console.error("Error parsing websocket message", e);
      }
    }
  }, [lastMessage]);

  const addSymbol = (symbol) => {
    sendMessage(JSON.stringify({ type: 'add_symbol', symbol }));
    setActiveSymbol(symbol);
  };

  const removeSymbol = (symbol) => {
    sendMessage(JSON.stringify({ type: 'remove_symbol', symbol }));
  };

  const setFilter = (filterName, enabled) => {
    sendMessage(JSON.stringify({ type: 'set_filter', filter: filterName, enabled }));
  };

  const toggleShihab = (enabled) => {
    sendMessage(JSON.stringify({ type: 'toggle_shihab', enabled }));
  };

  const toggleDemoShihab = (enabled) => {
    sendMessage(JSON.stringify({ type: 'toggle_demo_shihab', enabled }));
  };

  const setDemoInvest = (amount) => {
    sendMessage(JSON.stringify({ type: 'set_demo_invest', amount }));
  };

  const setDemoLeverage = (leverage) => {
    sendMessage(JSON.stringify({ type: 'set_demo_leverage', leverage }));
  };

  const setLiveLeverage = (leverage) => {
    sendMessage(JSON.stringify({ type: 'set_live_leverage', leverage }));
  };

  const toggleCircuitBreaker = (enabled) => {
    sendMessage(JSON.stringify({ type: 'toggle_circuit_breaker', enabled }));
  };

  const toggleRegimeFilter = (enabled) => {
    sendMessage(JSON.stringify({ type: 'toggle_regime_filter', enabled }));
  };

  const toggleMeanReversion = (enabled) => {
    sendMessage(JSON.stringify({ type: 'toggle_mean_reversion', enabled }));
  };

  const clearHistory = () => {
    sendMessage(JSON.stringify({ type: 'clear_history' }));
  };

  const sendMsg = (obj) => sendMessage(JSON.stringify(obj));

  return { 
    state, readyState, addSymbol, removeSymbol, activeSymbol, setActiveSymbol, setFilter,
    toggleShihab, toggleDemoShihab, toggleCircuitBreaker, toggleRegimeFilter, toggleMeanReversion, setDemoInvest, setDemoLeverage, setLiveLeverage, clearHistory,
    sendMessage: sendMsg,
  };
}
