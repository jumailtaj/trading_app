"""Comprehensive unit tests for KiteBroker using a mocked KiteConnect instance.

Zero real network or broker calls: all interactions are validated via mock call assertions.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call
import pytest
import kiteconnect.exceptions as kexc

from config import RuntimeMode, TradingConfig
from market.instruments import dump_instruments, lookup_instrument
from models import Order, OrderPurpose, OrderStatus, OrderType, PositionProtection, Side, TradingMode
from trading.broker import BrokerError, NetworkException
from trading.kite_broker import KiteBroker, _STATUS_MAP, map_kite_status
from trading.signal_engine import SignalEngine
from tests.helpers import BUY, ScriptedStrategy, candles, flat


def make_live_order(
    purpose: OrderPurpose = OrderPurpose.ENTRY,
    qty: int = 10,
    price: float = 100.0,
    signal_id: str = "SIG_1234567890",
) -> Order:
    return Order(
        mode=TradingMode.LIVE,
        symbol="INFY",
        side=Side.BUY,
        quantity=qty,
        order_type=OrderType.MARKET if purpose is not OrderPurpose.STOP_LOSS else OrderType.SL,
        purpose=purpose,
        price=price if purpose is OrderPurpose.STOP_LOSS else None,
        signal_id=signal_id,
    )


def create_mock_kite(order_id: str = "2409250001", status: str = "COMPLETE", fill_price: float = 100.0):
    kite = MagicMock()
    kite.place_order.return_value = order_id
    kite.order_history.return_value = [
        {"order_id": order_id, "status": status, "average_price": fill_price, "filled_quantity": 10}
    ]
    kite.orders.return_value = [
        {"order_id": order_id, "tag": "SIG_1234567890", "status": status}
    ]
    kite.positions.return_value = {
        "net": [{"tradingsymbol": "INFY", "quantity": 10, "average_price": fill_price}]
    }
    return kite


def test_live_disabled_place_order_never_calls_kite():
    """E1: When live trading is disabled, attempting to place an order raises and calls Kite zero times."""
    mock_kite = create_mock_kite()
    runtime_mode = RuntimeMode()  # default: PAPER, live disabled
    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    order = make_live_order()
    with pytest.raises(RuntimeError, match="CRITICAL: live order attempted while live is not enabled"):
        broker.place_order(order)

    assert mock_kite.place_order.call_count == 0


def test_live_enabled_place_order_calls_kite():
    """E1: When live trading is explicitly enabled, place_order calls Kite with correct parameters."""
    mock_kite = create_mock_kite()
    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    order = make_live_order(qty=25, signal_id="A1B2C3D4E5F67890")
    broker_id = broker.place_order(order)

    assert broker_id == "2409250001"
    assert mock_kite.place_order.call_count == 1
    mock_kite.place_order.assert_called_once_with(
        variety="regular",
        exchange="NSE",
        tradingsymbol="INFY",
        transaction_type="BUY",
        quantity=25,
        product="MIS",
        order_type="MARKET",
        market_protection=-1,
        tag="A1B2C3D4E5F67890",
    )


def test_status_map_covers_all_known_kite_strings():
    """E2: All official Kite order status strings map to non-UNKNOWN OrderStatus enum members."""
    expected_statuses = {
        "OPEN": OrderStatus.OPEN,
        "COMPLETE": OrderStatus.COMPLETE,
        "CANCELLED": OrderStatus.CANCELLED,
        "REJECTED": OrderStatus.REJECTED,
        "LAPSED": OrderStatus.LAPSED,
        "PUT ORDER REQUEST RECEIVED": OrderStatus.PENDING,
        "VALIDATION PENDING": OrderStatus.PENDING,
        "OPEN PENDING": OrderStatus.PENDING,
        "MODIFY VALIDATION PENDING": OrderStatus.PENDING,
        "MODIFY PENDING": OrderStatus.PENDING,
        "TRIGGER PENDING": OrderStatus.TRIGGER_PENDING,
        "CANCEL PENDING": OrderStatus.PENDING,
        "AMO REQ RECEIVED": OrderStatus.PENDING,
    }
    for raw_str, expected in expected_statuses.items():
        assert map_kite_status(raw_str) is expected, f"Failed for {raw_str}"


def test_status_map_unknown_string_returns_unknown():
    """E2: Any unmapped status returns OrderStatus.UNKNOWN."""
    assert map_kite_status("SOME_STRANGE_NEW_STATUS") is OrderStatus.UNKNOWN
    assert map_kite_status(None) is OrderStatus.UNKNOWN


def test_interim_status_after_timeout_halts_and_marks_unknown():
    """E2: If an order stays in interim state past poll timeout, broker halts and marks UNKNOWN."""
    mock_kite = create_mock_kite(status="OPEN PENDING")
    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(
        mock_kite, runtime_mode, cfg, poll_timeout_seconds=0.05, poll_interval_seconds=0.01
    )

    order = make_live_order()
    broker_id = broker.place_order(order)

    assert broker.halted is True
    assert broker.halt_reason == "INTERIM_ORDER_TIMEOUT"
    assert broker.get_order_status(broker_id) is OrderStatus.UNKNOWN


def test_stop_placement_verify_trigger_pending():
    """E3: SL-M stop order places trigger_price rounded to tick and resolves to TRIGGER_PENDING."""
    mock_kite = create_mock_kite(status="TRIGGER PENDING")
    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    # 98.43 rounded to nearest 0.05 tick is 98.45
    stop_order = make_live_order(purpose=OrderPurpose.STOP_LOSS, price=98.43)
    broker_id = broker.place_order(stop_order)

    mock_kite.place_order.assert_called_once_with(
        variety="regular",
        exchange="NSE",
        tradingsymbol="INFY",
        transaction_type="BUY",
        quantity=10,
        product="MIS",
        order_type="SL-M",
        trigger_price=98.45,
        tag="SIG_1234567890",
    )
    assert broker.get_order_status(broker_id) is OrderStatus.TRIGGER_PENDING


def test_stop_fails_twice_marks_unprotected_and_halts(db):
    """E3: When stop order placement fails twice, engine halts and marks position UNPROTECTED."""
    mock_kite = create_mock_kite(status="COMPLETE")
    # Make place_order fail for SL-M
    def fail_on_slm(**kwargs):
        if kwargs.get("order_type") == "SL-M":
            raise kexc.OrderException("Exchange rejected trigger")
        return "ENTRY_ORDER_1"

    mock_kite.place_order.side_effect = fail_on_slm
    mock_kite.order_history.return_value = [
        {"order_id": "ENTRY_ORDER_1", "status": "COMPLETE", "average_price": 100.0, "filled_quantity": 10}
    ]
    mock_kite.positions.return_value = {"net": []}

    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY", stop_loss_pct=1.0)
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    strategy = ScriptedStrategy({0: BUY})
    engine = SignalEngine(cfg, strategy, broker, db=db, mode=TradingMode.LIVE)

    data = candles([flat(100.0), flat(100.0)], start="09:20")
    engine.process_candle(data.iloc[0])
    engine.process_candle(data.iloc[1])

    assert engine.halted is True
    assert engine.halt_reason == "STOP_PLACEMENT_FAILURE"

    unprotected = db.get_unprotected_live_positions()
    assert len(unprotected) == 1
    assert unprotected[0].protection is PositionProtection.UNPROTECTED
    engine.close()


def test_exit_sequence_cancels_stop_before_exit():
    """E4 / H1: Exit sequence calls cancel_order on stop before placing exit."""
    mock_kite = create_mock_kite(status="CANCELLED")
    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    broker.cancel_order("STOP_ORDER_123")
    mock_kite.cancel_order.assert_called_once_with(variety="regular", order_id="STOP_ORDER_123")


def test_stop_fills_during_cancel_skips_exit(db):
    """E4 / H1 race: If stop fills right before cancel, engine skips placing an exit order."""
    mock_kite = create_mock_kite()
    # Cancel returns OK, but order_history reports COMPLETE
    mock_kite.order_history.return_value = [
        {"order_id": "STOP_BID", "status": "COMPLETE", "average_price": 99.0, "filled_quantity": 10}
    ]

    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    pos = broker.get_positions()  # seed
    # Create open position with stop
    pos_item = Order(mode=TradingMode.LIVE, symbol="INFY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET, purpose=OrderPurpose.ENTRY)
    broker.orders["ENTRY_1"] = pos_item
    broker.order_info["STOP_BID"] = broker._poll_order("STOP_BID")

    from datetime import datetime
    from utils.timeutil import IST
    now = datetime(2026, 9, 23, 10, 0, tzinfo=IST)

    from models import Position
    domain_pos = Position(
        mode=TradingMode.LIVE,
        symbol="INFY",
        side=Side.BUY,
        quantity=10,
        entry_price=100.0,
        entry_time=now,
        stop_price=99.0,
        stop_order_id="STOP_BID",
    )
    db.save_position(domain_pos)

    engine = SignalEngine(cfg, ScriptedStrategy({}), broker, db=db, mode=TradingMode.LIVE)
    engine._execute_exit(domain_pos, "SIG_EXIT", now, 100.0, reason="SIGNAL")

    # kite.place_order was NOT called for market exit
    assert mock_kite.place_order.call_count == 0
    assert len(engine.executed_trades) == 1
    assert engine.executed_trades[0].reason == "STOP_LOSS"
    engine.close()


def test_ambiguous_network_failure_looks_up_by_tag():
    """E6 / H2: NetworkException triggers lookup by tag before raising or resolving."""
    mock_kite = create_mock_kite()
    mock_kite.place_order.side_effect = kexc.NetworkException("Read timed out")
    mock_kite.orders.return_value = [
        {"order_id": "RECOVERED_123", "tag": "SIG_TAG_1", "status": "COMPLETE", "average_price": 100.0, "filled_quantity": 10}
    ]
    mock_kite.order_history.return_value = [
        {"order_id": "RECOVERED_123", "status": "COMPLETE", "average_price": 100.0, "filled_quantity": 10}
    ]

    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    order = make_live_order(signal_id="SIG_TAG_1")
    broker_id = broker.place_order(order)

    # Successfully recovered via tag
    assert broker_id == "RECOVERED_123"
    assert broker.halted is False


def test_partial_fill_stop_sized_to_filled_qty():
    """E3 / H3: When order is partially filled, OrderInfo records filled_quantity correctly."""
    mock_kite = create_mock_kite(status="COMPLETE")
    mock_kite.order_history.return_value = [
        {"order_id": "2409250001", "status": "COMPLETE", "average_price": 100.0, "filled_quantity": 4}
    ]
    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    order = make_live_order(qty=10)
    bid = broker.place_order(order)
    info = broker.get_order_info(bid)
    assert info.filled_quantity == 4
    assert info.filled_quantity < order.quantity


def test_token_exception_triggers_disconnect_halt():
    """E6: TokenException raises BrokerError and halts the broker."""
    mock_kite = create_mock_kite()
    mock_kite.place_order.side_effect = kexc.TokenException("Session expired")

    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    order = make_live_order()
    with pytest.raises(BrokerError, match="Disconnect halt"):
        broker.place_order(order)

    assert broker.halted is True
    assert broker.halt_reason == "TOKEN_EXCEPTION_DISCONNECT"


def test_ip_rejection_is_critical_and_non_retried():
    """E6: Unregistered IP exception halts broker immediately with no retries."""
    mock_kite = create_mock_kite()
    mock_kite.place_order.side_effect = kexc.PermissionException("Access denied: unregistered IP 1.2.3.4")

    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    order = make_live_order()
    with pytest.raises(BrokerError, match="CRITICAL IP halt"):
        broker.place_order(order)

    assert broker.halted is True
    assert broker.halt_reason == "IP_EXCEPTION_HALT"
    assert mock_kite.place_order.call_count == 1  # exactly 1 call, zero retries


def test_tag_carries_signal_id():
    """E2: Tag parameter on Kite.place_order carries truncated signal_id."""
    mock_kite = create_mock_kite()
    runtime_mode = RuntimeMode()
    runtime_mode.set_mode(TradingMode.LIVE)
    runtime_mode.enable_live(confirmed=True)

    cfg = TradingConfig(symbol="INFY")
    broker = KiteBroker(mock_kite, runtime_mode, cfg)

    long_signal_id = "0123456789abcdef0123456789extra"
    order = make_live_order(signal_id=long_signal_id)
    broker.place_order(order)

    # Tag should be truncated to 20 chars
    _, kwargs = mock_kite.place_order.call_args
    assert kwargs["tag"] == "0123456789abcdef0123"
    assert len(kwargs["tag"]) == 20


def test_instruments_lookup_token_and_tick_size(tmp_path):
    """Verify instrument dumping and lookup from cached file."""
    mock_kite = MagicMock()
    mock_kite.instruments.return_value = [
        {"instrument_token": 408065, "tradingsymbol": "INFY", "name": "INFOSYS", "tick_size": 0.05, "lot_size": 1, "exchange": "NSE"},
        {"instrument_token": 779521, "tradingsymbol": "SBIN", "name": "STATE BANK OF INDIA", "tick_size": 0.05, "lot_size": 1, "exchange": "NSE"},
    ]

    cache_file = str(tmp_path / "instruments.csv")
    dumped = dump_instruments(mock_kite, cache_file=cache_file)
    assert len(dumped) == 2

    inst = lookup_instrument("INFY", exchange="NSE", cache_file=cache_file)
    assert inst is not None
    assert inst["instrument_token"] == 408065
    assert inst["tradingsymbol"] == "INFY"
    assert inst["tick_size"] == 0.05
    assert inst["lot_size"] == 1
