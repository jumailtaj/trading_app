import ast
import pathlib

import numpy as np
import pandas as pd
import pytest

from models import Signal
from strategy.base_strategy import Strategy, StrategyDataError
from strategy.ema_strategy import EMACrossoverStrategy

BUY, SELL, HOLD = Signal.BUY, Signal.SELL, Signal.HOLD


def candles(closes, start="2026-09-01 09:15"):
    idx = pd.date_range(start, periods=len(closes), freq="5min")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1000})


def down_up_down():
    """60 falling closes, 40 rising, 40 falling: one golden cross then one death cross."""
    down1 = 100 - 0.3 * np.arange(60)
    up = down1[-1] + 1.0 * np.arange(1, 41)
    down2 = up[-1] - 1.0 * np.arange(1, 41)
    return np.concatenate([down1, up, down2])


@pytest.fixture
def strat():
    return EMACrossoverStrategy(9, 21)


def non_hold(signals):
    return [(i, s) for i, s in enumerate(signals) if s is not HOLD]


# ----------------------------------------------------------------- core behaviour
def test_name_and_defaults(strat):
    assert strat.name == "EMA 9/21"
    assert strat.warmup_candles == 63


def test_buy_on_upward_cross_exactly_on_that_candle(strat):
    data = candles(down_up_down())
    sig = strat.generate_signals(data)
    (buy_idx, buy_sig), _ = non_hold(sig)
    assert buy_sig is BUY
    fast, slow = strat._ema_lines(data["close"])
    assert fast.iloc[buy_idx - 1] <= slow.iloc[buy_idx - 1] and fast.iloc[buy_idx] > slow.iloc[buy_idx]
    assert strat.generate_signal(data.iloc[: buy_idx + 1]) is BUY
    assert strat.generate_signal(data.iloc[:buy_idx]) is HOLD
    assert strat.generate_signal(data.iloc[: buy_idx + 2]) is HOLD      # the very next candle: no repeat


def test_sell_on_downward_cross_exactly_on_that_candle(strat):
    data = candles(down_up_down())
    sig = strat.generate_signals(data)
    _, (sell_idx, sell_sig) = non_hold(sig)
    assert sell_sig is SELL
    fast, slow = strat._ema_lines(data["close"])
    assert fast.iloc[sell_idx - 1] >= slow.iloc[sell_idx - 1] and fast.iloc[sell_idx] < slow.iloc[sell_idx]
    assert strat.generate_signal(data.iloc[: sell_idx + 1]) is SELL
    assert strat.generate_signal(data.iloc[:sell_idx]) is HOLD


def test_hold_when_trend_continues_or_flat(strat):
    assert strat.generate_signal(candles(100 + 0.5 * np.arange(200))) is HOLD      # steady rise
    assert strat.generate_signal(candles(200 - 0.5 * np.arange(200))) is HOLD      # steady fall
    assert set(strat.generate_signals(candles([100.0] * 200))) == {HOLD}            # dead flat


def test_no_duplicate_signals_signals_alternate(strat):
    sig = strat.generate_signals(candles(down_up_down()))
    kinds = [s for _, s in non_hold(sig)]
    assert kinds == [BUY, SELL]                       # one per cross, despite ~40 candles beyond each cross
    noisy = 100 + 3 * np.sin(np.arange(600) / 5.0) + np.random.default_rng(1).normal(0, 0.3, 600)
    kinds = [s for _, s in non_hold(strat.generate_signals(candles(noisy)))]
    assert len(kinds) > 4
    assert all(a is not b for a, b in zip(kinds, kinds[1:]))      # never two BUYs or two SELLs in a row


def test_touch_without_crossing_is_not_a_signal():
    """above -> equal -> above must stay HOLD; below -> equal -> above is a BUY."""
    strat = EMACrossoverStrategy(2, 3, warmup_candles=4)
    data = candles([1.0] * 8)

    def fake(fast, slow):
        strat._ema_lines = lambda close: (pd.Series(fast, index=data.index), pd.Series(slow, index=data.index))

    fake([3, 3, 3, 3, 2, 3, 3, 3], [2] * 8)
    assert set(strat.generate_signals(data)) == {HOLD}
    fake([1, 1, 1, 1, 2, 3, 3, 3], [2] * 8)
    assert non_hold(strat.generate_signals(data)) == [(5, BUY)]
    fake([3, 3, 3, 3, 2, 1, 1, 1], [2] * 8)
    assert non_hold(strat.generate_signals(data)) == [(5, SELL)]


# ----------------------------------------------------------------- warm-up / data problems
def test_hold_until_enough_candles(strat):
    data = candles(down_up_down())
    assert strat.generate_signal(data.iloc[:5]) is HOLD
    assert strat.generate_signal(data.iloc[:0].copy()) is HOLD
    assert set(strat.generate_signals(data).iloc[: strat.warmup_candles - 1]) == {HOLD}


