import asyncio
from mexc_client import MEXCClient

async def main():
    client = MEXCClient()
    klines = await client.fetch_klines("BTCUSDT", "Day1", limit=2)
    # The client might not have get_current_price. Let's just use the last minute candle
    klines_1m = await client.fetch_klines("BTCUSDT", "Min1", limit=1)
    
    current_price = klines_1m[0]["c"] if klines_1m else 0
    
    if len(klines) > 1:
        prev_day = klines[-2]
        d1_high = prev_day["h"]
        d1_low = prev_day["l"]
        
        print(f"Current Price: {current_price}")
        print(f"1D High: {d1_high}")
        print(f"1D Low: {d1_low}")
    else:
        print("Not enough daily data")
        
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
