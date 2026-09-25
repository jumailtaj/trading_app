"""SQLite storage: settings, orders, trades, positions, backtests, logs.

One connection guarded by a lock (the engine thread and the UI thread both use it).
Timestamps are stored as IST ISO-8601 text, so substr(ts, 1, 10) is the IST calendar date.
CHECK constraints are the last line of defence against bad modes / quantities / statuses.
This module never logs (the DB log handler writes through it; logging here could recurse).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import date, datetime
from typing import Any, Optional

from models import (
    NON_TERMINAL_STATUSES, TERMINAL_STATUSES, Order, OrderPurpose, OrderStatus, OrderType,
    Position, Side, Trade, TradingMode,
)
from utils.timeutil import from_iso, now_ist, to_iso

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_SECRETISH_KEY = re.compile(r"secret|token|password|passwd|api[_-]?key", re.IGNORECASE)


def _enum_check(column: str, enum_cls: type) -> str:
    values = ", ".join(f"'{e.value}'" for e in enum_cls)
    return f"CHECK ({column} IN ({values}))"


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mode             TEXT NOT NULL {_enum_check('mode', TradingMode)},
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL {_enum_check('side', Side)},
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    price            REAL,
    order_type       TEXT NOT NULL {_enum_check('order_type', OrderType)},
    purpose          TEXT NOT NULL {_enum_check('purpose', OrderPurpose)},
    signal_id        TEXT,
    broker_order_id  TEXT,
    status           TEXT NOT NULL {_enum_check('status', OrderStatus)},
    fill_price       REAL,
    timestamp        TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (mode, signal_id, purpose)
);
CREATE INDEX IF NOT EXISTS idx_orders_signal ON orders (signal_id);
CREATE INDEX IF NOT EXISTS idx_orders_broker ON orders (broker_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_mode_ts ON orders (mode, timestamp);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mode         TEXT NOT NULL {_enum_check('mode', TradingMode)},
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL {_enum_check('side', Side)},
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    entry_time   TEXT NOT NULL,
    entry_price  REAL NOT NULL,
    exit_time    TEXT NOT NULL,
    exit_price   REAL NOT NULL,
    pnl          REAL NOT NULL,          -- NET of estimated charges
    charges      REAL NOT NULL DEFAULT 0,
    reason       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trades_mode_exit ON trades (mode, exit_time);

CREATE TABLE IF NOT EXISTS positions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    mode           TEXT NOT NULL {_enum_check('mode', TradingMode)},
    symbol         TEXT NOT NULL,
    side           TEXT NOT NULL {_enum_check('side', Side)},
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    entry_price    REAL NOT NULL,
    entry_time     TEXT NOT NULL,
    stop_price     REAL NOT NULL,
    target_price   REAL,
    stop_order_id  TEXT,
    UNIQUE (mode, symbol)                -- one open position per instrument per mode
);

CREATE TABLE IF NOT EXISTS backtests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    params_json  TEXT NOT NULL,
    result_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL,
    level      TEXT NOT NULL,
    logger     TEXT NOT NULL,
    message    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs (timestamp);
"""


class DatabaseError(RuntimeError):
    pass


