import json
from backend.google_sheets_client import GoogleSheetsClient

with open("backend/trade_history.json") as f:
    history = json.load(f)

trade = next((t for t in history if t["id"] == "71c5181f-78a9-4eb1-bcd3-f8e6b8819406"), None)
if trade:
    print(f"Testing update for trade: {trade['id']}")
    client = GoogleSheetsClient(credentials_path="backend/credentials.json")
    client.update_trade(trade)
    print("Done")
else:
    print("No such trade found")
