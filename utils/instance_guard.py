"""Single-instance guard using Database heartbeat and lock records (H4)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

from db import Database
from models import TradingMode
from utils.logger import get_logger
from utils.timeutil import from_iso, now_ist

logger = get_logger("instance_guard")


class InstanceGuard:
    """Guarantees only one live engine instance runs per trading mode."""

    def __init__(
        self,
        db: Database,
        mode: TradingMode = TradingMode.LIVE,
        timeout_seconds: float = 60.0,
        pid: Optional[int] = None,
    ) -> None:
        self.db = db
        self.mode = mode
        self.timeout_seconds = timeout_seconds
        self.pid = pid or os.getpid()
        self.acquired = False

    def acquire(self) -> None:
        """Acquire the instance lock. If a fresh lock exists from another PID, refuse to start."""
        existing = self.db.read_instance_lock(self.mode)
        if existing is not None:
            existing_pid = int(existing.get("pid", 0))
            ts_str = existing.get("ts")
            if ts_str:
                lock_time = from_iso(ts_str)
                age = (now_ist() - lock_time).total_seconds()
                if age < self.timeout_seconds and existing_pid != self.pid:
                    msg = f"Another instance of the live engine is running (PID {existing_pid})"
                    logger.critical(msg)
                    raise RuntimeError(msg)
                if age >= self.timeout_seconds:
                    logger.warning(
                        f"Overriding stale lock from PID {existing_pid} (age: {age:.1f}s > {self.timeout_seconds}s)"
                    )

        self.db.write_instance_lock(self.mode, self.pid)
        self.acquired = True
        logger.info(f"Acquired instance lock for mode {self.mode.value} (PID {self.pid})")

    def heartbeat(self, timestamp: Optional[datetime] = None) -> None:
        """Refresh the lock timestamp."""
        if not self.acquired:
            raise RuntimeError("Cannot heartbeat without an acquired instance lock")
        self.db.write_instance_lock(self.mode, self.pid, timestamp=timestamp)

    def release(self) -> None:
        """Release the instance lock on clean shutdown."""
        if self.acquired:
            self.db.delete_instance_lock(self.mode)
            self.acquired = False
            logger.info(f"Released instance lock for mode {self.mode.value} (PID {self.pid})")

    def __enter__(self) -> InstanceGuard:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
