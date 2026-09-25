import threading
from datetime import date, datetime

import pytest

from db import DatabaseError
from models import (
    Order, OrderPurpose, OrderStatus, OrderType, Position, Side, Trade, TradingMode,
)
from tests.conftest import ist
from utils.timeutil import IST

DAY = date(2026, 9, 23)


def order(**kw):
    base = dict(mode=TradingMode.PAPER, symbol="HDFCBANK", side=Side.BUY, quantity=10,
                order_type=OrderType.MARKET, purpose=OrderPurpose.ENTRY, timestamp=ist(2026, 9, 23))
    base.update(kw)
    return Order(**base)


def trade(pnl, mode=TradingMode.PAPER, exit_day=23, symbol="HDFCBANK"):
    return Trade(mode=mode, symbol=symbol, side=Side.BUY, quantity=10, entry_time=ist(2026, 9, exit_day, 10),
                 entry_price=100.0, exit_time=ist(2026, 9, exit_day, 11), exit_price=101.0, pnl=pnl, charges=1.5,
                 reason="target")


# ------------------------------------------------------------------ schema / settings
def test_all_tables_exist(db):
    names = {r["name"] for r in db._query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "orders", "trades", "positions", "backtests", "logs"} <= names


def test_settings_round_trip_and_overwrite(db):
    assert db.get_setting("missing", "dflt") == "dflt"
    db.set_setting("config", {"symbol": "TCS", "n": 3})
    db.set_setting("config", {"symbol": "INFY"})
    assert db.get_setting("config") == {"symbol": "INFY"}


@pytest.mark.parametrize("key", ["kite_access_token", "API_SECRET", "db_password", "api_key"])
def test_settings_refuse_secret_keys(db, key):
    with pytest.raises(ValueError):
        db.set_setting(key, "x")


# ------------------------------------------------------------------ orders
def test_order_round_trip(db):
    o = order(signal_id="sig-1", price=None)
    oid = db.insert_order(o)
    got = db.get_order(oid)
    assert got.id == oid == o.id
    assert (got.mode, got.symbol, got.side, got.quantity) == (TradingMode.PAPER, "HDFCBANK", Side.BUY, 10)
    assert got.status is OrderStatus.CREATED and got.signal_id == "sig-1"
    assert got.timestamp == ist(2026, 9, 23)


def test_order_status_progression_and_fill_recorded(db):
    oid = db.insert_order(order(mode=TradingMode.LIVE))
    db.update_order(oid, status=OrderStatus.SUBMITTED, broker_order_id="2200001")
    db.update_order(oid, status=OrderStatus.OPEN)
    db.update_order(oid, status=OrderStatus.COMPLETE, fill_price=1500.25)
    got = db.get_order(oid)
    assert (got.status, got.broker_order_id, got.fill_price) == (OrderStatus.COMPLETE, "2200001", 1500.25)


@pytest.mark.parametrize("terminal", [OrderStatus.COMPLETE, OrderStatus.REJECTED, OrderStatus.CANCELLED])
def test_terminal_order_cannot_change_state(db, terminal):
    oid = db.insert_order(order())
    db.update_order(oid, status=terminal)
    with pytest.raises(DatabaseError):
        db.update_order(oid, status=OrderStatus.OPEN)
    db.update_order(oid, status=terminal)               # repeating the same terminal state is harmless
    assert db.get_order(oid).status is terminal


def test_update_unknown_order_fails_loudly(db):
    with pytest.raises(DatabaseError):
        db.update_order(999, status=OrderStatus.OPEN)


def test_order_queries_by_mode_day_and_signal(db):
    db.insert_order(order(mode=TradingMode.PAPER, signal_id="a"))
    db.insert_order(order(mode=TradingMode.LIVE, signal_id="a"))
    db.insert_order(order(mode=TradingMode.PAPER, signal_id="b", timestamp=ist(2026, 9, 22)))
    assert len(db.get_orders(mode=TradingMode.PAPER)) == 2
    assert len(db.get_orders(mode=TradingMode.PAPER, day=DAY)) == 1
    assert len(db.get_orders(signal_id="a")) == 2
    assert len(db.get_orders(status=OrderStatus.COMPLETE)) == 0


def test_order_model_validation():
    with pytest.raises(ValueError):
        order(quantity=0)
    with pytest.raises(ValueError):
        order(quantity=2.5)
    with pytest.raises(ValueError):
        order(order_type=OrderType.LIMIT, price=None)
    with pytest.raises(ValueError):
        order(timestamp=datetime(2026, 9, 23, 10, 0))    # naive datetime


def test_database_check_constraints_block_bad_rows(db):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        db._execute("INSERT INTO orders (mode, symbol, side, quantity, order_type, purpose, status, timestamp, updated_at) "
                    "VALUES ('LIVEISH','X','BUY',1,'MARKET','ENTRY','CREATED','t','t')")
    with pytest.raises(sqlite3.IntegrityError):
        db._execute("INSERT INTO orders (mode, symbol, side, quantity, order_type, purpose, status, timestamp, updated_at) "
                    "VALUES ('LIVE','X','BUY',0,'MARKET','ENTRY','CREATED','t','t')")


