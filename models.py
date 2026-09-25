"""Plain data objects and enums shared by every module. No logic that talks to a broker or DB.

Enums are deliberately NOT str-subclasses: TradingMode.PAPER == "LIVE" style mix-ups
must never silently succeed. Convert with .value / Enum(value) at the storage edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from utils.timeutil import now_ist, to_ist


class TradingMode(Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class Signal(Enum):
    """What a strategy may say. Strategies return this and nothing else."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class OrderPurpose(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"


class OrderStatus(Enum):
    """Internal order states.

    The Kite adapter (Phase 5) maps broker status strings onto these. A broker status
    we do not recognise maps to UNKNOWN, which is NOT terminal and must halt trading.
    """
    CREATED = "CREATED"                # built locally, not sent yet
    SUBMITTED = "SUBMITTED"            # sent, broker order id may be known, state unverified
    PENDING = "PENDING"                # non-terminal interim (exchange received, not yet open)
    OPEN = "OPEN"                      # broker confirms it is working / pending
    TRIGGER_PENDING = "TRIGGER_PENDING"  # non-terminal (resting stop order)
    COMPLETE = "COMPLETE"              # fully filled (terminal)
    REJECTED = "REJECTED"              # (terminal)
    CANCELLED = "CANCELLED"            # (terminal)
    LAPSED = "LAPSED"                  # auto-cancelled by broker/exchange (terminal)
    UNKNOWN = "UNKNOWN"                # unrecognised broker state -> fail safe

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = frozenset({
    OrderStatus.COMPLETE, OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.LAPSED,
})

NON_TERMINAL_STATUSES = frozenset({
    OrderStatus.CREATED, OrderStatus.SUBMITTED, OrderStatus.PENDING, OrderStatus.OPEN,
    OrderStatus.TRIGGER_PENDING, OrderStatus.UNKNOWN,
})


class PositionProtection(Enum):
    PROTECTED = "PROTECTED"
    UNPROTECTED = "UNPROTECTED"


LEGAL_ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset({OrderStatus.SUBMITTED, OrderStatus.REJECTED}),
    OrderStatus.SUBMITTED: frozenset({
        OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING,
        OrderStatus.COMPLETE, OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.LAPSED,
    }),
    OrderStatus.PENDING: frozenset({
        OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING, OrderStatus.REJECTED,
        OrderStatus.CANCELLED, OrderStatus.LAPSED,
    }),
    OrderStatus.OPEN: frozenset({
        OrderStatus.COMPLETE, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.LAPSED,
    }),
    OrderStatus.TRIGGER_PENDING: frozenset({
        OrderStatus.OPEN, OrderStatus.COMPLETE, OrderStatus.CANCELLED, OrderStatus.LAPSED,
    }),
}


def _check_qty(quantity: int) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError(f"quantity must be a positive integer, got {quantity!r}")


@dataclass
class Order:
    mode: TradingMode
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    purpose: OrderPurpose
    price: Optional[float] = None          # limit / trigger price; None for MARKET
    status: OrderStatus = OrderStatus.CREATED
    broker_order_id: Optional[str] = None
    signal_id: Optional[str] = None        # ties every order back to the signal that caused it
    fill_price: Optional[float] = None     # actual average fill price, once known
    timestamp: datetime = field(default_factory=now_ist)
    id: Optional[int] = None

    def __post_init__(self) -> None:
        _check_qty(self.quantity)
        if self.order_type in (OrderType.LIMIT, OrderType.SL, OrderType.SL_M) and self.price is None:
            raise ValueError(f"{self.order_type.value} order needs a price")
        self.timestamp = to_ist(self.timestamp)

    def transition_to(self, new_status: OrderStatus, *, broker_order_id: Optional[str] = None,
                      fill_price: Optional[float] = None) -> None:
        """Validate and apply a legal order state transition."""
        if not isinstance(new_status, OrderStatus):
            raise TypeError(f"expected OrderStatus, got {type(new_status).__name__}")

        if self.status in TERMINAL_STATUSES:
            if new_status is self.status:
                return  # idempotent terminal transition
            raise ValueError(
                f"cannot transition terminal order from {self.status.value} to {new_status.value}"
            )

        if self.status in LEGAL_ORDER_TRANSITIONS:
            allowed = LEGAL_ORDER_TRANSITIONS[self.status]
            if new_status not in allowed:
                raise ValueError(
                    f"illegal order transition from {self.status.value} to {new_status.value}"
                )
        # OrderStatus.UNKNOWN is allowed to transition to any status to assist recovery

        target_broker_id = broker_order_id if broker_order_id is not None else self.broker_order_id
        target_fill_price = fill_price if fill_price is not None else self.fill_price

        if self.mode is TradingMode.LIVE and new_status is OrderStatus.COMPLETE:
            if target_broker_id is None or target_fill_price is None:
                raise ValueError(
                    "LIVE order cannot transition to COMPLETE without broker_order_id and fill_price"
                )

        self.status = new_status
        if broker_order_id is not None:
            self.broker_order_id = broker_order_id
        if fill_price is not None:
            self.fill_price = fill_price


@dataclass
class Trade:
    """A completed round trip. `side` is the ENTRY direction (BUY = long).
    `pnl` is NET of estimated charges; `charges` is stored separately (gross = pnl + charges)."""
    mode: TradingMode
    symbol: str
    side: Side
    quantity: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl: float
    charges: float = 0.0
    reason: str = ""
    id: Optional[int] = None

    def __post_init__(self) -> None:
        _check_qty(self.quantity)
        self.entry_time = to_ist(self.entry_time)
        self.exit_time = to_ist(self.exit_time)


@dataclass
class Position:
    """An open position. A stop price is mandatory: no position exists without a known stop."""
    mode: TradingMode
    symbol: str
    side: Side
    quantity: int
    entry_price: float
    entry_time: datetime
    stop_price: float
    target_price: Optional[float] = None
    stop_order_id: Optional[str] = None    # broker id of the protective stop (LIVE)

    def __post_init__(self) -> None:
        _check_qty(self.quantity)
        self.entry_time = to_ist(self.entry_time)
        long = self.side is Side.BUY
        if long and not self.stop_price < self.entry_price:
            raise ValueError("long position: stop_price must be below entry_price")
        if not long and not self.stop_price > self.entry_price:
            raise ValueError("short position: stop_price must be above entry_price")
        if self.target_price is not None:
            if long and not self.target_price > self.entry_price:
                raise ValueError("long position: target_price must be above entry_price")
            if not long and not self.target_price < self.entry_price:
                raise ValueError("short position: target_price must be below entry_price")

    @property
    def protection(self) -> PositionProtection:
        if self.mode is TradingMode.LIVE and self.stop_order_id is None:
            return PositionProtection.UNPROTECTED
        return PositionProtection.PROTECTED
