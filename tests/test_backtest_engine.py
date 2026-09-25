import ast
import json
import pathlib
from datetime import time

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestDataError, Backtester, LookAheadError
from db import Database
from models import TradingMode
from strategy.base_strategy import Strategy
from strategy.ema_strategy import EMACrossoverStrategy
from tests.conftest import ist
from tests.helpers import BUY, HOLD, SELL, SESSION, ScriptedStrategy, candles, cfg, flat, random_walk, run, session
from utils.charges import ChargesConfig, estimate_charges
from utils.timeutil import IST

DAY = (2026, 9, 23)

# 4 flat candles, then a steady rise; entry happens at candle 4's open (100), 500 shares
RISE = [flat(100)] * 4 + [(100, 101, 100, 101), (101, 102, 101, 102), (102, 103, 102, 103), flat(103),
                          (103, 104, 103, 104), flat(104)]


# ============================================================ entry and exit
def test_entry_and_exit_execute_at_the_next_candles_open():
    res = run(candles(RISE), {3: BUY, 7: SELL})
    (t,) = res.trades
    assert (t.entry_price, t.exit_price, t.quantity) == (100.0, 103.0, 500)
    assert t.pnl == pytest.approx(1500.0) and t.charges == 0 and t.reason == "SIGNAL"
    assert t.entry_time == ist(*DAY, 9, 35) and t.exit_time == ist(*DAY, 9, 55)
    assert t.mode is TradingMode.BACKTEST
    eq = res.equity_curve.to_numpy()
    assert eq[3] == 100_000 and eq[4] == 100_500 and eq[6] == 101_500 and eq[7] == 101_500 and eq[9] == 101_500
    assert res.signal_counts == {"BUY": 1, "SELL": 1} and res.skipped_signals == {}


def test_entry_uses_next_open_not_the_signal_candles_close():
    rows = [flat(100)] * 4 + [flat(105)] * 6
    (t,) = run(candles(rows), {3: BUY}).trades
    assert t.entry_price == 105.0                      # not 100 (the close that produced the signal)
    assert t.quantity == 476                           # sized from 105: floor(500 / 1.05)


def test_sell_while_flat_and_buy_while_long_are_ignored():
    res = run(candles(RISE), {1: SELL, 3: BUY, 5: BUY, 7: SELL})
    assert len(res.trades) == 1
    assert res.skipped_signals == {"BUY_WHILE_LONG": 1, "SELL_WHILE_FLAT": 1}


def test_never_short_and_only_one_position_at_a_time():
    res = run(session(), {2: SELL, 5: SELL, 8: BUY, 9: BUY, 10: BUY, 20: SELL, 21: SELL})
    assert all(t.side.value == "BUY" for t in res.trades)
    assert len(res.trades) == 1 and res.trades[0].reason == "SIGNAL"


def test_no_signals_means_no_trades_and_flat_equity():
    res = run(session(), {})
    assert res.trades == [] and res.metrics.total_trades == 0
    assert set(res.equity_curve) == {100_000.0}


def test_open_position_at_end_of_data_is_closed_at_the_last_close():
    rows = [flat(100)] * 5 + [flat(101)] * 3 + [(101, 102, 100.5, 101.5)]
    (t,) = run(candles(rows), {3: BUY}).trades
    assert t.reason == "END_OF_DATA" and t.exit_price == 101.5 and t.pnl == pytest.approx(750.0)


# ============================================================ stop loss / target
def stop_rows(candle5):
    return [flat(100)] * 4 + [(100, 100.2, 99.5, 100), candle5] + [flat(99.2)] * 3


def test_stop_loss_fills_at_the_stop_price():
    (t,) = run(candles(stop_rows((100, 100, 98.5, 99.2))), {3: BUY}).trades
    assert t.reason == "STOP_LOSS" and t.exit_price == pytest.approx(99.0)      # entry 100 - 1%
    assert t.pnl == pytest.approx(-500.0) and t.exit_time == ist(*DAY, 9, 40)


def test_gap_through_the_stop_fills_at_the_worse_open():
    (t,) = run(candles(stop_rows((97, 97.5, 96.5, 97))), {3: BUY}).trades
    assert t.reason == "STOP_LOSS" and t.exit_price == 97.0 and t.pnl == pytest.approx(-1500.0)


def test_target_fills_at_the_target_price():
    (t,) = run(candles(stop_rows((100, 102.5, 100, 102))), {3: BUY}, enable_target=True, target_pct=2.0).trades
    assert t.reason == "TARGET" and t.exit_price == pytest.approx(102.0) and t.pnl == pytest.approx(1000.0)


