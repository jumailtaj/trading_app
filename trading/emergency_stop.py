"""Emergency stop and kill switch management (H5)."""
from __future__ import annotations

from typing import Any, Optional

from db import Database
from models import Order, OrderPurpose, OrderStatus, OrderType, Position, Side, TradingMode
from trading.broker import Broker
from utils.logger import get_logger

logger = get_logger("emergency_stop")


class EmergencyStop:
    """Manages emergency stop activation (H5) and safe position liquidation."""

    @staticmethod
    def activate(db: Database, broker: Broker, mode: TradingMode) -> dict[str, Any]:
        """Activate emergency stop (H5):

        1. Set kill switch in DB (persisted).
        2. Block all new strategy signals.
        3. Cancel pending ENTRY orders only (not stops, not exits).
        4. Leave open positions and their protective stops untouched.
        5. Log CRITICAL.
        """
        logger.critical(f"EMERGENCY STOP ACTIVATED for mode {mode.value}")
        db.set_kill_switch(mode, True)

        unresolved = db.get_unresolved_orders(mode)
        cancelled_entries: list[Order] = []

        for order in unresolved:
            # H5 Guard: Cancel pending ENTRY orders ONLY. Never cancel stops or exits!
            if order.purpose is OrderPurpose.ENTRY:
                if order.broker_order_id:
                    try:
                        broker.cancel_order(order.broker_order_id)
                    except Exception as exc:
                        logger.warning(f"Error cancelling entry order {order.broker_order_id}: {exc}")
                order.transition_to(OrderStatus.CANCELLED)
                db.update_order(order.id, status=OrderStatus.CANCELLED)
                cancelled_entries.append(order)
                logger.info(f"Emergency stop cancelled pending entry order {order.id}")
            else:
                logger.info(
                    f"Emergency stop preserving non-entry order {order.id} (purpose={order.purpose.value})"
                )

        return {
            "kill_switch_active": True,
            "cancelled_entries": cancelled_entries,
        }

    @staticmethod
    def flatten_all(
        db: Database,
        broker: Broker,
        mode: TradingMode,
        *,
        confirmed: bool = False,
    ) -> list[Order]:
        """Flatten all positions (separate, explicit action requiring confirmed=True)."""
        if not confirmed:
            raise ValueError("FLATTEN requires confirmed=True")

        logger.critical(f"FLATTEN ALL POSITIONS initiated for mode {mode.value}")
        positions = db.get_open_positions(mode)
        exit_orders: list[Order] = []

        for pos in positions:
            # 1. Cancel resting stop if exists
            if pos.stop_order_id:
                try:
                    broker.cancel_order(pos.stop_order_id)
                except Exception as exc:
                    logger.warning(f"Error cancelling stop {pos.stop_order_id} during flatten: {exc}")

            # 2. Place market exit order
            exit_side = Side.SELL if pos.side is Side.BUY else Side.BUY
            exit_order = Order(
                mode=mode,
                symbol=pos.symbol,
                side=exit_side,
                quantity=pos.quantity,
                order_type=OrderType.MARKET,
                purpose=OrderPurpose.EXIT,
            )
            order_id = db.insert_order(exit_order)
            exit_order.id = order_id

            try:
                bid = broker.place_order(exit_order)
                exit_order.broker_order_id = bid
                db.update_order(order_id, broker_order_id=bid, status=exit_order.status)
            except Exception as exc:
                logger.error(f"Failed to place exit order during flatten for {pos.symbol}: {exc}")

            exit_orders.append(exit_order)
            db.delete_position(mode, pos.symbol)

        return exit_orders
