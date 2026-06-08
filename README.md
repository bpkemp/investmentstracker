# ASX Portfolio Tracker & Tax Calculator

Desktop GUI for tracking ASX share transactions via manual entry, computing current holdings cost base, and generating FIFO capital gains tax (CGT) reports with 50% discount eligibility and CPI indexation support.

## Project Structure

```
portfolio_tracker/
  ├── config/
  │    └── cpi.json              # Quarterly CPI data for indexation
  ├── core/
  │    ├── consolidator.py       # Ledger loading & data cleaning
  │    └── tax.py                # FIFO capital gains and holdings tracker
  ├── gui.py                     # CustomTkinter GUI entry point
  └── tests/
       └── test_consolidator.py  # Unit tests
requirements.txt                 # Unified requirements
setup.py                         # Package installation setup
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
*   **Load Existing Ledger**: Open a previously saved `master_ledger.csv` to resume tracking.
*   **Manual Transaction Entry**: Add Buy/Sell transactions directly with date, ticker, units, price, brokerage, and broker fields.
*   **Tabbed Dashboard**: View your ledger preview, current portfolio holdings summary, and FIFO realized CGT details instantly.
*   **Dashboard Cards**: Highlight total active holdings, invested capital, and realized capital gains.
*   **Multi-file Save**: Saving the master ledger will automatically export `holdings_summary.csv` and `cgt_report.csv` into the same directory.

---

## Tax Base Tracking and CGT Rules

*   **Buy & Sell Support**: Full tracking of both purchase types (Buys, DRPs, reinvestments) and sales (Sells, disposals).
*   **FIFO Matching**: Sells are matched against the oldest available Buy parcels.
*   **50% CGT Discount**: Calculates holding periods and marks discount eligibility for the current 2026-27 FY (requires assets to be held for *more than* 12 months before disposal).
*   **CPI Indexation**: For sales on or after 1 July 2027, cost base indexation replaces the 50% discount using quarterly CPI data.

---

## Development & Testing

Run unit tests using the module syntax:

```bash
python -m portfolio_tracker.tests.test_consolidator
```