"""True Markets reference data, explicitly separate from executable venue prices."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from alphacouncil.data.archive import fetch, file_sha256, sha256, write_json

HOST = "https://api.truemarkets.co"


def capture(path: Path, url: str) -> dict:
    """Cache exact JSON responses with hashes and the original observation time."""
    metadata_path = path.with_name(path.name + ".metadata.json")
    if path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        if metadata["url"] != url or file_sha256(path) != metadata["sha256"]:
            raise ValueError(f"Cached response integrity failure: {path}")
        return metadata
    body, metadata = fetch(url)
    json.loads(body)  # Fail before publishing if a gateway returns HTML with HTTP 200.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(body)
    temporary.replace(path)
    write_json(metadata_path, metadata)
    return metadata


def candle_url(symbol: str, end: date) -> str:
    return HOST + "/v1/defi/market/prices/candles?" + urlencode({
        "symbol": symbol, "asset_class": "spot", "window": "1d", "resolution": "5m",
        "as_of": end.isoformat() + "T00:00:00Z",
    })


def normalize_candles(records: list[dict], root: Path, symbol: str, start: date, end: date) -> tuple[pd.DataFrame, dict]:
    frames = []
    asset_ids = set()
    dropped_incomplete = 0
    for record in records:
        payload = json.loads((root / record["path"]).read_text())
        if payload.get("symbol") != symbol or payload.get("resolution") != "5m" or not payload.get("asset_id"):
            raise ValueError(f"Unexpected provider identity/resolution: {record['url']}")
        asset_ids.add(payload["asset_id"])
        frame = pd.DataFrame(payload["candles"])
        if frame.empty:
            raise ValueError(f"Empty candle response: {record['url']}")
        frame["open_time_utc"] = pd.to_datetime(frame.pop("t"), utc=True, errors="raise")
        if not frame["open_time_utc"].is_monotonic_increasing:
            raise ValueError("Provider returned unsorted candle buckets")
        frame["close_time_utc"] = frame["open_time_utc"] + pd.Timedelta(minutes=5)
        as_of = pd.Timestamp(record["day_end_utc"], tz="UTC")
        day_start = as_of - pd.Timedelta(days=1)
        mask = frame["open_time_utc"].ge(day_start) & frame["close_time_utc"].le(as_of)
        dropped_incomplete += int((~mask).sum())
        frame = frame.loc[mask].copy()
        for column in ("open", "high", "low", "close"):
            frame[column] = frame[column].map(Decimal)
            if not frame[column].map(lambda value: value.is_finite() and value > 0).all():
                raise ValueError(f"Invalid reference {column}")
        if not (
            frame["low"].le(frame["open"]) & frame["low"].le(frame["close"])
            & frame["high"].ge(frame["open"]) & frame["high"].ge(frame["close"])
        ).all():
            raise ValueError("Invalid reference OHLC bounds")
        frame["provider"] = "truemarkets"
        frame["venue"] = None  # The source venue is absent from this API response.
        frame["instrument_id"] = payload["asset_id"]
        frame["instrument_type"] = "spot"
        frame["base_currency"] = symbol
        frame["quote_currency"] = None  # Do not assume parity with USDT or an executable pair.
        frame["interval"] = "5m"
        frame["volume_base"] = None
        frame["volume_quote"] = None
        frame["trade_count"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
        frame["ingested_at_utc"] = pd.Timestamp(record["retrieved_at_utc"])
        frame["source_url"] = record["url"]
        frame["source_sha256"] = record["sha256"]
        frame["is_complete"] = frame["close_time_utc"].le(frame["ingested_at_utc"])
        if not frame["is_complete"].all():
            raise ValueError("Reference candle extends past its retrieval time")
        frames.append(frame)
    if len(asset_ids) != 1:
        raise ValueError(f"Asset ID changed within series: {asset_ids}")
    frame = pd.concat(frames, ignore_index=True).sort_values("open_time_utc").reset_index(drop=True)
    if frame["open_time_utc"].duplicated().any():
        raise ValueError("Duplicate reference candle timestamp")
    expected = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq="5min", inclusive="left")
    actual = pd.DatetimeIndex(frame["open_time_utc"])
    unexpected = actual.difference(expected)
    if len(unexpected):
        raise ValueError(f"{len(unexpected)} off-grid reference candles")
    missing = expected.difference(actual)
    report = {
        "status": "passed",
        "coverage": "complete" if not len(missing) else "gapped",
        "row_count": len(frame), "expected_row_count": len(expected),
        "missing_count": len(missing),
        "missing_timestamps_sample": [value.isoformat() for value in missing[:20]],
        "duplicate_count": 0,
        "excluded_out_of_window_or_incomplete": dropped_incomplete,
        "first_open_utc": frame["open_time_utc"].min().isoformat(),
        "last_close_utc_exclusive": frame["close_time_utc"].max().isoformat(),
        "asset_id": next(iter(asset_ids)),
        "unknown_fields": ["venue", "quote_currency", "volume_base", "volume_quote", "trade_count"],
    }
    return frame, report


def save_reference(frame: pd.DataFrame, path: Path) -> None:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    for column in ("open", "high", "low", "close", "volume_base", "volume_quote"):
        table = table.set_column(table.schema.get_field_index(column), column, table[column].cast(pa.decimal128(38, 18)))
    for column in ("venue", "quote_currency"):
        table = table.set_column(table.schema.get_field_index(column), column, table[column].cast(pa.string()))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)


def normalize_funding(payload: dict, record: dict) -> tuple[pd.DataFrame, dict]:
    """Snapshot buckets are observations, not promised funding settlements."""
    if not payload.get("asset_id") or payload.get("symbol") != record["symbol"] or payload.get("resolution") != "1h":
        raise ValueError("Unexpected funding identity/resolution")
    frame = pd.DataFrame(payload["points"])
    if frame.empty:
        raise ValueError("Empty funding response")
    frame["observed_at_utc"] = pd.to_datetime(frame.pop("t"), utc=True)
    if frame["observed_at_utc"].duplicated().any() or not frame["observed_at_utc"].is_monotonic_increasing:
        raise ValueError("Duplicate or unsorted funding snapshot")
    for column in ("funding_rate", "open_interest"):
        frame[column] = frame[column].map(Decimal)
        if not frame[column].map(lambda value: value.is_finite()).all():
            raise ValueError(f"Nonfinite {column}")
    if not frame["open_interest"].ge(0).all():
        raise ValueError("Negative open interest")
    retrieved = pd.Timestamp(record["retrieved_at_utc"])
    if not frame["observed_at_utc"].le(retrieved).all():
        raise ValueError("Funding timestamp is in the future")
    frame["provider"] = "truemarkets"
    frame["venue"] = None
    frame["instrument_id"] = payload["asset_id"]
    frame["instrument_type"] = "perp"
    frame["base_currency"] = record["symbol"]
    frame["funding_rate_unit"] = "hourly_decimal_fraction"
    frame["open_interest_unit"] = "base_asset_coin_count"
    frame["ingested_at_utc"] = retrieved
    frame["source_url"] = record["url"]
    frame["source_sha256"] = record["sha256"]
    expected = pd.date_range(frame["observed_at_utc"].min(), frame["observed_at_utc"].max(), freq="1h")
    missing = expected.difference(pd.DatetimeIndex(frame["observed_at_utc"]))
    off_grid = pd.DatetimeIndex(frame["observed_at_utc"]).difference(expected)
    if len(off_grid):
        raise ValueError("Off-grid funding snapshot")
    return frame, {
        "status": "passed", "row_count": len(frame), "missing_count_between_endpoints": len(missing),
        "missing_timestamps_sample": [value.isoformat() for value in missing[:20]],
        "first_observed_utc": frame["observed_at_utc"].min().isoformat(),
        "last_observed_utc": frame["observed_at_utc"].max().isoformat(),
        "note": "Missing snapshots remain absent. These are sampled reference metrics, not fee receipts or account eligibility.",
    }
