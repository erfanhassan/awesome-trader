import json
from backend.google_sheets_client import GoogleSheetsClient

with open("backend/trade_history.json") as f:
    history = json.load(f)

# Find the last PROFIT trade
trade = next((t for t in reversed(history) if t["status"] == "PROFIT"), None)
if trade:
    print(f"Testing update for trade: {trade['id']}")
    client = GoogleSheetsClient(credentials_path="backend/credentials.json")
    client.update_trade(trade)
    print("Done")
else:
    print("No PROFIT trade found")
