# investmentstracker

Consolidates historical ASX share trading CSVs from multiple Australian brokers into a single master ledger for tax tracking and Google Sheets import. Available as a CLI pipeline or a standalone desktop GUI.

## Project Structure

```
portfolio_tracker/           # CLI pipeline
  raw_data/                  # Drop broker CSV exports here
  output/                    # Generated master_ledger.csv
  consolidate.py
  requirements.txt

portfolio_tracker_gui/       # Desktop GUI (CustomTkinter)
  app.py
  requirements.txt
```

## CLI Pipeline

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

Or pass CSV files/directories directly:

```bash
python consolidate.py /path/to/cmc_2024.csv /path/to/commsec_folder
```

The master ledger is written to `portfolio_tracker/output/master_ledger.csv`.
If that file already exists, it is loaded first and the new run is appended/deduplicated, so previous consolidated output is built on instead of replaced.

### Compiling CLI to EXE

```bash
cd portfolio_tracker
pyinstaller --onefile --name "PortfolioConsolidatorCLI" consolidate.py
```

Run the EXE with CSVs:

```bash
PortfolioConsolidatorCLI.exe C:\exports\cmc.csv C:\exports\commsec.csv --output C:\exports\master_ledger.csv
```

## Desktop GUI

```bash
cd portfolio_tracker_gui
pip install -r requirements.txt
python app.py
```

The GUI lets you select CSV files via a file picker, process them, and save the consolidated ledger to any location.

### Compiling to Executable

```bash
pyinstaller --onefile --noconsole --collect-data customtkinter --name "PortfolioConsolidator" app.py
```

The compiled binary will be in `dist/PortfolioConsolidator.exe`.

## Supported Brokers

| Broker Key | Expected CSV Columns |
|---|---|
| `cmc` | Trade Date, Stock, Transaction, Quantity, Price, Brokerage |
| `commsec` | Date, Code, Details, Units, Average Price, Brokerage (inc GST) |
| `betashares` | Date, Ticker, Type, Units, Price, Brokerage |

To add a new broker, add an entry to the `BROKER_MAPPINGS` dictionary in `consolidate.py` or `app.py`.

## Master Schema

| Column | Format |
|---|---|
| Date | `YYYY-MM-DD` |
| Ticker | `ASX:<CODE>` (`.AX` suffix stripped) |
| Type | `Buy` (DRPs and reinvestments normalised) |
| Units | Float |
| Price | Float |
| Brokerage | Float (defaults to 0) |
| Broker | Uppercase identifier |
| Total_Cost | `(Units × Price) + Brokerage` |

## Key Features

- **DRP Handling** — Dividend Reinvestment, DRP, and Reinvestment transactions are captured and normalised to `Buy` for accurate cost-base tracking.
- **Idempotent** — Deduplication on `[Date, Ticker, Units, Broker]` means you can re-drop overlapping CSVs without inflating the ledger.
- **Incremental output** — Existing `master_ledger.csv` is loaded first so each run extends prior consolidated history.
- **Multi-broker** — Broker is auto-detected from the filename; column mappings are applied per broker.