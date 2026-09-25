"""Unit tests for single-instance guard (H4)."""
from __future__ import annotations

from datetime import timedelta
import pytest

from models import TradingMode
from utils.instance_guard import InstanceGuard
from utils.timeutil import now_ist


def test_second_live_engine_refuses_start(db):
    """H4: A second live engine instance refuses to start while another instance holds a fresh lock."""
    guard1 = InstanceGuard(db, mode=TradingMode.LIVE, pid=1001)
    guard1.acquire()

    guard2 = InstanceGuard(db, mode=TradingMode.LIVE, pid=1002)
    with pytest.raises(RuntimeError, match="Another instance of the live engine is running"):
        guard2.acquire()

    guard1.release()


def test_stale_lock_is_overrideable(db):
    """If the previous process crashed and the lock is stale (>60s), the new instance takes over."""
    guard1 = InstanceGuard(db, mode=TradingMode.LIVE, pid=2001)
    guard1.acquire()

    # Manually backdate the lock timestamp by 70 seconds
    stale_time = now_ist() - timedelta(seconds=70)
    db.write_instance_lock(TradingMode.LIVE, 2001, timestamp=stale_time)

    # Second instance should override cleanly without error
    guard2 = InstanceGuard(db, mode=TradingMode.LIVE, pid=2002)
    guard2.acquire()
    assert guard2.acquired is True

    lock = db.read_instance_lock(TradingMode.LIVE)
    assert lock["pid"] == 2002
    guard2.release()


def test_clean_shutdown_releases_lock(db):
    """Clean release removes the lock row so subsequent instances can acquire immediately."""
    guard = InstanceGuard(db, mode=TradingMode.LIVE, pid=3001)
    guard.acquire()
    assert db.read_instance_lock(TradingMode.LIVE) is not None

    guard.release()
    assert db.read_instance_lock(TradingMode.LIVE) is None

    # Subsequent acquire succeeds immediately
    guard_next = InstanceGuard(db, mode=TradingMode.LIVE, pid=3002)
    guard_next.acquire()
    assert guard_next.acquired is True
    guard_next.release()
