import gspread
from google.oauth2.service_account import Credentials
import os

def ensure_headers_on_all():
    credentials_path = "credentials.json"
    sheet_id = "1OCrTQSLiJ4TZ6cFV13_hj42L02TDzU2JXu329DT6OXE"
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    expected_headers = [
        "ID", "Open Time", "Symbol", "Direction", 
        "Entry", "Stop Loss", "Take Profit", 
        "Status", "Raw Profit", "PnL %", "Close Time", "Exit Price",
        "Slippage", "Fees", "Funding Rate", "Net Profit", "Reason",
        "Duration", "Max Drawdown", "Strategy", "Strategy Metric"
    ]

    if os.path.exists(credentials_path):
        credentials = Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
        client = gspread.authorize(credentials)
        doc = client.open_by_key(sheet_id)
        
        for ws in doc.worksheets():
            if ws.title != "Net Profit":
                print(f"Adding headers to {ws.title}...")
                ws.append_row(expected_headers)
                
        print("Headers added successfully!")

if __name__ == "__main__":
    ensure_headers_on_all()