class Database:
    def __init__(self, path: str = "trading_app.db"):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            cur = self._conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = cur.fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (1, to_iso(now_ist())),
                )
            elif row[0] != 1:
                raise DatabaseError(
                    f"Schema is version {row[0]}; expected 1. Delete the DB to start fresh."
                )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- helpers -----------------------------------------------------------------
    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:            # `with conn` = commit or roll back
            return self._conn.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---- settings ------------------------------------------------------------------
    def set_setting(self, key: str, value: Any) -> None:
        if _SECRETISH_KEY.search(key):
            raise ValueError(f"refusing to store {key!r}: secrets belong in .env, never in the database")
        self._execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), to_iso(now_ist())),
        )

    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self._query("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def is_kill_switch_active(self, mode: TradingMode) -> bool:
        return bool(self.get_setting(f"kill_switch:{mode.value}", False))

    def set_kill_switch(self, mode: TradingMode, active: bool = True) -> None:
        self.set_setting(f"kill_switch:{mode.value}", active)

    def is_daily_loss_latched(self, mode: TradingMode, day: date) -> bool:
        return bool(self.get_setting(f"daily_loss_halt:{mode.value}:{day.isoformat()}", False))

    def set_daily_loss_latch(self, mode: TradingMode, day: date, latched: bool = True) -> None:
        self.set_setting(f"daily_loss_halt:{mode.value}:{day.isoformat()}", latched)

    # ---- orders --------------------------------------------------------------------
    @staticmethod
    def _order_from_row(r: sqlite3.Row) -> Order:
        return Order(
            id=r["id"], mode=TradingMode(r["mode"]), symbol=r["symbol"], side=Side(r["side"]),
            quantity=r["quantity"], price=r["price"], order_type=OrderType(r["order_type"]),
            purpose=OrderPurpose(r["purpose"]), signal_id=r["signal_id"],
            broker_order_id=r["broker_order_id"], status=OrderStatus(r["status"]),
            fill_price=r["fill_price"], timestamp=from_iso(r["timestamp"]),
        )

    def insert_order(self, order: Order) -> int:
        now = to_iso(now_ist())
        cur = self._execute(
            "INSERT INTO orders (mode, symbol, side, quantity, price, order_type, purpose, signal_id, "
            "broker_order_id, status, fill_price, timestamp, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (order.mode.value, order.symbol, order.side.value, order.quantity, order.price,
             order.order_type.value, order.purpose.value, order.signal_id, order.broker_order_id,
             order.status.value, order.fill_price, to_iso(order.timestamp), now),
        )
        order.id = cur.lastrowid
        return order.id

    def update_order(self, order_id: int, *, status: Optional[OrderStatus] = None,
                     broker_order_id: Optional[str] = None, fill_price: Optional[float] = None) -> None:
        """Update an order. A terminal order (COMPLETE/REJECTED/CANCELLED) can never change state again."""
        with self._lock:
            current = self.get_order(order_id)
            if current is None:
                raise DatabaseError(f"order {order_id} not found")
            if current.status in TERMINAL_STATUSES and status is not None and status is not current.status:
                raise DatabaseError(
                    f"order {order_id} is already {current.status.value}; cannot move to {status.value}"
                )
            sets, params = ["updated_at = ?"], [to_iso(now_ist())]
            if status is not None:
                sets.append("status = ?"); params.append(status.value)
            if broker_order_id is not None:
                sets.append("broker_order_id = ?"); params.append(broker_order_id)
            if fill_price is not None:
                sets.append("fill_price = ?"); params.append(fill_price)
            params.append(order_id)
            self._execute(f"UPDATE orders SET {', '.join(sets)} WHERE id = ?", tuple(params))

    def get_order(self, order_id: int) -> Optional[Order]:
        rows = self._query("SELECT * FROM orders WHERE id = ?", (order_id,))
        return self._order_from_row(rows[0]) if rows else None

    def get_orders(self, mode: Optional[TradingMode] = None, symbol: Optional[str] = None,
                   day: Optional[date] = None, status: Optional[OrderStatus] = None,
                   signal_id: Optional[str] = None) -> list[Order]:
        clauses, params = [], []
        if mode is not None:
            clauses.append("mode = ?"); params.append(mode.value)
        if symbol is not None:
            clauses.append("symbol = ?"); params.append(symbol)
        if day is not None:
            clauses.append("substr(timestamp, 1, 10) = ?"); params.append(day.isoformat())
        if status is not None:
            clauses.append("status = ?"); params.append(status.value)
        if signal_id is not None:
            clauses.append("signal_id = ?"); params.append(signal_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM orders {where} ORDER BY id", tuple(params))
        return [self._order_from_row(r) for r in rows]

    def count_entries_today(self, mode: TradingMode, symbol: Optional[str] = None,
                            day: Optional[date] = None) -> int:
        target_day = day or now_ist().date()
        clauses = ["mode = ?", "purpose = 'ENTRY'", "substr(timestamp, 1, 10) = ?"]
        params: list[Any] = [mode.value, target_day.isoformat()]
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        rows = self._query(f"SELECT COUNT(*) AS count FROM orders WHERE {' AND '.join(clauses)}", tuple(params))
        return int(rows[0]["count"])

    def get_unresolved_orders(self, mode: TradingMode) -> list[Order]:
        marks = ",".join("?" * len(NON_TERMINAL_STATUSES))
        params = (mode.value,) + tuple(s.value for s in NON_TERMINAL_STATUSES)
        rows = self._query(
            f"SELECT * FROM orders WHERE mode = ? AND status IN ({marks}) ORDER BY id",
            params,
        )
        return [self._order_from_row(r) for r in rows]

    # ---- trades --------------------------------------------------------------------
    @staticmethod
    def _trade_from_row(r: sqlite3.Row) -> Trade:
        return Trade(
            id=r["id"], mode=TradingMode(r["mode"]), symbol=r["symbol"], side=Side(r["side"]),
            quantity=r["quantity"], entry_time=from_iso(r["entry_time"]), entry_price=r["entry_price"],
            exit_time=from_iso(r["exit_time"]), exit_price=r["exit_price"], pnl=r["pnl"],
            charges=r["charges"], reason=r["reason"],
        )

    def insert_trade(self, trade: Trade) -> int:
        cur = self._execute(
            "INSERT INTO trades (mode, symbol, side, quantity, entry_time, entry_price, exit_time, "
            "exit_price, pnl, charges, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (trade.mode.value, trade.symbol, trade.side.value, trade.quantity, to_iso(trade.entry_time),
             trade.entry_price, to_iso(trade.exit_time), trade.exit_price, trade.pnl, trade.charges,
             trade.reason),
        )
        trade.id = cur.lastrowid
        return trade.id

    def get_trades(self, mode: Optional[TradingMode] = None, symbol: Optional[str] = None,
                   day: Optional[date] = None) -> list[Trade]:
        """`day` filters on the EXIT date (when the P&L was realised)."""
        clauses, params = [], []
        if mode is not None:
            clauses.append("mode = ?"); params.append(mode.value)
        if symbol is not None:
            clauses.append("symbol = ?"); params.append(symbol)
        if day is not None:
            clauses.append("substr(exit_time, 1, 10) = ?"); params.append(day.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM trades {where} ORDER BY exit_time, id", tuple(params))
        return [self._trade_from_row(r) for r in rows]

    def realized_pnl(self, mode: TradingMode, day: date) -> float:
        """Net P&L of trades CLOSED on `day` (IST) in `mode`. Used by the daily-loss check."""
        rows = self._query(
            "SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE mode = ? AND substr(exit_time, 1, 10) = ?",
            (mode.value, day.isoformat()),
        )
        return float(rows[0]["total"])

    def realized_pnl_today(self, mode: TradingMode, day: date) -> float:
        return self.realized_pnl(mode, day)

    # ---- positions -----------------------------------------------------------------
    @staticmethod
    def _position_from_row(r: sqlite3.Row) -> Position:
        return Position(
            mode=TradingMode(r["mode"]), symbol=r["symbol"], side=Side(r["side"]), quantity=r["quantity"],
            entry_price=r["entry_price"], entry_time=from_iso(r["entry_time"]), stop_price=r["stop_price"],
            target_price=r["target_price"], stop_order_id=r["stop_order_id"],
        )

    def save_position(self, p: Position) -> None:
        """Insert or replace the single open position for (mode, symbol)."""
        self._execute(
            "INSERT INTO positions (mode, symbol, side, quantity, entry_price, entry_time, stop_price, "
            "target_price, stop_order_id) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(mode, symbol) DO UPDATE SET side=excluded.side, quantity=excluded.quantity, "
            "entry_price=excluded.entry_price, entry_time=excluded.entry_time, stop_price=excluded.stop_price, "
            "target_price=excluded.target_price, stop_order_id=excluded.stop_order_id",
            (p.mode.value, p.symbol, p.side.value, p.quantity, p.entry_price, to_iso(p.entry_time),
             p.stop_price, p.target_price, p.stop_order_id),
        )

    def get_position(self, mode: TradingMode, symbol: str) -> Optional[Position]:
        rows = self._query("SELECT * FROM positions WHERE mode = ? AND symbol = ?", (mode.value, symbol))
        return self._position_from_row(rows[0]) if rows else None

    def get_open_positions(self, mode: TradingMode) -> list[Position]:
        rows = self._query("SELECT * FROM positions WHERE mode = ? ORDER BY symbol", (mode.value,))
        return [self._position_from_row(r) for r in rows]

    def get_unprotected_live_positions(self) -> list[Position]:
        rows = self._query(
            "SELECT * FROM positions WHERE mode = ? AND (stop_order_id IS NULL OR stop_order_id = '') ORDER BY symbol",
            (TradingMode.LIVE.value,),
        )
        return [self._position_from_row(r) for r in rows]

    def delete_position(self, mode: TradingMode, symbol: str) -> bool:
        return self._execute("DELETE FROM positions WHERE mode = ? AND symbol = ?", (mode.value, symbol)).rowcount > 0

    # ---- backtests -----------------------------------------------------------------
    def save_backtest(self, symbol: str, params: dict, result: dict) -> int:
        cur = self._execute(
            "INSERT INTO backtests (created_at, symbol, params_json, result_json) VALUES (?,?,?,?)",
            (to_iso(now_ist()), symbol, json.dumps(params), json.dumps(result)),
        )
        return cur.lastrowid

    def get_backtest(self, backtest_id: int) -> Optional[dict]:
        rows = self._query("SELECT * FROM backtests WHERE id = ?", (backtest_id,))
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "created_at": from_iso(r["created_at"]), "symbol": r["symbol"],
                "params": json.loads(r["params_json"]), "result": json.loads(r["result_json"])}

    def list_backtests(self, limit: int = 20) -> list[dict]:
        rows = self._query("SELECT id, created_at, symbol FROM backtests ORDER BY id DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "created_at": from_iso(r["created_at"]), "symbol": r["symbol"]} for r in rows]

    # ---- logs ----------------------------------------------------------------------
    def insert_log(self, level: str, logger_name: str, message: str, timestamp: Optional[datetime] = None) -> None:
        self._execute(
            "INSERT INTO logs (timestamp, level, logger, message) VALUES (?,?,?,?)",
            (to_iso(timestamp or now_ist()), level, logger_name, message),
        )

    def get_logs(self, limit: int = 200, min_level: str = "DEBUG") -> list[dict]:
        floor = _LEVELS.get(min_level.upper(), 0)
        levels = tuple(name for name, n in _LEVELS.items() if n >= floor)
        marks = ",".join("?" * len(levels))
        rows = self._query(
            f"SELECT * FROM logs WHERE level IN ({marks}) ORDER BY id DESC LIMIT ?", levels + (limit,)
        )
        return [{"id": r["id"], "timestamp": from_iso(r["timestamp"]), "level": r["level"],
                 "logger": r["logger"], "message": r["message"]} for r in rows]
