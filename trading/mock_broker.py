"""Scriptable mock broker for unit testing execution pipelines and edge cases."""
from __future__ import annotations

from typing import Callable, Optional

from models import Order, OrderPurpose, OrderStatus, Position
from trading.broker import Broker, BrokerError, NetworkException, OrderInfo


class MockBroker(Broker):
    """Configurable and scriptable mock broker covering all execution scenarios."""

    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self.order_info: dict[str, OrderInfo] = {}
        self.positions: list[Position] = []
        self._next_id: int = 1

        # Direct hooks for fine-grained scriptability
        self.place_order_hook: Optional[Callable[[Order], Optional[str]]] = None
        self.get_status_hook: Optional[Callable[[str], Optional[OrderInfo]]] = None
        self.cancel_hook: Optional[Callable[[str], None]] = None
        self.get_positions_hook: Optional[Callable[[], Optional[list[Position]]]] = None

        # Sequences for delayed polling: order_id -> list of OrderInfo
        self.status_sequences: dict[str, list[OrderInfo]] = {}

        # Pre-set scenario toggles
        self.raise_on_place: bool = False
        self.raise_on_get_status: bool = False
        self.raise_on_cancel: bool = False
        self.fail_stop_orders: bool = False
        self.stop_fills_during_cancel: bool = False
        self.default_fill_price: float = 100.0

    def place_order(self, order: Order) -> str:
        if self.raise_on_place:
            raise NetworkException("Network timeout during place_order")

        if self.fail_stop_orders and order.purpose is OrderPurpose.STOP_LOSS:
            raise BrokerError("Broker rejected stop loss order placement")

        if self.place_order_hook is not None:
            custom_id = self.place_order_hook(order)
            if custom_id is not None:
                return custom_id

        broker_id = f"MOCK_{self._next_id}"
        self._next_id += 1
        self.orders[broker_id] = order

        if order.status is OrderStatus.CREATED:
            order.transition_to(OrderStatus.SUBMITTED, broker_order_id=broker_id)

        if order.purpose is OrderPurpose.STOP_LOSS:
            initial_status = OrderStatus.TRIGGER_PENDING
            fill_price = None
            filled_qty = 0
            order.status = OrderStatus.TRIGGER_PENDING
        else:
            initial_status = OrderStatus.COMPLETE
            fill_price = order.price or self.default_fill_price
            filled_qty = order.quantity
            order.transition_to(OrderStatus.COMPLETE, fill_price=fill_price)

        self.order_info[broker_id] = OrderInfo(
            broker_order_id=broker_id,
            status=initial_status,
            fill_price=fill_price,
            filled_quantity=filled_qty,
        )
        return broker_id

    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        return self.get_order_info(broker_order_id).status

    def get_order_info(self, broker_order_id: str) -> OrderInfo:
        if self.raise_on_get_status:
            raise NetworkException("Network timeout during get_order_status")

        if self.get_status_hook is not None:
            custom_info = self.get_status_hook(broker_order_id)
            if custom_info is not None:
                return custom_info

        if broker_order_id in self.status_sequences and self.status_sequences[broker_order_id]:
            seq = self.status_sequences[broker_order_id]
            next_info = seq.pop(0)
            self.order_info[broker_order_id] = next_info
            return next_info

        if broker_order_id in self.order_info:
            return self.order_info[broker_order_id]

        return OrderInfo(broker_order_id=broker_order_id, status=OrderStatus.UNKNOWN)

    def cancel_order(self, broker_order_id: str) -> None:
        if self.raise_on_cancel:
            raise NetworkException("Network timeout during cancel_order")

        if self.cancel_hook is not None:
            self.cancel_hook(broker_order_id)
            return

        if self.stop_fills_during_cancel:
            # H1 Race: broker fills order right before cancel takes effect
            if broker_order_id in self.order_info:
                info = self.order_info[broker_order_id]
                info.status = OrderStatus.COMPLETE
                if info.fill_price is None:
                    info.fill_price = self.default_fill_price
                if info.filled_quantity == 0 and broker_order_id in self.orders:
                    info.filled_quantity = self.orders[broker_order_id].quantity
            return

        if broker_order_id in self.order_info:
            self.order_info[broker_order_id].status = OrderStatus.CANCELLED

    def get_positions(self) -> list[Position]:
        if self.get_positions_hook is not None:
            custom = self.get_positions_hook()
            if custom is not None:
                return custom
        return list(self.positions)
