import sys
import os

# Add the backend dir to the path so we can import the client
sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from google_sheets_client import GoogleSheetsClient
    
    print("Connecting to Google Sheets...")
    client = GoogleSheetsClient(credentials_path="backend/credentials.json")
    if client.enabled:
        worksheets = client.doc.worksheets()
        print(f"Found {len(worksheets)} worksheets.")
        for ws in worksheets:
            if ws.title != "Net Profit":
                print(f"Checking headers for {ws.title}...")
                client._ensure_headers(ws)
        print("Done fixing headers.")
    else:
        print("Google Sheets client not enabled (missing credentials?).")
except Exception as e:
    print(f"Error: {e}")
