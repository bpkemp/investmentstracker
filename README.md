# ASX Portfolio Consolidator & Tax Tracker

Consolidates historical ASX share trading CSVs from multiple Australian brokers into a single master ledger for tax tracking, current holdings cost base calculations, and capital gains tax (CGT) reporting. Available as a unified CLI command or a standalone desktop GUI.

## Project Structure

```
portfolio_tracker/
  ├── config/
  │    └── brokers.json         # Externalised broker column mappings
  ├── core/
  │    ├── consolidator.py      # Core consolidation & cleaning logic
  │    └── tax.py               # FIFO capital gains and holdings tracker
  ├── cli.py                    # CLI entry point
  ├── gui.py                    # CustomTkinter GUI entry point
  └── tests/
       └── test_consolidator.py # Unit tests
requirements.txt                # Unified requirements
setup.py                        # Package installation setup
```

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

Alternatively, you can install the package in editable mode:

```bash
pip install -e .
```

## CLI Pipeline

Run the pipeline using the python module syntax:

```bash
python -m portfolio_tracker.cli [options] [csv_files...]
```

If you installed the package via `setup.py`, you can run the console script directly:

```bash
portfolio-consolidate [options] [csv_files...]
```

### Positional Arguments
*   `csv_files`: Optional CSV files or directories. If omitted, the tool scans the default `--input-dir` (`portfolio_tracker/raw_data/`).

### Options
*   `--input-dir`: Directory scanned for CSV files when no positional files are provided.
*   `--output`: Output path for the consolidated master ledger CSV (default: `portfolio_tracker/output/master_ledger.csv`).
*   `--holdings`: Optional path to export the current holdings summary CSV (units held, average cost, total invested).
*   `--cgt`: Optional path to export the FIFO realized capital gains tax report CSV (gain calculations and 50% discount eligibility).

### Example

```bash
python -m portfolio_tracker.cli C:\exports\cmc.csv C:\exports\commsec_folder --output output/ledger.csv --holdings output/holdings.csv --cgt output/cgt.csv
```

---

## Desktop GUI

Run the GUI tool:

```bash
python -m portfolio_tracker.gui
```

Or run the script if installed:

```bash
portfolio-consolidate-gui
```

### GUI Features
*   **Multi-Broker CSV picker**: Load multiple files at once.
*   **Merge with existing ledger**: Check this box to select your existing master ledger and append/deduplicate new files into it.
*   **Tabbed Dashboard**: View your consolidated ledger preview, current portfolio holdings summary, and FIFO realized CGT details instantly.
*   **Dashboard Cards**: Highlight total holdings, invested capital, and realized capital gains.
*   **Multi-file Save**: Saving the consolidated ledger will automatically export `holdings_summary.csv` and `cgt_report.csv` into the same directory.

---

## Supported Brokers

Column configurations are stored externally in [brokers.json](file:///C:/dev/investmentstracker/portfolio_tracker/config/brokers.json). The broker is auto-detected from the CSV header columns.

Default supported brokers:
*   `CMC` (expected columns: Trade Date, Stock, Transaction, Quantity, Price, Brokerage)
*   `CommSec` (expected columns: Date, Code, Type, Quantity, Unit Price ($), Brokerage+GST ($))
*   `Betashares` (expected columns: Date, Ticker, Type, Units, Price, Brokerage)

To add a new broker or modify columns, simply append an entry to [brokers.json](file:///C:/dev/investmentstracker/portfolio_tracker/config/brokers.json) without changing Python code.

---

## Tax base tracking and CGT rules

*   **Buy & Sell Support**: Full tracking of both purchase types (Buys, DRPs, reinvestments) and sales (Sells, disposals).
*   **FIFO matching**: Sells are matched against the oldest available Buy parcels.
*   **50% CGT discount**: Calculates holding periods and marks discount eligibility for the current 2026-27 FY (requires assets to be held for *more than* 12 months before disposal).

---

## Development & Testing

Run unit tests using the module syntax:

```bash
python -m portfolio_tracker.tests.test_consolidator
```