# ------------------------------------------------------------------ trades / P&L
def test_trade_round_trip(db):
    tid = db.insert_trade(trade(10.0))
    got = db.get_trades()[0]
    assert got.id == tid and got.pnl == 10.0 and got.charges == 1.5 and got.reason == "target"
    assert got.entry_time == ist(2026, 9, 23, 10) and got.exit_time == ist(2026, 9, 23, 11)


def test_realized_pnl_is_per_mode_and_per_exit_day(db):
    db.insert_trade(trade(-300.0))
    db.insert_trade(trade(120.0))
    db.insert_trade(trade(-5000.0, mode=TradingMode.BACKTEST))     # different mode
    db.insert_trade(trade(999.0, exit_day=22))                     # different day
    assert db.realized_pnl(TradingMode.PAPER, DAY) == pytest.approx(-180.0)
    assert db.realized_pnl(TradingMode.LIVE, DAY) == 0.0
    assert db.realized_pnl(TradingMode.BACKTEST, DAY) == -5000.0


def test_day_boundary_uses_ist_not_utc(db):
    # 00:30 IST on the 24th is still the 23rd in UTC; it must count as the 24th.
    t = Trade(mode=TradingMode.PAPER, symbol="X", side=Side.BUY, quantity=1,
              entry_time=datetime(2026, 9, 23, 18, 30, tzinfo=IST), entry_price=1, 
              exit_time=datetime(2026, 9, 24, 0, 30, tzinfo=IST), exit_price=2, pnl=1.0)
    db.insert_trade(t)
    assert db.realized_pnl(TradingMode.PAPER, date(2026, 9, 24)) == 1.0
    assert db.realized_pnl(TradingMode.PAPER, date(2026, 9, 23)) == 0.0


def test_utc_input_is_stored_as_ist(db):
    from datetime import timezone
    t = Trade(mode=TradingMode.PAPER, symbol="X", side=Side.BUY, quantity=1,
              entry_time=datetime(2026, 9, 23, 3, 45, tzinfo=timezone.utc), entry_price=1,
              exit_time=datetime(2026, 9, 23, 19, 0, tzinfo=timezone.utc), exit_price=2, pnl=1.0)   # 00:30 IST next day
    db.insert_trade(t)
    assert db.realized_pnl(TradingMode.PAPER, date(2026, 9, 24)) == 1.0


# ------------------------------------------------------------------ positions
def pos(**kw):
    base = dict(mode=TradingMode.PAPER, symbol="HDFCBANK", side=Side.BUY, quantity=10, entry_price=100.0,
                entry_time=ist(2026, 9, 23), stop_price=99.0, target_price=102.0)
    base.update(kw)
    return Position(**base)


def test_position_save_get_update_delete(db):
    assert db.get_position(TradingMode.PAPER, "HDFCBANK") is None
    db.save_position(pos())
    db.save_position(pos(stop_order_id="2200009"))                   # upsert, not a second row
    got = db.get_position(TradingMode.PAPER, "HDFCBANK")
    assert got.stop_order_id == "2200009" and got.stop_price == 99.0 and got.target_price == 102.0
    assert len(db.get_open_positions(TradingMode.PAPER)) == 1
    assert db.get_open_positions(TradingMode.LIVE) == []
    assert db.delete_position(TradingMode.PAPER, "HDFCBANK") is True
    assert db.delete_position(TradingMode.PAPER, "HDFCBANK") is False


def test_positions_are_separate_per_mode(db):
    db.save_position(pos(mode=TradingMode.PAPER))
    db.save_position(pos(mode=TradingMode.LIVE))
    assert len(db.get_open_positions(TradingMode.PAPER)) == 1
    assert len(db.get_open_positions(TradingMode.LIVE)) == 1


def test_position_requires_sane_stop_and_target():
    with pytest.raises(ValueError):
        pos(stop_price=100.0)              # stop not below entry
    with pytest.raises(ValueError):
        pos(stop_price=101.0)
    with pytest.raises(ValueError):
        pos(target_price=99.5)             # target not above entry
    assert pos(target_price=None).target_price is None


# ------------------------------------------------------------------ backtests / logs / threads
def test_backtest_round_trip(db):
    bid = db.save_backtest("TCS", {"sl": 1.0}, {"net_pnl": 12.5, "trades": []})
    got = db.get_backtest(bid)
    assert got["symbol"] == "TCS" and got["params"] == {"sl": 1.0} and got["result"]["net_pnl"] == 12.5
    assert db.list_backtests()[0]["id"] == bid
    assert db.get_backtest(999) is None


def test_concurrent_inserts_from_threads(db):
    def work():
        for _ in range(25):
            db.insert_order(order())
    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(db.get_orders()) == 150
