"""Paper trading controls and monitoring."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import TradingConfig
from models import TradingMode
from trading.emergency_stop import EmergencyStop
from ui.engine_singleton import get_current_engine, get_db, get_engine


def render_paper_page() -> None:
    st.title("Paper Trading")
    st.info("Paper trading simulates trade execution against simulated live feeds with zero capital risk.")

    db = get_db()
    mode = TradingMode.PAPER
    engine = get_current_engine()

    col_status1, col_status2, col_status3 = st.columns(3)
    with col_status1:
        is_running = engine is not None and not engine.halted
        st.metric("Engine Status", "RUNNING" if is_running else ("HALTED" if engine and engine.halted else "IDLE"))
    with col_status2:
        candle_count = len(engine.candle_history) if engine else 0
        st.metric("Candles Processed", candle_count)
    with col_status3:
        trade_count = len(engine.executed_trades) if engine else 0
        st.metric("Paper Trades Executed", trade_count)

    st.divider()

    # Controls
    c_start, c_stop = st.columns(2)
    with c_start:
        if st.button("Start Paper Trading", type="primary", disabled=is_running):
            cfg = TradingConfig(symbol="INFY")
            get_engine(config=cfg, mode=mode, db=db)
            st.success("Paper trading engine initialized.")
            st.rerun()

    with c_stop:
        if st.button("Stop Paper Trading", disabled=not is_running):
            if engine:
                EmergencyStop.activate(db, engine.broker, mode)
            st.warning("Paper trading halted.")
            st.rerun()

    # Trade History Table
    st.subheader("Paper Trades History")
    trades = db.get_trades(mode=mode)
    if trades:
        records = [
            {
                "Symbol": t.symbol,
                "Side": t.side.value,
                "Quantity": t.quantity,
                "Entry Time": t.entry_time.strftime("%Y-%m-%d %H:%M"),
                "Entry Price": t.entry_price,
                "Exit Time": t.exit_time.strftime("%Y-%m-%d %H:%M"),
                "Exit Price": t.exit_price,
                "Net P&L": t.pnl,
                "Charges": t.charges,
                "Reason": t.reason,
            }
            for t in trades
        ]
        st.dataframe(pd.DataFrame(records), use_container_width=True)
    else:
        st.info("No paper trades recorded yet.")


if __name__ == "__main__" or "streamlit" in __name__:
    render_paper_page()
