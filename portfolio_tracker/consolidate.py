"""
Portfolio Consolidation Pipeline
Consolidates historical share trading CSVs from multiple Australian brokers
into a single master ledger for tax tracking.
"""

import glob
import os
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# Broker column mappings
# Keys must appear somewhere in the CSV filename (lowercased) for matching.
# Values map broker-specific column names -> master schema column names.
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

# Transaction types that represent an acquisition of shares.
# All of these are normalised to "Buy" in the final output so DRPs
# are included in the cost base.  Add new variations here as needed.
ACQUISITION_TYPES: set[str] = {
    "Buy",
    "Drp",
    "Dividend Reinvestment",
    "Reinvestment",
    "Dividend Reinvestment Plan",
}

# Composite key used for deduplication.  If a single broker legitimately
# executes two identical-unit purchases of the same ticker on the same day,
# add "Price" or "Brokerage" to this list to preserve both rows.
DEDUP_SUBSET: list[str] = ["Date", "Ticker", "Units", "Broker"]

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "raw_data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "master_ledger.csv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def identify_broker(filename: str) -> tuple[str, dict] | None:
    """Return (broker_key, mapping_dict) if a known broker key is found in the
    filename, otherwise None."""
    name_lower = os.path.basename(filename).lower()
    for key, mapping in BROKER_MAPPINGS.items():
        if key in name_lower:
            return key, mapping
    return None


def clean_numeric(series: pd.Series) -> pd.Series:
    """Strip currency symbols / commas and convert to float."""
    return (
        series.astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"": "0", "nan": "0"})
        .astype(float)
    )


def standardise_ticker(ticker: str) -> str:
    """Prepend 'ASX:' and strip any '.AX' suffix."""
    t = str(ticker).strip().upper()
    if t.endswith(".AX"):
        t = t[:-3]
    if not t.startswith("ASX:"):
        t = f"ASX:{t}"
    return t


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run_pipeline() -> None:
    csv_files = glob.glob(os.path.join(RAW_DATA_DIR, "*.csv"))

    if not csv_files:
        print(f"No CSV files found in {RAW_DATA_DIR}. Add broker CSVs and re-run.")
        sys.exit(1)

    frames: list[pd.DataFrame] = []
    skipped: list[str] = []

    for filepath in csv_files:
        result = identify_broker(filepath)
        if result is None:
            skipped.append(os.path.basename(filepath))
            continue

        broker_key, mapping = result
        broker_id = mapping["broker_id"]
        col_map = mapping["columns"]

        try:
            df = pd.read_csv(filepath, encoding="utf-8-sig")
        except Exception as exc:
            print(f"[WARN] Could not read {filepath}: {exc}")
            continue

        # Check that expected source columns exist
        missing_cols = [c for c in col_map if c not in df.columns]
        if missing_cols:
            print(
                f"[WARN] {os.path.basename(filepath)} is missing columns: "
                f"{missing_cols}. Skipping."
            )
            continue

        # Rename to master schema
        df = df.rename(columns=col_map)
        df = df[list(col_map.values())]

        # Standardise Type to title-case, then keep any acquisition type
        df["Type"] = df["Type"].astype(str).str.strip().str.title()
        df = df[df["Type"].isin(ACQUISITION_TYPES)].copy()

        # Normalise all acquisition types to "Buy" for a consistent cost base
        df["Type"] = "Buy"

        if df.empty:
            continue

        # Clean numerics
        for col in ("Units", "Price", "Brokerage"):
            if col in df.columns:
                df[col] = clean_numeric(df[col])

        # Default brokerage to 0 where missing
        df["Brokerage"] = df["Brokerage"].fillna(0.0)

        # Standardise ticker
        df["Ticker"] = df["Ticker"].apply(standardise_ticker)

        # Parse date
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed")
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        # Add broker identifier
        df["Broker"] = broker_id

        # Calculate total cost
        df["Total_Cost"] = (df["Units"] * df["Price"]) + df["Brokerage"]

        frames.append(df)
        print(
            f"[OK]   {os.path.basename(filepath):40s}  ->  {len(df)} buy rows  ({broker_id})"
        )

    if skipped:
        print(f"\n[SKIP] Unrecognised broker files: {skipped}")

    if not frames:
        print("No buy transactions found across all files. Nothing to export.")
        sys.exit(0)

    master = pd.concat(frames, ignore_index=True)
    total_raw = len(master)

    # Deduplicate on composite key so re-importing overlapping CSVs is safe
    master = master.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
    dupes_dropped = total_raw - len(master)

    master = master.sort_values("Date").reset_index(drop=True)

    # Final column ordering
    master = master[
        [
            "Date",
            "Ticker",
            "Type",
            "Units",
            "Price",
            "Brokerage",
            "Broker",
            "Total_Cost",
        ]
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    master.to_csv(OUTPUT_FILE, index=False)

    # Summary
    print("\n--- Pipeline Summary ---")
    print(f"  Raw rows ingested:    {total_raw}")
    print(f"  Duplicates dropped:   {dupes_dropped}")
    print(f"  Rows written:         {len(master)}")
    print(f"  Output:               {OUTPUT_FILE}")


if __name__ == "__main__":
    run_pipeline()
