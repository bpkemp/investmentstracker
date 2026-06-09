import customtkinter as ctk
import pandas as pd
from tkinter import messagebox

from portfolio_tracker.core.utils import standardise_ticker
from portfolio_tracker.gui.constants import COLOR_TEAL, COLOR_TEAL_HOVER, COLOR_CARD_DARK

def build_manual_entry_tab(app) -> None:
    """Create split layout inside manual entry tab (Form + Log list)."""
    tab_me = app.tabview.tab("Manual Entry")
    tab_me.grid_columnconfigure(0, weight=0, minsize=320)
    tab_me.grid_columnconfigure(1, weight=1)
    tab_me.grid_rowconfigure(0, weight=1)

    # Left Column - Form Container
    frm_form = ctk.CTkFrame(tab_me, fg_color="transparent")
    frm_form.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
    frm_form.grid_columnconfigure(1, weight=1)

    # Form Fields
    labels = ["Date (YYYY-MM-DD):", "Ticker (e.g. CBA):", "Type:", "Units:", "Price ($):", "Brokerage ($):", "Broker:"]
    app.me_fields = {}

    # Date input with default
    ctk.CTkLabel(frm_form, text=labels[0]).grid(row=0, column=0, padx=10, pady=6, sticky="w")
    ent_date = ctk.CTkEntry(frm_form, placeholder_text="e.g. 2026-06-07")
    ent_date.insert(0, pd.Timestamp.now().strftime("%Y-%m-%d"))
    ent_date.grid(row=0, column=1, padx=10, pady=6, sticky="ew")
    app.me_fields["Date"] = ent_date

    # Ticker input
    ctk.CTkLabel(frm_form, text=labels[1]).grid(row=1, column=0, padx=10, pady=6, sticky="w")
    ent_ticker = ctk.CTkEntry(frm_form, placeholder_text="e.g. CBA")
    ent_ticker.grid(row=1, column=1, padx=10, pady=6, sticky="ew")
    app.me_fields["Ticker"] = ent_ticker

    # Type drop down
    ctk.CTkLabel(frm_form, text=labels[2]).grid(row=2, column=0, padx=10, pady=6, sticky="w")
    opt_type = ctk.CTkOptionMenu(frm_form, values=["Buy", "Sell"], fg_color=COLOR_CARD_DARK)
    opt_type.grid(row=2, column=1, padx=10, pady=6, sticky="ew")
    app.me_fields["Type"] = opt_type

    # Units input
    ctk.CTkLabel(frm_form, text=labels[3]).grid(row=3, column=0, padx=10, pady=6, sticky="w")
    ent_units = ctk.CTkEntry(frm_form, placeholder_text="e.g. 50.0")
    ent_units.grid(row=3, column=1, padx=10, pady=6, sticky="ew")
    app.me_fields["Units"] = ent_units

    # Price input
    ctk.CTkLabel(frm_form, text=labels[4]).grid(row=4, column=0, padx=10, pady=6, sticky="w")
    ent_price = ctk.CTkEntry(frm_form, placeholder_text="e.g. 102.50")
    ent_price.grid(row=4, column=1, padx=10, pady=6, sticky="ew")
    app.me_fields["Price"] = ent_price

    # Brokerage input
    ctk.CTkLabel(frm_form, text=labels[5]).grid(row=5, column=0, padx=10, pady=6, sticky="w")
    ent_brokerage = ctk.CTkEntry(frm_form, placeholder_text="e.g. 9.90 (default 0)")
    ent_brokerage.grid(row=5, column=1, padx=10, pady=6, sticky="ew")
    app.me_fields["Brokerage"] = ent_brokerage

    # Broker input
    ctk.CTkLabel(frm_form, text=labels[6]).grid(row=6, column=0, padx=10, pady=6, sticky="w")
    ent_broker = ctk.CTkEntry(frm_form, placeholder_text="e.g. CMC (default MANUAL)")
    ent_broker.grid(row=6, column=1, padx=10, pady=6, sticky="ew")
    app.me_fields["Broker"] = ent_broker

    # Add Row Button
    btn_add = ctk.CTkButton(
        frm_form,
        text="Add to Ledger",
        command=app._on_add_manual_row,
        fg_color=COLOR_TEAL,
        hover_color=COLOR_TEAL_HOVER,
        font=ctk.CTkFont(weight="bold")
    )
    btn_add.grid(row=7, column=0, columnspan=2, padx=10, pady=20, sticky="ew")

    # Right Column - Session Logs Container
    frm_log = ctk.CTkFrame(tab_me, fg_color=COLOR_CARD_DARK)
    frm_log.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
    frm_log.grid_columnconfigure(0, weight=1)
    frm_log.grid_rowconfigure(1, weight=1)

    lbl_log_title = ctk.CTkLabel(
        frm_log,
        text="Session Manual Logs:",
        font=ctk.CTkFont(size=12, weight="bold")
    )
    lbl_log_title.grid(row=0, column=0, padx=15, pady=8, sticky="w")

    app.txt_manual_logs = ctk.CTkTextbox(frm_log, wrap="none", font=ctk.CTkFont(family="Courier", size=11))
    app.txt_manual_logs.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")
    app.txt_manual_logs.insert("1.0", "--- Form logs will appear here ---")
    app.txt_manual_logs.configure(state="disabled")
