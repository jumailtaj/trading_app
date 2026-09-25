"""Unit tests for emergency stop and kill switch management (H5)."""
from __future__ import annotations

import pytest

from models import Order, OrderPurpose, OrderStatus, OrderType, Position, Side, TradingMode
from trading.emergency_stop import EmergencyStop
from trading.mock_broker import MockBroker
from utils.timeutil import now_ist


def make_order(
    mode: TradingMode = TradingMode.LIVE,
    symbol: str = "INFY",
    purpose: OrderPurpose = OrderPurpose.ENTRY,
    status: OrderStatus = OrderStatus.SUBMITTED,
    broker_order_id: str = "BID_1",
    price: Optional[float] = None,
) -> Order:
    calc_price = price if price is not None else (99.0 if purpose is OrderPurpose.STOP_LOSS else None)
    return Order(
        mode=mode,
        symbol=symbol,
        side=Side.BUY,
        quantity=10,
        order_type=OrderType.MARKET if purpose is not OrderPurpose.STOP_LOSS else OrderType.SL,
        purpose=purpose,
        price=calc_price,
        status=status,
        broker_order_id=broker_order_id,
    )


def test_emergency_stop_sets_kill_switch(db):
    """Emergency stop activation immediately persists the kill switch in the DB."""
    broker = MockBroker()
    mode = TradingMode.LIVE
    assert db.is_kill_switch_active(mode) is False

    res = EmergencyStop.activate(db, broker, mode)
    assert res["kill_switch_active"] is True
    assert db.is_kill_switch_active(mode) is True


def test_emergency_stop_cancels_pending_entries_only(db):
    """Emergency stop cancels pending ENTRY orders, while leaving exits and stops."""
    broker = MockBroker()
    mode = TradingMode.LIVE

    entry = make_order(purpose=OrderPurpose.ENTRY, broker_order_id="ENTRY_BID")
    stop = make_order(purpose=OrderPurpose.STOP_LOSS, broker_order_id="STOP_BID")
    exit_ord = make_order(purpose=OrderPurpose.EXIT, broker_order_id="EXIT_BID")

    db.insert_order(entry)
    db.insert_order(stop)
    db.insert_order(exit_ord)

    res = EmergencyStop.activate(db, broker, mode)
    cancelled_ids = [o.id for o in res["cancelled_entries"]]
    assert entry.id in cancelled_ids
    assert stop.id not in cancelled_ids
    assert exit_ord.id not in cancelled_ids

    # DB status verified
    assert db.get_order(entry.id).status is OrderStatus.CANCELLED
    assert db.get_order(stop.id).status is OrderStatus.SUBMITTED
    assert db.get_order(exit_ord.id).status is OrderStatus.SUBMITTED


def test_emergency_stop_does_not_cancel_protective_stops(db):
    """H5: Emergency stop must NEVER cancel resting protective stop orders."""
    broker = MockBroker()
    mode = TradingMode.LIVE

    cancelled_broker_ids: list[str] = []
    broker.cancel_hook = lambda bid: cancelled_broker_ids.append(bid)

    stop = make_order(purpose=OrderPurpose.STOP_LOSS, broker_order_id="STOP_BID_123")
    db.insert_order(stop)

    EmergencyStop.activate(db, broker, mode)

    assert "STOP_BID_123" not in cancelled_broker_ids
    assert db.get_order(stop.id).status is OrderStatus.SUBMITTED


def test_emergency_stop_does_not_close_positions(db):
    """Emergency stop leaves open positions untouched; flattening is a separate action."""
    broker = MockBroker()
    mode = TradingMode.LIVE

    pos = Position(
        mode=mode,
        symbol="INFY",
        side=Side.BUY,
        quantity=10,
        entry_price=100.0,
        entry_time=now_ist(),
        stop_price=99.0,
        stop_order_id="STOP_1",
    )
    db.save_position(pos)

    EmergencyStop.activate(db, broker, mode)

    open_pos = db.get_open_positions(mode)
    assert len(open_pos) == 1
    assert open_pos[0].symbol == "INFY"


def test_kill_switch_requires_confirmation_token_to_clear(db):
    """Clearing the kill switch requires exact token 'CONFIRM_CLEAR'; wrong token raises."""
    mode = TradingMode.LIVE
    db.set_kill_switch(mode, True)
    assert db.is_kill_switch_active(mode) is True

    with pytest.raises(ValueError, match="Invalid confirmation token"):
        db.clear_kill_switch(mode, "WRONG_TOKEN")

    assert db.is_kill_switch_active(mode) is True

    # Correct token successfully clears it
    db.clear_kill_switch(mode, "CONFIRM_CLEAR")
    assert db.is_kill_switch_active(mode) is False


def test_flatten_is_separate_explicit_action(db):
    """Flattening requires confirmed=True, cancels stops, and places market exit orders."""
    broker = MockBroker()
    mode = TradingMode.LIVE

    pos = Position(
        mode=mode,
        symbol="INFY",
        side=Side.BUY,
        quantity=10,
        entry_price=100.0,
        entry_time=now_ist(),
        stop_price=99.0,
        stop_order_id="STOP_1",
    )
    db.save_position(pos)

    # Calling without confirmed=True raises
    with pytest.raises(ValueError, match="FLATTEN requires confirmed=True"):
        EmergencyStop.flatten_all(db, broker, mode, confirmed=False)

    # Calling with confirmed=True executes flatten
    exits = EmergencyStop.flatten_all(db, broker, mode, confirmed=True)
    assert len(exits) == 1
    assert exits[0].purpose is OrderPurpose.EXIT
    assert exits[0].side is Side.SELL
    assert len(db.get_open_positions(mode)) == 0
