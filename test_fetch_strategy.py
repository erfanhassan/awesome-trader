from backend.google_sheets_client import GoogleSheetsClient

client = GoogleSheetsClient(credentials_path="backend/credentials.json")
sheet = client._get_or_create_worksheet("S0_Baseline_400x")
rows = sheet.get_all_values()
print("S0_Baseline_400x rows:")
for r in rows[-5:]:
    print(r)
