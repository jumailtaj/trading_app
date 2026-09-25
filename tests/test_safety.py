import pathlib
from datetime import date

import pytest

from config import TradingConfig
from db import Database
from models import Position, PositionProtection, Side, TradingMode
from tests.conftest import ist
from tests.helpers import cfg
from trading.risk_manager import DAILY_LOSS_LIMIT, KILL_SWITCH_ACTIVE, RiskManager


def test_restart_cannot_clear_daily_loss_halt(tmp_path: pathlib.Path):
    db_file = str(tmp_path / "safety_test.db")
    today = date(2026, 9, 23)

    # Session 1: trigger daily loss limit
    db1 = Database(db_file)
    rm1 = RiskManager(cfg(max_daily_loss=1000.0), db=db1, mode=TradingMode.LIVE)
    d1 = rm1.check_entry(when=ist(2026, 9, 23, 10, 0), entry_price=100.0,
                         realized_pnl_today=-1500.0, entries_today=0)
    assert not d1.allowed
    assert d1.reason == DAILY_LOSS_LIMIT
    db1.close()

    # Session 2: Fresh database instance on the same file (process restarted)
    db2 = Database(db_file)
    rm2 = RiskManager(cfg(max_daily_loss=1000.0), db=db2, mode=TradingMode.LIVE)
    # Even if session 2 starts with 0.0 in-memory realized pnl, persisted latch blocks it
    d2 = rm2.check_entry(when=ist(2026, 9, 23, 11, 0), entry_price=100.0,
                         realized_pnl_today=0.0, entries_today=0)
    assert not d2.allowed
    assert d2.reason == DAILY_LOSS_LIMIT
    db2.close()


def test_restart_cannot_clear_kill_switch(tmp_path: pathlib.Path):
    db_file = str(tmp_path / "safety_test.db")

    # Session 1: activate kill switch
    db1 = Database(db_file)
    db1.set_kill_switch(TradingMode.LIVE, active=True)
    db1.close()

    # Session 2: new DB instance on same file
    db2 = Database(db_file)
    assert db2.is_kill_switch_active(TradingMode.LIVE) is True
    rm = RiskManager(cfg(), db=db2, mode=TradingMode.LIVE)
    d = rm.check_entry(when=ist(2026, 9, 23, 10, 0), entry_price=100.0,
                       realized_pnl_today=0.0, entries_today=0)
    assert not d.allowed
    assert d.reason == KILL_SWITCH_ACTIVE
    db2.close()


def test_kill_switch_requires_explicit_user_clear(tmp_path: pathlib.Path):
    db_file = str(tmp_path / "safety_test.db")
    db = Database(db_file)
    db.set_kill_switch(TradingMode.LIVE, active=True)
    assert db.is_kill_switch_active(TradingMode.LIVE) is True

    # Remains active across queries
    assert db.is_kill_switch_active(TradingMode.LIVE) is True

    # Only explicit deactivation clears it
    db.set_kill_switch(TradingMode.LIVE, active=False)
    assert db.is_kill_switch_active(TradingMode.LIVE) is False
    db.close()


def test_position_with_no_stop_order_is_unprotected_in_live():
    p = Position(
        mode=TradingMode.LIVE, symbol="INFY", side=Side.BUY, quantity=10,
        entry_price=1500.0, entry_time=ist(2026, 9, 23, 10), stop_price=1485.0,
        stop_order_id=None,
    )
    assert p.protection is PositionProtection.UNPROTECTED


def test_position_with_stop_order_is_protected_in_live():
    p = Position(
        mode=TradingMode.LIVE, symbol="INFY", side=Side.BUY, quantity=10,
        entry_price=1500.0, entry_time=ist(2026, 9, 23, 10), stop_price=1485.0,
        stop_order_id="RESTING_STOP_101",
    )
    assert p.protection is PositionProtection.PROTECTED


def test_paper_position_does_not_require_stop_order_id():
    p = Position(
        mode=TradingMode.PAPER, symbol="INFY", side=Side.BUY, quantity=10,
        entry_price=1500.0, entry_time=ist(2026, 9, 23, 10), stop_price=1485.0,
        stop_order_id=None,
    )
    # Paper positions are simulated and thus considered PROTECTED without broker stop_order_id
    assert p.protection is PositionProtection.PROTECTED
