"""Risk manager: position sizing plus the pre-trade checks every mode goes through.

Pure logic: no broker, no DB, no clock. The caller passes in today's realised P&L and entry count,
so backtest, paper and live all get identical decisions from identical inputs.
(Phase 6 adds the live-only protections: stop-loss failure halt, disconnect / reconciliation halts.)

Check order (first failure wins): trading window -> daily loss -> max trades -> quantity.
The daily-loss halt LATCHES for the rest of that calendar day (IST): even if P&L recovers, trading
does not automatically resume.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from config import TradingConfig
from models import TradingMode
from utils.timeutil import to_ist

OK = "OK"
OUTSIDE_TRADING_WINDOW = "OUTSIDE_TRADING_WINDOW"
DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
MAX_TRADES = "MAX_TRADES"
QUANTITY_ZERO = "QUANTITY_ZERO"
KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    quantity: int
    reason: str            # one of the codes above


class RiskManager:
    def __init__(self, config: TradingConfig, db: Optional[Any] = None,
                 mode: TradingMode = TradingMode.BACKTEST):
        self.config = config
        self.db = db
        self.mode = mode
        self._loss_halt_day: Optional[date] = None

    def position_size(self, entry_price: float) -> int:
        """Shares to buy: risk-based, capped by what capital can afford (no leverage) and max_quantity.

        risk-based = floor( capital * risk% / (entry_price * stop_loss%) )
        A result of 0 means the trade is too small to take safely; it is never rounded up.
        """
        if isinstance(entry_price, bool) or not isinstance(entry_price, (int, float)) \
                or not math.isfinite(entry_price) or entry_price <= 0:
            raise ValueError(f"entry_price must be a positive finite number, got {entry_price!r}")
        c = self.config
        risk_amount = c.capital * c.risk_per_trade_pct / 100
        risk_per_share = entry_price * c.stop_loss_pct / 100
        by_risk = math.floor(risk_amount / risk_per_share + 1e-9)
        by_capital = math.floor(c.capital / entry_price + 1e-9)
        return max(0, min(by_risk, by_capital, c.max_quantity))

    def check_entry(self, *, when: datetime, entry_price: float, realized_pnl_today: float,
                    entries_today: int) -> RiskDecision:
        now = to_ist(when)
        c = self.config

        # 1. Kill switch check (highest priority)
        if self.db is not None and self.db.is_kill_switch_active(self.mode):
            return RiskDecision(False, 0, KILL_SWITCH_ACTIVE)

        # 2. Trading window check
        if not (c.trading_start <= now.time() <= c.trading_end):
            return RiskDecision(False, 0, OUTSIDE_TRADING_WINDOW)

        # 3. Daily loss limit check (with DB latch persistence if DB configured)
        today = now.date()
        if self._loss_halt_day is not None and self._loss_halt_day != today:
            self._loss_halt_day = None                       # a new day starts clean

        db_latched = self.db.is_daily_loss_latched(self.mode, today) if self.db is not None else False
        if realized_pnl_today <= -c.max_daily_loss:
            self._loss_halt_day = today
            if self.db is not None:
                self.db.set_daily_loss_latch(self.mode, today, True)

        if self._loss_halt_day == today or db_latched:
            return RiskDecision(False, 0, DAILY_LOSS_LIMIT)

        # 4. Max trades check
        if entries_today >= c.max_trades_per_day:
            return RiskDecision(False, 0, MAX_TRADES)

        # 5. Position sizing check
        qty = self.position_size(entry_price)
        if qty <= 0:
            return RiskDecision(False, 0, QUANTITY_ZERO)
        return RiskDecision(True, qty, OK)
