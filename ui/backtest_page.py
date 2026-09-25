"""Backtest page: CSV upload, parameters configuration, results, and equity curve."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from backtest.engine import Backtester
from config import TradingConfig
from market.historical_data import load_csv
from strategy.ema_strategy import EMACrossoverStrategy
from ui.engine_singleton import get_db


def render_backtest_page() -> None:
    st.title("Strategy Backtest")

    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        symbol = st.text_input("Symbol", value="INFY")
        capital = st.number_input("Capital (₹)", min_value=1000.0, value=100_000.0, step=5000.0)
        fast_period = st.number_input("Fast EMA Period", min_value=2, max_value=100, value=9)
    with col_cfg2:
        risk_pct = st.number_input("Risk Per Trade (%)", min_value=0.1, max_value=5.0, value=0.5, step=0.1)
        stop_loss_pct = st.number_input("Stop Loss (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.1)
        slow_period = st.number_input("Slow EMA Period", min_value=3, max_value=200, value=21)

    uploaded_file = st.file_uploader("Upload 5-minute OHLCV CSV file", type=["csv"])

    if st.button("Run Backtest", type="primary"):
        if uploaded_file is None:
            st.error("Please upload a CSV file to run the backtest.")
            return

        try:
            df = pd.read_csv(uploaded_file)
            cfg = TradingConfig(
                symbol=symbol,
                capital=capital,
                risk_per_trade_pct=risk_pct,
                stop_loss_pct=stop_loss_pct,
            )
            strategy = EMACrossoverStrategy(fast_period=fast_period, slow_period=slow_period)
            backtester = Backtester(cfg, strategy)
            result = backtester.run(df)

            # Display metrics
            st.success("Backtest completed successfully!")
            m = result.metrics

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Trades", m.total_trades)
            c2.metric("Win Rate", f"{m.win_rate:.1f}%")
            c3.metric("Net P&L", f"₹{m.net_pnl:,.2f}")
            c4.metric("Max Drawdown", f"₹{m.max_drawdown:,.2f} ({m.max_drawdown_pct:.1f}%)")

            # Chart equity curve
            if not result.equity_curve.empty:
                st.subheader("Equity Curve")
                st.line_chart(result.equity_curve)

            # Trades list
            st.subheader("Executed Trades")
            if result.trades:
                trades_df = pd.DataFrame([
                    {
                        "Side": t.side.value,
                        "Qty": t.quantity,
                        "Entry Time": t.entry_time,
                        "Entry Price": t.entry_price,
                        "Exit Time": t.exit_time,
                        "Exit Price": t.exit_price,
                        "Net P&L": t.pnl,
                        "Reason": t.reason,
                    }
                    for t in result.trades
                ])
                st.dataframe(trades_df, use_container_width=True)
            else:
                st.info("No trades executed during the backtest period.")

            # Save result to DB
            db = get_db()
            db.save_backtest(symbol, cfg.to_dict(), result.to_dict())

        except Exception as exc:
            st.error(f"Backtest error: {exc}")


if __name__ == "__main__" or "streamlit" in __name__:
    render_backtest_page()
