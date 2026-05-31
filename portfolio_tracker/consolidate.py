"""
Portfolio Consolidation Pipeline
Consolidates historical share trading CSVs from multiple Australian brokers
into a single master ledger for tax tracking.
"""

import argparse
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


def discover_csv_files(input_paths: list[str], input_dir: str) -> list[str]:
    """Return ordered CSV file paths from explicit args, otherwise from input_dir."""
    discovered: list[str] = []

    if input_paths:
        for path in input_paths:
            if os.path.isdir(path):
                discovered.extend(glob.glob(os.path.join(path, "*.csv")))
                continue
            if path.lower().endswith(".csv") and os.path.isfile(path):
                discovered.append(path)
    else:
        discovered = glob.glob(os.path.join(input_dir, "*.csv"))

    # Keep first-seen order while removing duplicates.
    return list(dict.fromkeys(discovered))


def load_existing_master(output_file: str) -> pd.DataFrame:
    """Load existing consolidated output if present."""
    if not os.path.exists(output_file):
        return pd.DataFrame(columns=MASTER_COLUMNS)

    existing = pd.read_csv(output_file, encoding="utf-8-sig")
    for col in MASTER_COLUMNS:
        if col not in existing.columns:
            existing[col] = 0.0 if col in {"Units", "Price", "Brokerage", "Total_Cost"} else ""

    existing = existing[MASTER_COLUMNS]
    for col in ("Units", "Price", "Brokerage", "Total_Cost"):
        existing[col] = clean_numeric(existing[col])
    existing["Ticker"] = existing["Ticker"].apply(standardise_ticker)
    existing["Date"] = pd.to_datetime(existing["Date"], dayfirst=True, format="mixed")
    existing["Date"] = existing["Date"].dt.strftime("%Y-%m-%d")
    existing["Broker"] = existing["Broker"].astype(str).str.strip().str.upper()
    existing["Type"] = "Buy"
    return existing


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run_pipeline(input_paths: list[str], input_dir: str, output_file: str) -> None:
    csv_files = discover_csv_files(input_paths=input_paths, input_dir=input_dir)

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

    existing_rows = 0
    try:
        existing_master = load_existing_master(output_file)
    except Exception as exc:
        print(f"[ERROR] Failed to load existing output {output_file}: {exc}")
        sys.exit(1)

    if not existing_master.empty:
        existing_rows = len(existing_master)
        frames.append(existing_master)
        print(f"[OK]   Loaded existing output rows: {existing_rows}")

    if not frames:
        print(f"No CSV files found in {input_dir}. Add broker CSVs and re-run.")
        sys.exit(1)

    master = pd.concat(frames, ignore_index=True)
    total_raw = len(master)

    # Deduplicate on composite key so re-importing overlapping CSVs is safe
    master = master.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
    dupes_dropped = total_raw - len(master)

    master = master.sort_values("Date").reset_index(drop=True)

    # Final column ordering
    master = master[MASTER_COLUMNS]

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    master.to_csv(output_file, index=False)

    # Summary
    print("\n--- Pipeline Summary ---")
    print(f"  Existing rows loaded: {existing_rows}")
    print(f"  Raw rows ingested:    {total_raw}")
    print(f"  Duplicates dropped:   {dupes_dropped}")
    print(f"  Rows written:         {len(master)}")
    print(f"  Output:               {output_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Consolidate broker CSVs into a master ledger. Existing output is "
            "loaded first so each run builds on prior consolidated data."
        )
    )
    parser.add_argument(
        "csv_files",
        nargs="*",
        help="Optional CSV files or directories. If omitted, scans --input-dir.",
    )
    parser.add_argument(
        "--input-dir",
        default=RAW_DATA_DIR,
        help=f"Directory scanned for CSV files when no positional files are provided (default: {RAW_DATA_DIR}).",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help=f"Output CSV path (default: {OUTPUT_FILE}).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(input_paths=args.csv_files, input_dir=args.input_dir, output_file=args.output)
