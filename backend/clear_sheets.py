import gspread
from google.oauth2.service_account import Credentials
import os

def clear_all_sheets():
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "1CfF5CZ9yMcp2tqsigHRKz0lA6B_3UKfwjGVU3b1ACmk")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    if os.path.exists(credentials_path):
        try:
            credentials = Credentials.from_service_account_file(
                credentials_path, scopes=scopes
            )
            client = gspread.authorize(credentials)
            doc = client.open_by_key(sheet_id)
            
            worksheets = doc.worksheets()
            print(f"Found {len(worksheets)} worksheets.")
            
            for ws in worksheets:
                print(f"Clearing {ws.title}...")
                ws.clear()
            
            print("All sheets cleared successfully!")
        except Exception as e:
            print(f"Failed: {e}")
    else:
        print("Credentials not found!")

if __name__ == "__main__":
    clear_all_sheets()
