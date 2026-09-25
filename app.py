"""Application entry point (CLI/headless initialization)."""
from __future__ import annotations

import sys
from config import TradingConfig
from db import Database
from utils.logger import get_logger, setup_logging

logger = get_logger("app")


def main() -> int:
    """Initialize application components and logging."""
    setup_logging(log_dir="logs", console=True)
    logger.info("Starting Trading App (headless mode)...")

    db = Database("trading_app.db")
    logger.info("Database initialized successfully.")

    cfg = TradingConfig(symbol="INFY")
    logger.info(f"Loaded default trading configuration for symbol: {cfg.symbol}")

    db.close()
    logger.info("Trading App initialization completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
