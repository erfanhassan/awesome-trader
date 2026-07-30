import { useState, useEffect } from 'react';
import useWebSocketLib from 'react-use-websocket';

export function useWebSocket(url) {
  const [state, setState] = useState({
    killzone_active: false,
    filter_killzone: false,
    filter_htf: false,
    filter_volume: false,
    filter_pressure: false,
    shihab_active: false,
    shihab_demo_active: false,
    demo_state: {
      balance: 100,
      invest_amount: 10,
      leverage: 10,
      positions: []
    },
    market_data: {},
    signals: [],
    signal_history: [],
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
            killzone_active: data.killzone_active,
            filter_killzone: data.filter_killzone ?? prev.filter_killzone,
            filter_htf: data.filter_htf ?? prev.filter_htf,
            filter_volume: data.filter_volume ?? prev.filter_volume,
            filter_pressure: data.filter_pressure ?? prev.filter_pressure,
            shihab_active: data.shihab_active ?? prev.shihab_active,
            shihab_demo_active: data.shihab_demo_active ?? prev.shihab_demo_active,
            demo_state: data.demo_state ?? prev.demo_state,
            market_data: data.market_data,
            trade_data: data.trade_data,
            signal_history: data.signal_history ?? prev.signal_history,
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

  const clearHistory = () => {
    sendMessage(JSON.stringify({ type: 'clear_history' }));
  };

  return { 
    state, readyState, addSymbol, removeSymbol, activeSymbol, setActiveSymbol, setFilter, 
    toggleShihab, toggleDemoShihab, setDemoInvest, setDemoLeverage, clearHistory
  };
}
