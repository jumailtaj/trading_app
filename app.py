"""Trading application entry point: Streamlit UI and headless runner."""
from __future__ import annotations

import sys
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from config import TradingConfig
from db import Database
from models import TradingMode
from trading.emergency_stop import EmergencyStop
from ui.backtest_page import render_backtest_page
from ui.dashboard import render_dashboard
from ui.engine_singleton import get_current_engine, get_db
from ui.live_page import render_live_page
from ui.logs_page import render_logs_page
from ui.paper_page import render_paper_page
from ui.settings_page import render_settings_page
from utils.logger import get_logger, setup_logging

logger = get_logger("app")


def run_ui() -> None:
    """Mount and execute the Streamlit UI."""
    db = get_db()
    mode = st.session_state.get("mode", TradingMode.PAPER)

    # Global sidebar Emergency Stop button (always visible across all pages)
    st.sidebar.title("🚨 Emergency Stop")
    if st.sidebar.button("🛑 STOP ALL TRADING", key="global_stop_btn", type="primary"):
        engine = get_current_engine()
        broker = engine.broker if engine else None
        EmergencyStop.activate(db, broker, mode)
        st.sidebar.error("EMERGENCY STOP ACTIVATED")
        st.rerun()

    st.sidebar.divider()

    # Multi-page navigation
    pages = [
        st.Page(render_dashboard, title="Dashboard", icon="📊", default=True),
        st.Page(render_backtest_page, title="Backtest", icon="🧪"),
        st.Page(render_paper_page, title="Paper Trading", icon="📝"),
        st.Page(render_live_page, title="Live Trading", icon="🔴"),
        st.Page(render_settings_page, title="Settings", icon="⚙️"),
        st.Page(render_logs_page, title="Logs", icon="📜"),
    ]

    nav = st.navigation(pages)
    nav.run()


def main() -> int:
    """Initialize application components and logging in headless mode."""
    setup_logging(log_dir="logs", console=True)
    logger.info("Starting Trading App (headless mode)...")

    db = Database("trading_app.db")
    logger.info("Database initialized successfully.")

    cfg = TradingConfig(symbol="INFY")
    logger.info(f"Loaded default trading configuration for symbol: {cfg.symbol}")

    db.close()
    logger.info("Trading App initialization completed.")
    return 0


# If executed under Streamlit context, run the UI. Otherwise run headless main.
if get_script_run_ctx() is not None:
    run_ui()
elif __name__ == "__main__":
    sys.exit(main())
