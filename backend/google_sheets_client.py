import gspread
from google.oauth2.service_account import Credentials
import os
import json
import time
import threading
import datetime
from dotenv import load_dotenv

load_dotenv()

class GoogleSheetsClient:
    def __init__(self, credentials_path=None, sheet_id=None):
        self.lock = threading.Lock()
        self.scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Robust credentials path resolution (checks env, current dir, and backend/ dir)
        if not credentials_path:
            env_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
            if os.path.exists(env_path):
                self.credentials_path = env_path
            elif os.path.exists(os.path.join("backend", env_path)):
                self.credentials_path = os.path.join("backend", env_path)
            elif os.path.exists("backend/credentials.json"):
                self.credentials_path = "backend/credentials.json"
            else:
                self.credentials_path = env_path
        else:
            self.credentials_path = credentials_path

        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID", "YOUR_GOOGLE_SHEET_ID_HERE")
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
            print(f"Google Sheets credentials not found at {self.credentials_path}. Integration disabled.")

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
            dt = datetime.datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            bd_dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=6)))
            return bd_dt.strftime("%Y-%m-%d %I:%M:%S %p")
        except Exception:
            return iso_str

    def _format_epoch_ms(self, ms_timestamp):
        if not ms_timestamp:
            return ""
        try:
            dt = datetime.datetime.fromtimestamp(ms_timestamp / 1000.0, tz=datetime.timezone.utc)
            bd_dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=6)))
            return bd_dt.strftime("%Y-%m-%d %I:%M:%S %p")
        except Exception:
            return str(ms_timestamp)

    def _get_or_create_worksheet(self, strategy_name):
        if not strategy_name:
            return self.sheet
        try:
            sheet = self._execute_with_retry(self.doc.worksheet, strategy_name)
            if strategy_name not in ["Net Profit", "Daily Summary"]:
                self._ensure_headers(sheet)
        except gspread.exceptions.WorksheetNotFound:
            sheet = self._execute_with_retry(self.doc.add_worksheet, title=strategy_name, rows="1000", cols="35")
            if strategy_name not in ["Net Profit", "Daily Summary"]:
                self._ensure_headers(sheet)
        return sheet

    def _ensure_headers(self, sheet=None):
        if sheet is None:
            sheet = self.sheet
        try:
            expected_headers = [
                "Trade ID", "Time (BD)", "Symbol", "Direction", "Strategy", 
                "Leverage", "Entry Price", "Stop Loss", "Take Profit", "Status",
                "Raw Profit ($)", "Exchange Fees ($)", "Funding Fees ($)", "Slippage Cost ($)",
                "Total Fees & Costs ($)", "Actual Net Profit ($)",
                "Margin Added per time ($)", "Total Margin Adds", "Total Cash In Trade ($)",
                "Daily Loss Status", "Trade Narrative"
            ]
            old_16_headers = [
                "Trade ID", "Time (BD)", "Symbol", "Direction", "Strategy", 
                "Entry Price", "Stop Loss", "Take Profit", "Status",
                "Raw Profit", "Total Fees", "Actual Net Profit",
                "Margin Added per time", "Total Margin Adds", "Total Cash In Trade",
                "Trade Narrative"
            ]

            headers = self._execute_with_retry(sheet.row_values, 1)

            # Check if this worksheet is in the old 16-column format and needs migration
            if headers == old_16_headers:
                all_data = self._execute_with_retry(sheet.get_all_values)
                if len(all_data) > 1:
                    migrated_rows = [expected_headers]
                    for row in all_data[1:]:
                        while len(row) < 16:
                            row.append("")
                        new_row = [
                            row[0], row[1], row[2], row[3], row[4],
                            "300x",
                            row[5], row[6], row[7], row[8],
                            row[9], row[10], "0.00", "0.00", row[10], row[11],
                            row[12], row[13], row[14],
                            "Active",
                            row[15]
                        ]
                        migrated_rows.append(new_row)
                    self._execute_with_retry(sheet.update, f"A1:U{len(migrated_rows)}", migrated_rows)
                    return

            if headers != expected_headers:
                if not headers:
                    self._execute_with_retry(sheet.append_row, expected_headers)
                else:
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
                            # Prevent duplicate entries
                            return
                
                leverage_val = hist_signal.get("computed_leverage", hist_signal.get("leverage", 300))
                leverage_str = f"{leverage_val}x"

                exchange_fees = float(hist_signal.get("exchange_fees", 0) or 0)
                funding_fees = float(hist_signal.get("funding_fees", 0) or 0)
                slippage_cost = float(hist_signal.get("slippage", 0) or 0)
                total_fees = float(hist_signal.get("fees", 0) or (exchange_fees + funding_fees + slippage_cost))
                
                margin_adds = hist_signal.get("margin_adds", 0)
                margin_added_per_time = 5.0
                initial_margin = float(hist_signal.get("initial_margin", 7.0) or 7.0)
                total_cash_in_trade = float(hist_signal.get("margin", initial_margin) or initial_margin)
                daily_loss_status = hist_signal.get("daily_loss_status", "Active")
                
                timeline = hist_signal.get("timeline_events", [])
                narrative_str = "\n\n".join([f"[{e.get('type', 'EVENT')}] {e.get('message', '')}" for e in timeline])
                if hist_signal.get("mentor_review"):
                    narrative_str += f"\n\n═════════════════════════════════════\nAI MENTOR REVIEW:\n{hist_signal['mentor_review']}"
                    
                is_closed = hist_signal.get("status") in ["WIN", "LOSS", "PROFIT", "LIQUIDATED", "CLOSED"]

                row_data = [
                    hist_signal.get("id", ""),
                    self._format_bd_time(hist_signal.get("timestamp", "")),
                    hist_signal.get("symbol", ""),
                    hist_signal.get("direction", ""),
                    hist_signal.get("strategy", ""),
                    leverage_str,
                    hist_signal.get("entry", ""),
                    hist_signal.get("sl", ""),
                    hist_signal.get("tp", ""),
                    hist_signal.get("status", "PENDING"),
                    hist_signal.get("raw_profit", "") if is_closed else "",
                    round(exchange_fees, 4) if is_closed else "",
                    round(funding_fees, 4) if is_closed else "",
                    round(slippage_cost, 4) if is_closed else "",
                    round(total_fees, 4) if is_closed else "",
                    hist_signal.get("net_profit", "") if is_closed else "",
                    margin_added_per_time,
                    margin_adds,
                    total_cash_in_trade,
                    daily_loss_status,
                    narrative_str
                ]
                self._execute_with_retry(sheet.append_row, row_data)
                
                if strategy_name == "Liquidity_Sweep_Shihab":
                    all_rows_after = self._execute_with_retry(sheet.get_all_values)
                    new_row_idx = len(all_rows_after)
                    # Light blue background: #cfe2f3
                    self._execute_with_retry(
                        sheet.format, 
                        f"A{new_row_idx}:U{new_row_idx}", 
                        {"backgroundColor": {"red": 0.81, "green": 0.88, "blue": 0.95}}
                    )

                self._update_net_profit_sheet_locked(hist_signal)
                if is_closed:
                    self._update_daily_summary_locked(hist_signal)
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
                all_rows = self._execute_with_retry(sheet.get_all_values)
                
                row_index = -1
                for i in range(len(all_rows) - 1, -1, -1):
                    if all_rows[i] and all_rows[i][0] == trade_id:
                        row_index = i + 1
                        break

                if row_index != -1:
                    leverage_val = hist_signal.get("computed_leverage", hist_signal.get("leverage", 190))
                    leverage_str = f"{leverage_val}x"
                    exchange_fees = float(hist_signal.get("exchange_fees", 0) or 0)
                    funding_fees = float(hist_signal.get("funding_fees", 0) or 0)
                    slippage_cost = float(hist_signal.get("slippage", 0) or 0)
                    total_fees = float(hist_signal.get("fees", 0) or (exchange_fees + funding_fees + slippage_cost))
                    
                    margin_adds = hist_signal.get("margin_adds", 0)
                    margin_added_per_time = 5.0
                    initial_margin = float(hist_signal.get("initial_margin", 7.0) or 7.0)
                    total_cash_in_trade = float(hist_signal.get("margin", initial_margin) or initial_margin)
                    daily_loss_status = hist_signal.get("daily_loss_status", "Active")

                    timeline = hist_signal.get("timeline_events", [])
                    narrative_str = "\n\n".join([f"[{e.get('type', 'EVENT')}] {e.get('message', '')}" for e in timeline])
                    if hist_signal.get("mentor_review"):
                        narrative_str += f"\n\n═════════════════════════════════════\nAI MENTOR REVIEW:\n{hist_signal['mentor_review']}"

                    is_closed = hist_signal.get("status") in ["WIN", "LOSS", "PROFIT", "LIQUIDATED", "CLOSED"]

                    updates = [
                        {'range': f'F{row_index}', 'values': [[leverage_str]]},
                        {'range': f'G{row_index}', 'values': [[hist_signal.get("entry", "")]]},
                        {'range': f'H{row_index}', 'values': [[hist_signal.get("sl", "")]]},
                        {'range': f'I{row_index}', 'values': [[hist_signal.get("tp", "")]]},
                        {'range': f'J{row_index}', 'values': [[hist_signal.get("status")]]},
                        {'range': f'K{row_index}', 'values': [[hist_signal.get("raw_profit", "") if is_closed else ""]]},
                        {'range': f'L{row_index}', 'values': [[round(exchange_fees, 4) if is_closed else ""]]},
                        {'range': f'M{row_index}', 'values': [[round(funding_fees, 4) if is_closed else ""]]},
                        {'range': f'N{row_index}', 'values': [[round(slippage_cost, 4) if is_closed else ""]]},
                        {'range': f'O{row_index}', 'values': [[round(total_fees, 4) if is_closed else ""]]},
                        {'range': f'P{row_index}', 'values': [[hist_signal.get("net_profit", "") if is_closed else ""]]},
                        {'range': f'Q{row_index}', 'values': [[margin_added_per_time]]},
                        {'range': f'R{row_index}', 'values': [[margin_adds]]},
                        {'range': f'S{row_index}', 'values': [[total_cash_in_trade]]},
                        {'range': f'T{row_index}', 'values': [[daily_loss_status]]},
                        {'range': f'U{row_index}', 'values': [[narrative_str]]},
                    ]
                    self._execute_with_retry(sheet.batch_update, updates)
                    
                    self._update_net_profit_sheet_locked(hist_signal)
                    if is_closed:
                        self._update_daily_summary_locked(hist_signal)
                else:
                    print(f"Trade ID {trade_id} not found in Google Sheet to update.")

            except Exception as e:
                print(f"Error updating trade in Google Sheet: {e}")

    def _update_daily_summary_locked(self, hist_signal):
        if not self.enabled or not self.doc:
            return
        try:
            is_closed = hist_signal.get("status") in ["WIN", "LOSS", "PROFIT", "LIQUIDATED", "CLOSED"]
            if not is_closed:
                return

            daily = hist_signal.get("daily_stats")
            if not daily:
                return

            sheet = self._get_or_create_worksheet("Daily Summary")
            headers = [
                "Date (BD)", "Total Closed Trades", "Wins", "Losses", "Win Rate",
                "Gross Profit ($)", "Exchange Fees ($)", "Funding Fees ($)", "Slippage ($)",
                "Total Costs ($)", "Net Daily Profit ($)", "Max Daily Loss Limit ($)",
                "Circuit Breaker Hit?", "Last Updated (BD)"
            ]
            curr_headers = self._execute_with_retry(sheet.row_values, 1)
            if curr_headers != headers:
                if not curr_headers:
                    self._execute_with_retry(sheet.append_row, headers)
                else:
                    cells = sheet.range(1, 1, 1, len(headers))
                    for i, c in enumerate(cells):
                        c.value = headers[i]
                    self._execute_with_retry(sheet.update_cells, cells)

            bd_tz = datetime.timezone(datetime.timedelta(hours=6))
            today_str = daily.get("date", datetime.datetime.now(bd_tz).strftime("%Y-%m-%d"))
            now_str = datetime.datetime.now(bd_tz).strftime("%I:%M:%S %p")

            row_data = [
                today_str,
                daily.get("total_trades", 0),
                daily.get("wins", 0),
                daily.get("losses", 0),
                f"{daily.get('win_rate', 0.0)}%",
                daily.get("gross_profit", 0.0),
                daily.get("exchange_fees", 0.0),
                daily.get("funding_fees", 0.0),
                daily.get("slippage", 0.0),
                daily.get("total_costs", 0.0),
                daily.get("net_profit", 0.0),
                daily.get("max_daily_loss", 15.0),
                daily.get("circuit_breaker_hit", "NO"),
                now_str
            ]

            all_rows = self._execute_with_retry(sheet.get_all_values)
            row_index = -1
            for i in range(1, len(all_rows)):
                if all_rows[i] and all_rows[i][0] == today_str:
                    row_index = i + 1
                    break

            if row_index == -1:
                self._execute_with_retry(sheet.append_row, row_data)
            else:
                self._execute_with_retry(sheet.update, f"A{row_index}:N{row_index}", [row_data])

        except Exception as e:
            print(f"Error updating Daily Summary in Google Sheet: {e}")

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
                headers.append(strategy_name)
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
