"""
Unit Tests for Portfolio Consolidator & Tax Tracker
"""

import os
import pandas as pd
from datetime import datetime
from portfolio_tracker.core.consolidator import (
    clean_numeric,
    standardise_ticker,
    standardise_transaction_type,
    identify_broker,
    load_broker_mappings,
    add_broker_mapping
)
from portfolio_tracker.core.tax import PortfolioTracker

def test_clean_numeric():
    assert clean_numeric(pd.Series(["$1,234.56"])).iloc[0] == 1234.56
    assert clean_numeric(pd.Series(["1,000"])).iloc[0] == 1000.0
    assert clean_numeric(pd.Series(["$0.00"])).iloc[0] == 0.0
    assert clean_numeric(pd.Series(["nan", ""])).iloc[0] == 0.0
    assert clean_numeric(pd.Series(["nan", ""])).iloc[1] == 0.0

def test_standardise_ticker():
    assert standardise_ticker("CBA.AX") == "ASX:CBA"
    assert standardise_ticker("ASX:CBA") == "ASX:CBA"
    assert standardise_ticker("cba") == "ASX:CBA"
    assert standardise_ticker("  vas.ax  ") == "ASX:VAS"

def test_standardise_transaction_type():
    assert standardise_transaction_type("Buy") == "Buy"
    assert standardise_transaction_type("Drp") == "Buy"
    assert standardise_transaction_type("Dividend Reinvestment Plan") == "Buy"
    assert standardise_transaction_type("Sell") == "Sell"
    assert standardise_transaction_type("Sale") == "Sell"
    assert standardise_transaction_type("unknown") is None

def test_identify_broker():
    broker_mappings = load_broker_mappings()
    
    # CMC columns
    cmc_cols = ["Trade Date", "Stock", "Transaction", "Quantity", "Price", "Brokerage", "Extra Col"]
    key, mapping = identify_broker(cmc_cols, broker_mappings)
    assert key == "cmc"
    assert mapping["broker_id"] == "CMC"

    # CommSec columns
    commsec_cols = ["Date", "Code", "Type", "Quantity", "Unit Price ($)", "Brokerage+GST ($)"]
    key, mapping = identify_broker(commsec_cols, broker_mappings)
    assert key == "commsec"
    assert mapping["broker_id"] == "COMMSEC"

    # Betashares columns
    beta_cols = ["Date", "Ticker", "Type", "Units", "Price", "Brokerage"]
    key, mapping = identify_broker(beta_cols, broker_mappings)
    assert key == "betashares"
    assert mapping["broker_id"] == "BETASHARES"

    # Unknown
    assert identify_broker(["A", "B", "C"], broker_mappings) is None

def test_fifo_tax_tracker():
    # Setup a mock ledger
    ledger_data = [
        # Buy 100 CBA on 2024-01-01
        {
            "Date": "2024-01-01",
            "Ticker": "ASX:CBA",
            "Type": "Buy",
            "Units": 100.0,
            "Price": 100.0,
            "Brokerage": 10.0,
            "Broker": "CMC",
            "Total_Cost": 10010.0
        },
        # Buy 50 CBA on 2024-02-01
        {
            "Date": "2024-02-01",
            "Ticker": "ASX:CBA",
            "Type": "Buy",
            "Units": 50.0,
            "Price": 105.0,
            "Brokerage": 10.0,
            "Broker": "CMC",
            "Total_Cost": 5260.0
        },
        # Sell 120 CBA on 2025-01-10 (eligibility test: held oldest 100 units > 12 months, newest 20 units < 12 months)
        {
            "Date": "2025-01-10",
            "Ticker": "ASX:CBA",
            "Type": "Sell",
            "Units": 120.0,
            "Price": 120.0,
            "Brokerage": 15.0,
            "Broker": "CMC",
            "Total_Cost": 14385.0  # 120 * 120 - 15
        }
    ]
    df = pd.DataFrame(ledger_data)
    
    tracker = PortfolioTracker(df)
    
    # Check holdings summary
    holdings = tracker.get_holdings_summary()
    assert len(holdings) == 1
    assert holdings.iloc[0]["Ticker"] == "ASX:CBA"
    assert holdings.iloc[0]["Units"] == 30.0 # 150 - 120
    # Remaining units should be from the second buy parcel (30 units remaining of 50)
    # Total cost of second parcel was 5260. Proportional cost for 30 units: 5260 * (30/50) = 3156
    assert holdings.iloc[0]["Total_Cost"] == 3156.0
    assert holdings.iloc[0]["Average_Price"] == 105.20 # 5260 / 50 = 105.20 (inc. brokerage)

    # Check CGT report
    cgt = tracker.get_cgt_report()
    assert len(cgt) == 2 # 1 sell split into 2 parcels (100 from first, 20 from second)
    
    # Parcel 1: 100 units (Buy 2024-01-01, Sell 2025-01-10) -> held > 12 months, discount eligible
    p1 = cgt.iloc[0]
    assert p1["Units"] == 100.0
    assert p1["Cost_Base"] == 10010.0
    # Proceeds: (100/120) * (120 * 120 - 15) = (5/6) * 14385 = 11987.50
    assert p1["Proceeds"] == 11987.50
    assert p1["Capital_Gain"] == 1977.50
    assert p1["Discount_Eligible"] == "Yes"
    assert p1["Discounted_Gain"] == 988.75

    # Parcel 2: 20 units (Buy 2024-02-01, Sell 2025-01-10) -> held < 12 months, not eligible
    p2 = cgt.iloc[1]
    assert p2["Units"] == 20.0
    # Cost base: (20/50) * 5260 = 2104.0
    assert p2["Cost_Base"] == 2104.0
    # Proceeds: (20/120) * 14385 = 2397.50
    assert p2["Proceeds"] == 2397.50
    assert p2["Capital_Gain"] == 293.50
    assert p2["Discount_Eligible"] == "No"
    assert p2["Discounted_Gain"] == 293.50

