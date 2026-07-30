import json
from google_sheets_client import GoogleSheetsClient

def fix_missing():
    print("Loading trade history...")
    with open("trade_history.json") as f:
        history = json.load(f)
        
    client = GoogleSheetsClient(credentials_path="credentials.json")
    
    count = 0
    # Process only non-PENDING trades from the last 100 trades to speed things up
    for trade in history[-200:]:
        if trade["status"] != "PENDING":
            print(f"Updating trade {trade['id']} ({trade['symbol']} {trade['strategy']} {trade['status']})")
            client.update_trade(trade)
            count += 1
            
    print(f"Successfully updated {count} trades.")

if __name__ == "__main__":
    fix_missing()
