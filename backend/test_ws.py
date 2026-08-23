import asyncio
import websockets
import json

async def test():
    async with websockets.connect("ws://localhost:8000/api/ws") as ws:
        # Request BTCUSDT
        await ws.send(json.dumps({"type": "subscribe", "symbol": "BTCUSDT"}))
        for _ in range(3):
            msg = await ws.recv()
            data = json.loads(msg)
            print("WS Message Keys:", data.keys())
            if "market_data" in data and "BTCUSDT" in data["market_data"]:
                print("BTCUSDT market_data:", json.dumps(data["market_data"]["BTCUSDT"], indent=2))
                break

asyncio.run(test())