def test_add_broker_mapping():
    original = load_broker_mappings()
    test_cols = {"Col1": "Date", "Col2": "Ticker"}
    try:
        add_broker_mapping("test_temp", "TEST_TEMP", test_cols)
        updated = load_broker_mappings()
        assert "test_temp" in updated
        assert updated["test_temp"]["broker_id"] == "TEST_TEMP"
        assert updated["test_temp"]["columns"] == test_cols
    finally:
        # Restore original configuration
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config",
            "brokers.json"
        )
        import json
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(original, f, indent=2)

def test_process_csv_with_custom_mapping():
    import tempfile
    import os
    from portfolio_tracker.core.consolidator import process_csv_files
    
    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("When,StockCode,Action,Qty,PriceEach\n")
            f.write("01/06/2026,CBA.AX,Buy,10.5,100.0\n")
        
        custom_mapping = {
            path: {
                "broker_id": "CUSTOM_MOCK",
                "columns": {
                    "When": "Date",
                    "StockCode": "Ticker",
                    "Action": "Type",
                    "Qty": "Units",
                    "PriceEach": "Price"
                }
            }
        }
        
        master, raw, dupes, warnings = process_csv_files([path], custom_mappings=custom_mapping)
        assert len(master) == 1
        assert master.iloc[0]["Ticker"] == "ASX:CBA"
        assert master.iloc[0]["Broker"] == "CUSTOM_MOCK"
        assert master.iloc[0]["Units"] == 10.5
        assert master.iloc[0]["Price"] == 100.0
    finally:
        if os.path.exists(path):
            os.remove(path)

def test_fifo_tax_tracker_indexation():
    # Setup mock ledger containing a sale after 1 July 2027
    ledger_data = [
        # Buy 100 VAS on 2024-01-15 (2024-Q1 CPI: 137.4)
        {
            "Date": "2024-01-15",
            "Ticker": "ASX:VAS",
            "Type": "Buy",
            "Units": 100.0,
            "Price": 10.0,
            "Brokerage": 10.0,
            "Broker": "CMC",
            "Total_Cost": 1010.0
        },
        # Sell 100 VAS on 2027-10-10 (2027-Q4 CPI: 155.2) -> Indexation reforms active!
        {
            "Date": "2027-10-10",
            "Ticker": "ASX:VAS",
            "Type": "Sell",
            "Units": 100.0,
            "Price": 15.0,
            "Brokerage": 15.0,
            "Broker": "CMC",
            "Total_Cost": 1485.0 # 100 * 15 - 15
        }
    ]
    df = pd.DataFrame(ledger_data)
    tracker = PortfolioTracker(df)
    
    # Check cgt report
    cgt = tracker.get_cgt_report()
    assert len(cgt) == 1
    
    p = cgt.iloc[0]
    assert p["Units"] == 100.0
    assert p["Cost_Base"] == 1010.0
    # CPI ratio: 155.2 / 137.4 = 1.129548... -> rounded to 4 decimals = 1.1295
    assert p["Index_Factor"] == 1.1295
    # Indexed Cost Base: 1010.0 * 1.1295 = 1140.79499... -> rounded to 2 decimals = 1140.79 due to float precision
    assert p["Indexed_Cost_Base"] == 1140.79
    # Proceeds: 1485.00
    assert p["Proceeds"] == 1485.00
    # Gain: 1485.00 - 1140.79 = 344.21
    assert p["Capital_Gain"] == 344.21
    assert p["Discount_Eligible"] == "No" # Disabled post 1 July 2027
    assert p["Discounted_Gain"] == 344.21 # No discount applied

if __name__ == "__main__":
    test_clean_numeric()
    test_standardise_ticker()
    test_standardise_transaction_type()
    test_identify_broker()
    test_fifo_tax_tracker()
    test_add_broker_mapping()
    test_process_csv_with_custom_mapping()
    test_fifo_tax_tracker_indexation()
    print("All tests passed successfully!")



