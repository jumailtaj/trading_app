"""Live trading controls with 4-step confirmation and safety barriers."""
from __future__ import annotations

import streamlit as st

from config import TradingConfig
from models import TradingMode
from trading.emergency_stop import EmergencyStop
from ui.engine_singleton import get_current_engine, get_db
from utils.timeutil import now_ist


def render_live_page() -> None:
    st.title("🔴 Live Trading")
    st.warning("⚠️ REAL MONEY AT RISK: Live orders will be routed directly to Zerodha Kite.")

    db = get_db()
    today = now_ist().date()
    cfg = TradingConfig(symbol="INFY")

    # Safety checks from DB
    if db.is_kill_switch_active(TradingMode.LIVE):
        st.error("🚨 CRITICAL: KILL SWITCH IS ACTIVE. Live trading cannot be enabled.")
        return

    # Check if live mode is already enabled in session
    is_live_active = st.session_state.get("live_trading_enabled", False)

    if not is_live_active:
        st.subheader("4-Step Live Activation Flow")

        # Step 1: Mode dropdown
        mode_selection = st.selectbox(
            "Step 1: Select Execution Mode",
            options=["PAPER", "BACKTEST", "LIVE"],
            index=0,
            key="live_step1_mode",
        )

        if mode_selection != "LIVE":
            st.info("Select 'LIVE' mode above to proceed with activation.")
            return

        # Step 2: Confirmation Checkbox
        ack = st.checkbox(
            "Step 2: I understand this will place real orders with real money",
            value=False,
            key="live_step2_ack",
        )

        if not ack:
            st.info("Check the confirmation box above to proceed.")
            return

        # Step 3: Type exact symbol
        expected_symbol = cfg.symbol
        symbol_input = st.text_input(
            f"Step 3: Type exact trading symbol to confirm ('{expected_symbol}')",
            value="",
            key="live_step3_symbol",
        )

        if symbol_input.strip().upper() != expected_symbol:
            if symbol_input:
                st.error(f"Symbol mismatch. You must type '{expected_symbol}' exactly.")
            return

        # Step 4: Activation Button
        if st.button("Step 4: ENABLE LIVE TRADING", type="primary", key="live_step4_btn"):
            st.session_state["live_trading_enabled"] = True
            st.session_state["mode"] = TradingMode.LIVE
            st.success("LIVE TRADING ENABLED")
            st.rerun()

    else:
        # Live Trading Active View
        st.success("🔴 LIVE TRADING IS ACTIVE")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Strategy", "EMA Crossover (9/21)")
            st.metric("Symbol", cfg.symbol)
        with col2:
            st.metric("Capital", f"₹{cfg.capital:,.2f}")
            st.metric("Risk Per Trade", f"{cfg.risk_per_trade_pct}%")
        with col3:
            st.metric("Max Daily Loss", f"₹{cfg.max_daily_loss:,.2f}")
            st.metric("Max Trades / Day", cfg.max_trades_per_day)

        st.divider()

        # Current Live Positions
        st.subheader("Current Live Positions")
        positions = db.get_open_positions(TradingMode.LIVE)
        if positions:
            st.table([
                {
                    "Symbol": p.symbol,
                    "Side": p.side.value,
                    "Quantity": p.quantity,
                    "Entry Price": p.entry_price,
                    "Stop Price": p.stop_price,
                    "Stop Order ID": p.stop_order_id or "UNPROTECTED",
                }
                for p in positions
            ])
        else:
            st.info("No open live positions.")

        st.divider()
        if st.button("🛑 DISABLE LIVE TRADING", type="primary", key="live_disable_btn"):
            st.session_state["live_trading_enabled"] = False
            st.session_state["mode"] = TradingMode.PAPER
            engine = get_current_engine()
            broker = engine.broker if engine else None
            EmergencyStop.activate(db, broker, TradingMode.LIVE)
            st.warning("Live trading disabled and kill switch activated.")
            st.rerun()


if __name__ == "__main__" or "streamlit" in __name__:
    render_live_page()
