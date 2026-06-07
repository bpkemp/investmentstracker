"""
FIFO Portfolio Tax and Holdings Calculator
===========================================
Tracks stock parcels using First-In-First-Out (FIFO) logic to calculate:
1. Current portfolio holdings (remaining units, average price, total cost).
2. Realized capital gains (CGT events), eligibility for the 50% CGT discount (pre-July 2027),
   and CPI-based cost base indexation (on/after 1 July 2027).
"""

import os
import json
import pandas as pd
from datetime import datetime

def load_cpi_data() -> dict[str, float]:
    """Load quarterly CPI data from config/cpi.json."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "cpi.json"
    )
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_quarter_key(date: datetime) -> str:
    """Return the year and quarter string (e.g. '2024-Q2') for a given datetime."""
    year = date.year
    month = date.month
    if month in (1, 2, 3):
        q = "Q1"
    elif month in (4, 5, 6):
        q = "Q2"
    elif month in (7, 8, 9):
        q = "Q3"
    else:
        q = "Q4"
    return f"{year}-{q}"


class PortfolioTracker:
    def __init__(self, ledger_df: pd.DataFrame) -> None:
        """Initialize and process the consolidated ledger."""
        # Ensure sorting by Date to process chronologically
        self.ledger = ledger_df.copy()
        self.ledger["Date"] = pd.to_datetime(self.ledger["Date"])
        self.ledger = self.ledger.sort_values("Date").reset_index(drop=True)
        
        # Load inflation indices
        self.cpi_data = load_cpi_data()
        
        # Ticker -> list of parcels. 
        # A parcel is: {"date": Timestamp, "units": float, "price": float, "brokerage": float, "total_cost": float}
        self.holdings: dict[str, list[dict]] = {}
        
        # List of CGT events
        self.cgt_events: list[dict] = []
        
        self._process_ledger()

    def _process_ledger(self) -> None:
        """Iterate through chronological transactions and build holdings/CGT history."""
        for _, row in self.ledger.iterrows():
            ticker = row["Ticker"]
            trans_type = row["Type"]
            date = row["Date"]
            units = float(row["Units"])
            price = float(row["Price"])
            brokerage = float(row["Brokerage"])
            broker = row["Broker"]
            total_cost = float(row["Total_Cost"])

            if ticker not in self.holdings:
                self.holdings[ticker] = []

            if trans_type == "Buy":
                self.holdings[ticker].append({
                    "date": date,
                    "units": units,
                    "price": price,
                    "brokerage": brokerage,
                    "total_cost": total_cost,
                    "broker": broker
                })
            elif trans_type == "Sell":
                self._process_sell(ticker, date, units, price, brokerage, broker)

    def _process_sell(self, ticker: str, sell_date: datetime, sell_units: float, sell_price: float, sell_brokerage: float, broker: str) -> None:
        """Consume buy parcels under FIFO order and record CGT events."""
        remaining_to_sell = sell_units
        total_sell_units = sell_units

        # Reform threshold date: 1 July 2027
        is_reform_active = sell_date >= pd.Timestamp("2027-07-01")

        while remaining_to_sell > 0 and self.holdings[ticker]:
            oldest_parcel = self.holdings[ticker][0]
            buy_units = oldest_parcel["units"]
            buy_date = oldest_parcel["date"]

            # Determine how many units are matched in this iteration
            matched_units = min(remaining_to_sell, buy_units)

            # Calculate cost base of matched units (proportional total cost)
            buy_ratio = matched_units / buy_units
            matched_cost_base = oldest_parcel["total_cost"] * buy_ratio

            # Calculate sale proceeds of matched units
            sell_ratio = matched_units / total_sell_units
            matched_proceeds = (matched_units * sell_price) - (sell_brokerage * sell_ratio)

            # Holding Days calculation
            holding_days = (sell_date - buy_date).days

            # -----------------------------------------------------------------
            # CGT Rules Branching (Pre-reform vs. Post-reform)
            # -----------------------------------------------------------------
            if is_reform_active:
                # 1. Post-July 2027: Remove 50% discount, apply CPI Indexation
                is_discount_eligible = False
                discounted_gain = 0.0
                
                # Fetch quarterly CPI values
                buy_quarter = get_quarter_key(buy_date)
                sell_quarter = get_quarter_key(sell_date)
                cpi_buy = self.cpi_data.get(buy_quarter)
                cpi_sell = self.cpi_data.get(sell_quarter)
                
                if cpi_buy and cpi_sell:
                    # Round indexation factor to 4 decimal places before applying to cost base
                    index_factor = round(max(1.0, cpi_sell / cpi_buy), 4)
                else:
                    index_factor = 1.0
                    
                indexed_cost_base = matched_cost_base * index_factor
                capital_gain = matched_proceeds - indexed_cost_base
                discounted_gain = capital_gain # No discount applied
            else:
                # 2. Pre-July 2027: Apply standard 50% discount if held > 12 months
                index_factor = 1.0
                indexed_cost_base = matched_cost_base
                
                # ATO rule: must be held for more than 12 months.
                try:
                    min_sell_date = buy_date.replace(year=buy_date.year + 1) + pd.Timedelta(days=1)
                except ValueError:  # Handles Feb 29 in leap year
                    min_sell_date = buy_date + pd.Timedelta(days=366)

                is_discount_eligible = sell_date >= min_sell_date
                capital_gain = matched_proceeds - matched_cost_base
                
                discounted_gain = capital_gain
                if is_discount_eligible and capital_gain > 0:
                    discounted_gain = capital_gain * 0.5

            self.cgt_events.append({
                "Ticker": ticker,
                "Buy_Date": buy_date.strftime("%Y-%m-%d"),
                "Sell_Date": sell_date.strftime("%Y-%m-%d"),
                "Units": matched_units,
                "Buy_Price": oldest_parcel["price"],
                "Sell_Price": sell_price,
                "Cost_Base": round(matched_cost_base, 2),
                "Index_Factor": round(index_factor, 4),
                "Indexed_Cost_Base": round(indexed_cost_base, 2),
                "Proceeds": round(matched_proceeds, 2),
                "Capital_Gain": round(capital_gain, 2),
                "Holding_Days": holding_days,
                "Discount_Eligible": "Yes" if is_discount_eligible else "No",
                "Discounted_Gain": round(discounted_gain, 2),
                "Buy_Broker": oldest_parcel["broker"],
                "Sell_Broker": broker
            })

            # Update the buy parcel in the queue
            if buy_units > remaining_to_sell:
                oldest_parcel["units"] -= remaining_to_sell
                oldest_parcel["total_cost"] -= matched_cost_base
                remaining_to_sell = 0
            else:
                self.holdings[ticker].pop(0)
                remaining_to_sell -= buy_units

        # Handle short-sale or missing buy parcel case
        if remaining_to_sell > 0:
            matched_proceeds = (remaining_to_sell * sell_price) - (sell_brokerage * (remaining_to_sell / total_sell_units))
            self.cgt_events.append({
                "Ticker": ticker,
                "Buy_Date": "MISSING",
                "Sell_Date": sell_date.strftime("%Y-%m-%d"),
                "Units": remaining_to_sell,
                "Buy_Price": 0.0,
                "Sell_Price": sell_price,
                "Cost_Base": 0.0,
                "Index_Factor": 1.0,
                "Indexed_Cost_Base": 0.0,
                "Proceeds": round(matched_proceeds, 2),
                "Capital_Gain": round(matched_proceeds, 2),
                "Holding_Days": 0,
                "Discount_Eligible": "No",
                "Discounted_Gain": round(matched_proceeds, 2),
                "Buy_Broker": "UNKNOWN",
                "Sell_Broker": broker
            })

    def get_holdings_summary(self) -> pd.DataFrame:
        """Return a summary DataFrame of current holdings."""
        summary = []
        for ticker, parcels in self.holdings.items():
            total_units = sum(p["units"] for p in parcels)
            if total_units <= 0:
                continue
            total_cost = sum(p["total_cost"] for p in parcels)
            avg_price = total_cost / total_units
            summary.append({
                "Ticker": ticker,
                "Units": round(total_units, 4),
                "Total_Cost": round(total_cost, 2),
                "Average_Price": round(avg_price, 4)
            })
        
        if not summary:
            return pd.DataFrame(columns=["Ticker", "Units", "Total_Cost", "Average_Price"])
        return pd.DataFrame(summary).sort_values("Ticker").reset_index(drop=True)

    def get_cgt_report(self) -> pd.DataFrame:
        """Return a DataFrame of all realized CGT events."""
        if not self.cgt_events:
            return pd.DataFrame(columns=[
                "Ticker", "Buy_Date", "Sell_Date", "Units", "Buy_Price", "Sell_Price",
                "Cost_Base", "Index_Factor", "Indexed_Cost_Base", "Proceeds", 
                "Capital_Gain", "Holding_Days", "Discount_Eligible", "Discounted_Gain", 
                "Buy_Broker", "Sell_Broker"
            ])
        return pd.DataFrame(self.cgt_events)
