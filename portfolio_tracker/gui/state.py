import pandas as pd

class AppState:
    """Manages the central memory state of the portfolio tracker."""
    def __init__(self):
        self.master_df: pd.DataFrame | None = None
        self.holdings_df: pd.DataFrame | None = None
        self.cgt_df: pd.DataFrame | None = None

    def clear(self):
        self.master_df = None
        self.holdings_df = None
        self.cgt_df = None

    @property
    def has_data(self) -> bool:
        return self.master_df is not None and not self.master_df.empty
