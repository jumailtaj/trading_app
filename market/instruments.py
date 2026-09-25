"""Instrument master cache and symbol-to-token lookup for Kite Connect."""
from __future__ import annotations

import csv
import pathlib
from typing import Any, Optional


def dump_instruments(kite_client: Any, cache_file: str = "instruments.csv", exchange: str = "NSE") -> list[dict[str, Any]]:
    """Fetch instruments from Kite Connect API, cache locally, and return list."""
    if kite_client is None:
        raise ValueError("kite_client is required to dump instruments")

    instruments = kite_client.instruments(exchange)
    if not instruments:
        return []

    p = pathlib.Path(cache_file)
    p.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "instrument_token", "exchange_token", "tradingsymbol", "name",
        "last_price", "expiry", "strike", "tick_size", "lot_size",
        "instrument_type", "segment", "exchange"
    ]

    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(instruments)

    return instruments


def load_instruments(cache_file: str = "instruments.csv") -> list[dict[str, Any]]:
    """Load cached instruments from CSV."""
    p = pathlib.Path(cache_file)
    if not p.exists():
        return []

    with open(p, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        instruments = []
        for row in reader:
            parsed: dict[str, Any] = dict(row)
            try:
                parsed["instrument_token"] = int(row["instrument_token"])
                parsed["tick_size"] = float(row.get("tick_size", 0.05))
                parsed["lot_size"] = int(row.get("lot_size", 1))
            except (ValueError, TypeError):
                pass
            instruments.append(parsed)
        return instruments


def lookup_instrument(
    symbol: str,
    exchange: str = "NSE",
    cache_file: str = "instruments.csv",
    instruments: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    """Find instrument token, tick size, and lot size for a symbol."""
    target_symbol = symbol.strip().upper()
    target_exchange = exchange.strip().upper()

    inst_list = instruments if instruments is not None else load_instruments(cache_file)
    for inst in inst_list:
        sym = str(inst.get("tradingsymbol", "")).strip().upper()
        exch = str(inst.get("exchange", "")).strip().upper()
        if sym == target_symbol and (not target_exchange or exch == target_exchange):
            return {
                "instrument_token": int(inst["instrument_token"]),
                "tradingsymbol": sym,
                "name": inst.get("name", sym),
                "tick_size": float(inst.get("tick_size", 0.05)),
                "lot_size": int(inst.get("lot_size", 1)),
                "exchange": exch,
            }
    return None
