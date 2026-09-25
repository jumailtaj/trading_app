"""Kite Connect Live/Mocked Broker adapter conforming to Broker ABC."""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional

import kiteconnect.exceptions as kexc

from config import RuntimeMode, TradingConfig
from models import Order, OrderPurpose, OrderStatus, OrderType, Position, Side, TradingMode
from trading.broker import Broker, BrokerError, NetworkException, OrderInfo
from utils.logger import get_logger
from utils.timeutil import now_ist

logger = get_logger("kite_broker")

_STATUS_MAP: dict[str, OrderStatus] = {
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


def map_kite_status(raw_status: Optional[str]) -> OrderStatus:
    """Map raw Kite Connect status string to domain OrderStatus."""
    if not raw_status:
        return OrderStatus.UNKNOWN
    norm = str(raw_status).strip().upper()
    return _STATUS_MAP.get(norm, OrderStatus.UNKNOWN)


class KiteBroker(Broker):
    """Execution broker talking to Zerodha Kite Connect API."""

    def __init__(
        self,
        kite_client: Any,
        runtime_mode: RuntimeMode,
        config: TradingConfig,
        poll_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.01,
        tick_size: float = 0.05,
    ) -> None:
        self.kite = kite_client
        self._runtime_mode = runtime_mode
        self.config = config
        self.poll_timeout_seconds = poll_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.tick_size = tick_size

        self.orders: dict[str, Order] = {}
        self.order_info: dict[str, OrderInfo] = {}
        self.halted: bool = False
        self.halt_reason: str = ""

    @staticmethod
    def round_tick(price: float, tick_size: float = 0.05) -> float:
        """Round price to the nearest valid exchange tick size."""
        if price <= 0:
            return 0.05
        return round(round(price / tick_size) * tick_size, 2)

    def _check_live_allowed(self) -> None:
        """Enforce live execution safety gate (E1)."""
        if not self._runtime_mode.is_live_allowed():
            raise RuntimeError("CRITICAL: live order attempted while live is not enabled")

    def _is_ip_exception(self, exc: Exception) -> bool:
        """Check if an exception is an IP registration failure."""
        msg = str(exc).lower()
        exc_type = type(exc).__name__.lower()
        return "ip" in exc_type or "ip" in msg or "unregistered" in msg

    def place_order(self, order: Order) -> str:
        """Place an order with Kite Connect, enforcing live gates and error translations."""
        self._check_live_allowed()

        if self.halted:
            raise BrokerError(f"Broker is halted: {self.halt_reason}")

        variety = "regular"
        exchange = self.config.exchange
        tradingsymbol = order.symbol
        transaction_type = "BUY" if order.side is Side.BUY else "SELL"
        quantity = order.quantity
        product = "MIS"

        # Determine order type and price
        if order.order_type is OrderType.MARKET:
            order_type = "MARKET"
            price = None
            trigger_price = None
            market_protection = -1
        elif order.order_type is OrderType.SL:
            order_type = "SL-M"
            price = None
            trigger_price = self.round_tick(order.price or 100.0, self.tick_size)
            market_protection = None
        else:
            order_type = order.order_type.value
            price = order.price
            trigger_price = None
            market_protection = None

        # Truncate tag to 20 alphanumeric characters (OD5)
        tag = order.signal_id[:20] if order.signal_id else None

        params = {
            "variety": variety,
            "exchange": exchange,
            "tradingsymbol": tradingsymbol,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "product": product,
            "order_type": order_type,
        }
        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price
        if market_protection is not None:
            params["market_protection"] = market_protection
        if tag is not None:
            params["tag"] = tag

        try:
            raw_id = self.kite.place_order(**params)
            broker_order_id = str(raw_id)
        except kexc.TokenException as exc:
            logger.critical(f"Kite auth TokenException: {exc}")
            self.halted = True
            self.halt_reason = "TOKEN_EXCEPTION_DISCONNECT"
            raise BrokerError(f"Disconnect halt: {exc}") from exc
        except (kexc.PermissionException, kexc.InputException) as exc:
            if self._is_ip_exception(exc):
                logger.critical(f"CRITICAL: Unregistered IP error: {exc}")
                self.halted = True
                self.halt_reason = "IP_EXCEPTION_HALT"
                raise BrokerError(f"CRITICAL IP halt: {exc}") from exc
            logger.error(f"Kite order rejected: {exc}")
            raise BrokerError(f"Order rejected: {exc}") from exc
        except kexc.NetworkException as exc:
            logger.warning(f"Kite NetworkException during place_order for tag {tag}: {exc}")
            # H2 Ambiguous failure: try lookup by tag
            found_id = self._lookup_order_by_tag(tag)
            if found_id is not None:
                broker_order_id = found_id
            else:
                self.halted = True
                self.halt_reason = "AMBIGUOUS_NETWORK_FAILURE"
                raise NetworkException(f"Network timeout placing order (tag {tag}): {exc}") from exc
        except Exception as exc:
            logger.error(f"Unexpected Kite error on place_order: {exc}")
            raise BrokerError(f"Place order failed: {exc}") from exc

        self.orders[broker_order_id] = order
        order.broker_order_id = broker_order_id
        if order.status is OrderStatus.CREATED:
            order.transition_to(OrderStatus.SUBMITTED, broker_order_id=broker_order_id)

        # Poll order to resolve initial status
        info = self._poll_order(broker_order_id)
        self.order_info[broker_order_id] = info
        return broker_order_id

    def _lookup_order_by_tag(self, tag: Optional[str]) -> Optional[str]:
        """Look up broker order ID by tag from Kite order book (H2 recovery)."""
        if not tag:
            return None
        try:
            orders = self.kite.orders()
            for o in orders:
                if str(o.get("tag", "")) == tag:
                    return str(o.get("order_id"))
        except Exception as exc:
            logger.warning(f"Failed to lookup order by tag {tag}: {exc}")
        return None

    def _poll_order(self, broker_order_id: str) -> OrderInfo:
        """Poll order until terminal state or timeout (E2)."""
        start = time.monotonic()
        while time.monotonic() - start < self.poll_timeout_seconds:
            try:
                history = self.kite.order_history(broker_order_id)
                if history:
                    latest = history[-1]
                    raw_status = latest.get("status")
                    status = map_kite_status(raw_status)
                    fill_price = float(latest.get("average_price", 0.0)) or None
                    filled_qty = int(latest.get("filled_quantity", 0))

                    info = OrderInfo(
                        broker_order_id=broker_order_id,
                        status=status,
                        fill_price=fill_price,
                        filled_quantity=filled_qty,
                    )
                    self.order_info[broker_order_id] = info

                    if status.is_terminal or status is OrderStatus.TRIGGER_PENDING:
                        return info
            except Exception as exc:
                logger.warning(f"Error polling order {broker_order_id}: {exc}")

            time.sleep(self.poll_interval_seconds)

        # Timeout reached while in interim state -> UNKNOWN -> halt
        logger.critical(f"Order {broker_order_id} timed out in interim state")
        self.halted = True
        self.halt_reason = "INTERIM_ORDER_TIMEOUT"
        info = OrderInfo(broker_order_id=broker_order_id, status=OrderStatus.UNKNOWN)
        self.order_info[broker_order_id] = info
        return info

    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        return self.get_order_info(broker_order_id).status

    def get_order_info(self, broker_order_id: str) -> OrderInfo:
        if broker_order_id in self.order_info:
            return self.order_info[broker_order_id]
        return self._poll_order(broker_order_id)

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel an open order with Kite Connect."""
        self._check_live_allowed()
        try:
            self.kite.cancel_order(variety="regular", order_id=broker_order_id)
        except Exception as exc:
            logger.warning(f"Kite cancel_order failed for {broker_order_id}: {exc}")

        # Poll order to terminal state
        self._poll_order(broker_order_id)

    def get_positions(self) -> list[Position]:
        """Fetch open positions from Kite and reconcile with domain models."""
        self._check_live_allowed()
        try:
            raw_pos = self.kite.positions()
            net_positions = raw_pos.get("net", []) if isinstance(raw_pos, dict) else []
        except Exception as exc:
            logger.error(f"Failed to fetch Kite positions: {exc}")
            return []

        out: list[Position] = []
        for p in net_positions:
            qty = int(p.get("quantity", 0))
            if qty > 0:
                pos = Position(
                    mode=TradingMode.LIVE,
                    symbol=p.get("tradingsymbol", ""),
                    side=Side.BUY,
                    quantity=qty,
                    entry_price=float(p.get("average_price", 0.0)),
                    entry_time=now_ist(),
                    stop_price=0.0,
                    target_price=None,
                )
                out.append(pos)
        return out