def test_gap_above_target_still_fills_at_the_target_not_better():
    (t,) = run(candles(stop_rows((103, 104, 103, 104))), {3: BUY}, enable_target=True, target_pct=2.0).trades
    assert t.exit_price == pytest.approx(102.0)


def test_target_ignored_when_disabled():
    res = run(candles(stop_rows((100, 102.5, 100, 102))), {3: BUY}, enable_target=False, target_pct=2.0)
    assert res.trades[0].reason == "END_OF_DATA"


def test_candle_touching_both_stop_and_target_counts_as_a_stop():
    (t,) = run(candles(stop_rows((100, 103, 98, 100))), {3: BUY}, enable_target=True, target_pct=2.0).trades
    assert t.reason == "STOP_LOSS" and t.pnl == pytest.approx(-500.0)


def test_stop_is_live_on_the_entry_candle_itself():
    rows = [flat(100)] * 4 + [(100, 100.1, 98.9, 99)] + [flat(99)] * 3
    (t,) = run(candles(rows), {3: BUY}).trades
    assert t.reason == "STOP_LOSS" and t.entry_time == t.exit_time == ist(*DAY, 9, 35)
    assert t.pnl == pytest.approx(-500.0)


def test_after_a_stop_out_the_strategy_waits_for_the_next_buy():
    rows = stop_rows((100, 100, 98.5, 99.2)) + [flat(100)] * 3
    res = run(candles(rows), {3: BUY, 6: SELL})           # SELL after being stopped out has nothing to close
    assert len(res.trades) == 1 and res.skipped_signals == {"SELL_WHILE_FLAT": 1}


# ============================================================ slippage
def test_slippage_hits_entry_signal_exit_and_stop_but_not_targets():
    slip = 0.1
    (sig,) = run(candles(RISE), {3: BUY, 7: SELL}, slippage_pct=slip).trades
    assert sig.entry_price == pytest.approx(100.1) and sig.exit_price == pytest.approx(102.897)
    assert sig.quantity == 500                                              # sized from the raw open

    (stop,) = run(candles(stop_rows((100, 100, 98.5, 99.2))), {3: BUY}, slippage_pct=slip).trades
    assert stop.entry_price == pytest.approx(100.1)
    assert stop.exit_price == pytest.approx(100.1 * 0.99 * 0.999)           # stop from fill price, then slipped

    (tgt,) = run(candles(stop_rows((100, 103, 100, 102))), {3: BUY}, slippage_pct=slip,
                 enable_target=True, target_pct=2.0).trades
    assert tgt.reason == "TARGET" and tgt.exit_price == pytest.approx(100.1 * 1.02)   # no slippage on the limit


def test_slippage_always_reduces_profit():
    a = run(candles(RISE), {3: BUY, 7: SELL}, slippage_pct=0.0).metrics.net_pnl
    b = run(candles(RISE), {3: BUY, 7: SELL}, slippage_pct=0.2).metrics.net_pnl
    assert b < a


# ============================================================ charges
def test_estimated_charges_are_deducted_from_pnl():
    res = run(candles(RISE), {3: BUY, 7: SELL}, charges=ChargesConfig())
    (t,) = res.trades
    expected = estimate_charges(100 * 500, 103 * 500).total
    assert t.charges == pytest.approx(expected) and t.charges > 0
    assert t.pnl == pytest.approx(1500 - expected)
    assert res.metrics.total_charges == pytest.approx(expected) and res.metrics.gross_pnl == pytest.approx(1500)
    assert res.equity_curve.iloc[-1] == pytest.approx(100_000 + 1500 - expected)


def test_charges_default_to_on_and_can_be_switched_off():
    on = Backtester(cfg(), ScriptedStrategy({3: BUY, 7: SELL})).run(candles(RISE))
    off = run(candles(RISE), {3: BUY, 7: SELL})
    assert on.metrics.total_charges > 0 and off.metrics.total_charges == 0


# ============================================================ trading window, square-off, expiry
def test_entry_before_trading_start_is_blocked_and_start_is_inclusive():
    rows = [flat(100)] * 12
    res = run(candles(rows), {0: BUY}, trading_start=time(9, 30))           # would execute at 09:20
    assert res.trades == [] and res.skipped_signals == {"OUTSIDE_TRADING_WINDOW": 1}
    res = run(candles(rows), {2: BUY}, trading_start=time(9, 30))           # executes exactly at 09:30
    assert len(res.trades) == 1 and res.trades[0].entry_time == ist(*DAY, 9, 30)


