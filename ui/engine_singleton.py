"""Process-wide engine and database singletons for Streamlit (survives reruns)."""
from __future__ import annotations

import queue
import threading
from typing import Any, Optional

from config import TradingConfig
from db import Database
from models import TradingMode
from strategy.ema_strategy import EMACrossoverStrategy
from trading.broker import Broker
from trading.paper_broker import PaperBroker
from trading.signal_engine import SignalEngine
from utils.logger import get_logger

logger = get_logger("ui.engine_singleton")

_engine_lock = threading.Lock()
_engine: Optional[SignalEngine] = None
_db_lock = threading.Lock()
_db: Optional[Database] = None

engine_command_queue: queue.Queue[dict[str, Any]] = queue.Queue()


def get_db(path: str = "trading_app.db") -> Database:
    """Return the shared database instance, initializing if needed."""
    global _db
    with _db_lock:
        if _db is None:
            _db = Database(path)
    return _db


def set_db(db: Optional[Database]) -> None:
    """Explicitly set or replace the database instance (useful for tests)."""
    global _db
    with _db_lock:
        _db = db


def get_engine(
    config: Optional[TradingConfig] = None,
    mode: TradingMode = TradingMode.PAPER,
    db: Optional[Database] = None,
    broker: Optional[Broker] = None,
    strategy: Optional[Any] = None,
) -> SignalEngine:
    """Return the process-wide SignalEngine instance, initializing on first call."""
    global _engine
    with _engine_lock:
        if _engine is None:
            database = db or get_db()
            cfg = config or TradingConfig(symbol="INFY")
            strat = strategy or EMACrossoverStrategy(fast_period=9, slow_period=21)
            brk = broker or PaperBroker(cfg.capital, cfg.slippage_pct)
            _engine = SignalEngine(
                config=cfg,
                strategy=strat,
                broker=brk,
                db=database,
                mode=mode,
                enforce_singleton=False,
            )
            logger.info(f"Initialized UI engine singleton in {mode.value} mode")
    return _engine


def get_current_engine() -> Optional[SignalEngine]:
    """Return the active engine if initialized, without creating a new one."""
    with _engine_lock:
        return _engine


def clear_engine() -> None:
    """Close and clear the active engine singleton."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.close()
            _engine = None
            logger.info("Cleared UI engine singleton")
