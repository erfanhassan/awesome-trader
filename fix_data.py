import sys
import os

sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from google_sheets_client import GoogleSheetsClient
    client = GoogleSheetsClient(credentials_path="backend/credentials.json")
    if not client.enabled:
        print("Not enabled")
        sys.exit(1)
        
    for ws in client.doc.worksheets():
        if ws.title == "Net Profit":
            continue
            
        print(f"Fixing sheet {ws.title}...")
        all_values = ws.get_all_values()
        if not all_values or len(all_values) <= 1:
            continue
            
        # First row is header
        updates = []
        for i in range(1, len(all_values)):
            row = all_values[i]
            # Old format has 20 columns max (sometimes trailing empty strings are omitted by sheets API, so length could be < 20)
            # But the key is that 'Insight' is a long string, and it used to be at index 15.
            # In the old format, index 14 is Net Profit, 15 is Insight.
            # In the new format, index 15 is Net Profit, 16 is Reason.
            
            # Let's pad the row to 21 elements just in case
            while len(row) < 21:
                row.append("")
                
            # How to know if it's the old format? 
            # In old format, index 8 is PnL %. PnL % is usually a number or empty.
            # In new format, index 8 is Raw Profit. 
            # Wait, easier: old format had Strategy at 18, new at 19.
            # If row[18] starts with "S0" or "S1" etc., it's the old format!
            # If row[19] starts with "S0" or "S1", it's the new format!
            
            is_old_format = False
            if len(row) >= 19 and str(row[18]).startswith("S"):
                is_old_format = True
            elif len(row) >= 20 and str(row[19]).startswith("S"):
                is_old_format = False
            else:
                # Fallback, check if index 15 is a long text (insight)
                if len(str(row[15])) > 50:
                    is_old_format = True
                    
            if is_old_format:
                # Migrate to new format
                new_row = [
                    row[0], # ID
                    row[1], # Open Time
                    row[2], # Symbol
                    row[3], # Direction
                    row[4], # Entry
                    row[5], # Stop Loss
                    row[6], # Take Profit
                    row[7], # Status
                    "",     # Raw Profit (didn't exist)
                    row[8], # PnL %
                    row[9], # Close Time
                    row[10], # Exit Price
                    row[11], # Slippage
                    row[12], # Fees
                    row[13], # Funding Rate
                    row[14], # Net Profit
                    "",      # Reason (didn't exist)
                    row[16], # Duration
                    row[17], # Max Drawdown
                    row[18], # Strategy
                    row[19]  # Strategy Metric
                ]
                
                # Update the row in the sheet
                # +1 because gspread is 1-indexed, and +1 because row 0 is header
                row_index = i + 1 
                updates.append({
                    'range': f'A{row_index}:U{row_index}',
                    'values': [new_row]
                })
        
        if updates:
            ws.batch_update(updates)
            print(f"Fixed {len(updates)} rows in {ws.title}")
        else:
            print(f"No rows needed fixing in {ws.title}")
            
except Exception as e:
    print(f"Error: {e}")
