"""
Core Portfolio Consolidator Logic
=================================
Handles reading, cleaning, auto-detecting, and merging ASX broker CSV exports.
Supports broker-agnostic custom column mapping.
"""

import json
import os
import sys
import glob
import pandas as pd

def get_config_path(filename: str) -> str:
    """Get absolute path to config file, works for dev and for PyInstaller"""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, "config", filename)

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

# Standardized transaction types
BUY_TYPES = {"BUY", "DRP", "DIVIDEND REINVESTMENT", "REINVESTMENT", "DIVIDEND REINVESTMENT PLAN", "PURCHASE"}
SELL_TYPES = {"SELL", "SALE", "DISPOSAL", "DISPOSE", "CANCELLATION"}

def load_broker_mappings() -> dict:
    """Load broker configurations from brokers.json config file."""
    config_path = get_config_path("brokers.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def add_broker_mapping(broker_key: str, broker_id: str, columns: dict) -> None:
    """Save a new broker configuration mapping back to brokers.json."""
    config_path = get_config_path("brokers.json")
    data = load_broker_mappings()
    data[broker_key] = {
        "broker_id": broker_id,
        "columns": columns
    }
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def find_header_row(filepath: str, broker_mappings: dict, custom_columns: list[str] = None) -> int:
    """Scan the file to find the row number containing valid CSV column headers.
    Returns 0 if the first row is the header (or no clear header is found)."""
    known_columns = set()
    for mapping in broker_mappings.values():
        known_columns.update(mapping["columns"].keys())
    if custom_columns:
        known_columns.update(custom_columns)

    with open(filepath, "r", encoding="utf-8-sig") as fh:
        for idx, line in enumerate(fh):
            # Split by comma but be mindful of quotes
            fields = [f.strip().strip('"') for f in line.split(",")]
            if sum(1 for f in fields if f in known_columns) >= 3:
                return idx
    return 0

def read_csv_auto(filepath: str, broker_mappings: dict, custom_columns: list[str] = None) -> pd.DataFrame:
    """Read a CSV, automatically skipping metadata rows before the header."""
    skip = find_header_row(filepath, broker_mappings, custom_columns)
    return pd.read_csv(
        filepath, skiprows=skip, encoding="utf-8-sig", on_bad_lines="skip"
    )

def identify_broker(columns: list[str], broker_mappings: dict) -> tuple[str, dict] | None:
    """Return (broker_key, mapping_dict) if a known broker's expected columns
    are all present in the CSV header, otherwise None."""
    col_set = set(columns)
    for key, mapping in broker_mappings.items():
        expected = set(mapping["columns"].keys())
        if expected.issubset(col_set):
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

def standardise_transaction_type(trans_type: str) -> str | None:
    """Normalise transaction type to 'Buy' or 'Sell'. Returns None if unsupported."""
    val = str(trans_type).strip().upper()
    if val in BUY_TYPES:
        return "Buy"
    if val in SELL_TYPES:
        return "Sell"
    return None

def discover_csv_files(input_paths: list[str], input_dir: str = None) -> list[str]:
    """Return ordered CSV file paths from explicit args, otherwise from input_dir."""
    discovered = []

    if input_paths:
        for path in input_paths:
            if os.path.isdir(path):
                discovered.extend(glob.glob(os.path.join(path, "*.csv")))
                continue
            if path.lower().endswith(".csv") and os.path.isfile(path):
                discovered.append(path)
    elif input_dir and os.path.isdir(input_dir):
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
    existing["Date"] = pd.to_datetime(existing["Date"], dayfirst=True, format="mixed")
    existing["Date"] = existing["Date"].dt.strftime("%Y-%m-%d")
    existing["Broker"] = existing["Broker"].astype(str).str.strip().str.upper()
    
    # Map Type cleanly
    existing["Type"] = existing["Type"].apply(lambda t: standardise_transaction_type(t) or "Buy")
    return existing

def process_csv_files(
    filepaths: list[str],
    custom_mappings: dict[str, dict] = None
) -> tuple[pd.DataFrame, int, int, list[str]]:
    """Process files and return (consolidated_df, raw_count, dupes_dropped, warnings).
    
    custom_mappings dictionary: {filepath: {"broker_id": broker_id, "columns": col_map}}
    """
    broker_mappings = load_broker_mappings()
    frames = []
    warnings = []

    for filepath in filepaths:
        col_map = None
        broker_id = None
        custom_cols = None

        if custom_mappings and filepath in custom_mappings:
            custom_entry = custom_mappings[filepath]
            broker_id = custom_entry["broker_id"]
            col_map = custom_entry["columns"]
            custom_cols = list(col_map.keys())

        # 1. Read file
        try:
            df = read_csv_auto(filepath, broker_mappings, custom_cols)
        except Exception as exc:
            warnings.append(f"Read error - {os.path.basename(filepath)}: {exc}")
            continue

        # 2. Identify column mappings if not custom
        if col_map is None:
            result = identify_broker(df.columns.tolist(), broker_mappings)
            if result is None:
                warnings.append(f"Skipped (unknown broker): {os.path.basename(filepath)}")
                continue
            broker_key, mapping = result
            broker_id = mapping["broker_id"]
            col_map = mapping["columns"]

        # Rename to master schema
        df = df.rename(columns=col_map)
        
        # Check if all mapped columns exist in df
        missing_cols = [c for c in col_map.values() if c not in df.columns]
        if missing_cols:
            warnings.append(f"Missing expected columns {missing_cols} in {os.path.basename(filepath)}")
            continue
            
        df = df[list(col_map.values())].copy()

        # Ensure Brokerage column exists if omitted in mapping
        if "Brokerage" not in df.columns:
            df["Brokerage"] = 0.0

        # Standardise and filter Type
        df["Type"] = df["Type"].apply(standardise_transaction_type)
        # Drop rows with unsupported transaction types
        df = df.dropna(subset=["Type"])

        if df.empty:
            continue

        # Clean numerics
        for col in ("Units", "Price", "Brokerage"):
            if col in df.columns:
                df[col] = clean_numeric(df[col])

        df["Brokerage"] = df["Brokerage"].fillna(0.0)
        df["Ticker"] = df["Ticker"].apply(standardise_ticker)

        # Parse date
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed")
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        # Add broker identifier
        df["Broker"] = broker_id

        # Calculate total cost or net proceeds
        df["Total_Cost"] = 0.0
        buys_mask = df["Type"] == "Buy"
        sells_mask = df["Type"] == "Sell"
        df.loc[buys_mask, "Total_Cost"] = (df.loc[buys_mask, "Units"] * df.loc[buys_mask, "Price"]) + df.loc[buys_mask, "Brokerage"]
        df.loc[sells_mask, "Total_Cost"] = (df.loc[sells_mask, "Units"] * df.loc[sells_mask, "Price"]) - df.loc[sells_mask, "Brokerage"]

        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=MASTER_COLUMNS), 0, 0, warnings

    master = pd.concat(frames, ignore_index=True)
    raw_count = len(master)

    # Deduplicate on composite key including Price, Type, and Broker
    master = master.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
    dupes_dropped = raw_count - len(master)

    master = master.sort_values("Date").reset_index(drop=True)
    master = master[MASTER_COLUMNS]

    return master, raw_count, dupes_dropped, warnings
