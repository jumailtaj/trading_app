import math
from datetime import datetime, time, timezone

import pytest

from db import Database
from models import TradingMode
from tests.conftest import ist
from tests.helpers import cfg
from trading.risk_manager import (
    DAILY_LOSS_LIMIT, KILL_SWITCH_ACTIVE, MAX_TRADES, OK, OUTSIDE_TRADING_WINDOW,
    QUANTITY_ZERO, RiskManager,
)


def check(rm, when, price=100.0, pnl=0.0, entries=0):
    return rm.check_entry(when=when, entry_price=price, realized_pnl_today=pnl, entries_today=entries)


# ------------------------------------------------------------------ sizing
def test_position_size_is_risk_based():
    assert RiskManager(cfg()).position_size(100.0) == 500        # 500 rupees of risk / Rs 1 per share
    assert RiskManager(cfg()).position_size(1000.0) == 50


def test_position_size_floors_never_rounds_up():
    assert RiskManager(cfg()).position_size(300.0) == 166        # 500 / 3 = 166.67


def test_position_size_capped_by_max_quantity():
    assert RiskManager(cfg(max_quantity=100)).position_size(100.0) == 100


def test_position_size_capped_by_what_capital_can_buy():
    rm = RiskManager(cfg(capital=1_000.0, risk_per_trade_pct=5.0, stop_loss_pct=0.5, max_daily_loss=100.0))
    assert rm.position_size(100.0) == 10                         # risk-based says 100, capital buys only 10


def test_position_size_zero_when_one_share_risks_too_much():
    assert RiskManager(cfg()).position_size(100_000.0) == 0      # 500 / 1000 = 0.5 -> 0, not rounded up


@pytest.mark.parametrize("price", [0, -5, math.nan, math.inf, True, "100", None])
def test_position_size_rejects_bad_prices(price):
    with pytest.raises(ValueError):
        RiskManager(cfg()).position_size(price)


# ------------------------------------------------------------------ trading window
def test_window_boundaries_are_inclusive():
    rm = RiskManager(cfg(trading_start=time(9, 30), trading_end=time(15, 0)))
    assert check(rm, ist(2026, 9, 23, 9, 29)).reason == OUTSIDE_TRADING_WINDOW
    assert check(rm, ist(2026, 9, 23, 9, 30)).reason == OK
    assert check(rm, ist(2026, 9, 23, 15, 0)).reason == OK
    assert check(rm, ist(2026, 9, 23, 15, 1)).reason == OUTSIDE_TRADING_WINDOW


def test_allowed_decision_carries_quantity():
    d = check(RiskManager(cfg()), ist(2026, 9, 23, 10, 0))
    assert d.allowed and d.quantity == 500 and d.reason == OK


def test_naive_time_rejected_and_utc_converted_to_ist():
    rm = RiskManager(cfg())
    with pytest.raises(ValueError):
        check(rm, datetime(2026, 9, 23, 10, 0))
    assert check(rm, datetime(2026, 9, 23, 4, 0, tzinfo=timezone.utc)).allowed    # 04:00 UTC = 09:30 IST
    assert not check(rm, datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)).allowed  # 15:30 IST


# ------------------------------------------------------------------ daily loss
def test_daily_loss_blocks_at_the_limit_not_only_beyond_it():
    rm = RiskManager(cfg(max_daily_loss=1_000.0))
    when = ist(2026, 9, 23, 10, 0)
    assert check(rm, when, pnl=-999.99).allowed
    d = check(rm, when, pnl=-1_000.0)
    assert not d.allowed and d.reason == DAILY_LOSS_LIMIT and d.quantity == 0
    assert not check(rm, when, pnl=-2_500.0).allowed


def test_profit_never_triggers_daily_loss():
    assert check(RiskManager(cfg()), ist(2026, 9, 23, 10, 0), pnl=+50_000.0).allowed


