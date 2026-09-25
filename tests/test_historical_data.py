import pathlib
import pytest
import pandas as pd

from market.historical_data import DataLoadError, load_csv, load_kite
from utils.timeutil import IST


def test_csv_load_roundtrip_produces_engine_schema(tmp_path: pathlib.Path):
    p = tmp_path / "sample.csv"
    p.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2026-09-23 09:15:00,100.0,102.0,99.0,101.0,500\n"
        "2026-09-23 09:20:00,101.0,103.0,100.0,102.5,600\n"
    )
    df = load_csv(p)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) == "Asia/Kolkata"
    assert len(df) == 2
    assert df.iloc[0]["open"] == 100.0


def test_csv_with_missing_required_column_raises_data_load_error(tmp_path: pathlib.Path):
    p = tmp_path / "missing_col.csv"
    p.write_text(
        "Date,Open,High,Low,Volume\n"
        "2026-09-23 09:15:00,100.0,102.0,99.0,500\n"
    )
    with pytest.raises(DataLoadError, match="missing required columns"):
        load_csv(p)


def test_csv_timezone_naive_gets_localized_to_ist(tmp_path: pathlib.Path):
    p = tmp_path / "naive.csv"
    p.write_text(
        "timestamp,open,high,low,close\n"
        "2026-09-23 09:15:00,100.0,101.0,99.0,100.5\n"
    )
    df = load_csv(p)
    assert df.index.tz == IST


def test_csv_with_invalid_ohlc_raises(tmp_path: pathlib.Path):
    p = tmp_path / "invalid_ohlc.csv"
    # high (95) < low (99)
    p.write_text(
        "timestamp,open,high,low,close\n"
        "2026-09-23 09:15:00,100.0,95.0,99.0,100.0\n"
    )
    with pytest.raises(DataLoadError, match="failed validation"):
        load_csv(p)


def test_csv_nonexistent_file_raises(tmp_path: pathlib.Path):
    p = tmp_path / "does_not_exist.csv"
    with pytest.raises(DataLoadError, match="does not exist"):
        load_csv(p)


def test_csv_column_aliases_handled(tmp_path: pathlib.Path):
    p = tmp_path / "aliases.csv"
    p.write_text(
        "datetime,OPEN,HIGH,LOW,CLOSE,VOL\n"
        "2026-09-23 09:15:00,100.0,101.0,99.0,100.5,1234\n"
    )
    df = load_csv(p)
    assert "volume" in df.columns
    assert df["volume"].iloc[0] == 1234


def test_kite_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="Kite fetch is not available until Phase D"):
        load_kite(None, "HDFCBANK", "2026-09-01", "2026-09-25")
