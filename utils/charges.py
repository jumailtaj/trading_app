"""Estimated trading charges for INDIAN EQUITY INTRADAY (MIS) trades on NSE.

These are ESTIMATES. Rates change (NSE's transaction charge differed between three snapshots of
the same Zerodha page while this was being written). Defaults below were read from
https://zerodha.com/charges on 2026-09-24; re-check before trusting cost-sensitive results.
Every rate is a field, so updating one is a one-line change. Not modelled: IPFT (about
Rs 0.01/crore), DP charges (delivery sells only), call-and-trade fees, exchange-specific extras.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Optional

RATES_CHECKED = "2026-09-24 from zerodha.com/charges (equity intraday, NSE)"


@dataclass(frozen=True)
class ChargesConfig:
    brokerage_pct: float = 0.03                       # % of order value ...
    brokerage_cap_per_order: Optional[float] = 20.0   # ... capped at this many rupees per order (None = no cap)
    stt_sell_pct: float = 0.025                       # securities transaction tax, sell side only
    exchange_txn_pct: float = 0.00307                 # NSE transaction charge, both sides
    sebi_pct: float = 0.0001                          # Rs 10 per crore, both sides
    stamp_buy_pct: float = 0.003                      # stamp duty, buy side only
    gst_pct: float = 18.0                             # on brokerage + SEBI + exchange charges

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "brokerage_cap_per_order" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{f.name} must be a finite number >= 0, got {value!r}")

    @classmethod
    def none(cls) -> "ChargesConfig":
        """Charges switched off (every rate zero)."""
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Charges:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst

    def to_dict(self) -> dict[str, float]:
        return {"brokerage": self.brokerage, "stt": self.stt, "exchange": self.exchange, "sebi": self.sebi,
                "stamp": self.stamp, "gst": self.gst, "total": self.total}


def _brokerage(order_value: float, cfg: ChargesConfig) -> float:
    fee = order_value * cfg.brokerage_pct / 100
    return fee if cfg.brokerage_cap_per_order is None else min(fee, cfg.brokerage_cap_per_order)


def estimate_charges(buy_value: float, sell_value: float, cfg: Optional[ChargesConfig] = None) -> Charges:
    """Charges for ONE round trip: one buy order worth buy_value and one sell order worth sell_value (INR)."""
    cfg = cfg or ChargesConfig()
    for name, v in (("buy_value", buy_value), ("sell_value", sell_value)):
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"{name} must be a finite number >= 0, got {v!r}")
    turnover = buy_value + sell_value
    brokerage = _brokerage(buy_value, cfg) + _brokerage(sell_value, cfg)
    stt = sell_value * cfg.stt_sell_pct / 100
    exchange = turnover * cfg.exchange_txn_pct / 100
    sebi = turnover * cfg.sebi_pct / 100
    stamp = buy_value * cfg.stamp_buy_pct / 100
    gst = (brokerage + sebi + exchange) * cfg.gst_pct / 100
    return Charges(brokerage, stt, exchange, sebi, stamp, gst)
