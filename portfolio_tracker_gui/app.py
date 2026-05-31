"""
Multi-Broker Portfolio Consolidator – CustomTkinter GUI
=======================================================
Consolidates ASX broker CSV exports into a single master ledger.

# -----------------------------------------------------------------------
# PyInstaller compilation command (run from the portfolio_tracker_gui dir):
#
#   pyinstaller --onefile --noconsole --name "PortfolioConsolidator" app.py
#
# If CustomTkinter assets are not found at runtime, add them explicitly:
#
#   pyinstaller --onefile --noconsole --name "PortfolioConsolidator" \
#       --collect-data customtkinter app.py
# -----------------------------------------------------------------------
"""

from __future__ import annotations

import os
import threading
from tkinter import filedialog

import customtkinter as ctk
import pandas as pd

# ---------------------------------------------------------------------------
# Broker configuration
# ---------------------------------------------------------------------------
BROKER_MAPPINGS: dict[str, dict] = {
    "cmc": {
        "broker_id": "CMC",
        "columns": {
            "Trade Date": "Date",
            "Stock": "Ticker",
            "Transaction": "Type",
            "Quantity": "Units",
            "Price": "Price",
            "Brokerage": "Brokerage",
        },
    },
    "commsec": {
        "broker_id": "COMMSEC",
        "columns": {
            "Date": "Date",
            "Code": "Ticker",
            "Details": "Type",
            "Units": "Units",
            "Average Price": "Price",
            "Brokerage (inc GST)": "Brokerage",
        },
    },
    "betashares": {
        "broker_id": "BETASHARES",
        "columns": {
            "Date": "Date",
            "Ticker": "Ticker",
            "Type": "Type",
            "Units": "Units",
            "Price": "Price",
            "Brokerage": "Brokerage",
        },
    },
}

ACQUISITION_TYPES: set[str] = {
    "Buy",
    "Drp",
    "Dividend Reinvestment",
    "Reinvestment",
    "Dividend Reinvestment Plan",
}

# Composite key for deduplication.  If a broker legitimately executes two
# identical-unit purchases of the same ticker on the same day, add "Price"
# or "Brokerage" to this list to preserve both rows.
DEDUP_SUBSET: list[str] = ["Date", "Ticker", "Units", "Broker"]

MASTER_COLUMNS: list[str] = [
    "Date",
    "Ticker",
    "Type",
    "Units",
    "Price",
    "Brokerage",
    "Broker",
    "Total_Cost",
]


# ---------------------------------------------------------------------------
# Data-processing helpers
# ---------------------------------------------------------------------------
def _identify_broker(filename: str) -> tuple[str, dict] | None:
    name_lower = os.path.basename(filename).lower()
    for key, mapping in BROKER_MAPPINGS.items():
        if key in name_lower:
            return key, mapping
    return None


def _clean_numeric(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"": "0", "nan": "0"})
        .astype(float)
    )


def _standardise_ticker(ticker: str) -> str:
    t = str(ticker).strip().upper()
    if t.endswith(".AX"):
        t = t[:-3]
    if not t.startswith("ASX:"):
        t = f"ASX:{t}"
    return t


