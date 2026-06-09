"""
Core Portfolio Consolidator Logic
=================================
Handles reading, cleaning, and loading the master ledger CSV.
"""

import os
import pandas as pd

from portfolio_tracker.core.utils import (
    clean_numeric,
    standardise_ticker,
    standardise_transaction_type
)

# Default columns for master ledger
MASTER_COLUMNS = [
    "Date",
    "Ticker",
    "Type",
    "Units",
    "Price",
    "Brokerage",
    "Broker",
    "Total_Cost"
]

# Composite key used for deduplication.
DEDUP_SUBSET = ["Date", "Ticker", "Units", "Price", "Type", "Broker"]

def load_existing_master(output_file: str) -> pd.DataFrame:
    """Load existing consolidated output if present."""
    if not os.path.exists(output_file):
        return pd.DataFrame(columns=MASTER_COLUMNS)

    existing = pd.read_csv(output_file, encoding="utf-8-sig")
    for col in MASTER_COLUMNS:
        if col not in existing.columns:
            if col in {"Units", "Price", "Brokerage", "Total_Cost"}:
                existing[col] = 0.0
            elif col == "Type":
                existing[col] = "Buy"
            else:
                existing[col] = ""

    existing = existing[MASTER_COLUMNS]
    for col in ("Units", "Price", "Brokerage", "Total_Cost"):
        existing[col] = clean_numeric(existing[col])
    existing["Ticker"] = existing["Ticker"].apply(standardise_ticker)
    existing["Date"] = pd.to_datetime(existing["Date"], format="mixed")
    existing["Date"] = existing["Date"].dt.strftime("%Y-%m-%d")
    existing["Broker"] = existing["Broker"].astype(str).str.strip().str.upper()
    
    # Map Type cleanly
    existing["Type"] = existing["Type"].apply(lambda t: standardise_transaction_type(t) or "Buy")
    return existing


# Column mapping for Sharesight / raw trade export CSV format
RAW_CSV_COLUMNS = {
    "Code": "Ticker",
    "Date": "Date",
    "Type": "Type",
    "Qty": "Units",
    "Price": "Price",
    "Brokerage": "Brokerage",
}

def import_raw_csv(filepath: str, broker_label: str = "IMPORT") -> tuple[pd.DataFrame, int, list[str]]:
    """Import a raw trade history CSV (Sharesight export format) into master ledger format.

    Returns (DataFrame in MASTER_COLUMNS schema, row count, list of warnings).
    """
    warnings: list[str] = []

    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig", on_bad_lines="skip")
    except Exception as exc:
        return pd.DataFrame(columns=MASTER_COLUMNS), 0, [f"Read error: {exc}"]

    # Check required columns exist
    required = set(RAW_CSV_COLUMNS.keys())
    present = set(df.columns.str.strip())
    df.columns = df.columns.str.strip()

    missing = required - present
    if missing:
        return pd.DataFrame(columns=MASTER_COLUMNS), 0, [f"Missing required columns: {missing}"]

    # Rename to master schema
    df = df.rename(columns=RAW_CSV_COLUMNS)

    # Build ticker with market prefix (e.g. ASX:CBA, CRYPTO:BTC)
    if "Market Code" in df.columns:
        df["Ticker"] = df["Market Code"].astype(str).str.strip().str.upper() + ":" + df["Ticker"].astype(str).str.strip().str.upper()
    else:
        df["Ticker"] = df["Ticker"].apply(standardise_ticker)

    # Standardise and filter Type
    df["Type"] = df["Type"].apply(standardise_transaction_type)
    dropped = df["Type"].isna().sum()
    if dropped > 0:
        warnings.append(f"Skipped {dropped} rows with unsupported transaction types.")
    df = df.dropna(subset=["Type"])

    if df.empty:
        return pd.DataFrame(columns=MASTER_COLUMNS), 0, warnings

    # Clean numerics
    for col in ("Units", "Price", "Brokerage"):
        if col in df.columns:
            df[col] = clean_numeric(df[col])
    df["Brokerage"] = df["Brokerage"].fillna(0.0)

    # Normalise units: Sharesight uses negative qty for sells, but the tax
    # engine determines direction from the Type column and expects positive values.
    df["Units"] = df["Units"].abs()

    # Drop zero-unit rows (e.g. cash dividends that didn't allocate shares)
    df = df[df["Units"] > 0]

    # Parse date
    df["Date"] = pd.to_datetime(df["Date"], format="mixed")
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    # Add broker identifier
    df["Broker"] = broker_label.upper()

    # Calculate total cost or net proceeds
    df["Total_Cost"] = 0.0
    buys_mask = df["Type"] == "Buy"
    sells_mask = df["Type"] == "Sell"
    df.loc[buys_mask, "Total_Cost"] = (df.loc[buys_mask, "Units"] * df.loc[buys_mask, "Price"]) + df.loc[buys_mask, "Brokerage"]
    df.loc[sells_mask, "Total_Cost"] = (df.loc[sells_mask, "Units"] * df.loc[sells_mask, "Price"]) - df.loc[sells_mask, "Brokerage"]

    # Deduplicate and sort
    raw_count = len(df)
    df = df.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
    dupes = raw_count - len(df)
    if dupes > 0:
        warnings.append(f"Removed {dupes} duplicate rows.")

    df = df.sort_values("Date").reset_index(drop=True)
    df = df[MASTER_COLUMNS]

    return df, len(df), warnings
