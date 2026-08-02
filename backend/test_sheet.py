import sys
import uuid
import datetime
import os
from google_sheets_client import GoogleSheetsClient

def test_sheet():
    client = GoogleSheetsClient()
    if not client.enabled:
        print("Client not enabled. Check credentials.")
        sys.exit(1)
        
    dummy_trade = {
        "id": str(uuid.uuid4())[:8],
        "setup_id": "SETUP_TEST_123",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry": 95000.0,
        "sl": 94000.0,
        "tp": 97000.0,
        "status": "PENDING",
        "strategy": "S0_Baseline"
    }
    
    try:
        print(f"Appending dummy trade {dummy_trade['id']}...")
        client.append_trade(dummy_trade)
        print("Append successful.")
        
        print("Attempting to append same trade again (duplicate check)...")
        client.append_trade(dummy_trade)
        print("Duplicate check passed (no crash).")
        
    except Exception as e:
        print(f"Error during sheet operation: {e}")

if __name__ == "__main__":
    test_sheet()
