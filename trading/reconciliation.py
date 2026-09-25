"""Startup and periodic broker-to-DB reconciliation and safe mode (F1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from db import Database
from models import Position, PositionProtection, TradingMode
from trading.broker import Broker
from utils.logger import get_logger
from utils.timeutil import now_ist

logger = get_logger("reconciliation")


@dataclass
class ReconciliationResult:
    """Outcome of a reconciliation check between Broker and DB."""
    is_clean: bool
    safe_mode: bool
    error_reasons: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=now_ist)


class Reconciler:
    """Validates state parity between the broker and local database."""

    def __init__(
        self,
        db: Database,
        broker: Broker,
        mode: TradingMode = TradingMode.LIVE,
        interval_minutes: int = 5,
    ) -> None:
        self.db = db
        self.broker = broker
        self.mode = mode
        self.interval_minutes = interval_minutes

        self.safe_mode: bool = False
        self.last_result: Optional[ReconciliationResult] = None

    def reconcile(self) -> ReconciliationResult:
        """Run full reconciliation:

        1. Ping broker profile if available.
        2. Compare broker positions with DB positions (symbol, qty).
        3. Verify all live positions are protected (have resting stops).
        4. Compare broker orders today with DB orders today for unknown orders.
        5. Trigger SAFE MODE on any discrepancy.
        """
        reasons: list[str] = []

        # 1. Connection check
        kite_client = getattr(self.broker, "kite", None)
        if kite_client is not None and hasattr(kite_client, "profile"):
            try:
                kite_client.profile()
            except Exception as exc:
                reasons.append(f"Broker profile ping failed: {exc}")

        # 2. Position comparison
        try:
            broker_positions = self.broker.get_positions()
        except Exception as exc:
            broker_positions = []
            reasons.append(f"Failed to fetch broker positions: {exc}")

        db_positions = self.db.get_open_positions(self.mode)
        broker_pos_by_sym = {p.symbol: p for p in broker_positions}
        db_pos_by_sym = {p.symbol: p for p in db_positions}

        # Check for symbols in broker not in DB
        for sym, b_pos in broker_pos_by_sym.items():
            if sym not in db_pos_by_sym:
                reasons.append(f"Broker has position for {sym} (qty={b_pos.quantity}) not recorded in DB")
            elif b_pos.quantity != db_pos_by_sym[sym].quantity:
                reasons.append(
                    f"Quantity mismatch for {sym}: broker has {b_pos.quantity}, DB has {db_pos_by_sym[sym].quantity}"
                )

        # Check for symbols in DB not in broker
        for sym, d_pos in db_pos_by_sym.items():
            if sym not in broker_pos_by_sym:
                reasons.append(f"DB has position for {sym} (qty={d_pos.quantity}) missing from broker")

        # 3. Check for unprotected live positions in DB
        if self.mode is TradingMode.LIVE:
            unprotected = self.db.get_unprotected_live_positions()
            if unprotected:
                syms = [p.symbol for p in unprotected]
                reasons.append(f"Unprotected live positions found without stop orders: {syms}")

        # 4. Compare orders today: detect unknown broker orders
        try:
            if hasattr(self.broker, "kite") and hasattr(self.broker.kite, "orders"):
                b_orders = self.broker.kite.orders() or []
                known_db_bids = {
                    o.broker_order_id for o in self.db.get_orders(self.mode) if o.broker_order_id
                }
                for bo in b_orders:
                    bid = str(bo.get("order_id", ""))
                    if bid and bid not in known_db_bids:
                        reasons.append(f"Unknown broker order {bid} found on exchange")
            elif hasattr(self.broker, "orders"):
                # MockBroker or in-memory tracking
                known_db_bids = {
                    o.broker_order_id for o in self.db.get_orders(self.mode) if o.broker_order_id
                }
                for bid in self.broker.orders.keys():
                    if bid and bid not in known_db_bids:
                        reasons.append(f"Unknown broker order {bid} not recorded in DB")
        except Exception as exc:
            reasons.append(f"Error checking broker orders: {exc}")

        # 5. Evaluate clean vs safe mode
        if reasons:
            self.safe_mode = True
            logger.critical(f"RECONCILIATION ERROR -> SAFE MODE: {reasons}")
            result = ReconciliationResult(is_clean=False, safe_mode=True, error_reasons=reasons)
        else:
            self.safe_mode = False
            logger.info("Reconciliation clean: state parity verified")
            result = ReconciliationResult(is_clean=True, safe_mode=False, error_reasons=[])

        self.last_result = result
        return result

    def check_can_trade(self) -> None:
        """Enforce SAFE MODE gate. Raises RuntimeError if safe mode is active."""
        if self.safe_mode:
            reasons_str = "; ".join(self.last_result.error_reasons) if self.last_result else "Safe mode active"
            raise RuntimeError(f"SAFE MODE active: {reasons_str}")
