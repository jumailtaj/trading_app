import logging
from datetime import datetime

import pytest

from db import Database
from utils import logger as logger_mod
from utils.timeutil import IST


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture(autouse=True)
def clean_logging_state():
    """Each test starts with no registered secrets and no trading_app handlers."""
    logger_mod.clear_secrets()
    yield
    root = logging.getLogger(logger_mod.LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    logger_mod.clear_secrets()


def ist(y, mo, d, h=10, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)
