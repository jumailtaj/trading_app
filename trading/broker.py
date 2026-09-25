"""Abstract broker interface and common broker exceptions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from models import Order, OrderStatus, Position


class BrokerError(Exception):
    """Base exception for all broker communication and execution failures."""


class NetworkException(BrokerError):
    """Raised when communication with broker times out or disconnects."""


@dataclass
class OrderInfo:
    broker_order_id: str
    status: OrderStatus
    fill_price: Optional[float] = None
    filled_quantity: int = 0


class Broker(ABC):
    """Abstract interface defining required broker operations for paper and live trading."""

    @abstractmethod
    def place_order(self, order: Order) -> str:
        """Place an order and return the broker_order_id."""
        ...

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """Return the current OrderStatus for a given broker order ID."""
        ...

    def get_order_info(self, broker_order_id: str) -> OrderInfo:
        """Return full order status and fill details."""
        status = self.get_order_status(broker_order_id)
        return OrderInfo(broker_order_id=broker_order_id, status=status)

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return all open positions known to the broker."""
        ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel an open or pending order."""
        ...
