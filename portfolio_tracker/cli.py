"""
Portfolio Consolidation CLI Pipeline
====================================
Consolidates Australian broker trading CSV files into a master ledger, and
optionally generates holdings summaries and capital gains tax (CGT) reports.
Supports interactive column mapping for unrecognized files.
"""

import argparse
import os
import sys
import pandas as pd

from portfolio_tracker.core.consolidator import (
    discover_csv_files,
    load_existing_master,
    process_csv_files,
    identify_broker,
    find_header_row,
    add_broker_mapping,
    load_broker_mappings,
    DEDUP_SUBSET,
    MASTER_COLUMNS
)
from portfolio_tracker.core.tax import PortfolioTracker

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(SCRIPT_DIR, "raw_data")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "master_ledger.csv")

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Consolidate ASX broker CSVs into a master ledger. Existing output is "
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
    parser.add_argument(
        "--holdings",
        help="Optional path to output the current holdings summary CSV file.",
    )
    parser.add_argument(
        "--cgt",
        help="Optional path to output the FIFO realized capital gains tax report CSV file.",
    )

    args = parser.parse_args()

    # 1. Discover CSV files
    csv_files = discover_csv_files(input_paths=args.csv_files, input_dir=args.input_dir)
    if not csv_files and not os.path.exists(args.output):
        print(f"[ERROR] No CSV files discovered and no existing ledger at: {args.output}")
        sys.exit(1)

    # 2. Inspect and resolve mappings for unrecognized files
    custom_mappings = {}
    broker_mappings = load_broker_mappings()
    files_to_process = []

    for filepath in csv_files:
        mapping_found = False
        try:
            skip = find_header_row(filepath, broker_mappings)
            df_temp = pd.read_csv(filepath, skiprows=skip, nrows=2, encoding="utf-8-sig", on_bad_lines="skip")
            result = identify_broker(df_temp.columns.tolist(), broker_mappings)
            if result is not None:
                mapping_found = True
        except Exception:
            pass

        if not mapping_found:
            if sys.stdin.isatty():
                # Read CSV headers using custom skip heuristic
                headers = []
                try:
                    with open(filepath, "r", encoding="utf-8-sig") as f:
                        for line in f:
                            fields = [h.strip().strip('"') for h in line.split(",") if h.strip()]
                            if len(fields) >= 4:
                                headers = fields
                                break
                except Exception:
                    pass

                if not headers:
                    print(f"[WARN] Skipped (could not parse headers): {os.path.basename(filepath)}")
                    continue

                print(f"\n[MAP REQUIRED] Unrecognized CSV headers in: {os.path.basename(filepath)}")
                print("Available columns:")
                for idx, h in enumerate(headers):
                    print(f"  {idx}: {h}")

                print("\nPlease enter the column index (number) for each required field:")
                col_map = {}
                fields_to_map = ["Date", "Ticker", "Type", "Units", "Price", "Brokerage"]
                
                broker_name = input("Enter Broker ID / Name (e.g. PEARLER): ").strip().upper()
                if not broker_name:
                    broker_name = "UNKNOWN"

                for field in fields_to_map:
                    prompt = f"  Index for '{field}'"
                    if field == "Brokerage":
                        prompt += " (Press Enter to skip)"
                    prompt += ": "

                    while True:
                        val = input(prompt).strip()
                        if not val and field == "Brokerage":
                            break
                        try:
                            val_idx = int(val)
                            if 0 <= val_idx < len(headers):
                                col_map[headers[val_idx]] = field
                                break
                            else:
                                print(f"  Invalid index. Must be between 0 and {len(headers)-1}.")
                        except ValueError:
                            print("  Please enter a valid number.")

                custom_mappings[filepath] = {
                    "broker_id": broker_name,
                    "columns": col_map
                }
                files_to_process.append(filepath)

                # Ask to save mapping
                save = input("Save this mapping for future auto-detection? (y/n): ").strip().lower()
                if save in {"y", "yes"}:
                    broker_key = broker_name.lower().replace(" ", "_")
                    add_broker_mapping(broker_key, broker_name, col_map)
                    print(f"[OK] Saved mapping under key '{broker_key}'.")
            else:
                print(f"[WARN] Skipped unrecognized file (non-interactive): {os.path.basename(filepath)}")
                continue
        else:
            files_to_process.append(filepath)

    # 3. Process files
    new_master = pd.DataFrame(columns=MASTER_COLUMNS)
    raw_count = 0
    dupes_dropped = 0
    warnings = []

    if files_to_process:
        new_master, raw_count, dupes_dropped, warnings = process_csv_files(
            files_to_process,
            custom_mappings=custom_mappings
        )
        for w in warnings:
            print(f"[WARN] {w}")

    # 4. Load existing master ledger
    existing_master = pd.DataFrame(columns=MASTER_COLUMNS)
    existing_rows = 0
    if os.path.exists(args.output):
        try:
            existing_master = load_existing_master(args.output)
            existing_rows = len(existing_master)
            print(f"[OK] Loaded existing output rows: {existing_rows}")
        except Exception as exc:
            print(f"[ERROR] Failed to load existing output {args.output}: {exc}")
            sys.exit(1)

    # 5. Concatenate and Deduplicate
    frames = []
    if not existing_master.empty:
        frames.append(existing_master)
    if not new_master.empty:
        frames.append(new_master)

    if not frames:
        print("[OK] No transactions to write.")
        sys.exit(0)

    final_master = pd.concat(frames, ignore_index=True)
    total_raw = len(final_master)

    # Deduplicate on composite key
    final_master = final_master.drop_duplicates(subset=DEDUP_SUBSET, keep="first")
    final_dupes_dropped = total_raw - len(final_master)

    final_master = final_master.sort_values("Date").reset_index(drop=True)
    final_master = final_master[MASTER_COLUMNS]

    # 6. Write Consolidated master ledger
    try:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        final_master.to_csv(args.output, index=False)
    except Exception as exc:
        print(f"[ERROR] Failed to write master ledger to {args.output}: {exc}")
        sys.exit(1)

    # 7. Run Tax Calculations
    tracker = PortfolioTracker(final_master)
    holdings_df = tracker.get_holdings_summary()
    cgt_df = tracker.get_cgt_report()

    # 8. Write Holdings and CGT Reports if requested
    if args.holdings:
        try:
            os.makedirs(os.path.dirname(args.holdings), exist_ok=True)
            holdings_df.to_csv(args.holdings, index=False)
            print(f"[OK] Exported holdings summary to: {args.holdings}")
        except Exception as exc:
            print(f"[ERROR] Failed to write holdings summary to {args.holdings}: {exc}")

    if args.cgt:
        try:
            os.makedirs(os.path.dirname(args.cgt), exist_ok=True)
            cgt_df.to_csv(args.cgt, index=False)
            print(f"[OK] Exported CGT report to: {args.cgt}")
        except Exception as exc:
            print(f"[ERROR] Failed to write CGT report to {args.cgt}: {exc}")

    # 9. Print Summary
    print("\n--- Pipeline Summary ---")
    print(f"  Existing rows loaded:   {existing_rows}")
    print(f"  New raw rows ingested:  {raw_count}")
    print(f"  New duplicates dropped: {dupes_dropped}")
    print(f"  Total duplicates clean: {final_dupes_dropped}")
    print(f"  Final rows written:     {len(final_master)}")
    print(f"  Ledger Output:          {args.output}")
    
    print("\n--- Portfolio Summary ---")
    if not holdings_df.empty:
        print(f"  Active Holdings:        {len(holdings_df)}")
        total_invested = holdings_df["Total_Cost"].sum()
        print(f"  Total Value (Cost):     ${total_invested:,.2f}")
    else:
        print("  Active Holdings:        None")

    if not cgt_df.empty:
        total_gain = cgt_df["Capital_Gain"].sum()
        total_disc_gain = cgt_df["Discounted_Gain"].sum()
        print(f"  Realized Capital Gain:  ${total_gain:,.2f} (${total_disc_gain:,.2f} discounted)")
    else:
        print("  Realized Capital Gain:  $0.00")

if __name__ == "__main__":
    main()
