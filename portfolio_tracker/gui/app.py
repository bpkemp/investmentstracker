"""
Portfolio Tracker - Desktop GUI
===============================
Manages a master ledger of stock transactions via manual entry,
computes current holdings, and displays realized FIFO capital gains
with 50% CGT discount status.
"""

from __future__ import annotations

import os
from tkinter import filedialog, messagebox
import customtkinter as ctk
import pandas as pd

from portfolio_tracker.core.utils import standardise_ticker
from portfolio_tracker.core.consolidator import (
    load_existing_master,
    import_raw_csv,
    DEDUP_SUBSET,
    MASTER_COLUMNS
)
from portfolio_tracker.core.tax import PortfolioTracker
from portfolio_tracker.gui.constants import (
    COLOR_TEAL, COLOR_TEAL_HOVER, COLOR_GREEN, 
    COLOR_GREEN_HOVER, COLOR_BG_DARK, COLOR_CARD_DARK
)
from portfolio_tracker.gui.state import AppState
from portfolio_tracker.gui.tabs.manual_entry import build_manual_entry_tab


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("ASX Portfolio Consolidator & Tax Tracker")
        self.geometry("1080x700")
        self.minsize(900, 550)

        # State Variables
        self.app_state = AppState()
        self._build_ui()

    @property
    def _master_df(self): return self.app_state.master_df
    @_master_df.setter
    def _master_df(self, val): self.app_state.master_df = val

    @property
    def _holdings_df(self): return self.app_state.holdings_df
    @_holdings_df.setter
    def _holdings_df(self, val): self.app_state.holdings_df = val

    @property
    def _cgt_df(self): return self.app_state.cgt_df
    @_cgt_df.setter
    def _cgt_df(self, val): self.app_state.cgt_df = val
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
        left_panel.grid_rowconfigure(7, weight=1) # Spacer row

        # Title
        lbl_title = ctk.CTkLabel(
            left_panel,
            text="Portfolio Tracker",
            font=ctk.CTkFont(size=20, weight="bold", family="Helvetica"),
            anchor="w"
        )
        lbl_title.grid(row=0, column=0, padx=20, pady=(20, 2), sticky="ew")

        lbl_subtitle = ctk.CTkLabel(
            left_panel,
            text="ASX Ledger & CGT Tool",
            font=ctk.CTkFont(size=12, slant="italic"),
            text_color="gray",
            anchor="w"
        )
        lbl_subtitle.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")

        # Section: Load Ledger
        btn_load = ctk.CTkButton(
            left_panel,
            text="Load Existing Ledger",
            command=self._on_load_ledger,
            fg_color=COLOR_TEAL,
            hover_color=COLOR_TEAL_HOVER,
            font=ctk.CTkFont(weight="bold")
        )
        btn_load.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.lbl_ledger_status = ctk.CTkLabel(
            left_panel,
            text="No ledger loaded.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w"
        )
        self.lbl_ledger_status.grid(row=3, column=0, padx=20, pady=(0, 15), sticky="ew")

        # Section: Import Raw CSV
        btn_import = ctk.CTkButton(
            left_panel,
            text="Import Raw CSV",
            command=self._on_import_csv,
            fg_color=COLOR_TEAL,
            hover_color=COLOR_TEAL_HOVER,
            font=ctk.CTkFont(weight="bold")
        )
        btn_import.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

        self.lbl_import_status = ctk.CTkLabel(
            left_panel,
            text="Import a Sharesight trade history CSV.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w"
        )
        self.lbl_import_status.grid(row=5, column=0, padx=20, pady=(0, 15), sticky="ew")

        # Section: Recalculate
        self.btn_recalc = ctk.CTkButton(
            left_panel,
            text="Recalculate Holdings & CGT",
            command=self._on_recalculate,
            state="disabled",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36
        )
        self.btn_recalc.grid(row=6, column=0, padx=20, pady=10, sticky="ew")

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
        self.btn_save.grid(row=8, column=0, padx=20, pady=(10, 20), sticky="ew")

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
        build_manual_entry_tab(self)

        # Status Bar
        self.lbl_status = ctk.CTkLabel(
            right_panel,
            text="Ready. Load an existing ledger or add manual trades.",
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self.lbl_status.grid(row=2, column=0, padx=10, pady=(0, 5), sticky="ew")



    # ----- Callbacks & Event Handlers ----------------------------------------
    def _on_load_ledger(self) -> None:
        """Load an existing master ledger CSV file."""
        path = filedialog.askopenfilename(
            title="Select Master Ledger CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            self._master_df = load_existing_master(path)
        except Exception as exc:
            self._show_error(f"Failed to load ledger: {exc}")
            return

        if self._master_df.empty:
            self.lbl_ledger_status.configure(text=f"Loaded (empty): {os.path.basename(path)}", text_color="yellow")
            self.lbl_status.configure(text="Ledger loaded but contains no transactions.", text_color="yellow")
        else:
            self.lbl_ledger_status.configure(text=f"{os.path.basename(path)} ({len(self._master_df)} rows)", text_color="white")
            self.lbl_status.configure(text=f"Loaded {len(self._master_df)} transactions from {os.path.basename(path)}.", text_color="white")

        # Recalculate
        self._recalculate_and_refresh()
        self.btn_save.configure(state="normal")
        self.btn_recalc.configure(state="normal")

    def _on_import_csv(self) -> None:
        """Import a raw trade history CSV (Sharesight format) into the ledger."""
        path = filedialog.askopenfilename(
            title="Select Raw Trade History CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        imported_df, row_count, warnings = import_raw_csv(path)

        if row_count == 0:
            warn_text = "; ".join(warnings) if warnings else "No transactions found."
            self.lbl_import_status.configure(text=f"Import failed: {warn_text}", text_color="red")
            self._show_error(f"Import failed: {warn_text}")
            return

        # Merge with existing in-memory ledger if present
        if self._master_df is not None and not self._master_df.empty:
            self._master_df = pd.concat([self._master_df, imported_df], ignore_index=True)
            self._master_df = self._master_df.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
            self._master_df = self._master_df.sort_values("Date").reset_index(drop=True)
            self._master_df = self._master_df[MASTER_COLUMNS]
        else:
            self._master_df = imported_df

        # Update status
        warn_suffix = f" ({len(warnings)} warnings)" if warnings else ""
        self.lbl_import_status.configure(
            text=f"Imported {row_count} rows from {os.path.basename(path)}{warn_suffix}",
            text_color="white"
        )
        self.lbl_status.configure(
            text=f"Imported {row_count} transactions. Total ledger: {len(self._master_df)} rows.",
            text_color="white"
        )

        # Show warnings if any
        for w in warnings:
            self._log_manual_action(f"[IMPORT] {w}")

        self._recalculate_and_refresh()
        self.btn_save.configure(state="normal")
        self.btn_recalc.configure(state="normal")

    def _on_recalculate(self) -> None:
        """Recalculate holdings and CGT from the current in-memory ledger."""
        if self._master_df is None or self._master_df.empty:
            self._show_error("No ledger data to recalculate.")
            return
        self._recalculate_and_refresh()
        self.lbl_status.configure(text="Recalculation complete.", text_color="white")

    def _recalculate_and_refresh(self) -> None:
        """Run tax calculations and update all display views."""
        if self._master_df is not None and not self._master_df.empty:
            tracker = PortfolioTracker(self._master_df)
            self._holdings_df = tracker.get_holdings_summary()
            self._cgt_df = tracker.get_cgt_report()
        else:
            self._holdings_df = None
            self._cgt_df = None
        self._refresh_tab_views()

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

    def _show_error(self, message: str) -> None:
        self.lbl_status.configure(text=f"Error: {message}", text_color="red")

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
        self._recalculate_and_refresh()
        self.btn_save.configure(state="normal")
        self.btn_recalc.configure(state="normal")

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
