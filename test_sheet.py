import sys
import os

sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from google_sheets_client import GoogleSheetsClient
    client = GoogleSheetsClient(credentials_path="backend/credentials.json")
    if client.enabled:
        ws = client.doc.worksheet("S0_Baseline_400x")
        print(ws.row_values(1))
        print(ws.row_values(2))
except Exception as e:
    print(f"Error: {e}")