def consolidate(filepaths: list[str]) -> tuple[pd.DataFrame, int, int, list[str]]:
    """Run the full pipeline and return (master_df, raw_count, dupes_dropped, warnings)."""
    frames: list[pd.DataFrame] = []
    warnings: list[str] = []

    for filepath in filepaths:
        result = _identify_broker(filepath)
        if result is None:
            warnings.append(f"Skipped (unknown broker): {os.path.basename(filepath)}")
            continue

        _broker_key, mapping = result
        broker_id = mapping["broker_id"]
        col_map = mapping["columns"]

        try:
            df = pd.read_csv(filepath, encoding="utf-8-sig")
        except Exception as exc:
            warnings.append(f"Read error – {os.path.basename(filepath)}: {exc}")
            continue

        missing = [c for c in col_map if c not in df.columns]
        if missing:
            warnings.append(
                f"{os.path.basename(filepath)} missing columns {missing}. Skipped."
            )
            continue

        df = df.rename(columns=col_map)[list(col_map.values())]

        # Filter to acquisition types
        df["Type"] = df["Type"].astype(str).str.strip().str.title()
        df = df[df["Type"].isin(ACQUISITION_TYPES)].copy()
        df["Type"] = "Buy"

        if df.empty:
            continue

        for col in ("Units", "Price", "Brokerage"):
            df[col] = _clean_numeric(df[col])
        df["Brokerage"] = df["Brokerage"].fillna(0.0)

        df["Ticker"] = df["Ticker"].apply(_standardise_ticker)
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed")
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        df["Broker"] = broker_id
        df["Total_Cost"] = (df["Units"] * df["Price"]) + df["Brokerage"]

        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=MASTER_COLUMNS), 0, 0, warnings

    master = pd.concat(frames, ignore_index=True)
    raw_count = len(master)

    master = master.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
    dupes_dropped = raw_count - len(master)

    master = master.sort_values("Date").reset_index(drop=True)
    master = master[MASTER_COLUMNS]

    return master, raw_count, dupes_dropped, warnings


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Multi-Broker Portfolio Consolidator")
        self.geometry("780x560")
        self.minsize(640, 480)

        self._selected_files: list[str] = []
        self._master_df: pd.DataFrame | None = None

        self._build_ui()

    # ----- UI construction --------------------------------------------------
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Row 0 – header
        header = ctk.CTkLabel(
            self,
            text="Multi-Broker Portfolio Consolidator",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        header.grid(row=0, column=0, padx=20, pady=(20, 4), sticky="w")

        subtitle = ctk.CTkLabel(
            self,
            text="Select broker CSV files, process, then save the consolidated ledger.",
            font=ctk.CTkFont(size=13),
            text_color="gray",
        )
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

        # Row 2 – file list
        self._file_list = ctk.CTkTextbox(self, state="disabled", wrap="none")
        self._file_list.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="nsew")

        # Row 3 – buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=20, pady=(0, 6), sticky="ew")
        btn_frame.grid_columnconfigure(2, weight=1)

        self._btn_select = ctk.CTkButton(
            btn_frame,
            text="Select Broker CSV Files",
            command=self._on_select_files,
        )
        self._btn_select.grid(row=0, column=0, padx=(0, 8))

        self._btn_process = ctk.CTkButton(
            btn_frame,
            text="Process & Consolidate",
            command=self._on_process,
            state="disabled",
        )
        self._btn_process.grid(row=0, column=1, padx=(0, 8))

        self._btn_save = ctk.CTkButton(
            btn_frame,
            text="Save Consolidated File",
            command=self._on_save,
            state="disabled",
            fg_color="green",
            hover_color="#1b7a1b",
        )
        self._btn_save.grid(row=0, column=3)

        # Row 4 – status
        self._status_var = ctk.StringVar(value="No files selected.")
        self._status_label = ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=13),
            anchor="w",
        )
        self._status_label.grid(row=4, column=0, padx=20, pady=(0, 16), sticky="ew")

    # ----- Callbacks --------------------------------------------------------
    def _on_select_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select Broker CSV Files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not paths:
            return

        self._selected_files = list(paths)
        self._master_df = None

        self._file_list.configure(state="normal")
        self._file_list.delete("1.0", "end")
        for p in self._selected_files:
            self._file_list.insert("end", p + "\n")
        self._file_list.configure(state="disabled")

        self._status_var.set(f"{len(self._selected_files)} file(s) selected.")
        self._btn_process.configure(state="normal")
        self._btn_save.configure(state="disabled")

    def _on_process(self) -> None:
        self._btn_select.configure(state="disabled")
        self._btn_process.configure(state="disabled")
        self._btn_save.configure(state="disabled")
        self._status_var.set("Processing…")

        # Run pipeline off the main thread to keep the UI responsive
        threading.Thread(target=self._run_pipeline, daemon=True).start()

    def _run_pipeline(self) -> None:
        master, raw_count, dupes, warnings = consolidate(self._selected_files)
        # Schedule UI update on the main thread
        self.after(0, self._pipeline_done, master, raw_count, dupes, warnings)

    def _pipeline_done(
        self,
        master: pd.DataFrame,
        raw_count: int,
        dupes: int,
        warnings: list[str],
    ) -> None:
        self._master_df = master
        self._btn_select.configure(state="normal")
        self._btn_process.configure(state="normal")

        if master.empty:
            msg = "No buy/acquisition rows found."
            if warnings:
                msg += "  Warnings: " + "; ".join(warnings)
            self._status_var.set(msg)
            return

        self._btn_save.configure(state="normal")
        summary = (
            f"Done — Rows ingested: {raw_count}  |  "
            f"Duplicates removed: {dupes}  |  "
            f"Final rows: {len(master)}"
        )
        if warnings:
            summary += f"  |  Warnings: {len(warnings)}"
        self._status_var.set(summary)

        # Show warnings in the textbox
        if warnings:
            self._file_list.configure(state="normal")
            self._file_list.insert("end", "\n--- Warnings ---\n")
            for w in warnings:
                self._file_list.insert("end", f"  • {w}\n")
            self._file_list.configure(state="disabled")

    def _on_save(self) -> None:
        if self._master_df is None or self._master_df.empty:
            return

        path = filedialog.asksaveasfilename(
            title="Save Consolidated Ledger",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="master_ledger.csv",
        )
        if not path:
            return

        self._master_df.to_csv(path, index=False)
        self._status_var.set(f"Saved {len(self._master_df)} rows to {path}")


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    App().mainloop()
