"""Logs viewer page: filter and inspect database logs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.engine_singleton import get_db


def render_logs_page() -> None:
    st.title("System Logs")

    db = get_db()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        min_level = st.selectbox(
            "Minimum Log Level",
            options=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            index=1,
            key="logs_min_level",
        )
    with col2:
        search_term = st.text_input("Search Logs", value="", key="logs_search")
    with col3:
        limit = st.number_input("Limit", min_value=10, max_value=1000, value=200, step=50, key="logs_limit")

    logs = db.get_logs(limit=int(limit), min_level=min_level)

    if search_term:
        term = search_term.lower()
        logs = [entry for entry in logs if term in entry["message"].lower() or term in entry["logger"].lower()]

    if logs:
        records = [
            {
                "Timestamp": entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                "Level": entry["level"],
                "Logger": entry["logger"],
                "Message": entry["message"],
            }
            for entry in logs
        ]
        st.dataframe(pd.DataFrame(records), use_container_width=True)
    else:
        st.info("No logs found matching the selected criteria.")


if __name__ == "__main__" or "streamlit" in __name__:
    render_logs_page()
