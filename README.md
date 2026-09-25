# Simple Algo Trading (Zerodha Kite) - work in progress

A small personal trading terminal: **Backtest -> Paper -> Live**, one strategy (EMA 9/21 crossover),
one instrument, 5-minute candles, SQLite storage, Streamlit UI (later phase).

**Status: Phases 1-3 of 10 done (config, strategy, backtest). There is no paper trading, broker code or UI yet.
Nothing in this repo can place an order.** See "Build status" below.

## Install and test

    python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python -m pytest

## Layout (flat, so `streamlit run app.py` works from this folder)

    config.py          TradingConfig (validated), RuntimeMode (live safety switch), credential loading
    models.py          enums (TradingMode, Signal, Side, OrderStatus...) and dataclasses (Order, Trade, Position)
    db.py              SQLite: settings, orders, trades, positions, backtests, logs
    strategy/          Strategy interface + EMA crossover (no broker/DB imports - enforced by a test)
    trading/           risk_manager.py: position sizing + window / daily-loss / max-trades checks
    backtest/          engine.py (the loop), broker.py (simulated fills), metrics.py
    utils/             logger (secret redaction), timeutil (IST, timezone-aware only), charges (estimated costs)
    tests/             pytest suite
    market/ ui/        empty until their phases

Deliberate simplification of the suggested tree: `models/models.py` -> `models.py`, `database/db.py` -> `db.py`.

## Rules baked in so far

* Units: every `*_pct` value is a percent (0.5 = 0.5%). Money is INR. Default numbers are examples, not advice.
* Signals: generated from a CLOSED candle, executed at the NEXT candle's open. Strategies only ever see closed candles.
* EMA "cross" = sign of (fast - slow) flips. Exact ties carry the previous sign, so touch-and-return is not a signal.
* Warm-up: no signals until `3 x slow_period` candles exist (63 for 9/21).
* Stop loss is mandatory (`stop_loss_pct > 0`); a `Position` cannot exist without a valid stop price.
* App starts in PAPER with LIVE disabled. `RuntimeMode` is in-memory only and is never saved, so a stored config can't enable live.
* Credentials come from `.env` (`KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN`), never from code or the DB, and are masked in logs.
* Timestamps must be timezone-aware; they are stored as IST.

## Running a backtest (Python, until the UI exists)

    from config import TradingConfig
    from strategy.ema_strategy import EMACrossoverStrategy
    from backtest.engine import Backtester
    from utils.charges import ChargesConfig

    # candles: DataFrame with open, high, low, close (+ volume), indexed by timezone-aware timestamps
    config = TradingConfig(symbol="HDFCBANK", capital=100_000, risk_per_trade_pct=0.5, stop_loss_pct=1.0)
    result = Backtester(config, EMACrossoverStrategy(9, 21)).run(candles)     # ChargesConfig.none() switches costs off
    print(result.metrics)          # trades, win rate, net P&L, max drawdown, profit factor ...
    result.trades                  # trade history        result.equity_curve   # one value per candle
    result.skipped_signals         # why signals did NOT become trades
    result.assumptions             # the execution rules below, in plain words

## Backtest rules (also returned in `result.assumptions`)

* Signal from a closed candle -> executed at the NEXT candle's open, same day only.
* Long-only, one position at a time, intraday only (closed at `square_off_time`, default 15:15).
* Size = min(risk-based, what capital can buy with no leverage, `max_quantity`); a size of 0 skips the trade.
* Stop is set from the actual fill and is live on the entry candle. Stop and target in one candle -> stop wins.
  A gap through the stop fills at the worse open. Slippage hurts every market-type fill.
* Charges are ESTIMATES (NSE equity intraday rates read from zerodha.com/charges on 2026-09-24; the exchange
  fee has changed between page versions, so re-check `utils/charges.py`). P&L is net of them.
* The strategy's fast whole-series signals are spot-checked against one-candle-at-a-time signals on every run;
  a mismatch raises `LookAheadError` instead of producing results.

## Build status

| Phase | Scope | State |
|---|---|---|
| 1 | structure, config, models, logging, SQLite | done, tested |
| 2 | strategy interface, EMA 9/21 | done, tested |
| 3 | backtest engine, simulated broker, metrics, charges (+ the sizing/limit half of the risk manager) | done, tested |
| 4 | paper trading, live data, paper broker | next |
| 5-9 | Kite adapter (mock-tested), live-only risk protections, reconciliation, Streamlit UI, integration tests | not started |
| 10 | paper-trading instructions and the live-readiness checklist | not started |
