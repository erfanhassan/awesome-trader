import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import httpx
import time
import certifi
from logic_engine import LogicEngine
from mexc_client import MEXCClient

# Global instances
logic_engine = LogicEngine()
mexc_client = MEXCClient(logic_engine)
logic_engine.mexc_client = mexc_client

# Active WebSocket connections
active_connections: list[WebSocket] = []

@asynccontextmanager
async def lifespan(app):
    # Startup
    asyncio.create_task(mexc_client.start())
    asyncio.create_task(broadcast_state())
    yield
    # Shutdown (cleanup if needed)

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)





@app.get("/api/health")
async def health_check():
    """Health check endpoint for system monitoring."""
    return {
        "status": "healthy",
        "service": "awesome-trader",
        "symbol": getattr(logic_engine, "current_symbol", "BTCUSDT"),
        "mexc_ws_active": getattr(mexc_client, "ws", None) is not None,
        "google_sheets_enabled": getattr(logic_engine, "sheets_client", None) is not None,
    }

@app.get("/api/klines")
async def get_klines(symbol: str = "BTCUSDT", interval: str = "Min1"):
    """Return kline data for chart rendering."""
    data = logic_engine.get_klines(symbol, interval)
    return {"symbol": symbol, "interval": interval, "data": data}

cached_symbols = []
cached_symbols_time = 0

@app.get("/api/symbols")
async def get_symbols():
    global cached_symbols, cached_symbols_time
    if time.time() - cached_symbols_time < 3600 and cached_symbols:
        return {"symbols": cached_symbols}
    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            resp = await client.get("https://contract.mexc.com/api/v1/contract/detail", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                symbols = []
                for s in data.get("data", []):
                    if s.get("quoteCoin") == "USDT" and s.get("state") == 0:
                        ws_symbol = s.get("symbol", "")
                        rest_symbol = ws_symbol.replace("_", "")
                        symbols.append(rest_symbol)
                cached_symbols = sorted(symbols)
                cached_symbols_time = time.time()
    except Exception as e:
        print(f"Error fetching symbols: {e}")
    return {"symbols": cached_symbols}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        # Send initial state
        await websocket.send_json(logic_engine.get_state())
        while True:
            # We can receive messages from the UI here (e.g. adding symbols)
            data = await websocket.receive_text()
            message = json.loads(data)
            if message.get("type") == "add_symbol":
                symbol = message.get("symbol")
                if symbol:
                    await mexc_client.add_symbol(symbol)
                    await logic_engine.add_symbol(symbol)
            elif message.get("type") == "remove_symbol":
                symbol = message.get("symbol")
                if symbol:
                    await mexc_client.remove_symbol(symbol)
                    await logic_engine.remove_symbol(symbol)
            elif message.get("type") == "set_filter":
                filter_name = message.get("filter")
                enabled = message.get("enabled", False)
                if filter_name == "killzone":
                    logic_engine.filter_killzone = enabled
                elif filter_name == "htf":
                    logic_engine.filter_htf = enabled
                elif filter_name == "volume":
                    logic_engine.filter_volume = enabled
                elif filter_name == "pressure":
                    logic_engine.filter_pressure = enabled
            elif message.get("type") == "toggle_shihab":
                enabled = message.get("enabled", False)
                logic_engine.shihab_active = enabled
                print(f"SHIHAB AUTO-TRADER is now {'ON' if enabled else 'OFF'}")
            elif message.get("type") == "toggle_demo_shihab":
                enabled = message.get("enabled", False)
                logic_engine.shihab_demo_active = enabled
                print(f"DEMO SHIHAB is now {'ON' if enabled else 'OFF'}")
            elif message.get("type") == "set_demo_invest":
                amount = float(message.get("amount", 10.0))
                logic_engine.demo_invest_amount = amount
            elif message.get("type") == "set_demo_leverage":
                leverage = int(message.get("leverage", 10))
                logic_engine.demo_leverage = leverage
            elif message.get("type") == "clear_history":
                logic_engine.clear_history()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)

async def broadcast_state():
    """Periodically broadcasts the full state to all connected clients."""
    while True:
        if active_connections:
            state = logic_engine.get_state()
            # Also flush any signals that have fired
            signals = logic_engine.get_and_clear_signals()
            if signals:
                state["signals"] = signals

            for connection in active_connections:
                try:
                    await connection.send_json(state)
                except Exception as e:
                    print(f"Error broadcasting: {e}")
                    pass
        # Broadcast roughly every 1 second
        await asyncio.sleep(1)

# Serve the React frontend (this must be placed after all API/WebSocket routes)
frontend_path = os.path.join(os.path.dirname(__file__), "../frontend/dist")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    print(f"Warning: Frontend build directory not found at {frontend_path}. You need to run 'npm run build' in the frontend folder.")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