def test_entry_after_trading_end_is_blocked_and_end_is_inclusive():
    ok = run(session(), {68: BUY})                                          # executes at 15:00
    assert len(ok.trades) == 1 and ok.trades[0].entry_time == ist(*DAY, 15, 0)
    late = run(session(), {69: BUY})                                        # would execute at 15:05
    assert late.trades == [] and late.skipped_signals == {"OUTSIDE_TRADING_WINDOW": 1}


def test_open_position_is_squared_off_at_the_open_of_the_square_off_candle():
    data = session(overrides={72: flat(101), 73: flat(150), 74: flat(50)})  # 72 is the 15:15 candle
    (t,) = run(data, {68: BUY}).trades
    assert t.reason == "SQUARE_OFF" and t.exit_time == ist(*DAY, 15, 15)
    assert t.exit_price == 101.0 and t.pnl == pytest.approx(500.0)


def test_signal_on_the_last_candle_of_a_day_expires_and_never_trades_overnight():
    data = pd.concat([session("2026-09-23"), session("2026-09-24")])
    res = run(data, {SESSION - 1: BUY})                                     # 15:25 candle of day one
    assert res.trades == [] and res.skipped_signals == {"NO_NEXT_CANDLE_TODAY": 1}


def test_positions_never_carry_overnight():
    data = pd.concat([session("2026-09-23"), session("2026-09-24")])
    res = run(data, {3: BUY, SESSION + 3: BUY})
    assert len(res.trades) == 2
    assert all(t.entry_time.date() == t.exit_time.date() for t in res.trades)


# ============================================================ risk limits inside the engine
def test_daily_loss_limit_blocks_more_entries_that_day_but_not_the_next_day():
    day1 = session("2026-09-23", overrides={5: (100, 100, 98.5, 99.2)})      # stop-out costs exactly 500
    data = pd.concat([day1, session("2026-09-24")])
    res = run(data, {3: BUY, 8: BUY, SESSION + 3: BUY}, max_daily_loss=500.0)
    assert res.skipped_signals == {"DAILY_LOSS_LIMIT": 1}
    assert [t.entry_time.date().day for t in res.trades] == [23, 24]
    assert res.trades[0].pnl == pytest.approx(-500.0)


def test_a_loss_just_under_the_limit_still_allows_trading():
    overrides = {5: (100, 100, 98.5, 99.2), 10: (100, 100, 98.5, 99.2)}
    res = run(session(overrides=overrides), {3: BUY, 8: BUY, 13: BUY}, max_daily_loss=900.0)
    assert len(res.trades) == 2                                             # -500 (ok), -500 (now -1000 >= 900)
    assert res.skipped_signals == {"DAILY_LOSS_LIMIT": 1}


def test_max_trades_per_day_blocks_then_resets_next_day():
    data = pd.concat([session("2026-09-23"), session("2026-09-24")])
    res = run(data, {3: BUY, 7: SELL, 12: BUY, SESSION + 3: BUY}, max_trades_per_day=1)
    assert res.skipped_signals == {"MAX_TRADES": 1}
    assert [t.entry_time.date().day for t in res.trades] == [23, 24]


def test_quantity_zero_means_no_trade_not_a_rounded_up_one():
    res = run(session(price=100_000.0), {3: BUY})
    assert res.trades == [] and res.skipped_signals == {"QUANTITY_ZERO": 1}


# ============================================================ equity and accounting
def test_equity_is_marked_to_market_so_drawdown_includes_open_losses():
    rows = [flat(100)] * 4 + [(100, 100, 99.5, 99.5), (99.5, 101, 99.5, 101), (101, 103, 101, 103), flat(103), flat(103)]
    res = run(candles(rows), {3: BUY, 6: SELL})
    assert res.equity_curve.iloc[4] == pytest.approx(100_000 - 250)         # 500 shares x -0.5 while still open
    assert res.trades[0].pnl == pytest.approx(1500.0)                        # ...yet the trade ends profitable
    assert res.metrics.max_drawdown == pytest.approx(250.0)
    assert res.metrics.max_drawdown_pct == pytest.approx(0.25)


def test_final_equity_equals_capital_plus_net_pnl_on_a_long_random_run():
    res = Backtester(cfg(max_daily_loss=5000.0), EMACrossoverStrategy(3, 8)).run(random_walk(n_days=10, seed=5))
    assert res.metrics.total_trades > 10
    assert res.equity_curve.iloc[-1] == pytest.approx(100_000 + res.metrics.net_pnl)
    assert len(res.equity_curve) == res.candles == 10 * SESSION
    assert res.metrics.gross_pnl - res.metrics.total_charges == pytest.approx(res.metrics.net_pnl)


