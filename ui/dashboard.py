"""Dashboard page: positions, P&L, status banners, and safety controls."""
from __future__ import annotations

import streamlit as st

from config import TradingConfig
from models import TradingMode
from trading.emergency_stop import EmergencyStop
from ui.engine_singleton import get_current_engine, get_db
from utils.timeutil import now_ist


def render_dashboard() -> None:
    st.title("Trading Dashboard")

    db = get_db()
    today = now_ist().date()
    mode = st.session_state.get("mode", TradingMode.PAPER)

    # 1. Persistent Safety Banners from DB
    kill_switch_active = db.is_kill_switch_active(mode)
    daily_loss_latched = db.is_daily_loss_latched(mode, today)
    safe_mode_active = db.get_setting(f"safe_mode:{mode.value}", False)

    if kill_switch_active:
        st.error("🚨 CRITICAL: KILL SWITCH IS ACTIVE. ALL TRADING IS HALTED.")
    if safe_mode_active:
        st.error("⚠️ RECONCILIATION ERROR / SAFE MODE ACTIVE: Order placement blocked.")
    if daily_loss_latched:
        st.warning("⚠️ DAILY LOSS LIMIT REACHED: Trading halted for remainder of the day.")

    # 2. Config & metrics
    config = TradingConfig(symbol="INFY")
    trades_today = db.count_entries_today(mode, day=today)
    if trades_today >= config.max_trades_per_day:
        st.warning("⚠️ MAXIMUM DAILY TRADES REACHED.")

    pnl_today = db.realized_pnl_today(mode, today)
    positions = db.get_open_positions(mode)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Mode", mode.value)
    with col2:
        st.metric("Realized P&L Today", f"₹{pnl_today:,.2f}")
    with col3:
        st.metric("Trades Today", f"{trades_today} / {config.max_trades_per_day}")
    with col4:
        st.metric("Open Positions", len(positions))

    # 3. Open Positions Table
    st.subheader("Open Positions")
    if positions:
        pos_data = [
            {
                "Symbol": p.symbol,
                "Side": p.side.value,
                "Quantity": p.quantity,
                "Entry Price": p.entry_price,
                "Stop Price": p.stop_price,
                "Target Price": p.target_price or "-",
                "Stop Order ID": p.stop_order_id or "UNPROTECTED",
                "Entry Time": p.entry_time.strftime("%H:%M:%S"),
            }
            for p in positions
        ]
        st.dataframe(pos_data, use_container_width=True)
    else:
        st.info("No open positions.")

    # 4. Emergency & Kill Switch Controls
    st.divider()
    st.subheader("Safety Controls")
    col_stop, col_clear = st.columns(2)

    with col_stop:
        if st.button("🛑 STOP ALL TRADING", key="dash_stop_btn", type="primary"):
            engine = get_current_engine()
            broker = engine.broker if engine else None
            EmergencyStop.activate(db, broker, mode)
            st.rerun()

    with col_clear:
        if kill_switch_active:
            token = st.text_input("Enter 'CONFIRM_CLEAR' to reset kill switch:", key="clear_token")
            if st.button("Reset Kill Switch", key="reset_ks_btn"):
                try:
                    db.clear_kill_switch(mode, token)
                    st.success("Kill switch reset successfully.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


if __name__ == "__main__" or "streamlit" in __name__:
    render_dashboard()
