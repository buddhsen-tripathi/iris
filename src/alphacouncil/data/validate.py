"""Strict integrity checks: never fill gaps or silently discard duplicates."""

from datetime import date
from decimal import Decimal

import pandas as pd

from alphacouncil.data.archive import DECIMAL_COLUMNS, INTERVALS


def validate_candles(frame: pd.DataFrame, symbol: str, interval: str, start: date, end: date) -> dict:
    errors = []
    for column in ("open_time_utc", "close_time_utc", "source_close_time_utc", "ingested_at_utc"):
        series = frame[column]
        if not isinstance(series.dtype, pd.DatetimeTZDtype) or str(series.dt.tz) != "UTC" or series.isna().any():
            errors.append(f"{column} must contain non-null UTC timestamps")
    for column, expected in {
        "venue": "binance", "instrument_id": symbol, "instrument_type": "spot",
        "interval": interval, "quote_currency": "USDT", "base_currency": symbol.removesuffix("USDT"),
    }.items():
        if not frame[column].eq(expected).all():
            errors.append(f"Unexpected {column}")
    key = ["venue", "instrument_id", "interval", "open_time_utc"]
    duplicates = int(frame.duplicated(key).sum())
    if duplicates:
        errors.append(f"{duplicates} duplicate candle keys")
    if not frame["open_time_utc"].is_monotonic_increasing:
        errors.append("Timestamps are not ascending")
    expected_times = pd.date_range(
        pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"),
        freq=pd.Timedelta(INTERVALS[interval]), inclusive="left",
    )
    actual = pd.DatetimeIndex(frame["open_time_utc"])
    missing = expected_times.difference(actual)
    unexpected = actual.difference(expected_times)
    if len(missing):
        errors.append(f"{len(missing)} missing candles")
    if len(unexpected):
        errors.append(f"{len(unexpected)} off-grid/out-of-range candles")
    if not frame["close_time_utc"].eq(frame["open_time_utc"] + INTERVALS[interval]).all():
        errors.append("Bar durations do not match interval")
    if not frame["is_complete"].eq(True).all():
        errors.append("Incomplete candle present")
    if not frame["close_time_utc"].le(frame["ingested_at_utc"]).all():
        errors.append("Candle was ingested before it completed")
    for column in DECIMAL_COLUMNS:
        if not frame[column].map(lambda value: isinstance(value, Decimal) and value.is_finite()).all():
            errors.append(f"{column}: missing/non-finite/non-decimal value")
    if not any("non-finite" in error for error in errors):
        if not frame[["open", "high", "low", "close"]].gt(0).all().all():
            errors.append("Nonpositive OHLC price")
        if not (
            frame["low"].le(frame["open"]) & frame["low"].le(frame["close"])
            & frame["high"].ge(frame["open"]) & frame["high"].ge(frame["close"])
        ).all():
            errors.append("OHLC bounds invalid")
        if not frame[list(DECIMAL_COLUMNS[4:])].ge(0).all().all():
            errors.append("Negative volume")
    if frame["trade_count"].isna().any() or not frame["trade_count"].ge(0).all():
        errors.append("Invalid trade count")
    if frame["source_url"].isna().any() or not frame["source_url"].str.startswith(
        "https://data.binance.vision/data/spot/"
    ).all():
        errors.append("Missing/unexpected source URL")
    if not frame["source_sha256"].str.fullmatch(r"[a-f0-9]{64}", na=False).all():
        errors.append("Invalid source hash")
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "row_count": len(frame),
        "expected_row_count": len(expected_times),
        "duplicate_count": duplicates,
        "missing_count": len(missing),
        "missing_timestamps_sample": [value.isoformat() for value in missing[:20]],
        "unexpected_count": len(unexpected),
        "first_open_utc": None if frame.empty else frame["open_time_utc"].iloc[0].isoformat(),
        "last_close_utc_exclusive": None if frame.empty else frame["close_time_utc"].iloc[-1].isoformat(),
        "zero_volume_count": int(frame["volume_base"].eq(0).sum()),
    }