@pytest.mark.parametrize("bad", [
    "not a dataframe",
    pd.DataFrame({"open": [1.0, 2.0]}),                                       # no close column
    pd.DataFrame({"close": [1.0, float("nan"), 3.0]}),                        # NaN
    pd.DataFrame({"close": [1.0, float("inf"), 3.0]}),
    pd.DataFrame({"close": [1.0, -2.0, 3.0]}),                                # non-positive
    pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=[2, 1, 0]),                # unsorted
    pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=[0, 0, 1]),                # duplicate index
])
def test_bad_data_raises_instead_of_guessing(strat, bad):
    with pytest.raises(StrategyDataError):
        strat.generate_signal(bad)


@pytest.mark.parametrize("args", [(21, 9), (9, 9), (0, 5), (-1, 5), (9.5, 21), (True, 21), ("9", 21)])
def test_invalid_periods_rejected(args):
    with pytest.raises(ValueError):
        EMACrossoverStrategy(*args)


def test_invalid_warmup_rejected():
    with pytest.raises(ValueError):
        EMACrossoverStrategy(9, 21, warmup_candles=10)
    assert EMACrossoverStrategy(9, 21, warmup_candles=30).warmup_candles == 30


def test_custom_periods_are_configurable():
    s = EMACrossoverStrategy(5, 13)
    assert s.name == "EMA 5/13"
    assert s.warmup_candles == 39


# ----------------------------------------------------------------- no look-ahead / determinism
def test_no_look_ahead_signal_at_i_equals_signal_from_data_up_to_i(strat):
    rng = np.random.default_rng(42)
    data = candles(100 + np.cumsum(rng.normal(0, 0.8, 400)))
    full = strat.generate_signals(data)
    for i in range(strat.warmup_candles - 1, len(data)):
        assert strat.generate_signal(data.iloc[: i + 1]) is full.iloc[i], f"mismatch at candle {i}"


def test_changing_future_candles_never_changes_past_signals(strat):
    rng = np.random.default_rng(7)
    base = 100 + np.cumsum(rng.normal(0, 0.8, 300))
    original = strat.generate_signals(candles(base))
    for cut in (80, 150, 220):
        altered = base.copy()
        altered[cut:] = altered[cut:] * rng.uniform(0.5, 1.5, len(altered) - cut)
        result = strat.generate_signals(candles(altered))
        assert list(result.iloc[:cut]) == list(original.iloc[:cut])


def test_deterministic_and_input_not_mutated(strat):
    data = candles(down_up_down())
    before = data.copy()
    a, b = strat.generate_signals(data), strat.generate_signals(data)
    assert list(a) == list(b)
    pd.testing.assert_frame_equal(data, before)


def test_returns_signal_enum(strat):
    assert isinstance(strat.generate_signal(candles(down_up_down())), Signal)


# ----------------------------------------------------------------- architecture rule
def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        Strategy()


def test_strategy_package_imports_no_broker_db_or_engine_code():
    forbidden = {"trading", "market", "backtest", "db", "kiteconnect", "sqlite3", "ui"}
    for path in pathlib.Path("strategy").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert n.split(".")[0] not in forbidden, f"{path} imports {n}"


# ----------------------------------------------------------------- warm-up boundary
def test_early_crossovers_inside_warmup_are_suppressed(strat):
    """Rising then falling in the first 40 candles makes a real early flip that must be ignored."""
    early = np.concatenate([100 + 1.0 * np.arange(15), 115 - 1.0 * np.arange(1, 26)])   # 40 candles, flips down
    data = candles(early)
    fast, slow = strat._ema_lines(data["close"])
    assert (np.sign(fast - slow).iloc[1:] != np.sign(fast - slow).iloc[1:].shift(1)).sum() >= 1   # a flip exists
    assert set(strat.generate_signals(data)) == {HOLD}


def test_warmup_boundary_is_exact():
    strat = EMACrossoverStrategy(2, 3, warmup_candles=4)
    data = candles([1.0] * 8)
    fast = [3, 3, 1, 3, 3, 3, 3, 3]            # flips down at idx 2 (inside warm-up), up at idx 3 (4th candle)
    fast_full = pd.Series(fast, index=data.index, dtype=float)
    slow_full = pd.Series([2.0] * 8, index=data.index)
    strat._ema_lines = lambda close: (fast_full.loc[close.index], slow_full.loc[close.index])   # follow the slice
    assert non_hold(strat.generate_signals(data)) == [(3, BUY)]
    assert strat.generate_signal(data.iloc[:4]) is BUY     # exactly warmup_candles candles: allowed
    assert strat.generate_signal(data.iloc[:3]) is HOLD    # one fewer: not enough history
