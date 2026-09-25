"""End-to-end integration and safety tests for SignalEngine."""
from datetime import datetime, time
import pytest
import pandas as pd

from backtest.engine import Backtester
from config import TradingConfig
from db import Database
from market.live_data import ReplayFeed
from models import Order, OrderPurpose, OrderStatus, OrderType, PositionProtection, Side, Signal, TradingMode
from tests.conftest import ist
from tests.helpers import BUY, HOLD, NO_FEES, SELL, ScriptedStrategy, candles, cfg, flat, session
from trading.broker import NetworkException, OrderInfo
from trading.mock_broker import MockBroker
from trading.paper_broker import PaperBroker
from trading.signal_engine import SignalEngine
from utils.charges import ChargesConfig


@pytest.fixture(autouse=True)
def cleanup_engine_singleton():
    """Ensure SignalEngine singleton instance is reset between tests."""
    SignalEngine._active_instance = None
    yield
    SignalEngine._active_instance = None


def test_parity_backtest_vs_paper_engine(db: Database):
    """Parity test (D4): Verify that Backtester and SignalEngine + PaperBroker produce identical trades."""
    # 10 flat candles at 100.0, with a price move at candle 6 to 105.0
    c_list = [flat(100.0)] * 10
    c_list[6] = (105.0, 106.0, 104.0, 105.0)
    c_list[7] = (105.0, 105.0, 105.0, 105.0)
    data = candles(c_list, start="09:20")

    # Script: BUY at candle 1 (fills at candle 2 open), SELL at candle 5 (exits at candle 6 open)
    script = {1: BUY, 5: SELL}
    strategy = ScriptedStrategy(script)
    test_cfg = cfg(trading_start=time(9, 20), trading_end=time(15, 0), square_off_time=time(15, 15), slippage_pct=0.0)

    # 1. Run through Backtester
    backtester = Backtester(test_cfg, strategy, charges=NO_FEES, filter_hours=False)
    bt_result = backtester.run(data)

    # 2. Run through SignalEngine with PaperBroker
    paper_broker = PaperBroker(test_cfg, charges=NO_FEES)
    engine = SignalEngine(test_cfg, strategy, paper_broker, db=db, mode=TradingMode.PAPER)
    feed = ReplayFeed(data)
    engine_trades = engine.run_replay(feed)

    # Parity assertions
    assert len(bt_result.trades) == len(engine_trades)
    assert len(engine_trades) == 1

    bt_t = bt_result.trades[0]
    eng_t = engine_trades[0]

    assert bt_t.symbol == eng_t.symbol
    assert bt_t.quantity == eng_t.quantity
    assert bt_t.entry_time == eng_t.entry_time
    assert bt_t.entry_price == eng_t.entry_price
    assert bt_t.exit_time == eng_t.exit_time
    assert bt_t.exit_price == eng_t.exit_price
    assert abs(bt_t.pnl - eng_t.pnl) < 1e-6


def test_duplicate_signal_id_skipped(db: Database):
    """Ensure duplicate signals with identical signal_id are skipped without error."""
    test_cfg = cfg(trading_start=time(9, 20), trading_end=time(15, 0), square_off_time=time(15, 15))
    strategy = ScriptedStrategy({0: BUY})
    mock_broker = MockBroker()
    engine = SignalEngine(test_cfg, strategy, mock_broker, db=db, mode=TradingMode.PAPER)

    c0 = candles([flat(100.0)], start="09:20").iloc[0]
    engine.process_candle(c0)
    assert engine.skipped_signals["DUPLICATE_SIGNAL"] == 0

    # Feeding the exact same candle again produces duplicate signal_id
    engine.process_candle(c0)
    assert engine.skipped_signals["DUPLICATE_SIGNAL"] == 1


def test_entry_with_failed_stop_halts_engine_and_marks_unprotected(db: Database):
    """If stop placement fails after retries, engine halts and position is marked UNPROTECTED."""
    test_cfg = cfg(trading_start=time(9, 20), trading_end=time(15, 0), square_off_time=time(15, 15))
    strategy = ScriptedStrategy({0: BUY})
    mock_broker = MockBroker()
    mock_broker.fail_stop_orders = True  # Stop placement will fail

    engine = SignalEngine(test_cfg, strategy, mock_broker, db=db, mode=TradingMode.LIVE)
    data = candles([flat(100.0), flat(100.0)], start="09:20")

    # Candle 0 queues BUY; Candle 1 executes entry
    engine.process_candle(data.iloc[0])
    engine.process_candle(data.iloc[1])

    assert engine.halted is True
    assert engine.halt_reason == "STOP_PLACEMENT_FAILURE"

    # Verify position is stored with stop_order_id = None (UNPROTECTED)
    unprotected = db.get_unprotected_live_positions()
    assert len(unprotected) == 1
    assert unprotected[0].protection is PositionProtection.UNPROTECTED


