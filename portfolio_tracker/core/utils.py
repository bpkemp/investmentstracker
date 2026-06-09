"""
Common Utilities
================
Shared functions for parsing, data cleaning, and path management.
"""

import os
import sys
import pandas as pd

def get_config_path(filename: str) -> str:
    """Get absolute path to config file, works for dev and for PyInstaller"""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        # Utilities is in portfolio_tracker/core/, so two levels up is portfolio_tracker/
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, "config", filename)


# Standardized transaction types
BUY_TYPES = {"BUY", "DRP", "DIVIDEND REINVESTMENT", "REINVESTMENT", "DIVIDEND REINVESTMENT PLAN", "PURCHASE"}
SELL_TYPES = {"SELL", "SALE", "DISPOSAL", "DISPOSE", "CANCELLATION"}

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