def test_every_trade_is_flat_by_the_end_of_its_day_and_marked_backtest():
    res = Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(random_walk(n_days=6, seed=11))
    assert res.trades
    assert all(t.mode is TradingMode.BACKTEST for t in res.trades)
    assert all(t.entry_time.date() == t.exit_time.date() and t.exit_time.time() <= time(15, 25) for t in res.trades)


# ============================================================ determinism and look-ahead
def test_backtest_is_deterministic():
    data = random_walk(n_days=6, seed=2)
    a = Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(data).to_dict()
    b = Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(data.copy()).to_dict()
    assert a == b


def test_input_data_is_not_modified():
    data = random_walk(n_days=3, seed=4)
    before = data.copy()
    Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(data)
    pd.testing.assert_frame_equal(data, before)


def test_changing_future_candles_never_changes_the_past():
    base = random_walk(n_days=4, seed=8)
    cut = 170
    altered = base.copy()
    factor = np.random.default_rng(1).uniform(0.6, 1.6, len(base) - cut)
    altered.iloc[cut:, :4] = altered.iloc[cut:, :4].to_numpy() * factor[:, None]     # keeps every candle consistent
    make = lambda d: Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(d)
    a, b = make(base), make(altered)
    assert np.array_equal(a.equity_curve.to_numpy()[:cut], b.equity_curve.to_numpy()[:cut])
    boundary = base.index[cut].to_pydatetime()
    before_a = [t for t in a.trades if t.exit_time < boundary]
    assert before_a and before_a == [t for t in b.trades if t.exit_time < boundary]


def test_fast_whole_series_signals_match_candle_by_candle_signals():
    class SlowEMA(EMACrossoverStrategy):
        def generate_signal(self, data):                        # independent one-candle answer, computed on this prefix only
            self.validate_candles(data)
            if len(data) < self.warmup_candles:
                return HOLD
            return EMACrossoverStrategy.generate_signals(self, data).iloc[-1]

        generate_signals = Strategy.generate_signals            # the obviously-causal loop over growing prefixes

    data = random_walk(n_days=4, seed=21)
    fast = Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(data).to_dict()
    slow = Backtester(cfg(), SlowEMA(3, 8)).run(data).to_dict()
    assert fast == slow and fast["trades"]


def test_engine_catches_a_strategy_that_peeks_at_the_future():
    class Cheater(Strategy):
        warmup_candles = 1
        name = "cheater"

        def generate_signal(self, data):
            return HOLD                                                      # honest one-at-a-time answer

        def generate_signals(self, data):                                    # ...but the bulk answer peeks ahead
            up_next = data["close"].shift(-1) > data["close"]
            return pd.Series([BUY if u else HOLD for u in up_next], index=data.index, dtype=object)

    with pytest.raises(LookAheadError):
        Backtester(cfg(), Cheater()).run(random_walk(n_days=3, seed=3))


def test_lookahead_check_can_be_turned_off_but_is_on_by_default():
    assert Backtester(cfg(), EMACrossoverStrategy()).lookahead_check_samples > 0
    assert Backtester(cfg(), EMACrossoverStrategy(), lookahead_check_samples=0).lookahead_check_samples == 0


# ============================================================ data validation
def good():
    return candles([flat(100)] * 30)


def test_good_data_passes():
    assert Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(good()).candles == 30


@pytest.mark.parametrize("mutate", [
    lambda d: d.reset_index(drop=True),                                      # no timezone-aware DatetimeIndex
    lambda d: d.tz_localize(None),                                           # naive datetimes
    lambda d: d.iloc[::-1],                                                  # newest first
    lambda d: d.iloc[[0, 0, 1, 2]],                                          # duplicate timestamps
    lambda d: d.drop(columns=["close"]),
    lambda d: d.iloc[0:0],                                                   # empty
    lambda d: d.assign(close=np.where(np.arange(len(d)) == 5, np.nan, d["close"])),
    lambda d: d.assign(low=np.where(np.arange(len(d)) == 5, 0.0, d["low"])),
    lambda d: d.assign(close=-1.0),
    lambda d: d.assign(high=np.where(np.arange(len(d)) == 5, 90.0, d["high"])),   # high below the other prices
    lambda d: d.assign(open=np.where(np.arange(len(d)) == 5, 200.0, d["open"])),  # open above the high
])
def test_bad_candles_are_rejected(mutate):
    with pytest.raises(BacktestDataError):
        Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(mutate(good()))


