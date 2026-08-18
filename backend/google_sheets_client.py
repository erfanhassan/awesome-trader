import gspread
from google.oauth2.service_account import Credentials
import os
import json
import time
import threading
from dotenv import load_dotenv

load_dotenv()

class GoogleSheetsClient:
    def __init__(self, credentials_path=None, sheet_id=None):
        self.lock = threading.Lock()
        self.scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        self.credentials_path = credentials_path or os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID", "1CfF5CZ9yMcp2tqsigHRKz0lA6B_3UKfwjGVU3b1ACmk")
        self.client = None
        self.sheet = None
        self.enabled = False

        if os.path.exists(self.credentials_path):
            try:
                credentials = Credentials.from_service_account_file(
                    self.credentials_path, scopes=self.scopes
                )
                self.client = gspread.authorize(credentials)
                self.doc = self.client.open_by_key(self.sheet_id)
                self.sheet = self.doc.sheet1
                self.enabled = True
                print("Google Sheets integration enabled successfully.")
            except Exception as e:
                print(f"Failed to initialize Google Sheets client: {e}")
        else:
            print(f"Google Sheets credentials not found at {credentials_path}. Integration disabled.")

    def _execute_with_retry(self, func, *args, **kwargs):
        for attempt in range(5):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == 4:
                    raise e
                time.sleep(2 ** attempt)

    def _format_bd_time(self, iso_str):
        if not iso_str:
            return ""
        try:
            import datetime
            dt = datetime.datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            bd_dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=6)))
            return bd_dt.strftime("%Y-%m-%d %I:%M:%S %p")
        except Exception:
            return iso_str

    def _get_or_create_worksheet(self, strategy_name):
        if not strategy_name:
            return self.sheet
        try:
            sheet = self._execute_with_retry(self.doc.worksheet, strategy_name)
            if strategy_name != "Net Profit":
                self._ensure_headers(sheet)
        except gspread.exceptions.WorksheetNotFound:
            sheet = self._execute_with_retry(self.doc.add_worksheet, title=strategy_name, rows="1000", cols="35")
            if strategy_name != "Net Profit":
                self._ensure_headers(sheet)
        return sheet

    def _ensure_headers(self, sheet=None):
        if sheet is None:
            sheet = self.sheet
        try:
            # Check if the first row has headers
            headers = self._execute_with_retry(sheet.row_values, 1)
            expected_headers = [
                "ID", "Open Time", "Symbol", "Direction", 
                "Entry", "Stop Loss", "Take Profit", 
                "Status", "Raw Profit", "PnL %", "Close Time", "Exit Price",
                "Slippage", "Fees", "Funding Rate", "Net Profit", "Reason",
                "Duration", "Max Drawdown", "Strategy", "Strategy Metric"
            ]
            if headers != expected_headers:
                if not headers:
                    self._execute_with_retry(sheet.append_row, expected_headers)
                else:
                    # Extend headers if needed
                    cells = sheet.range(1, 1, 1, len(expected_headers))
                    for i, cell in enumerate(cells):
                        cell.value = expected_headers[i]
                    self._execute_with_retry(sheet.update_cells, cells)
        except Exception as e:
            print(f"Error checking/creating headers in Google Sheet: {e}")

    def append_trade(self, hist_signal):
        if not self.enabled or not self.doc:
            return

        with self.lock:
            try:
                strategy_name = hist_signal.get("strategy", "S0_Baseline")
                sheet = self._get_or_create_worksheet(strategy_name)
                
                trade_id = str(hist_signal.get("id", ""))
                if trade_id:
                    all_rows = self._execute_with_retry(sheet.get_all_values)
                    for i in range(len(all_rows) - 1, -1, -1):
                        if all_rows[i] and str(all_rows[i][0]) == trade_id:
                            # Prevent duplicate (twin) entries
                            return
                
                row_data = [
                    hist_signal.get("id", ""),
                    self._format_bd_time(hist_signal.get("timestamp", "")),
                    hist_signal.get("symbol", ""),
                    hist_signal.get("direction", ""),
                    hist_signal.get("entry", ""),
                    hist_signal.get("sl", ""),
                    hist_signal.get("tp", ""),
                    hist_signal.get("status", "PENDING"),
                    hist_signal.get("raw_profit", ""),
                    hist_signal.get("pnl", ""),
                    self._format_bd_time(hist_signal.get("close_time", "")),
                    hist_signal.get("exit_price", ""),
                    hist_signal.get("slippage", ""),
                    hist_signal.get("fees", ""),
                    hist_signal.get("funding_rate", ""),
                    hist_signal.get("net_profit", ""),
                    hist_signal.get("close_reason", ""),
                    hist_signal.get("duration", ""),
                    hist_signal.get("max_drawdown", ""),
                    hist_signal.get("strategy", "S0_Baseline"),
                    hist_signal.get("strategy_metric") or ""
                ]
                self._execute_with_retry(sheet.append_row, row_data)
                self._update_net_profit_sheet_locked(hist_signal)
            except Exception as e:
                print(f"Error appending trade to Google Sheet: {e}")

    def update_trade(self, hist_signal):
        if not self.enabled or not self.doc:
            return

        with self.lock:
            try:
                strategy_name = hist_signal.get("strategy", "S0_Baseline")
                sheet = self._get_or_create_worksheet(strategy_name)
                
                trade_id = hist_signal.get("id")
                if not trade_id:
                    return

                # Find the row with this ID
                # get_all_values() returns list of lists (rows)
                all_rows = self._execute_with_retry(sheet.get_all_values)
                
                row_index = -1
                # Start searching from the end as it's likely a recent trade
                for i in range(len(all_rows) - 1, -1, -1):
                    if all_rows[i] and all_rows[i][0] == trade_id:
                        row_index = i + 1 # gspread is 1-indexed
                        break

                if row_index != -1:
                    # Update specific columns
                    updates = [
                        {'range': f'H{row_index}', 'values': [[hist_signal.get("status")]]},
                        {'range': f'I{row_index}', 'values': [[hist_signal.get("raw_profit", "")]]},
                        {'range': f'J{row_index}', 'values': [[hist_signal.get("pnl")]]},
                        {'range': f'K{row_index}', 'values': [[self._format_bd_time(hist_signal.get("close_time"))]]},
                        {'range': f'L{row_index}', 'values': [[hist_signal.get("exit_price")]]},
                        {'range': f'M{row_index}', 'values': [[hist_signal.get("slippage", "")]]},
                        {'range': f'N{row_index}', 'values': [[hist_signal.get("fees", "")]]},
                        {'range': f'O{row_index}', 'values': [[hist_signal.get("funding_rate", "")]]},
                        {'range': f'P{row_index}', 'values': [[hist_signal.get("net_profit", "")]]},
                        {'range': f'Q{row_index}', 'values': [[hist_signal.get("close_reason", "")]]},
                        {'range': f'R{row_index}', 'values': [[hist_signal.get("duration", "")]]},
                        {'range': f'S{row_index}', 'values': [[hist_signal.get("max_drawdown", "")]]}
                    ]
                    self._execute_with_retry(sheet.batch_update, updates)
                    
                    # Update the Net Profit comparison sheet with final results
                    self._update_net_profit_sheet_locked(hist_signal)
                else:
                    print(f"Trade ID {trade_id} not found in Google Sheet to update.")

            except Exception as e:
                print(f"Error updating trade in Google Sheet: {e}")

    def _update_net_profit_sheet(self, hist_signal):
        with self.lock:
            self._update_net_profit_sheet_locked(hist_signal)
            
    def _update_net_profit_sheet_locked(self, hist_signal):
        if not self.enabled or not self.doc:
            return
        try:
            sheet = self._get_or_create_worksheet("Net Profit")
            headers = [
                "Setup ID", "Open Time", 
                "S0_Baseline_400x", "S1_AutoLeverage", "S2_PreLiq_SL", "S3_ATR_Filter",
                "S4_CrossMargin", "S5_ScaleOut_BE", "S6_HTF_Aligned", "S7_Delta_Div",
                "S8_RSI_Div", "S9_TimeExit", "S10_FVG_Conf"
            ]
            curr_headers = self._execute_with_retry(sheet.row_values, 1)
            if not curr_headers:
                self._execute_with_retry(sheet.append_row, headers)
            else:
                # Merge existing headers with hardcoded ones to avoid dropping dynamic ones on restart
                updated = False
                for h in headers:
                    if h not in curr_headers:
                        curr_headers.append(h)
                        updated = True
                headers = curr_headers
                if updated:
                    cells = sheet.range(1, 1, 1, len(headers))
                    for i, c in enumerate(cells):
                        c.value = headers[i]
                    self._execute_with_retry(sheet.update_cells, cells)
            
            setup_id = hist_signal.get("setup_id")
            if not setup_id:
                return
                
            all_rows = self._execute_with_retry(sheet.get_all_values)
            row_index = -1
            for i in range(len(all_rows) - 1, -1, -1):
                if all_rows[i] and all_rows[i][0] == setup_id:
                    row_index = i + 1
                    break
                    
            strategy_name = hist_signal.get("strategy")
            
            try:
                col_index = headers.index(strategy_name) + 1
            except ValueError:
                # Strategy not in headers, let's append it dynamically
                headers.append(strategy_name)
                # Update the headers in the sheet
                cells = sheet.range(1, 1, 1, len(headers))
                for i, c in enumerate(cells):
                    c.value = headers[i]
                self._execute_with_retry(sheet.update_cells, cells)
                col_index = headers.index(strategy_name) + 1
                
            col_letter = chr(64 + col_index) if col_index <= 26 else f"{chr(64 + ((col_index - 1) // 26))}{chr(64 + ((col_index - 1) % 26 + 1))}"
            net_profit_val = hist_signal.get("net_profit", "")
            if hist_signal.get("status") == "PENDING" and net_profit_val == 0.0:
                net_profit_val = "Running..."
                
            if row_index == -1:
                new_row = [setup_id, self._format_bd_time(hist_signal.get("timestamp"))] + [""] * (len(headers) - 2)
                new_row[col_index - 1] = net_profit_val
                self._execute_with_retry(sheet.append_row, new_row)
            else:
                self._execute_with_retry(sheet.update_acell, f'{col_letter}{row_index}', net_profit_val)
        except Exception as e:
            print(f"Error updating net profit sheet: {e}")

