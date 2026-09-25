"""Simulated broker for backtests: holds the one open long position, applies slippage,
fills stops/targets against candle prices, and records completed trades with estimated charges.
It never touches the network or a real broker.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from config import TradingConfig
from models import Position, Side, Trade, TradingMode
from utils.charges import ChargesConfig, estimate_charges


class ExitReason(Enum):
    SIGNAL = "SIGNAL"
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    SQUARE_OFF = "SQUARE_OFF"
    END_OF_DATA = "END_OF_DATA"


class SimulatedBroker:
    def __init__(self, config: TradingConfig, charges: ChargesConfig):
        self.config = config
        self.charges = charges
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []

    # -- slippage always works against us ------------------------------------------------
    def _buy_price(self, raw: float) -> float:
        return raw * (1 + self.config.slippage_pct / 100)

    def _sell_price(self, raw: float) -> float:
        return raw * (1 - self.config.slippage_pct / 100)

    def enter_long(self, when: datetime, open_price: float, quantity: int) -> Position:
        """Market buy at the candle open (plus slippage). Stop/target are derived from the FILL price."""
        if self.position is not None:
            raise RuntimeError("already in a position; the engine must not enter twice")
        c = self.config
        fill = self._buy_price(open_price)
        self.position = Position(
            mode=TradingMode.BACKTEST, symbol=c.symbol, side=Side.BUY, quantity=quantity,
            entry_price=fill, entry_time=when,
            stop_price=fill * (1 - c.stop_loss_pct / 100),
            target_price=fill * (1 + c.target_pct / 100) if c.enable_target else None,
        )
        return self.position

    def exit_long(self, when: datetime, raw_price: float, reason: ExitReason, *, slippage: bool = True) -> Trade:
        pos = self.position
        if pos is None:
            raise RuntimeError("no open position to exit")
        exit_price = self._sell_price(raw_price) if slippage else raw_price
        gross = (exit_price - pos.entry_price) * pos.quantity
        fees = estimate_charges(pos.entry_price * pos.quantity, exit_price * pos.quantity, self.charges).total
        trade = Trade(
            mode=TradingMode.BACKTEST, symbol=pos.symbol, side=Side.BUY, quantity=pos.quantity,
            entry_time=pos.entry_time, entry_price=pos.entry_price, exit_time=when, exit_price=exit_price,
            pnl=gross - fees, charges=fees, reason=reason.value,
        )
        self.trades.append(trade)
        self.position = None
        return trade

    def check_stop_and_target(self, when: datetime, open_: float, high: float, low: float) -> Optional[Trade]:
        """Did this candle hit the stop or the target? (Conservative rules, see engine ASSUMPTIONS.)

        * Stop hit  (low <= stop): fills at min(stop, open) so a gap through the stop fills at the
          worse open price, with slippage. If the same candle also touches the target, the stop wins.
        * Target hit (high >= target): fills at the target price, no slippage, no price improvement.
        """
        pos = self.position
        if pos is None:
            return None
        if low <= pos.stop_price:
            return self.exit_long(when, min(pos.stop_price, open_), ExitReason.STOP_LOSS)
        if pos.target_price is not None and high >= pos.target_price:
            return self.exit_long(when, pos.target_price, ExitReason.TARGET, slippage=False)
        return None