def test_not_a_dataframe_rejected():
    with pytest.raises(BacktestDataError):
        Backtester(cfg(), EMACrossoverStrategy()).run([1, 2, 3])


def test_utc_indexed_candles_are_accepted_and_treated_as_ist_times():
    utc = candles(RISE)
    utc.index = utc.index.tz_convert("UTC")
    (t,) = run(utc, {3: BUY, 7: SELL}).trades
    assert t.entry_time == ist(*DAY, 9, 35)


# ============================================================ result output
def test_result_is_json_safe_and_round_trips_through_the_database():
    res = Backtester(cfg(), EMACrossoverStrategy(3, 8)).run(random_walk(n_days=3, seed=9))
    payload = json.loads(json.dumps(res.to_dict()))
    assert payload["metrics"]["total_trades"] == len(res.trades) == len(payload["trades"])
    assert len(payload["equity_curve"]) == res.candles and payload["assumptions"]
    db = Database(":memory:")
    bid = db.save_backtest("TEST", payload["config"], payload)
    assert db.get_backtest(bid)["result"]["metrics"]["net_pnl"] == pytest.approx(res.metrics.net_pnl)
    db.close()


def test_assumptions_are_listed_and_charges_are_labelled_estimated():
    res = run(candles(RISE), {3: BUY, 7: SELL})
    text = " ".join(res.assumptions)
    assert "NEXT candle's open" in text and "ESTIMATES" in text and "STOP is assumed to hit first" in text


def test_signal_expires_if_next_candle_is_not_exactly_one_timeframe_later():
    part1_idx = pd.date_range("2026-09-23 09:15", periods=4, freq="5min", tz=IST)
    part2_idx = pd.date_range("2026-09-23 10:30", periods=4, freq="5min", tz=IST)
    idx = part1_idx.append(part2_idx)
    rows = [flat(100.0)] * len(idx)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)
    df["volume"] = 1000
    res = run(df, {3: BUY})
    assert len(res.trades) == 0
    assert res.skipped_signals.get("GAP_SIGNAL_EXPIRED") == 1


def test_candles_outside_market_hours_are_filtered():
    part1_idx = pd.date_range("2026-09-23 03:00", periods=2, freq="5min", tz=IST)
    part2_idx = pd.date_range("2026-09-23 09:15", periods=10, freq="5min", tz=IST)
    idx = part1_idx.append(part2_idx)
    rows = [flat(100.0)] * len(idx)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)
    df["volume"] = 1000
    res = run(df, {3: BUY, 7: SELL})
    assert res.candles == 10
    assert all(c.time() >= time(9, 15) and c.time() < time(15, 30) for c in res.equity_curve.index)


def test_wrong_timeframe_raises_backtest_data_error():
    idx = pd.date_range("2026-09-23 09:15", periods=10, freq="15min", tz=IST)
    rows = [flat(100.0)] * len(idx)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)
    df["volume"] = 1000
    with pytest.raises(BacktestDataError, match="candle spacing mode is 900s, expected 300s"):
        run(df, {})


def test_gap_count_reported_in_result():
    idx1 = pd.date_range("2026-09-23 09:15", periods=2, freq="5min", tz=IST)
    idx2 = pd.date_range("2026-09-23 09:35", periods=2, freq="5min", tz=IST)
    idx3 = pd.date_range("2026-09-23 10:00", periods=2, freq="5min", tz=IST)
    idx = idx1.append(idx2).append(idx3)
    rows = [flat(100.0)] * len(idx)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)
    df["volume"] = 1000
    res = run(df, {1: BUY, 3: BUY})
    assert res.skipped_signals.get("GAP_SIGNAL_EXPIRED") == 2


# ============================================================ architecture rule
def test_backtest_and_risk_code_cannot_reach_a_real_broker_or_network():
    forbidden_top = {"kiteconnect", "requests", "socket", "urllib", "http", "websocket", "market", "ui", "db", "sqlite3"}
    forbidden_dotted = ("trading.live_broker", "trading.kite_broker")
    files = list(pathlib.Path("backtest").glob("*.py")) + [pathlib.Path("trading/risk_manager.py")]
    assert len(files) >= 5
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for n in names:
                assert n.split(".")[0] not in forbidden_top, f"{path} imports {n}"
                assert not n.startswith(forbidden_dotted), f"{path} imports {n}"
