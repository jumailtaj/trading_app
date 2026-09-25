import pandas as pd
import pytest

from backtest.metrics import compute_metrics, max_drawdown
from models import Side, Trade, TradingMode
from tests.conftest import ist


def tr(pnl, charges=1.0):
    return Trade(mode=TradingMode.BACKTEST, symbol="X", side=Side.BUY, quantity=1, entry_time=ist(2026, 9, 23, 10),
                 entry_price=100, exit_time=ist(2026, 9, 23, 11), exit_price=101, pnl=pnl, charges=charges)


def curve(values):
    return pd.Series(values, index=pd.date_range("2026-09-23 09:15", periods=len(values), freq="5min", tz="Asia/Kolkata"))


# ------------------------------------------------------------------ drawdown
def test_max_drawdown_hand_calculated():
    # equity 1000 -> 1100 -> 900 -> 1200 -> 600 -> 700: worst fall is 1200 -> 600
    assert max_drawdown([1100, 900, 1200, 600, 700], 1000) == (600.0, 50.0)


def test_drawdown_counts_the_starting_equity_as_a_peak():
    assert max_drawdown([900, 950], 1000) == (100.0, 10.0)


def test_no_drawdown_when_equity_only_rises_or_is_flat():
    assert max_drawdown([1000, 1010, 1020], 1000) == (0.0, 0.0)
    assert max_drawdown([], 1000) == (0.0, 0.0)


def test_percent_drawdown_is_measured_from_the_peak_it_fell_from():
    # a 100 fall from 1000 (10%) is smaller in % than a 60 fall from 400 (15%)
    assert max_drawdown([1000, 900, 400, 340], 1000) == (660.0, pytest.approx(66.0))
    abs_dd, pct = max_drawdown([1000, 900, 300, 400, 340], 1000)
    assert pct == pytest.approx(70.0) and abs_dd == 700.0


# ------------------------------------------------------------------ trade statistics
def test_trade_statistics_hand_calculated():
    trades = [tr(100), tr(-50), tr(200), tr(-25), tr(0)]
    m = compute_metrics(trades, curve([100_000, 100_225]), capital=100_000)
    assert (m.total_trades, m.winning_trades, m.losing_trades, m.breakeven_trades) == (5, 2, 2, 1)
    assert m.win_rate_pct == pytest.approx(40.0)
    assert m.net_pnl == pytest.approx(225) and m.total_charges == pytest.approx(5) and m.gross_pnl == pytest.approx(230)
    assert m.profit_factor == pytest.approx(300 / 75)
    assert m.avg_profit == pytest.approx(150) and m.avg_loss == pytest.approx(-37.5) and m.avg_trade == pytest.approx(45)
    assert m.return_pct == pytest.approx(0.225)
    assert m.final_equity == 100_225


def test_no_trades():
    m = compute_metrics([], curve([100_000, 100_000]), capital=100_000)
    assert m.total_trades == 0 and m.win_rate_pct is None and m.profit_factor is None
    assert m.avg_profit is None and m.avg_loss is None and m.avg_trade is None
    assert m.net_pnl == 0 and m.max_drawdown == 0


def test_all_winners_profit_factor_is_undefined_not_infinite():
    m = compute_metrics([tr(10), tr(20)], curve([100_030]), capital=100_000)
    assert m.profit_factor is None and m.win_rate_pct == 100.0 and m.avg_loss is None


def test_all_losers_profit_factor_is_zero():
    m = compute_metrics([tr(-10), tr(-20)], curve([99_970]), capital=100_000)
    assert m.profit_factor == 0.0 and m.win_rate_pct == 0.0 and m.avg_profit is None


def test_metrics_are_json_safe():
    import json
    json.dumps(compute_metrics([tr(10), tr(-5)], curve([100_005]), capital=100_000).to_dict())
