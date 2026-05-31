# investmentstracker

Local Python pipeline that consolidates historical ASX share trading CSVs from multiple brokers into a single master ledger for tax tracking and Google Sheets import.

## Project Structure

```
portfolio_tracker/
  raw_data/          # Drop broker CSV exports here
  output/            # Generated master_ledger.csv
  consolidate.py     # Pipeline script
  requirements.txt
```

## Quick Start

```bash
cd portfolio_tracker
pip install -r requirements.txt
```

1. Export trade history CSVs from your brokers (CMC, CommSec, Betashares, etc.).
2. Drop them into `portfolio_tracker/raw_data/`. The filename **must** contain the broker key (e.g. `cmc_trades_2024.csv`, `commsec_export.csv`, `betashares_history.csv`).
3. Run the pipeline:

```bash
python consolidate.py
```

The master ledger is written to `portfolio_tracker/output/master_ledger.csv`.

## Supported Brokers

| Broker Key | Expected CSV Columns |
|---|---|
| `cmc` | Trade Date, Stock, Transaction, Quantity, Price, Brokerage |
| `commsec` | Date, Code, Details, Units, Average Price, Brokerage (inc GST) |
| `betashares` | Date, Ticker, Type, Units, Price, Brokerage |

To add a new broker, add an entry to the `BROKER_MAPPINGS` dictionary in `consolidate.py`.

## Master Schema

| Column | Format |
|---|---|
| Date | `YYYY-MM-DD` |
| Ticker | `ASX:<CODE>` (`.AX` suffix stripped) |
| Type | Title case (`Buy`) |
| Units | Float |
| Price | Float |
| Brokerage | Float (defaults to 0) |
| Broker | Uppercase identifier |
| Total_Cost | `(Units × Price) + Brokerage` |