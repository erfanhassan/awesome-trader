import sys
import os

sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from google_sheets_client import GoogleSheetsClient
    client = GoogleSheetsClient(credentials_path="backend/credentials.json")
    if not client.enabled:
        print("Not enabled")
        sys.exit(1)
        
    worksheets = client.doc.worksheets()
    for ws in worksheets:
        print(f"Clearing sheet {ws.title}...")
        # Get headers first
        headers = ws.row_values(1)
        
        # Clear the entire sheet
        ws.clear()
        
        # Re-insert the headers if they exist
        if headers:
            ws.append_row(headers)
        else:
            client._ensure_headers(ws)
            
    print("All sheets cleared successfully!")
except Exception as e:
    print(f"Error: {e}")
