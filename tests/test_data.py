import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from alphacouncil.data import archive
from alphacouncil.data.archive import (
    Archive, download_archive, parse_archive, plan_archives, save_parquet, sha256, source_timestamps,
)
from alphacouncil.data.validate import validate_candles


def make_source(tmp_path, day, *, unit="us", count=288):
    start = pd.Timestamp(day, tz="UTC")
    rows = []
    for index in range(count):
        opened = start + pd.Timedelta(minutes=5 * index)
        stamp = opened.value // (1000 if unit == "us" else 1_000_000)
        duration = 300_000_000 if unit == "us" else 300_000
        rows.append(f"{stamp},10.00000001,12,9,11,2,{stamp + duration - 1},21,5,1,10,0")
    path = tmp_path / f"BTCUSDT-5m-{day}.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(path.stem + ".csv", "\n".join(rows) + "\n")
    record = {
        "relative_raw_path": path.name, "symbol": "BTCUSDT", "interval": "5m",
        "retrieved_at_utc": "2026-10-24T12:00:00+00:00", "sha256": sha256(path.read_bytes()),
        "url": f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/5m/{path.name}",
    }
    return record


@pytest.mark.parametrize("day,unit", [("2024-12-31", "ms"), ("2025-01-01", "us")])
def test_source_precision_and_exclusive_close_survive_parquet(tmp_path, day, unit):
    start = date.fromisoformat(day)
    end = start + timedelta(days=1)
    record = make_source(tmp_path, day, unit=unit)
    frame = parse_archive(record, tmp_path, start, end)
    assert frame.iloc[0]["open"] == Decimal("10.00000001")
    assert frame.iloc[0]["open_time_utc"] == pd.Timestamp(day, tz="UTC")
    assert frame.iloc[0]["close_time_utc"] == pd.Timestamp(day, tz="UTC") + pd.Timedelta(minutes=5)
    difference = frame.iloc[0]["close_time_utc"] - frame.iloc[0]["source_close_time_utc"]
    assert difference == pd.Timedelta(microseconds=1 if unit == "us" else 1000)
    path = tmp_path / "candles.parquet"
    save_parquet(frame, path)
    loaded = pd.read_parquet(path)
    assert loaded.iloc[0]["open"] == Decimal("10.00000001")
    assert validate_candles(loaded, "BTCUSDT", "5m", start, end)["status"] == "passed"


def test_mixed_timestamp_units_at_year_boundary():
    expected = pd.to_datetime(["2024-12-31T23:55:00Z", "2025-01-01T00:00:00Z"], utc=True)
    actual = source_timestamps(pd.Series([str(expected[0].value // 1_000_000), str(expected[1].value // 1000)]))
    assert list(actual) == list(expected)


def test_parser_excludes_candles_outside_requested_window(tmp_path):
    record = make_source(tmp_path, "2026-10-22", count=576)
    frame = parse_archive(record, tmp_path, date(2026, 10, 23), date(2026, 10, 24))
    assert len(frame) == 288
    assert frame["open_time_utc"].min() == pd.Timestamp("2026-10-23T00:00:00Z")
    assert frame["close_time_utc"].max() == pd.Timestamp("2026-10-24T00:00:00Z")


@pytest.fixture
def candles(tmp_path):
    record = make_source(tmp_path, "2026-10-23")
    return parse_archive(record, tmp_path, date(2026, 10, 23), date(2026, 10, 24))


def quality(frame):
    return validate_candles(frame, "BTCUSDT", "5m", date(2026, 10, 23), date(2026, 10, 24))


def test_missing_and_duplicate_candles_are_rejected_without_repair(candles):
    missing = quality(candles.drop(index=42))
    assert missing["status"] == "failed"
    assert missing["missing_count"] == 1
    duplicate = quality(pd.concat([candles, candles.iloc[[42]]], ignore_index=True))
    assert duplicate["duplicate_count"] == 1
    assert duplicate["status"] == "failed"


@pytest.mark.parametrize("column,value", [
    ("high", Decimal("8")), ("volume_base", Decimal("-1")),
    ("close", Decimal("NaN")), ("is_complete", False),
    ("source_sha256", "missing"), ("quote_currency", "USD"),
])
def test_corrupt_values_and_incomplete_candles_fail(candles, column, value):
    candles.loc[0, column] = value
    assert quality(candles)["status"] == "failed"


def test_off_grid_timestamps_are_rejected(candles):
    candles.loc[0, "open_time_utc"] += pd.Timedelta(seconds=1)
    report = quality(candles)
    assert report["unexpected_count"] == 1
    assert report["status"] == "failed"


def test_source_bar_length_is_checked(tmp_path):
    record = make_source(tmp_path, "2026-10-23", count=1)
    record["interval"] = "1h"
    with pytest.raises(ValueError, match="close time inconsistent"):
        parse_archive(record, tmp_path, date(2026, 10, 23), date(2026, 10, 24))


def test_archive_plan_has_no_monthly_daily_overlap():
    planned = plan_archives("BTCUSDT", "5m", date(2025, 10, 24), date(2026, 10, 24))
    assert len(planned) == 35
    assert planned[0] == Archive("BTCUSDT", "5m", "monthly", "2025-10")
    assert planned[-1] == Archive("BTCUSDT", "5m", "daily", "2026-10-23")
    assert not any(item.frequency == "daily" and item.period.startswith("2026-09") for item in planned)


def test_cached_download_is_verified_and_original_receipt_preserved(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr("BTCUSDT-5m-2025-10.csv", "source data")
    content = buffer.getvalue()
    item = Archive("BTCUSDT", "5m", "monthly", "2025-10")

    def fake_fetch(url):
        body = (sha256(content) + "  " + item.relative_path.name + "\n").encode() if url.endswith(".CHECKSUM") else content
        return body, {"url": url, "sha256": sha256(body), "retrieved_at_utc": "2026-10-24T12:00:00+00:00"}

    monkeypatch.setattr(archive, "fetch", fake_fetch)
    first = download_archive(item, tmp_path)
    monkeypatch.setattr(archive, "fetch", lambda url: pytest.fail("Cached files must not be fetched"))
    assert download_archive(item, tmp_path) == first
    path = tmp_path / first["relative_raw_path"]
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity verification"):
        download_archive(item, tmp_path)


def test_provider_checksum_mismatch_never_publishes_raw_file(tmp_path, monkeypatch):
    item = Archive("BTCUSDT", "5m", "monthly", "2025-10")

    def fake_fetch(url):
        body = ("0" * 64 + "  " + item.relative_path.name).encode() if url.endswith(".CHECKSUM") else b"bad zip"
        return body, {"url": url, "sha256": sha256(body)}

    monkeypatch.setattr(archive, "fetch", fake_fetch)
    with pytest.raises(ValueError, match="Provider SHA-256 mismatch"):
        download_archive(item, tmp_path)
    assert not (tmp_path / "binance" / item.relative_path).exists()
