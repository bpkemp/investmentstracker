"""
Multi-Broker Portfolio Consolidator - Desktop GUI
=================================================
Consolidates ASX broker CSV exports into a single master ledger, computes current
holdings, and displays realized FIFO capital gains with 50% CGT discount status.
Supports broker-agnostic custom column mapping and manual transaction entry.
"""

from __future__ import annotations

import os
import threading
from tkinter import filedialog, messagebox
import customtkinter as ctk
import pandas as pd

from portfolio_tracker.core.consolidator import (
    process_csv_files,
    load_existing_master,
    identify_broker,
    find_header_row,
    add_broker_mapping,
    load_broker_mappings,
    standardise_ticker,
    DEDUP_SUBSET,
    MASTER_COLUMNS
)
from portfolio_tracker.core.tax import PortfolioTracker

# GUI Custom Palette
COLOR_TEAL = "#13B4B1"
COLOR_TEAL_HOVER = "#0A7377"
COLOR_GREEN = "#2CA58D"
COLOR_GREEN_HOVER = "#1E7F6B"
COLOR_BG_DARK = "#1E1E24"
COLOR_CARD_DARK = "#282830"

class ColumnMappingDialog(ctk.CTkToplevel):
    """Modal dialog to map CSV columns to the master ledger schema."""
    def __init__(self, parent: ctk.CTk, filepath: str) -> None:
        super().__init__(parent)
        self.filepath = filepath
        self.result_mapping = None  # Stores {"broker_id": broker_id, "columns": col_map}
        
        self.title("Map CSV Columns")
        self.geometry("460x520")
        self.resizable(False, False)
        
        # Read CSV headers
        self.headers = self._read_headers()
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._build_ui()
        
    def _read_headers(self) -> list[str]:
        """Try to read CSV headers skipping metadata rows."""
        try:
            with open(self.filepath, "r", encoding="utf-8-sig") as f:
                for line in f:
                    fields = [h.strip().strip('"') for h in line.split(",") if h.strip()]
                    if len(fields) >= 4:
                        return fields
        except Exception:
            pass
        return []

    def _build_ui(self) -> None:
        self.grid_columnconfigure((0, 1), weight=1, uniform="col")
        
        # Header Info
        lbl_info = ctk.CTkLabel(
            self,
            text=f"Unrecognized File:\n{os.path.basename(self.filepath)}\n\nPlease map the CSV columns to the ledger fields:",
            font=ctk.CTkFont(size=13, weight="bold"),
            justify="center"
        )
        lbl_info.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 15), sticky="ew")
        
        # Broker Name Input
        ctk.CTkLabel(self, text="Broker ID / Name:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=1, column=0, padx=20, pady=8, sticky="w")
        self.ent_broker = ctk.CTkEntry(self, placeholder_text="e.g. Pearler")
        self.ent_broker.grid(row=1, column=1, padx=20, pady=8, sticky="ew")
        
        # Create mapping fields
        self.dropdowns: dict[str, ctk.CTkOptionMenu] = {}
        fields = ["Date", "Ticker", "Type", "Units", "Price", "Brokerage"]
        
        options = ["(Select Column)"] + self.headers
        
        for idx, field in enumerate(fields, start=2):
            label_text = f"{field} Column:"
            if field == "Brokerage":
                label_text += " (Optional)"
                
            ctk.CTkLabel(self, text=label_text, font=ctk.CTkFont(size=12)).grid(row=idx, column=0, padx=20, pady=6, sticky="w")
            
            menu = ctk.CTkOptionMenu(self, values=options, fg_color=COLOR_CARD_DARK)
            menu.grid(row=idx, column=1, padx=20, pady=6, sticky="ew")
            self.dropdowns[field] = menu
            
            # Simple heuristic matching
            lower_headers = [h.lower() for h in self.headers]
            field_l = field.lower()
            best_match = None
            
            # Find best string match
            for h_idx, h in enumerate(lower_headers):
                if field_l in h or (field_l == "ticker" and "stock" in h or "code" in h) or (field_l == "type" and "transaction" in h):
                    best_match = self.headers[h_idx]
                    break
            if best_match:
                menu.set(best_match)

        # Save mapping checkbox
        self.chk_save_var = ctk.StringVar(value="on")
        self.chk_save = ctk.CTkCheckBox(self, text="Save mapping for future auto-detection", variable=self.chk_save_var, onvalue="on", offvalue="off")
        self.chk_save.grid(row=8, column=0, columnspan=2, padx=20, pady=15)
        
        # Error text
        self.lbl_error = ctk.CTkLabel(self, text="", text_color="red", font=ctk.CTkFont(size=12))
        self.lbl_error.grid(row=9, column=0, columnspan=2, padx=20, pady=2)

        # Apply button
        btn_apply = ctk.CTkButton(
            self,
            text="Apply Mapping",
            command=self._on_apply,
            fg_color=COLOR_GREEN,
            hover_color=COLOR_GREEN_HOVER,
            font=ctk.CTkFont(weight="bold")
        )
        btn_apply.grid(row=10, column=0, columnspan=2, padx=20, pady=(10, 20), sticky="ew")

    def _on_apply(self) -> None:
        broker_id = self.ent_broker.get().strip()
        if not broker_id:
            self.lbl_error.configure(text="Please enter a Broker ID / Name.")
            return

        col_map = {}
        # Core columns must be selected
        required = ["Date", "Ticker", "Type", "Units", "Price"]
        selected_csv_cols = []
        
        for field in required:
            sel = self.dropdowns[field].get()
            if sel == "(Select Column)":
                self.lbl_error.configure(text=f"Please select a column for {field}.")
                return
            col_map[sel] = field
            selected_csv_cols.append(sel)

        # Check for duplicate column selections
        if len(set(selected_csv_cols)) != len(selected_csv_cols):
            self.lbl_error.configure(text="Duplicate selections. Each field must map to a unique column.")
            return

        # Optional Brokerage
        brokerage_col = self.dropdowns["Brokerage"].get()
        if brokerage_col != "(Select Column)":
            col_map[brokerage_col] = "Brokerage"

        self.result_mapping = {
            "broker_id": broker_id.upper(),
            "columns": col_map
        }
        
        # Save mapping back to config if checked
        if self.chk_save_var.get() == "on":
            broker_key = broker_id.lower().replace(" ", "_")
            add_broker_mapping(broker_key, broker_id.upper(), col_map)

        self.destroy()


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("ASX Portfolio Consolidator & Tax Tracker")
        self.geometry("1080x700")
        self.minsize(900, 550)

        # State Variables
        self._selected_files: list[str] = []
        self._existing_ledger_path: str = ""
        self._master_df: pd.DataFrame | None = None
        self._holdings_df: pd.DataFrame | None = None
        self._cgt_df: pd.DataFrame | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        # Configure Grid layout (1 row, 2 columns: Left control panel, Right display panel)
        self.grid_columnconfigure(0, weight=0, minsize=320)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------------------------------------------------------------------
        # LEFT CONTROL PANEL
        # ---------------------------------------------------------------------
        left_panel = ctk.CTkFrame(self, width=320, corner_radius=0, fg_color=COLOR_BG_DARK)
        left_panel.grid(row=0, column=0, sticky="nsew")
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(8, weight=1) # Spacer row

        # Title
        lbl_title = ctk.CTkLabel(
            left_panel,
            text="Portfolio Consolidator",
            font=ctk.CTkFont(size=20, weight="bold", family="Helvetica"),
            anchor="w"
        )
        lbl_title.grid(row=0, column=0, padx=20, pady=(20, 2), sticky="ew")

        lbl_subtitle = ctk.CTkLabel(
            left_panel,
            text="ASX Multi-Broker Ledger & CGT tool",
            font=ctk.CTkFont(size=12, slant="italic"),
            text_color="gray",
            anchor="w"
        )
        lbl_subtitle.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")

        # Section: CSV Selection
        btn_select = ctk.CTkButton(
            left_panel,
            text="Browse Broker CSVs",
            command=self._on_select_files,
            fg_color=COLOR_TEAL,
            hover_color=COLOR_TEAL_HOVER,
            font=ctk.CTkFont(weight="bold")
        )
        btn_select.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.lbl_selected_status = ctk.CTkLabel(
            left_panel,
            text="No broker CSV files selected.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w"
        )
        self.lbl_selected_status.grid(row=3, column=0, padx=20, pady=(0, 15), sticky="ew")

        # Section: Merging Options
        self.chk_merge_var = ctk.StringVar(value="off")
        self.chk_merge = ctk.CTkCheckBox(
            left_panel,
            text="Merge with existing ledger",
            command=self._toggle_merge_ledger,
            variable=self.chk_merge_var,
            onvalue="on",
            offvalue="off"
        )
        self.chk_merge.grid(row=4, column=0, padx=20, pady=5, sticky="w")

        self.btn_select_ledger = ctk.CTkButton(
            left_panel,
            text="Select Existing Ledger CSV",
            command=self._on_select_existing_ledger,
            state="disabled",
            fg_color="gray40",
            hover_color="gray30"
        )
        self.btn_select_ledger.grid(row=5, column=0, padx=20, pady=5, sticky="ew")

        self.lbl_ledger_status = ctk.CTkLabel(
            left_panel,
            text="No ledger selected.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w"
        )
        self.lbl_ledger_status.grid(row=6, column=0, padx=20, pady=(0, 20), sticky="ew")

        # Section: Actions
        self.btn_process = ctk.CTkButton(
            left_panel,
            text="Consolidate & Calculate",
            command=self._on_process,
            state="disabled",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36
        )
        self.btn_process.grid(row=7, column=0, padx=20, pady=10, sticky="ew")

        # Down at the bottom: Save Button
        self.btn_save = ctk.CTkButton(
            left_panel,
            text="Save Master Ledger",
            command=self._on_save_ledger,
            state="disabled",
            fg_color=COLOR_GREEN,
            hover_color=COLOR_GREEN_HOVER,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36
        )
        self.btn_save.grid(row=9, column=0, padx=20, pady=(10, 20), sticky="ew")

        # ---------------------------------------------------------------------
        # RIGHT DISPLAY PANEL
        # ---------------------------------------------------------------------
        right_panel = ctk.CTkFrame(self, corner_radius=0)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(0, weight=0) # Dashboard cards
        right_panel.grid_rowconfigure(1, weight=1) # Tabs

        # Dashboard Summary Cards
        db_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        db_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        db_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # Card 1: Total Holdings
        card1 = ctk.CTkFrame(db_frame, fg_color=COLOR_CARD_DARK, height=80)
        card1.grid(row=0, column=0, padx=5, pady=0, sticky="nsew")
        card1.grid_propagate(False)
        self.lbl_stat_holdings = ctk.CTkLabel(card1, text="0", font=ctk.CTkFont(size=22, weight="bold"), text_color=COLOR_TEAL)
        self.lbl_stat_holdings.pack(pady=(12, 0))
        ctk.CTkLabel(card1, text="Active Holdings", font=ctk.CTkFont(size=11), text_color="gray").pack()

        # Card 2: Portfolio Cost
        card2 = ctk.CTkFrame(db_frame, fg_color=COLOR_CARD_DARK, height=80)
        card2.grid(row=0, column=1, padx=5, pady=0, sticky="nsew")
        card2.grid_propagate(False)
        self.lbl_stat_cost = ctk.CTkLabel(card2, text="$0.00", font=ctk.CTkFont(size=22, weight="bold"), text_color=COLOR_TEAL)
        self.lbl_stat_cost.pack(pady=(12, 0))
        ctk.CTkLabel(card2, text="Invested Capital", font=ctk.CTkFont(size=11), text_color="gray").pack()

        # Card 3: Realized Gain
        card3 = ctk.CTkFrame(db_frame, fg_color=COLOR_CARD_DARK, height=80)
        card3.grid(row=0, column=2, padx=5, pady=0, sticky="nsew")
        card3.grid_propagate(False)
        self.lbl_stat_gain = ctk.CTkLabel(card3, text="$0.00", font=ctk.CTkFont(size=22, weight="bold"), text_color=COLOR_GREEN)
        self.lbl_stat_gain.pack(pady=(12, 0))
        ctk.CTkLabel(card3, text="Realized CGT Gains (Disc.)", font=ctk.CTkFont(size=11), text_color="gray").pack()

        # Tabs View for results
        self.tabview = ctk.CTkTabview(right_panel)
        self.tabview.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        self.tabview.add("Ledger Preview")
        self.tabview.add("Holdings Summary")
        self.tabview.add("Realized CGT")
        self.tabview.add("Manual Entry")

        # Textboxes for reports
        self.txt_ledger = ctk.CTkTextbox(self.tabview.tab("Ledger Preview"), wrap="none", font=ctk.CTkFont(family="Courier", size=12))
        self.txt_ledger.pack(fill="both", expand=True)
        self.txt_ledger.configure(state="disabled")

        self.txt_holdings = ctk.CTkTextbox(self.tabview.tab("Holdings Summary"), wrap="none", font=ctk.CTkFont(family="Courier", size=12))
        self.txt_holdings.pack(fill="both", expand=True)
        self.txt_holdings.configure(state="disabled")

        self.txt_cgt = ctk.CTkTextbox(self.tabview.tab("Realized CGT"), wrap="none", font=ctk.CTkFont(family="Courier", size=12))
        self.txt_cgt.pack(fill="both", expand=True)
        self.txt_cgt.configure(state="disabled")

        # Setup manual entry UI
        self._build_manual_entry_tab()

        # Status Bar
        self.lbl_status = ctk.CTkLabel(
            right_panel,
            text="Ready. Select broker CSV files to begin, or add manual trades.",
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self.lbl_status.grid(row=2, column=0, padx=10, pady=(0, 5), sticky="ew")

    def _build_manual_entry_tab(self) -> None:
        """Create split layout inside manual entry tab (Form + Log list)."""
        tab_me = self.tabview.tab("Manual Entry")
        tab_me.grid_columnconfigure(0, weight=0, minsize=320)
        tab_me.grid_columnconfigure(1, weight=1)
        tab_me.grid_rowconfigure(0, weight=1)

        # Left Column - Form Container
        frm_form = ctk.CTkFrame(tab_me, fg_color="transparent")
        frm_form.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        frm_form.grid_columnconfigure(1, weight=1)

        # Form Fields
        labels = ["Date (YYYY-MM-DD):", "Ticker (e.g. CBA):", "Type:", "Units:", "Price ($):", "Brokerage ($):", "Broker:"]
        self.me_fields: dict[str, ctk.CTkEntry | ctk.CTkOptionMenu] = {}

        # Date input with default
        ctk.CTkLabel(frm_form, text=labels[0]).grid(row=0, column=0, padx=10, pady=6, sticky="w")
        ent_date = ctk.CTkEntry(frm_form, placeholder_text="e.g. 2026-06-07")
        ent_date.insert(0, pd.Timestamp.now().strftime("%Y-%m-%d"))
        ent_date.grid(row=0, column=1, padx=10, pady=6, sticky="ew")
        self.me_fields["Date"] = ent_date

        # Ticker input
        ctk.CTkLabel(frm_form, text=labels[1]).grid(row=1, column=0, padx=10, pady=6, sticky="w")
        ent_ticker = ctk.CTkEntry(frm_form, placeholder_text="e.g. CBA")
        ent_ticker.grid(row=1, column=1, padx=10, pady=6, sticky="ew")
        self.me_fields["Ticker"] = ent_ticker

        # Type drop down
        ctk.CTkLabel(frm_form, text=labels[2]).grid(row=2, column=0, padx=10, pady=6, sticky="w")
        opt_type = ctk.CTkOptionMenu(frm_form, values=["Buy", "Sell"], fg_color=COLOR_CARD_DARK)
        opt_type.grid(row=2, column=1, padx=10, pady=6, sticky="ew")
        self.me_fields["Type"] = opt_type

        # Units input
        ctk.CTkLabel(frm_form, text=labels[3]).grid(row=3, column=0, padx=10, pady=6, sticky="w")
        ent_units = ctk.CTkEntry(frm_form, placeholder_text="e.g. 50.0")
        ent_units.grid(row=3, column=1, padx=10, pady=6, sticky="ew")
        self.me_fields["Units"] = ent_units

        # Price input
        ctk.CTkLabel(frm_form, text=labels[4]).grid(row=4, column=0, padx=10, pady=6, sticky="w")
        ent_price = ctk.CTkEntry(frm_form, placeholder_text="e.g. 102.50")
        ent_price.grid(row=4, column=1, padx=10, pady=6, sticky="ew")
        self.me_fields["Price"] = ent_price

        # Brokerage input
        ctk.CTkLabel(frm_form, text=labels[5]).grid(row=5, column=0, padx=10, pady=6, sticky="w")
        ent_brokerage = ctk.CTkEntry(frm_form, placeholder_text="e.g. 9.90 (default 0)")
        ent_brokerage.grid(row=5, column=1, padx=10, pady=6, sticky="ew")
        self.me_fields["Brokerage"] = ent_brokerage

        # Broker input
        ctk.CTkLabel(frm_form, text=labels[6]).grid(row=6, column=0, padx=10, pady=6, sticky="w")
        ent_broker = ctk.CTkEntry(frm_form, placeholder_text="e.g. CMC (default MANUAL)")
        ent_broker.grid(row=6, column=1, padx=10, pady=6, sticky="ew")
        self.me_fields["Broker"] = ent_broker

        # Add Row Button
        btn_add = ctk.CTkButton(
            frm_form,
            text="Add to Ledger",
            command=self._on_add_manual_row,
            fg_color=COLOR_TEAL,
            hover_color=COLOR_TEAL_HOVER,
            font=ctk.CTkFont(weight="bold")
        )
        btn_add.grid(row=7, column=0, columnspan=2, padx=10, pady=20, sticky="ew")

        # Right Column - Session Logs Container
        frm_log = ctk.CTkFrame(tab_me, fg_color=COLOR_CARD_DARK)
        frm_log.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        frm_log.grid_columnconfigure(0, weight=1)
        frm_log.grid_rowconfigure(1, weight=1)

        lbl_log_title = ctk.CTkLabel(
            frm_log,
            text="Session Manual Logs:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_log_title.grid(row=0, column=0, padx=15, pady=8, sticky="w")

        self.txt_manual_logs = ctk.CTkTextbox(frm_log, wrap="none", font=ctk.CTkFont(family="Courier", size=11))
        self.txt_manual_logs.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self.txt_manual_logs.insert("1.0", "--- Form logs will appear here ---")
        self.txt_manual_logs.configure(state="disabled")

    # ----- Callbacks & Event Handlers ----------------------------------------
    def _on_select_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select Broker CSV Files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not paths:
            return

        self._selected_files = list(paths)
        filename_summary = ", ".join(os.path.basename(p) for p in self._selected_files)
        if len(filename_summary) > 40:
            filename_summary = f"{len(self._selected_files)} CSV files selected"
        
        self.lbl_selected_status.configure(text=filename_summary, text_color="white")
        self.btn_process.configure(state="normal")
        self._clear_displays()

    def _toggle_merge_ledger(self) -> None:
        if self.chk_merge_var.get() == "on":
            self.btn_select_ledger.configure(state="normal", fg_color=COLOR_TEAL, hover_color=COLOR_TEAL_HOVER)
        else:
            self.btn_select_ledger.configure(state="disabled", fg_color="gray40", hover_color="gray30")
            self._existing_ledger_path = ""
            self.lbl_ledger_status.configure(text="No ledger selected.", text_color="gray")
        self._clear_displays()

    def _on_select_existing_ledger(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Existing Master Ledger",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return
        self._existing_ledger_path = path
        self.lbl_ledger_status.configure(text=os.path.basename(path), text_color="white")
        self._clear_displays()

    def _clear_displays(self) -> None:
        self.btn_save.configure(state="disabled")
        self.lbl_stat_holdings.configure(text="0")
        self.lbl_stat_cost.configure(text="$0.00")
        self.lbl_stat_gain.configure(text="$0.00")
        self._set_text_content(self.txt_ledger, "")
        self._set_text_content(self.txt_holdings, "")
        self._set_text_content(self.txt_cgt, "")
        self._master_df = None
        self._holdings_df = None
        self._cgt_df = None

    def _set_text_content(self, widget: ctk.CTkTextbox, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _log_manual_action(self, message: str) -> None:
        self.txt_manual_logs.configure(state="normal")
        # Clear default placeholder if there
        current_val = self.txt_manual_logs.get("1.0", "end").strip()
        if "--- Form logs will appear here ---" in current_val:
            self.txt_manual_logs.delete("1.0", "end")
        
        self.txt_manual_logs.insert("end", f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] {message}\n")
        self.txt_manual_logs.configure(state="disabled")

    def _on_process(self) -> None:
        self.btn_process.configure(state="disabled")
        self.lbl_status.configure(text="Inspecting broker files...")
        
        # We check for unrecognized CSVs on the main thread so we can show modal popups
        broker_mappings = load_broker_mappings()
        custom_mappings = {}
        
        for filepath in self._selected_files:
            try:
                # Guess header row and see if it can be identified
                skip = find_header_row(filepath, broker_mappings)
                df_temp = pd.read_csv(filepath, skiprows=skip, nrows=2, encoding="utf-8-sig", on_bad_lines="skip")
                result = identify_broker(df_temp.columns.tolist(), broker_mappings)
                if result is not None:
                    continue
            except Exception:
                pass
            
            # Show interactive dialog for unrecognized columns
            dialog = ColumnMappingDialog(self, filepath)
            self.wait_window(dialog)
            
            if dialog.result_mapping:
                custom_mappings[filepath] = dialog.result_mapping
            else:
                # Cancel clicked or dialog closed, abort
                self.lbl_status.configure(text="Consolidation cancelled (mapping missing).", text_color="yellow")
                self.btn_process.configure(state="normal")
                return

        # Trigger consolidator on background thread with custom mappings
        self.lbl_status.configure(text="Processing transactions...")
        threading.Thread(target=self._run_consolidation, args=(custom_mappings,), daemon=True).start()

    def _run_consolidation(self, custom_mappings: dict) -> None:
        # Process files
        new_master, raw_count, dupes, warnings = process_csv_files(self._selected_files, custom_mappings)
        
        # Load existing ledger if requested
        existing_master = pd.DataFrame(columns=MASTER_COLUMNS)
        if self.chk_merge_var.get() == "on" and self._existing_ledger_path:
            try:
                existing_master = load_existing_master(self._existing_ledger_path)
            except Exception as exc:
                self.after(0, self._show_error, f"Failed to load existing ledger: {exc}")
                return

        # Combine
        frames = []
        if not existing_master.empty:
            frames.append(existing_master)
        if not new_master.empty:
            frames.append(new_master)

        if not frames:
            self.after(0, self._show_error, "No transactions found or processed.")
            return

        final_master = pd.concat(frames, ignore_index=True)
        total_raw = len(final_master)

        # Deduplicate
        final_master = final_master.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
        final_dupes_dropped = total_raw - len(final_master)

        final_master = final_master.sort_values("Date").reset_index(drop=True)
        final_master = final_master[MASTER_COLUMNS]

        # Calculate taxes
        tracker = PortfolioTracker(final_master)
        holdings = tracker.get_holdings_summary()
        cgt = tracker.get_cgt_report()

        # Update GUI on main thread
        self.after(
            0,
            self._on_processing_complete,
            final_master,
            holdings,
            cgt,
            raw_count,
            dupes,
            final_dupes_dropped,
            warnings
        )

    def _show_error(self, message: str) -> None:
        self.lbl_status.configure(text=f"Error: {message}", text_color="red")
        self.btn_process.configure(state="normal")

    def _on_processing_complete(
        self,
        master: pd.DataFrame,
        holdings: pd.DataFrame,
        cgt: pd.DataFrame,
        raw_count: int,
        dupes: int,
        total_dupes_clean: int,
        warnings: list[str]
    ) -> None:
        self._master_df = master
        self._holdings_df = holdings
        self._cgt_df = cgt

        # Enable UI
        self.btn_process.configure(state="normal")
        self.btn_save.configure(state="normal")

        self._refresh_tab_views()

        # Status Message
        status_msg = f"Consolidation done! New rows: {raw_count} | Duplicates removed: {dupes} | Total ledger size: {len(master)}"
        if warnings:
            status_msg += f" (Warnings: {len(warnings)})"
        self.lbl_status.configure(text=status_msg, text_color="white")

    def _refresh_tab_views(self) -> None:
        """Repopulate text boxes and update dashboard stats from current memory state."""
        if self._master_df is None:
            return

        # Update Dashboard Stats
        num_holdings = len(self._holdings_df) if self._holdings_df is not None else 0
        self.lbl_stat_holdings.configure(text=str(num_holdings))

        total_invested = self._holdings_df["Total_Cost"].sum() if (self._holdings_df is not None and not self._holdings_df.empty) else 0.0
        self.lbl_stat_cost.configure(text=f"${total_invested:,.2f}")

        total_disc_gain = self._cgt_df["Discounted_Gain"].sum() if (self._cgt_df is not None and not self._cgt_df.empty) else 0.0
        self.lbl_stat_gain.configure(text=f"${total_disc_gain:,.2f}")

        # Update text views
        pd.set_option('display.max_columns', 20)
        pd.set_option('display.width', 1000)

        self._set_text_content(self.txt_ledger, self._master_df.to_string(index=False))
        
        if self._holdings_df is not None and not self._holdings_df.empty:
            self._set_text_content(self.txt_holdings, self._holdings_df.to_string(index=False))
        else:
            self._set_text_content(self.txt_holdings, "No active stock holdings in portfolio.")

        if self._cgt_df is not None and not self._cgt_df.empty:
            self._set_text_content(self.txt_cgt, self._cgt_df.to_string(index=False))
        else:
            self._set_text_content(self.txt_cgt, "No realized capital gains events (Sells matched to Buys).")

    def _on_add_manual_row(self) -> None:
        """Validate manual entry form fields and append a row to memory."""
        # 1. Validate Date
        date_raw = self.me_fields["Date"].get().strip()
        try:
            parsed_date = pd.to_datetime(date_raw, dayfirst=True)
            formatted_date = parsed_date.strftime("%Y-%m-%d")
        except Exception:
            messagebox.showerror("Validation Error", "Invalid Date format. Use YYYY-MM-DD or DD/MM/YYYY.")
            return

        # 2. Validate Ticker
        ticker_raw = self.me_fields["Ticker"].get().strip()
        if not ticker_raw:
            messagebox.showerror("Validation Error", "Ticker cannot be empty.")
            return
        ticker = standardise_ticker(ticker_raw)

        # 3. Type
        trans_type = self.me_fields["Type"].get()

        # 4. Units
        try:
            units = float(self.me_fields["Units"].get().strip())
            if units <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Validation Error", "Units must be a positive number.")
            return

        # 5. Price
        try:
            price = float(self.me_fields["Price"].get().strip())
            if price <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Validation Error", "Price must be a positive number.")
            return

        # 6. Brokerage (Optional)
        brokerage_raw = self.me_fields["Brokerage"].get().strip()
        if not brokerage_raw:
            brokerage = 0.0
        else:
            try:
                brokerage = float(brokerage_raw)
                if brokerage < 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Validation Error", "Brokerage must be a non-negative number.")
                return

        # 7. Broker (Optional)
        broker_raw = self.me_fields["Broker"].get().strip()
        broker = broker_raw.upper() if broker_raw else "MANUAL"

        # Calculate Total Cost / Net Proceeds
        if trans_type == "Buy":
            total_cost = (units * price) + brokerage
        else:
            total_cost = (units * price) - brokerage

        # Create row dict
        new_row = {
            "Date": formatted_date,
            "Ticker": ticker,
            "Type": trans_type,
            "Units": units,
            "Price": price,
            "Brokerage": brokerage,
            "Broker": broker,
            "Total_Cost": total_cost
        }

        # Append to memory
        if self._master_df is None:
            self._master_df = pd.DataFrame(columns=MASTER_COLUMNS)

        new_df = pd.DataFrame([new_row])
        
        self._master_df = pd.concat([self._master_df, new_df], ignore_index=True)
        self._master_df = self._master_df.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
        self._master_df = self._master_df.sort_values("Date").reset_index(drop=True)
        self._master_df = self._master_df[MASTER_COLUMNS]

        # Recalculate tax
        tracker = PortfolioTracker(self._master_df)
        self._holdings_df = tracker.get_holdings_summary()
        self._cgt_df = tracker.get_cgt_report()

        # Update display
        self._refresh_tab_views()
        self.btn_save.configure(state="normal")

        # Logging
        log_msg = f"Added {units} units of {ticker} @ ${price:.2f} ({trans_type}) via {broker}"
        self._log_manual_action(log_msg)
        self.lbl_status.configure(text=f"Manually added transaction for {ticker}.", text_color="white")

        # Clear inputs for next entry, keeping Date and Broker for user convenience
        self.me_fields["Ticker"].delete(0, "end")
        self.me_fields["Units"].delete(0, "end")
        self.me_fields["Price"].delete(0, "end")
        self.me_fields["Brokerage"].delete(0, "end")

    def _on_save_ledger(self) -> None:
        if self._master_df is None or self._master_df.empty:
            return

        path = filedialog.asksaveasfilename(
            title="Save Consolidated Master Ledger",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="master_ledger.csv"
        )
        if not path:
            return

        try:
            self._master_df.to_csv(path, index=False)
            self.lbl_status.configure(text=f"Saved master ledger to: {path}", text_color=COLOR_GREEN)
            
            dir_path = os.path.dirname(path)
            if self._holdings_df is not None and not self._holdings_df.empty:
                self._holdings_df.to_csv(os.path.join(dir_path, "holdings_summary.csv"), index=False)
            if self._cgt_df is not None and not self._cgt_df.empty:
                self._cgt_df.to_csv(os.path.join(dir_path, "cgt_report.csv"), index=False)
        except Exception as exc:
            self._show_error(f"Failed to save output files: {exc}")

if __name__ == "__main__":
    App().mainloop()
