"""Unit tests for Broker implementations (MockBroker and PaperBroker)."""
import ast
import pathlib
import pytest

from config import TradingConfig
from models import Order, OrderPurpose, OrderStatus, OrderType, Side, TradingMode
from trading.broker import NetworkException, OrderInfo
from trading.mock_broker import MockBroker
from trading.paper_broker import PaperBroker
from market.live_data import FakeFeed
from utils.timeutil import now_ist


def make_order(purpose: OrderPurpose = OrderPurpose.ENTRY, qty: int = 10, price: float = 100.0) -> Order:
    return Order(
        mode=TradingMode.PAPER,
        symbol="INFY",
        side=Side.BUY,
        quantity=qty,
        order_type=OrderType.MARKET if purpose is not OrderPurpose.STOP_LOSS else OrderType.SL,
        purpose=purpose,
        price=price if purpose is OrderPurpose.STOP_LOSS else None,
    )


def test_mock_broker_immediate_success():
    broker = MockBroker()
    o = make_order()
    bid = broker.place_order(o)
    assert bid.startswith("MOCK_")
    info = broker.get_order_info(bid)
    assert info.status is OrderStatus.COMPLETE
    assert info.filled_quantity == 10
    assert info.fill_price == 100.0


def test_mock_broker_delayed_fill_returns_pending_then_complete():
    broker = MockBroker()
    o = make_order()
    bid = broker.place_order(o)

    # Configure delayed polling sequence: PENDING -> COMPLETE
    broker.status_sequences[bid] = [
        OrderInfo(broker_order_id=bid, status=OrderStatus.PENDING, fill_price=None, filled_quantity=0),
        OrderInfo(broker_order_id=bid, status=OrderStatus.COMPLETE, fill_price=101.5, filled_quantity=10),
    ]

    status1 = broker.get_order_status(bid)
    assert status1 is OrderStatus.PENDING

    status2 = broker.get_order_status(bid)
    assert status2 is OrderStatus.COMPLETE
    info2 = broker.get_order_info(bid)
    assert info2.fill_price == 101.5


def test_mock_broker_rejection():
    broker = MockBroker()
    o = make_order()
    bid = broker.place_order(o)
    broker.order_info[bid].status = OrderStatus.REJECTED
    assert broker.get_order_status(bid) is OrderStatus.REJECTED


def test_mock_broker_timeout_returns_unknown():
    broker = MockBroker()
    # Unrecognized or timed out order returns UNKNOWN
    info = broker.get_order_info("NON_EXISTENT_ID")
    assert info.status is OrderStatus.UNKNOWN


def test_mock_broker_partial_fill_sized_to_filled_quantity():
    broker = MockBroker()
    o = make_order(qty=100)
    bid = broker.place_order(o)
    broker.order_info[bid] = OrderInfo(
        broker_order_id=bid,
        status=OrderStatus.OPEN,
        fill_price=100.0,
        filled_quantity=40,
    )
    info = broker.get_order_info(bid)
    assert info.filled_quantity == 40
    assert info.filled_quantity < o.quantity


def test_mock_broker_disconnect_raises():
    broker = MockBroker()
    broker.raise_on_place = True
    with pytest.raises(NetworkException, match="Network timeout"):
        broker.place_order(make_order())

    broker.raise_on_place = False
    bid = broker.place_order(make_order())

    broker.raise_on_get_status = True
    with pytest.raises(NetworkException, match="Network timeout"):
        broker.get_order_status(bid)


def test_mock_broker_stop_fills_during_cancel_h1_race():
    broker = MockBroker()
    stop_order = make_order(purpose=OrderPurpose.STOP_LOSS, qty=10, price=95.0)
    bid = broker.place_order(stop_order)
    assert broker.get_order_status(bid) is OrderStatus.TRIGGER_PENDING

    # Enable H1 race simulation: cancel returns without error, but order was filled
    broker.stop_fills_during_cancel = True
    broker.cancel_order(bid)
    info = broker.get_order_info(bid)
    assert info.status is OrderStatus.COMPLETE
    assert info.filled_quantity == 10


def test_paper_broker_never_imports_kiteconnect():
    """Verify that trading/paper_broker.py does not import kiteconnect."""
    path = pathlib.Path("trading/paper_broker.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "kiteconnect", "paper_broker.py must never import kiteconnect"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "kiteconnect", "paper_broker.py must never import kiteconnect"


def test_paper_broker_fills_at_next_candle_open():
    cfg = TradingConfig(symbol="INFY", capital=100_000.0, slippage_pct=0.0)
    broker = PaperBroker(cfg)
    feed = FakeFeed.generate(symbol="INFY", candles=5)

    # 1. Place order before candle arrives -> status is SUBMITTED
    o = make_order(qty=10)
    bid = broker.place_order(o)
    assert broker.get_order_status(bid) is OrderStatus.SUBMITTED

    # 2. Next candle arrives -> on_candle fills order at that candle's open
    candle0 = feed.iloc[0]
    broker.on_candle(candle0)
    info = broker.get_order_info(bid)
    assert info.status is OrderStatus.COMPLETE
    assert info.fill_price == float(candle0["open"])
    assert len(broker.get_positions()) == 1
