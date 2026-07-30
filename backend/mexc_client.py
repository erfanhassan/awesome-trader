import asyncio
import json
import ssl
import os
import logging
import certifi
import websockets
import httpx
import hashlib
import hmac
import time
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mexc_client")

class MEXCClient:
    def __init__(self, logic_engine):
        self.logic_engine = logic_engine
        self.ws_url = "wss://contract.mexc.com/edge"
        self.rest_base = "https://contract.mexc.com"
        self.active_symbols = set()
        self.ws = None
        self.reconnect_delay = 5
        self.access_key = os.getenv("MEXC_ACCESS_KEY", "")
        self.api_secret = os.getenv("MEXC_API_SECRET", "")
        # Build a proper SSL context using certifi's CA bundle
        self.ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    def _to_ws_symbol(self, symbol: str) -> str:
        """Convert REST symbol (BTCUSDT) to WS symbol (BTC_USDT)."""
        # Common USDT pairs
        if symbol.endswith("USDT"):
            return symbol[:-4] + "_USDT"
        elif symbol.endswith("USDC"):
            return symbol[:-4] + "_USDC"
        elif symbol.endswith("BTC"):
            return symbol[:-3] + "_BTC"
        elif symbol.endswith("ETH"):
            return symbol[:-3] + "_ETH"
        return symbol

    def _to_rest_symbol(self, symbol: str) -> str:
        """Convert WS symbol (BTC_USDT) to REST symbol (BTCUSDT)."""
        return symbol.replace("_", "")

    def _generate_signature(self, timestamp: str, body_str: str) -> str:
        """Generate HMAC SHA256 signature for MEXC Futures V1 API."""
        text = self.access_key + timestamp + body_str
        return hmac.new(self.api_secret.encode('utf-8'), text.encode('utf-8'), hashlib.sha256).hexdigest()

    async def submit_order(self, symbol: str, direction: str, entry: float, sl: float, tp: float):
        """Submit a Market order with SL/TP to MEXC."""
        if not self.access_key or not self.api_secret:
            logger.error("Missing API keys. Cannot submit order.")
            return None

        ws_symbol = self._to_ws_symbol(symbol)
        
        # 1: Open Long, 2: Close Short, 3: Open Short, 4: Close Long
        side = 1 if direction == "LONG" else 3
        
        # We use a fixed volume of 1 contract for safety
        vol = 1

        payload = {
            "symbol": ws_symbol,
            "price": entry,
            "vol": vol,
            "side": side,
            "type": 5, # 5: Market Order
            "openType": 2, # 2: Cross margin
            "stopLossPrice": sl,
            "takeProfitPrice": tp
        }

        body_str = json.dumps(payload)
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, body_str)

        headers = {
            "ApiKey": self.access_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Content-Type": "application/json"
        }

        url = f"{self.rest_base}/api/v1/private/order/submit"
        
        logger.info(f"Submitting {direction} order for {ws_symbol}: {payload}")

        async with httpx.AsyncClient(verify=certifi.where()) as client:
            try:
                resp = await client.post(url, headers=headers, content=body_str, timeout=10)
                result = resp.json()
                logger.info(f"Order submit response: {result}")
                return result
            except Exception as e:
                logger.error(f"Error submitting order: {e}")
                return None

    async def get_funding_rate(self, symbol: str) -> float:
        """Fetch real-time funding rate from MEXC Futures"""
        ws_symbol = self._to_ws_symbol(symbol)
        url = f"{self.rest_base}/api/v1/contract/funding_rate/{ws_symbol}"
        try:
            async with httpx.AsyncClient(verify=certifi.where()) as client:
                resp = await client.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        return float(data["data"].get("fundingRate", 0.0001))
        except Exception as e:
            logger.error(f"Error fetching funding rate for {symbol}: {e}")
        return 0.0001 # fallback

    async def start(self):
        """Connect to MEXC via WS and polling."""
        # Auto-add BTCUSDT on startup
        default_symbols = ["BTCUSDT"]
        for sym in default_symbols:
            if sym not in self.active_symbols:
                self.active_symbols.add(sym)
                await self.logic_engine.add_symbol(sym)
                # Initial fetch of all timeframes
                await self._fetch_historical_klines(sym)

        # Start background loops
        asyncio.create_task(self._ws_loop())
        asyncio.create_task(self._trades_polling_loop())

    async def _trades_polling_loop(self):
        while True:
            try:
                # Poll Trades for Delta Pressure Calculation once per symbol
                if self.active_symbols:
                    async with httpx.AsyncClient(verify=certifi.where()) as client:
                        for sym in list(self.active_symbols):
                            try:
                                ws_symbol = self._to_ws_symbol(sym)
                                trades_url = f"{self.rest_base}/api/v1/contract/deals/{ws_symbol}"
                                trades_resp = await client.get(trades_url, timeout=5)
                                if trades_resp.status_code == 200:
                                    trades_data = trades_resp.json()
                                    if trades_data and trades_data.get('success'):
                                        trades_list = trades_data.get('data', [])
                                        # Map futures trades format
                                        mapped_trades = []
                                        for t in trades_list:
                                            mapped_trades.append({
                                                "time": t.get("t"),
                                                "qty": t.get("v"),
                                                "isBuyerMaker": t.get("T") == 2 # T=2 is sell
                                            })
                                        if mapped_trades:
                                            await self.logic_engine.process_trades(sym, mapped_trades)
                            except Exception as e:
                                pass
            except Exception as e:
                logger.error(f"Trades polling error: {e}")
            await asyncio.sleep(2)

    async def _ws_loop(self):
        while True:
            try:
                logger.info(f"Connecting to MEXC WS at {self.ws_url}")
                async with websockets.connect(self.ws_url, ssl=self.ssl_ctx, ping_interval=None) as ws:
                    self.ws = ws
                    
                    # Start ping task
                    ping_task = asyncio.create_task(self._ping_loop())
                    
                    # If this is a reconnect, fetch historical data again to fill any gaps!
                    if getattr(self, '_has_connected_once', False):
                        for sym in self.active_symbols:
                            await self._fetch_historical_klines(sym)
                    self._has_connected_once = True

                    # Resubscribe to active symbols
                    for sym in self.active_symbols:
                        await self._subscribe_symbol(sym)
                        
                    async for message in ws:
                        await self.handle_message(message)
            except Exception as e:
                logger.error(f"WS error: {e}")
            finally:
                self.ws = None
                if 'ping_task' in locals() and not ping_task.done():
                    ping_task.cancel()
            await asyncio.sleep(self.reconnect_delay)
            
    async def _ping_loop(self):
        while self.ws:
            try:
                await self.ws.send(json.dumps({"method": "ping"}))
                await asyncio.sleep(15)
            except Exception as e:
                logger.error(f"Ping error: {e}")
                break

    async def _fetch_historical_klines(self, symbol: str):
        """Fetch historical kline data via MEXC REST API to bootstrap EMA calculations and chart."""
        intervals = ["Min1", "Min15", "Min60", "Hour4", "Day1"]
        ws_symbol = self._to_ws_symbol(symbol)

        async with httpx.AsyncClient(verify=certifi.where()) as client:
            for interval in intervals:
                try:
                    url = f"{self.rest_base}/api/v1/contract/kline/{ws_symbol}"
                    params = {
                        "interval": interval,
                        "limit": 1000,
                    }
                    resp = await client.get(url, params=params, timeout=15)
                    resp.raise_for_status()
                    data = resp.json().get('data', {})

                    times = data.get('time', [])
                    opens = data.get('open', [])
                    highs = data.get('high', [])
                    lows = data.get('low', [])
                    closes = data.get('close', [])
                    vols = data.get('vol', [])

                    for i in range(len(times)):
                        kline_data = {
                            "t": times[i] * 1000,  # open time (ms)
                            "o": float(opens[i]),
                            "h": float(highs[i]),
                            "l": float(lows[i]),
                            "c": float(closes[i]),
                            "v": float(vols[i]),
                            "is_closed": True,
                        }
                        await self.logic_engine.process_kline(symbol, interval, kline_data, is_historical=True)

                    logger.info(f"Loaded {len(times)} historical {interval} candles for {symbol}")
                except Exception as e:
                    logger.info(f"Error fetching historical {interval} klines for {symbol}: {e}")

    async def _subscribe_symbol(self, symbol: str):
        """Subscribe to kline channels for a single symbol using correct MEXC WS v3 format."""
        if not self.ws:
            return

        ws_symbol = self._to_ws_symbol(symbol)
        intervals = ["Min1", "Min15", "Min60", "Hour4", "Day1"]

        for interval in intervals:
            sub_msg = {
                "method": "sub.kline",
                "param": {
                    "symbol": ws_symbol,
                    "interval": interval
                }
            }
            await self.ws.send(json.dumps(sub_msg))
            logger.info(f"Subscribed to {ws_symbol} @ {interval}")
            await asyncio.sleep(0.1)  # Small delay between subscriptions

    async def _unsubscribe_symbol(self, symbol: str):
        """Unsubscribe from all kline channels for a single symbol."""
        if not self.ws:
            return

        ws_symbol = self._to_ws_symbol(symbol)
        for interval in ["Min1", "Min15", "Min60", "Hour4", "Day1"]:
            unsub_msg = {
                "method": "unsub.kline",
                "param": {
                    "symbol": ws_symbol,
                    "interval": interval
                }
            }
            await self.ws.send(json.dumps(unsub_msg))
            await asyncio.sleep(0.05)
        logger.info(f"Unsubscribed from all intervals for {ws_symbol}")

    async def add_symbol(self, symbol: str):
        if symbol not in self.active_symbols:
            self.active_symbols.add(symbol)
            # Fetch historical data first
            await self._fetch_historical_klines(symbol)
            await self._subscribe_symbol(symbol)

    async def remove_symbol(self, symbol: str):
        if symbol in self.active_symbols:
            self.active_symbols.remove(symbol)
            await self._unsubscribe_symbol(symbol)

    async def handle_message(self, message):
        data = json.loads(message)

        # Handle push.kline channel (MEXC V3 WS format)
        if data.get("channel") == "push.kline" and "data" in data:
            kline = data["data"]
            # Convert WS symbol back to REST format for internal use
            ws_symbol = kline.get("symbol", data.get("symbol", ""))
            symbol = self._to_rest_symbol(ws_symbol)
            interval = kline.get("interval", "Min1")

            kline_data = {
                "t": kline.get("t", 0) * 1000 if kline.get("t", 0) < 1e12 else kline.get("t", 0),  # Ensure ms
                "o": float(kline.get("o", 0)),
                "h": float(kline.get("h", 0)),
                "l": float(kline.get("l", 0)),
                "c": float(kline.get("c", 0)),
                "v": float(kline.get("q", 0)),  # 'q' is volume in contracts, 'a' is amount in USDT
                "is_closed": False
            }
            await self.logic_engine.process_kline(symbol, interval, kline_data)

        # Handle old format just in case
        elif "c" in data and "spot@public.kline" in str(data.get("c", "")):
            channel = data["c"]
            parts = channel.split("@")
            if len(parts) >= 4:
                symbol = parts[2]
                interval = parts[3]
                kline = data.get("d", {}).get("k", {})

                if kline:
                    kline_data = {
                        "t": kline.get("t"),
                        "o": float(kline.get("o", 0)),
                        "h": float(kline.get("h", 0)),
                        "l": float(kline.get("l", 0)),
                        "c": float(kline.get("c", 0)),
                        "v": float(kline.get("v", 0)),
                        "is_closed": False
                    }
                    await self.logic_engine.process_kline(symbol, interval, kline_data)
