from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

from config import ConfigError, TradingConfig
from models import TradingMode
from ui.engine_singleton import get_db, set_db

ROOT = Path(__file__).resolve().parent.parent


def test_stop_all_trading_always_visible():
    """Verify that the STOP ALL TRADING emergency button is always visible in the sidebar."""
    at = AppTest.from_file(str(ROOT / "app.py"))
    at.run(timeout=10)
    assert not at.exception
    stop_buttons = [btn for btn in at.sidebar.button if "STOP ALL TRADING" in btn.label]
    assert len(stop_buttons) >= 1


def test_live_page_step1_requires_live_mode_selection():
    """In live page, step 1 requires selecting LIVE before subsequent steps or activation button appear."""
    at = AppTest.from_file(str(ROOT / "ui" / "live_page.py"))
    at.run(timeout=10)
    assert not at.exception

    # Step 1 default is PAPER; activation button must not be present
    activate_buttons = [btn for btn in at.button if "ENABLE LIVE TRADING" in btn.label]
    assert len(activate_buttons) == 0
    assert any("Select 'LIVE' mode" in info.value for info in at.info)


def test_live_page_step3_rejects_wrong_symbol():
    """Step 3 rejects typed symbol that does not match the exact expected symbol."""
    at = AppTest.from_file(str(ROOT / "ui" / "live_page.py"))
    at.run(timeout=10)
    assert not at.exception

    # Select LIVE mode in Step 1
    at.selectbox(key="live_step1_mode").select("LIVE").run(timeout=10)
    # Check confirmation in Step 2
    at.checkbox(key="live_step2_ack").check().run(timeout=10)
    # Type incorrect symbol in Step 3
    at.text_input(key="live_step3_symbol").input("WRONG_SYM").run(timeout=10)

    # Must show symbol mismatch error and NOT show activation button
    assert any("Symbol mismatch" in err.value for err in at.error)
    activate_buttons = [btn for btn in at.button if "ENABLE LIVE TRADING" in btn.label]
    assert len(activate_buttons) == 0


def test_critical_banner_shows_from_db_state(db):
    """When kill switch is set in DB, dashboard displays the persistent critical alert banner."""
    set_db(db)
    db.set_kill_switch(TradingMode.PAPER, True)

    at = AppTest.from_file(str(ROOT / "ui" / "dashboard.py"))
    at.run(timeout=10)
    assert not at.exception

    # Banner must come from DB state
    assert any("KILL SWITCH IS ACTIVE" in err.value for err in at.error)

    # Clean up
    db.set_kill_switch(TradingMode.PAPER, False)
    set_db(None)


def test_settings_cannot_set_live_flag_to_true():
    """TradingConfig rejects any unknown or injected live parameters; UI cannot set live flag."""
    with pytest.raises(ConfigError, match="unknown config keys"):
        TradingConfig.from_dict({"symbol": "INFY", "live": True})

    with pytest.raises(ConfigError, match="unknown config keys"):
        TradingConfig.from_dict({"symbol": "INFY", "live_enabled": True})

    # Verify settings page has no live flag inputs
    at = AppTest.from_file(str(ROOT / "ui" / "settings_page.py"))
    at.run(timeout=10)
    assert not at.exception
    for inp in at.text_input:
        assert "live" not in inp.label.lower()
    for cb in at.checkbox:
        assert "live" not in cb.label.lower()


def test_settings_validates_through_trading_config(db):
    """Submitting invalid settings triggers ConfigError validation through TradingConfig."""
    set_db(db)
    at = AppTest.from_file(str(ROOT / "ui" / "settings_page.py"))
    at.run(timeout=10)
    assert not at.exception

    # Enter invalid symbol and submit
    at.text_input[0].input("").run(timeout=10)
    at.button[0].click().run(timeout=10)

    # Must display validation error from ConfigError
    assert any("validation failed" in err.value.lower() for err in at.error)
    set_db(None)
