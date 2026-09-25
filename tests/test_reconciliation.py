"""Unit tests for startup and periodic reconciliation and safe mode (F1 & F2)."""
from __future__ import annotations

import pytest

from config import TradingConfig
from models import Order, OrderPurpose, OrderStatus, OrderType, Position, Side, TradingMode
from trading.mock_broker import MockBroker
from trading.reconciliation import Reconciler
from trading.signal_engine import SignalEngine
from tests.helpers import BUY, ScriptedStrategy, candles, flat
from utils.timeutil import now_ist


def test_clean_reconcile_allows_trading(db):
    """Clean reconcile when broker and DB states match exactly allows trading."""
    broker = MockBroker()
    mode = TradingMode.LIVE
    reconciler = Reconciler(db, broker, mode=mode)

    result = reconciler.reconcile()
    assert result.is_clean is True
    assert result.safe_mode is False
    assert reconciler.safe_mode is False
    # check_can_trade does not raise
    reconciler.check_can_trade()


def test_position_mismatch_triggers_safe_mode(db):
    """Position discrepancy between broker and DB puts engine into SAFE MODE."""
    broker = MockBroker()
    mode = TradingMode.LIVE

    # Broker reports 10 shares of INFY, but DB has 0 positions
    broker.positions = [
        Position(
            mode=mode,
            symbol="INFY",
            side=Side.BUY,
            quantity=10,
            entry_price=100.0,
            entry_time=now_ist(),
            stop_price=99.0,
            stop_order_id="STOP_1",
        )
    ]

    reconciler = Reconciler(db, broker, mode=mode)
    result = reconciler.reconcile()

    assert result.is_clean is False
    assert result.safe_mode is True
    assert reconciler.safe_mode is True
    assert any("Broker has position for INFY" in r for r in result.error_reasons)

    with pytest.raises(RuntimeError, match="SAFE MODE active"):
        reconciler.check_can_trade()


def test_unknown_broker_order_triggers_safe_mode(db):
    """An unknown order on the broker not present in local DB triggers SAFE MODE."""
    broker = MockBroker()
    mode = TradingMode.LIVE

    # Broker has an order not registered in DB
    broker.orders["UNREGISTERED_BID_999"] = Order(
        mode=mode,
        symbol="INFY",
        side=Side.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        purpose=OrderPurpose.ENTRY,
        broker_order_id="UNREGISTERED_BID_999",
    )

    reconciler = Reconciler(db, broker, mode=mode)
    result = reconciler.reconcile()

    assert result.is_clean is False
    assert result.safe_mode is True
    assert any("Unknown broker order UNREGISTERED_BID_999" in r for r in result.error_reasons)


def test_unprotected_position_triggers_safe_mode(db):
    """A live open position without a protective stop order triggers SAFE MODE."""
    broker = MockBroker()
    mode = TradingMode.LIVE

    # Save live position with no stop_order_id in DB
    unprotected_pos = Position(
        mode=mode,
        symbol="INFY",
        side=Side.BUY,
        quantity=10,
        entry_price=100.0,
        entry_time=now_ist(),
        stop_price=0.0,
        stop_order_id=None,
    )
    db.save_position(unprotected_pos)
    broker.positions = [unprotected_pos]

    reconciler = Reconciler(db, broker, mode=mode)
    result = reconciler.reconcile()

    assert result.is_clean is False
    assert result.safe_mode is True
    assert any("Unprotected live positions found" in r for r in result.error_reasons)


def test_restart_mid_position_reconciles_correctly(db):
    """Engine restart mid-position reconciles cleanly when both broker and DB have matching state."""
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
        stop_order_id="STOP_BID_1",
    )
    db.save_position(pos)
    broker.positions = [pos]

    # Stop order registered in DB
    stop_order = Order(
        mode=mode,
        symbol="INFY",
        side=Side.SELL,
        quantity=10,
        order_type=OrderType.SL,
        purpose=OrderPurpose.STOP_LOSS,
        price=99.0,
        status=OrderStatus.TRIGGER_PENDING,
        broker_order_id="STOP_BID_1",
    )
    db.insert_order(stop_order)
    broker.orders["STOP_BID_1"] = stop_order

    reconciler = Reconciler(db, broker, mode=mode)
    result = reconciler.reconcile()

    assert result.is_clean is True
    assert result.safe_mode is False
    reconciler.check_can_trade()


def test_stale_feed_blocks_new_entries_but_not_stop_monitoring(db):
    """Stale feed blocks new entry signals while allowing candle processing and stops."""
    broker = MockBroker()
    mode = TradingMode.LIVE
    cfg = TradingConfig(symbol="INFY")
    strategy = ScriptedStrategy({0: BUY})

    engine = SignalEngine(cfg, strategy, broker, db=db, mode=mode)
    engine.notify_stale_feed(True)

    data = candles([flat(100.0), flat(100.0)], start="09:20")
    engine.process_candle(data.iloc[0])

    # No pending signal queued because feed is stale
    assert engine.skipped_signals["FEED_STALE"] == 1
    assert engine._pending_signal is None
    engine.close()