def test_stop_fills_during_exit_cancel_does_not_double_sell(db: Database):
    """H1 race: If stop order fills right as cancel is attempted, engine avoids double selling."""
    test_cfg = cfg(trading_start=time(9, 20), trading_end=time(15, 0), square_off_time=time(15, 15))
    strategy = ScriptedStrategy({0: BUY, 1: SELL})
    mock_broker = MockBroker()

    engine = SignalEngine(test_cfg, strategy, mock_broker, db=db, mode=TradingMode.LIVE)
    data = candles([flat(100.0), flat(100.0), flat(100.0)], start="09:20")

    # Candle 0 queues BUY, Candle 1 fills entry and queues SELL
    engine.process_candle(data.iloc[0])
    engine.process_candle(data.iloc[1])

    # Now enable H1 race simulation: cancel returns OK but stop filled
    mock_broker.stop_fills_during_cancel = True
    orders_before = len(mock_broker.orders)

    # Candle 2 processes exit
    engine.process_candle(data.iloc[2])

    # Engine should NOT have placed a new market exit order
    # (only the entry and original stop orders exist)
    exit_orders = [o for o in mock_broker.orders.values() if o.purpose is OrderPurpose.EXIT]
    assert len(exit_orders) == 0

    # Trade is recorded with reason STOP_LOSS
    assert len(engine.executed_trades) == 1
    assert engine.executed_trades[0].reason == "STOP_LOSS"


def test_ambiguous_place_order_failure_halts_new_orders(db: Database):
    """H2 ambiguous failure: NetworkException on place_order halts engine."""
    test_cfg = cfg(trading_start=time(9, 20), trading_end=time(15, 0), square_off_time=time(15, 15))
    strategy = ScriptedStrategy({0: BUY, 1: BUY})
    mock_broker = MockBroker()
    mock_broker.raise_on_place = True

    engine = SignalEngine(test_cfg, strategy, mock_broker, db=db, mode=TradingMode.LIVE)
    data = candles([flat(100.0), flat(100.0), flat(100.0)], start="09:20")

    engine.process_candle(data.iloc[0])
    engine.process_candle(data.iloc[1])

    assert engine.halted is True
    assert engine.halt_reason == "AMBIGUOUS_PLACE_FAILURE"

    # Subsequent candles are ignored
    engine.process_candle(data.iloc[2])
    assert len(mock_broker.orders) == 0


def test_partial_fill_stop_sized_to_filled_qty(db: Database):
    """H3: Stop-loss order is sized to filled_quantity when a partial fill occurs."""
    test_cfg = cfg(trading_start=time(9, 20), trading_end=time(15, 0), square_off_time=time(15, 15))
    strategy = ScriptedStrategy({0: BUY})
    mock_broker = MockBroker()

    # Override place_order to return partial fill (40 shares out of 500)
    original_place = mock_broker.place_order
    def partial_place(order: Order):
        bid = original_place(order)
        if order.purpose is OrderPurpose.ENTRY:
            mock_broker.order_info[bid].filled_quantity = 40
        return bid

    mock_broker.place_order = partial_place
    engine = SignalEngine(test_cfg, strategy, mock_broker, db=db, mode=TradingMode.PAPER)
    data = candles([flat(100.0), flat(100.0)], start="09:20")

    engine.process_candle(data.iloc[0])
    engine.process_candle(data.iloc[1])

    # Find the stop order
    stop_orders = [o for o in mock_broker.orders.values() if o.purpose is OrderPurpose.STOP_LOSS]
    assert len(stop_orders) == 1
    assert stop_orders[0].quantity == 40


def test_end_of_day_square_off_at_configured_time(db: Database):
    """Position is closed at or after square_off_time with reason SQUARE_OFF."""
    test_cfg = cfg(trading_start=time(9, 20), trading_end=time(15, 0), square_off_time=time(15, 15))
    strategy = ScriptedStrategy({0: BUY})
    mock_broker = MockBroker()

    engine = SignalEngine(test_cfg, strategy, mock_broker, db=db, mode=TradingMode.PAPER)
    # Candle 0 (09:20), Candle 1 (09:25 entry fill), Candle 2 (15:15 square off)
    c0 = candles([flat(100.0)], start="09:20").iloc[0]
    c1 = candles([flat(100.0)], start="09:25").iloc[0]
    c_eod = candles([flat(102.0)], start="15:15").iloc[0]

    engine.process_candle(c0)
    engine.process_candle(c1)
    assert len(engine.executed_trades) == 0

    # Candle at 15:15 triggers EOD square-off
    engine.process_candle(c_eod)
    assert len(engine.executed_trades) == 1
    assert engine.executed_trades[0].reason == "SQUARE_OFF"


def test_engine_is_process_singleton():
    """H4 early version: Only one SignalEngine instance may be active simultaneously."""
    test_cfg = cfg()
    mock_broker = MockBroker()
    strategy = ScriptedStrategy({})

    engine1 = SignalEngine(test_cfg, strategy, mock_broker, mode=TradingMode.PAPER)
    assert SignalEngine._active_instance is engine1

    with pytest.raises(RuntimeError, match="Only one SignalEngine instance may be active"):
        SignalEngine(test_cfg, strategy, mock_broker, mode=TradingMode.PAPER)

    engine1.close()
    assert SignalEngine._active_instance is None

    # Now a new instance can be created
    engine2 = SignalEngine(test_cfg, strategy, mock_broker, mode=TradingMode.PAPER)
    assert SignalEngine._active_instance is engine2
    engine2.close()
