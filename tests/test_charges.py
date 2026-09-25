import math

import pytest

from utils.charges import ChargesConfig, estimate_charges


def test_known_round_trip_hand_calculated():
    c = estimate_charges(50_000, 51_500)
    assert c.brokerage == pytest.approx(30.45)            # 0.03% of each order, both under the Rs 20 cap
    assert c.stt == pytest.approx(12.875)                 # 0.025% of the SELL value only
    assert c.exchange == pytest.approx(3.11605)           # 0.00307% of turnover 101,500
    assert c.sebi == pytest.approx(0.1015)                # Rs 10 per crore of turnover
    assert c.stamp == pytest.approx(1.5)                  # 0.003% of the BUY value only
    assert c.gst == pytest.approx((30.45 + 0.1015 + 3.11605) * 0.18)   # not on STT or stamp
    assert c.total == pytest.approx(30.45 + 12.875 + 3.11605 + 0.1015 + 1.5 + c.gst)


def test_brokerage_is_capped_per_order():
    c = estimate_charges(1_000_000, 1_000_000)            # 0.03% would be Rs 300 per order
    assert c.brokerage == pytest.approx(40.0)
    assert estimate_charges(1_000_000, 1_000_000, ChargesConfig(brokerage_cap_per_order=None)).brokerage == pytest.approx(600.0)


def test_stt_only_on_sell_and_stamp_only_on_buy():
    assert estimate_charges(50_000, 0).stt == 0
    assert estimate_charges(0, 50_000).stamp == 0


def test_none_config_is_all_zero():
    assert estimate_charges(123_456, 130_000, ChargesConfig.none()).total == 0


@pytest.mark.parametrize("kwargs", [{"brokerage_pct": -1}, {"gst_pct": math.nan}, {"stt_sell_pct": math.inf},
                                    {"exchange_txn_pct": True}, {"brokerage_cap_per_order": -5}, {"sebi_pct": "0.1"}])
def test_invalid_rates_rejected(kwargs):
    with pytest.raises(ValueError):
        ChargesConfig(**kwargs)


@pytest.mark.parametrize("buy,sell", [(-1, 100), (100, -1), (math.nan, 1), (1, math.inf)])
def test_invalid_values_rejected(buy, sell):
    with pytest.raises(ValueError):
        estimate_charges(buy, sell)
