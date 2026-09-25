import logging

from db import Database
from utils.logger import LOGGER_NAME, get_logger, redact, register_secret, setup_logging


def test_registered_secret_is_masked():
    register_secret("supersecrettoken")
    assert "supersecrettoken" not in redact("token is supersecrettoken ok")


def test_key_value_patterns_are_masked_without_registration():
    for line in ("access_token=abc123xyz", "api_secret: hunter22", 'password="pa55word"',
                 '{"access_token": "abc123xyz"}', "API_KEY = k3y3y3y"):
        out = redact(line)
        assert "abc123xyz" not in out and "hunter22" not in out and "pa55word" not in out and "k3y3y3y" not in out
        assert "***" in out


def test_ordinary_text_untouched():
    msg = "BUY signal generated for HDFCBANK instrument_token=738561 order id 2200001"
    assert redact(msg) == msg


def test_setup_is_idempotent(tmp_path):
    for _ in range(3):
        setup_logging(log_dir=str(tmp_path), console=True)
    root = logging.getLogger(LOGGER_NAME)
    assert len(root.handlers) == 2          # console + file, not 6


def test_file_log_written_and_redacted(tmp_path):
    register_secret("supersecrettoken")
    setup_logging(log_dir=str(tmp_path), console=False)
    get_logger("t").info("using supersecrettoken here")
    for h in logging.getLogger(LOGGER_NAME).handlers:
        h.flush()
    text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "using *** here" in text and "supersecrettoken" not in text


def test_db_handler_stores_levels_and_redacts(db: Database):
    register_secret("supersecrettoken")
    setup_logging(log_dir=None, console=False, db=db)
    log = get_logger("engine")
    log.info("Strategy started")
    log.warning("careful")
    log.error("failed with supersecrettoken")
    log.critical("Position filled but stop-loss order failed")
    rows = db.get_logs()
    assert [r["level"] for r in rows] == ["CRITICAL", "ERROR", "WARNING", "INFO"]
    assert all("supersecrettoken" not in r["message"] for r in rows)
    assert [r["level"] for r in db.get_logs(min_level="ERROR")] == ["CRITICAL", "ERROR"]


def test_db_handler_never_raises_into_caller(db: Database):
    setup_logging(log_dir=None, console=False, db=db)
    db.close()                               # break the DB on purpose
    get_logger("x").critical("still must not raise")