def test_daily_loss_halt_latches_for_the_day_and_resets_next_day():
    rm = RiskManager(cfg(max_daily_loss=1_000.0))
    assert check(rm, ist(2026, 9, 23, 10, 0), pnl=-1_200.0).reason == DAILY_LOSS_LIMIT
    # even if reported P&L recovers later that day, trading does not resume by itself
    assert check(rm, ist(2026, 9, 23, 13, 0), pnl=-100.0).reason == DAILY_LOSS_LIMIT
    assert check(rm, ist(2026, 9, 24, 10, 0), pnl=0.0).allowed            # next day is clean


# ------------------------------------------------------------------ max trades
def test_max_trades_blocks_at_the_limit():
    rm = RiskManager(cfg(max_trades_per_day=3))
    when = ist(2026, 9, 23, 10, 0)
    assert check(rm, when, entries=2).allowed
    d = check(rm, when, entries=3)
    assert not d.allowed and d.reason == MAX_TRADES


def test_quantity_zero_blocks_the_trade():
    d = check(RiskManager(cfg()), ist(2026, 9, 23, 10, 0), price=100_000.0)
    assert not d.allowed and d.reason == QUANTITY_ZERO


def test_check_priority_window_then_loss_then_trades_then_quantity():
    rm = RiskManager(cfg(max_daily_loss=1_000.0, max_trades_per_day=1))
    assert check(rm, ist(2026, 9, 23, 8, 0), pnl=-5_000, entries=9, price=1e6).reason == OUTSIDE_TRADING_WINDOW
    assert check(rm, ist(2026, 9, 23, 10, 0), pnl=-5_000, entries=9, price=1e6).reason == DAILY_LOSS_LIMIT
    assert check(RiskManager(cfg(max_trades_per_day=1)), ist(2026, 9, 23, 10, 0), entries=9, price=1e6).reason == MAX_TRADES


def test_kill_switch_blocks_entry_before_all_other_checks(db):
    db.set_kill_switch(TradingMode.LIVE, active=True)
    rm = RiskManager(cfg(), db=db, mode=TradingMode.LIVE)
    # Even outside trading window and with normal pnl, kill switch is returned first
    d = check(rm, ist(2026, 9, 23, 8, 0), pnl=0.0)
    assert not d.allowed
    assert d.reason == KILL_SWITCH_ACTIVE


def test_kill_switch_survives_risk_manager_restart(db):
    db.set_kill_switch(TradingMode.LIVE, active=True)
    # Simulate process restart by instantiating a completely new RiskManager
    rm_new = RiskManager(cfg(), db=db, mode=TradingMode.LIVE)
    d = check(rm_new, ist(2026, 9, 23, 10, 0))
    assert not d.allowed
    assert d.reason == KILL_SWITCH_ACTIVE

    # Clear kill switch -> allowed
    db.set_kill_switch(TradingMode.LIVE, active=False)
    rm_after = RiskManager(cfg(), db=db, mode=TradingMode.LIVE)
    assert check(rm_after, ist(2026, 9, 23, 10, 0)).allowed


def test_daily_loss_latch_survives_risk_manager_restart(db):
    rm1 = RiskManager(cfg(max_daily_loss=1000.0), db=db, mode=TradingMode.LIVE)
    d1 = check(rm1, ist(2026, 9, 23, 10, 0), pnl=-1500.0)
    assert not d1.allowed
    assert d1.reason == DAILY_LOSS_LIMIT

    # Simulate restart on same day: new RiskManager instance
    rm2 = RiskManager(cfg(max_daily_loss=1000.0), db=db, mode=TradingMode.LIVE)
    # Even if pnl reports 0.0 now, the latch in DB must block entry!
    d2 = check(rm2, ist(2026, 9, 23, 11, 0), pnl=0.0)
    assert not d2.allowed
    assert d2.reason == DAILY_LOSS_LIMIT

    # Next day: latch does not block next day
    d3 = check(rm2, ist(2026, 9, 24, 10, 0), pnl=0.0)
    assert d3.allowed
