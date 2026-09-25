"""Settings page: validates configuration through TradingConfig without exposing live flag."""
from __future__ import annotations

import streamlit as st

from config import ConfigError, TradingConfig
from ui.engine_singleton import get_db


def render_settings_page() -> None:
    st.title("Strategy & Risk Settings")
    st.info("Configuration is strictly validated through TradingConfig before persisting to DB.")

    db = get_db()
    saved_cfg = db.get_setting("ui_config", {})

    with st.form("settings_form"):
        col1, col2 = st.columns(2)
        with col1:
            symbol = st.text_input("Symbol", value=saved_cfg.get("symbol", "INFY"))
            capital = st.number_input(
                "Capital (₹)",
                min_value=100.0,
                value=float(saved_cfg.get("capital", 100_000.0)),
                step=5000.0,
            )
            risk_pct = st.number_input(
                "Risk Per Trade (%)",
                min_value=0.01,
                max_value=5.0,
                value=float(saved_cfg.get("risk_per_trade_pct", 0.5)),
                step=0.1,
            )
            max_daily_loss = st.number_input(
                "Max Daily Loss (₹)",
                min_value=1.0,
                value=float(saved_cfg.get("max_daily_loss", 1000.0)),
                step=100.0,
            )

        with col2:
            max_trades = st.number_input(
                "Max Trades Per Day",
                min_value=1,
                max_value=50,
                value=int(saved_cfg.get("max_trades_per_day", 5)),
            )
            max_qty = st.number_input(
                "Max Quantity",
                min_value=1,
                value=int(saved_cfg.get("max_quantity", 100)),
            )
            stop_loss = st.number_input(
                "Stop Loss (%)",
                min_value=0.1,
                max_value=20.0,
                value=float(saved_cfg.get("stop_loss_pct", 1.0)),
                step=0.1,
            )
            slippage = st.number_input(
                "Estimated Slippage (%)",
                min_value=0.0,
                max_value=5.0,
                value=float(saved_cfg.get("slippage_pct", 0.05)),
                step=0.01,
            )

        submitted = st.form_submit_button("Save Configuration", type="primary")
        if submitted:
            form_dict = {
                "symbol": symbol,
                "capital": capital,
                "risk_per_trade_pct": risk_pct,
                "max_daily_loss": max_daily_loss,
                "max_trades_per_day": max_trades,
                "max_quantity": max_qty,
                "stop_loss_pct": stop_loss,
                "slippage_pct": slippage,
            }
            try:
                # Validation through immutable domain dataclass
                validated = TradingConfig.from_dict(form_dict)
                db.set_setting("ui_config", validated.to_dict())
                st.success("Configuration validated and saved successfully!")
            except ConfigError as err:
                st.error(f"Configuration validation failed: {err}")
            except Exception as exc:
                st.error(f"Error saving settings: {exc}")


if __name__ == "__main__" or "streamlit" in __name__:
    render_settings_page()
