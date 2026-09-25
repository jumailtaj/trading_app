"""Single mode-agnostic execution pipeline for paper and live trading."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Counter, Optional
import pandas as pd

from config import TradingConfig
from db import Database
from models import (
    Order, OrderPurpose, OrderStatus, OrderType, Position, PositionProtection, Side,
    Signal, Trade, TradingMode,
)
from trading.broker import Broker, BrokerError, NetworkException, OrderInfo
from trading.risk_manager import RiskDecision, RiskManager
from utils.logger import get_logger
from utils.signal_id import generate_signal_id
from utils.timeutil import IST, now_ist, to_ist

logger = get_logger("engine")


class EngineHaltedError(RuntimeError):
    """Raised when an operation is attempted while the engine is halted."""


class SignalEngine:
    """Core trade execution engine implementing the single paper/live pipeline."""

    _active_instance: Optional[SignalEngine] = None

    def __init__(
        self,
        config: TradingConfig,
        strategy: any,
        broker: Broker,
        db: Optional[Database] = None,
        mode: TradingMode = TradingMode.PAPER,
        max_poll_attempts: int = 5,
        enforce_singleton: bool = True,
    ) -> None:
        if enforce_singleton:
            if SignalEngine._active_instance is not None and SignalEngine._active_instance is not self:
                raise RuntimeError("Only one SignalEngine instance may be active per process")
            SignalEngine._active_instance = self

        self.config = config
        self.strategy = strategy
        self.broker = broker
        self.db = db
        self.mode = mode
        self.max_poll_attempts = max_poll_attempts
        self.risk_manager = RiskManager(config, db=db, mode=mode)

        self.candle_history: list[pd.Series] = []
        self.executed_trades: list[Trade] = []
        self.skipped_signals: Counter[str] = Counter()
        self._seen_signal_ids: set[str] = set()
        self.halted: bool = False
        self.halt_reason: str = ""
        self._pending_entry_order_id: Optional[str] = None
        self._pending_signal: Optional[tuple[Signal, str, datetime]] = None

    def close(self) -> None:
        if SignalEngine._active_instance is self:
            SignalEngine._active_instance = None

    def _get_open_position(self) -> Optional[Position]:
        """Fetch current open position from broker or DB."""
        broker_positions = self.broker.get_positions()
        if broker_positions:
            return broker_positions[0]
        if self.db is not None:
            db_positions = self.db.get_open_positions(self.mode)
            if db_positions:
                return db_positions[0]
        return None

    def _poll_order(self, broker_order_id: str) -> OrderInfo:
        """Poll broker until order reaches terminal state or attempts exhaust."""
        for _ in range(self.max_poll_attempts):
            info = self.broker.get_order_info(broker_order_id)
            if info.status.is_terminal:
                return info
        return self.broker.get_order_info(broker_order_id)

    def process_candle(self, candle: pd.Series) -> None:
        """Process one closed candle through the entire strategy and execution pipeline."""
        if self.halted:
            logger.error(f"Engine is halted ({self.halt_reason}); ignoring candle")
            return

        candle_time = to_ist(candle.name) if isinstance(candle.name, datetime) else to_ist(candle.get("timestamp"))
        clock = candle_time.time()
        open_price = float(candle["open"])
        high_price = float(candle["high"])
        low_price = float(candle["low"])
        close_price = float(candle["close"])

        # Notify broker if it tracks candles (e.g. PaperBroker)
        if hasattr(self.broker, "on_candle"):
            self.broker.on_candle(candle)

        # 1. Execute any signal queued from the previous candle at this candle's open
        if self._pending_signal is not None:
            sig, sig_id, sig_time = self._pending_signal
            self._pending_signal = None
            timeframe_secs = self.config.timeframe_minutes * 60

            if (candle_time - sig_time).total_seconds() != timeframe_secs:
                self.skipped_signals["GAP_SIGNAL_EXPIRED"] += 1
            elif sig is Signal.BUY:
                pos = self._get_open_position()
                if pos is not None:
                    self.skipped_signals["BUY_WHILE_LONG"] += 1
                else:
                    self._execute_entry(sig_id, candle_time, open_price)
            elif sig is Signal.SELL:
                pos = self._get_open_position()
                if pos is None:
                    self.skipped_signals["SELL_WHILE_FLAT"] += 1
                else:
                    self._execute_exit(pos, sig_id, candle_time, open_price, reason="SIGNAL")

        # 2. Check for End-of-Day Square-Off at or after square_off_time
        pos = self._get_open_position()
        if pos is not None and clock >= self.config.square_off_time:
            self._execute_exit(pos, f"SQ_{candle_time.strftime('%Y%m%d%H%M')}", candle_time, open_price, reason="SQUARE_OFF")

        # 3. Check if broker closed the position internally during the candle (e.g. stop hit)
        active_pos = self._get_open_position()
        if pos is not None and active_pos is None:
            # Position was closed by stop/target
            if self.db is not None:
                self.db.delete_position(self.mode, self.config.symbol)

        # 4. Generate strategy signal for this closed candle
        if self.candle_history:
            last_ts = to_ist(self.candle_history[-1].name) if isinstance(self.candle_history[-1].name, datetime) else to_ist(self.candle_history[-1].get("timestamp"))
            if candle_time == last_ts:
                self.candle_history[-1] = candle
            else:
                self.candle_history.append(candle)
        else:
            self.candle_history.append(candle)

        df_history = pd.DataFrame(self.candle_history)
        if not isinstance(df_history.index, pd.DatetimeIndex):
            timestamps = [
                to_ist(c.name) if isinstance(c.name, datetime) else to_ist(c.get("timestamp"))
                for c in self.candle_history
            ]
            df_history.index = pd.DatetimeIndex(timestamps, tz=IST)

        sig = self.strategy.generate_signal(df_history)

        # 5. Queue signal for next candle's open (same day only)
        if sig is not Signal.HOLD:
            sig_id = generate_signal_id(self.mode, self.config.symbol, self.config.timeframe, candle_time, sig)
            # Deduplication check in-memory and DB
            if sig_id in self._seen_signal_ids or (self.db is not None and self.db.get_orders(mode=self.mode, signal_id=sig_id)):
                self.skipped_signals["DUPLICATE_SIGNAL"] += 1
            else:
                self._seen_signal_ids.add(sig_id)
                self._pending_signal = (sig, sig_id, candle_time)

    def _execute_entry(self, signal_id: str, when: datetime, price: float) -> None:
        """Perform risk check, place entry order, poll fill, update DB, and place protective stop."""
        today = when.date()
        pnl_today = self.db.realized_pnl_today(self.mode, today) if self.db is not None else 0.0
        entries_today = self.db.count_entries_today(self.mode, day=today) if self.db is not None else len(self.executed_trades)

        decision = self.risk_manager.check_entry(
            when=when,
            entry_price=price,
            realized_pnl_today=pnl_today,
            entries_today=entries_today,
        )
        if not decision.allowed:
            self.skipped_signals[decision.reason] += 1
            return

        order = Order(
            mode=self.mode,
            symbol=self.config.symbol,
            side=Side.BUY,
            quantity=decision.quantity,
            order_type=OrderType.MARKET,
            purpose=OrderPurpose.ENTRY,
            signal_id=signal_id,
            timestamp=when,
        )

        # H2: Ambiguous network failure check
        try:
            broker_order_id = self.broker.place_order(order)
            order.broker_order_id = broker_order_id
            if self.db is not None:
                self.db.insert_order(order)
        except NetworkException as exc:
            logger.critical(f"NetworkException on place_order for {signal_id}: {exc}")
            order.status = OrderStatus.UNKNOWN
            if self.db is not None:
                try:
                    self.db.insert_order(order)
                except Exception:
                    pass
            self.halted = True
            self.halt_reason = "AMBIGUOUS_PLACE_FAILURE"
            return
        except Exception as exc:
            logger.error(f"Failed to place entry order: {exc}")
            return

        # Poll for fill
        info = self._poll_order(broker_order_id)
        if info.status is OrderStatus.COMPLETE:
            # H3: Partial fill check
            actual_qty = info.filled_quantity if 0 < info.filled_quantity < order.quantity else order.quantity
            fill_price = info.fill_price or price

            if order.status is not OrderStatus.COMPLETE:
                order.transition_to(OrderStatus.COMPLETE, broker_order_id=broker_order_id, fill_price=fill_price)
            if self.db is not None:
                self.db.update_order(order.id, status=OrderStatus.COMPLETE, broker_order_id=broker_order_id, fill_price=fill_price)

            stop_price = fill_price * (1 - self.config.stop_loss_pct / 100)
            target_price = fill_price * (1 + self.config.target_pct / 100) if self.config.enable_target else None

            pos = Position(
                mode=self.mode,
                symbol=self.config.symbol,
                side=Side.BUY,
                quantity=actual_qty,
                entry_price=fill_price,
                entry_time=when,
                stop_price=stop_price,
                target_price=target_price,
                stop_order_id=None,
            )

            # Place stop-loss order
            stop_order = Order(
                mode=self.mode,
                symbol=self.config.symbol,
                side=Side.SELL,
                quantity=actual_qty,
                order_type=OrderType.SL,
                purpose=OrderPurpose.STOP_LOSS,
                price=stop_price,
                signal_id=signal_id,
                timestamp=when,
            )

            stop_placed = False
            for attempt in range(2):  # Try once + retry once
                try:
                    stop_bid = self.broker.place_order(stop_order)
                    stop_order.broker_order_id = stop_bid
                    if self.db is not None:
                        self.db.insert_order(stop_order)
                    pos.stop_order_id = stop_bid
                    stop_placed = True
                    break
                except Exception as exc:
                    logger.warning(f"Stop placement attempt {attempt + 1} failed: {exc}")

            if not stop_placed:
                logger.critical(f"CRITICAL: Failed to place stop order for {pos.symbol}. Halting engine.")
                self.halted = True
                self.halt_reason = "STOP_PLACEMENT_FAILURE"

            if self.db is not None:
                self.db.save_position(pos)
        else:
            logger.warning(f"Entry order {broker_order_id} did not reach COMPLETE (status={info.status.value})")
            if info.status is OrderStatus.UNKNOWN:
                self.halted = True
                self.halt_reason = "ENTRY_ORDER_TIMEOUT"

    def _execute_exit(self, pos: Position, signal_id: str, when: datetime, price: float, reason: str = "SIGNAL") -> None:
        """Perform safe exit: cancel stop, verify cancel, handle H1 race, then exit."""
        # H1 Exit Race Guard: Cancel stop order first and verify
        if pos.stop_order_id is not None:
            stop_bid = pos.stop_order_id
            try:
                self.broker.cancel_order(stop_bid)
            except Exception as exc:
                logger.warning(f"Failed to cancel stop {stop_bid}: {exc}")

            # Verify terminal state of stop
            stop_info = self.broker.get_order_info(stop_bid)
            if stop_info.status is OrderStatus.COMPLETE:
                # Stop filled right before/during cancel! Position is already closed.
                logger.info(f"Stop order {stop_bid} was already filled. Skipping exit placement to prevent double-sell.")
                trade = Trade(
                    mode=self.mode,
                    symbol=pos.symbol,
                    side=pos.side,
                    quantity=pos.quantity,
                    entry_time=pos.entry_time,
                    entry_price=pos.entry_price,
                    exit_time=when,
                    exit_price=stop_info.fill_price or pos.stop_price,
                    pnl=((stop_info.fill_price or pos.stop_price) - pos.entry_price) * pos.quantity,
                    charges=0.0,
                    reason="STOP_LOSS",
                )
                self.executed_trades.append(trade)
                if self.db is not None:
                    self.db.insert_trade(trade)
                    self.db.delete_position(self.mode, pos.symbol)
                return

        # Place market exit order
        exit_order = Order(
            mode=self.mode,
            symbol=pos.symbol,
            side=Side.SELL,
            quantity=pos.quantity,
            order_type=OrderType.MARKET,
            purpose=OrderPurpose.EXIT,
            signal_id=signal_id,
            timestamp=when,
        )

        try:
            exit_bid = self.broker.place_order(exit_order)
            exit_order.broker_order_id = exit_bid
            if self.db is not None:
                self.db.insert_order(exit_order)
        except Exception as exc:
            logger.critical(f"Failed to place exit order: {exc}")
            self.halted = True
            self.halt_reason = "EXIT_PLACEMENT_FAILURE"
            return

        exit_info = self._poll_order(exit_bid)
        exit_price = exit_info.fill_price or price
        if exit_order.status is not OrderStatus.COMPLETE:
            exit_order.transition_to(OrderStatus.COMPLETE, broker_order_id=exit_bid, fill_price=exit_price)

        trade = Trade(
            mode=self.mode,
            symbol=pos.symbol,
            side=pos.side,
            quantity=pos.quantity,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=when,
            exit_price=exit_price,
            pnl=(exit_price - pos.entry_price) * pos.quantity,
            charges=0.0,
            reason=reason,
        )
        self.executed_trades.append(trade)
        if self.db is not None:
            self.db.insert_trade(trade)
            self.db.delete_position(self.mode, pos.symbol)
            if exit_order.id is not None:
                self.db.update_order(exit_order.id, status=OrderStatus.COMPLETE, fill_price=exit_price)

    def run_replay(self, feed: any) -> list[Trade]:
        """Convenience method to process an entire replay feed to completion."""
        while feed.has_next:
            candle = feed.next_candle()
            if candle is not None:
                self.process_candle(candle)
        return list(self.executed_trades)
