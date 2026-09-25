"""Simulated broker implementing the Broker ABC for paper trading.

Uses the exact same core matching and charges logic as SimulatedBroker in backtest/broker.py,
filling orders at candle open prices with zero network calls and never importing kiteconnect.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
import pandas as pd

from backtest.broker import ExitReason, SimulatedBroker
from config import TradingConfig
from models import Order, OrderPurpose, OrderStatus, Position, Side, TradingMode
from trading.broker import Broker, BrokerError, OrderInfo
from utils.charges import ChargesConfig
from utils.timeutil import to_ist


class PaperBroker(Broker):
    """Broker implementation executing paper orders against simulated market feeds."""

    def __init__(self, config: TradingConfig, charges: Optional[ChargesConfig] = None) -> None:
        self.config = config
        self.charges = charges if charges is not None else ChargesConfig.none()
        self.simulated = SimulatedBroker(config, self.charges)
        self.orders: dict[str, Order] = {}
        self.order_info: dict[str, OrderInfo] = {}
        self._next_id: int = 1
        self.current_candle: Optional[pd.Series] = None
        self._stop_order_id: Optional[str] = None

    def on_candle(self, candle: pd.Series) -> None:
        """Receive a new closed candle and process any pending stops or entries."""
        self.current_candle = candle
        when = to_ist(candle.name) if isinstance(candle.name, datetime) else to_ist(candle.get("timestamp"))
        open_price = float(candle["open"])
        high_price = float(candle["high"])
        low_price = float(candle["low"])

        # 1. Fill any pending orders at this candle's open
        for broker_id, info in list(self.order_info.items()):
            if info.status in (OrderStatus.CREATED, OrderStatus.SUBMITTED, OrderStatus.PENDING):
                order = self.orders[broker_id]
                if order.purpose is OrderPurpose.ENTRY:
                    fill = self.simulated._buy_price(open_price)
                    self.simulated.enter_long(when, open_price, order.quantity)
                    info.status = OrderStatus.COMPLETE
                    info.fill_price = fill
                    info.filled_quantity = order.quantity
                    order.transition_to(OrderStatus.COMPLETE, broker_order_id=broker_id, fill_price=fill)
                elif order.purpose is OrderPurpose.EXIT:
                    trade = self.simulated.exit_long(when, open_price, ExitReason.SIGNAL)
                    info.status = OrderStatus.COMPLETE
                    info.fill_price = trade.exit_price
                    info.filled_quantity = order.quantity
                    order.transition_to(OrderStatus.COMPLETE, broker_order_id=broker_id, fill_price=trade.exit_price)

        # 2. Check stops and targets inside this candle
        if self.simulated.position is not None:
            trade = self.simulated.check_stop_and_target(when, open_price, high_price, low_price)
            if trade is not None and self._stop_order_id is not None:
                stop_info = self.order_info.get(self._stop_order_id)
                if stop_info is not None:
                    stop_info.status = OrderStatus.COMPLETE
                    stop_info.fill_price = trade.exit_price
                    stop_info.filled_quantity = trade.quantity

    def place_order(self, order: Order) -> str:
        broker_id = f"PAPER_{self._next_id}"
        self._next_id += 1
        self.orders[broker_id] = order

        if order.status is OrderStatus.CREATED:
            order.transition_to(OrderStatus.SUBMITTED, broker_order_id=broker_id)

        if order.purpose is OrderPurpose.STOP_LOSS:
            # Resting protective stop order
            self._stop_order_id = broker_id
            self.order_info[broker_id] = OrderInfo(
                broker_order_id=broker_id,
                status=OrderStatus.TRIGGER_PENDING,
                fill_price=None,
                filled_quantity=0,
            )
            order.status = OrderStatus.TRIGGER_PENDING
            order.broker_order_id = broker_id
            return broker_id

        # For ENTRY or EXIT orders, if a candle is already active, fill immediately at open,
        # otherwise queue as SUBMITTED until next candle arrives
        if self.current_candle is not None:
            when = to_ist(self.current_candle.name) if isinstance(self.current_candle.name, datetime) else to_ist(self.current_candle.get("timestamp"))
            open_price = float(self.current_candle["open"])
            if order.purpose is OrderPurpose.ENTRY:
                fill = self.simulated._buy_price(open_price)
                self.simulated.enter_long(when, open_price, order.quantity)
                self.order_info[broker_id] = OrderInfo(
                    broker_order_id=broker_id,
                    status=OrderStatus.COMPLETE,
                    fill_price=fill,
                    filled_quantity=order.quantity,
                )
                order.transition_to(OrderStatus.COMPLETE, broker_order_id=broker_id, fill_price=fill)
            elif order.purpose is OrderPurpose.EXIT:
                trade = self.simulated.exit_long(when, open_price, ExitReason.SIGNAL)
                self.order_info[broker_id] = OrderInfo(
                    broker_order_id=broker_id,
                    status=OrderStatus.COMPLETE,
                    fill_price=trade.exit_price,
                    filled_quantity=order.quantity,
                )
                order.transition_to(OrderStatus.COMPLETE, broker_order_id=broker_id, fill_price=trade.exit_price)
            else:
                self.order_info[broker_id] = OrderInfo(
                    broker_order_id=broker_id,
                    status=OrderStatus.COMPLETE,
                    fill_price=open_price,
                    filled_quantity=order.quantity,
                )
                order.status = OrderStatus.COMPLETE
                order.broker_order_id = broker_id
        else:
            self.order_info[broker_id] = OrderInfo(
                broker_order_id=broker_id,
                status=OrderStatus.SUBMITTED,
                fill_price=None,
                filled_quantity=0,
            )
            order.status = OrderStatus.SUBMITTED
            order.broker_order_id = broker_id

        return broker_id

    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        return self.get_order_info(broker_order_id).status

    def get_order_info(self, broker_order_id: str) -> OrderInfo:
        if broker_order_id in self.order_info:
            return self.order_info[broker_order_id]
        return OrderInfo(broker_order_id=broker_order_id, status=OrderStatus.UNKNOWN)

    def cancel_order(self, broker_order_id: str) -> None:
        if broker_order_id in self.order_info:
            info = self.order_info[broker_order_id]
            if not info.status.is_terminal:
                info.status = OrderStatus.CANCELLED
                if broker_order_id in self.orders:
                    self.orders[broker_order_id].status = OrderStatus.CANCELLED
            if self._stop_order_id == broker_order_id:
                self._stop_order_id = None

    def get_positions(self) -> list[Position]:
        pos = self.simulated.position
        if pos is None:
            return []
        # Return position with paper mode
        paper_pos = Position(
            mode=TradingMode.PAPER,
            symbol=pos.symbol,
            side=pos.side,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            entry_time=pos.entry_time,
            stop_price=pos.stop_price,
            target_price=pos.target_price,
            stop_order_id=self._stop_order_id,
        )
        return [paper_pos]
