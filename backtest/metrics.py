"""Backtest performance metrics. Pure functions over completed trades and the equity curve."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from models import Trade


@dataclass(frozen=True)
class Metrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_pct: Optional[float]          # None when there are no trades
    gross_pnl: float                       # before estimated charges
    total_charges: float                   # ESTIMATED
    net_pnl: float                         # after estimated charges
    return_pct: float                      # net_pnl / starting capital
    max_drawdown: float                    # rupees, positive number
    max_drawdown_pct: float                # % of the running equity peak
    profit_factor: Optional[float]         # gross profit / gross loss; None when there are no losing trades
    avg_profit: Optional[float]            # mean of winning trades
    avg_loss: Optional[float]              # mean of losing trades (negative)
    avg_trade: Optional[float]
    final_equity: float

    def to_dict(self) -> dict:
        return asdict(self)


def max_drawdown(equity: Sequence[float], start_equity: float) -> tuple[float, float]:
    """Largest peak-to-trough fall as (rupees, percent of that peak). The starting equity counts as a peak."""
    values = np.concatenate([[start_equity], np.asarray(equity, dtype=float)])
    peaks = np.maximum.accumulate(values)
    drops = peaks - values
    if not len(drops) or drops.max() <= 0:
        return 0.0, 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(peaks > 0, drops / peaks * 100, 0.0)
    return float(drops.max()), float(pct.max())


def compute_metrics(trades: Sequence[Trade], equity_curve: pd.Series, capital: float) -> Metrics:
    pnls = [t.pnl for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    total = len(pnls)
    charges = sum(t.charges for t in trades)
    net = sum(pnls)
    gross_loss = -sum(losers)
    dd, dd_pct = max_drawdown(equity_curve.to_numpy(), capital)
    return Metrics(
        total_trades=total,
        winning_trades=len(winners),
        losing_trades=len(losers),
        breakeven_trades=total - len(winners) - len(losers),
        win_rate_pct=(len(winners) / total * 100) if total else None,
        gross_pnl=net + charges,
        total_charges=charges,
        net_pnl=net,
        return_pct=net / capital * 100,
        max_drawdown=dd,
        max_drawdown_pct=dd_pct,
        profit_factor=(sum(winners) / gross_loss) if gross_loss > 0 else None,
        avg_profit=(sum(winners) / len(winners)) if winners else None,
        avg_loss=(sum(losers) / len(losers)) if losers else None,
        avg_trade=(net / total) if total else None,
        final_equity=float(equity_curve.iloc[-1]) if len(equity_curve) else capital,
    )
