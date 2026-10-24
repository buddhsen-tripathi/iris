"""Download and normalize official Binance spot archives without API credentials."""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

BASE_URL = "https://data.binance.vision"
INTERVALS = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1)}
DECIMAL_COLUMNS = (
    "open", "high", "low", "close", "volume_base", "volume_quote",
    "taker_buy_volume_base", "taker_buy_volume_quote",
)
RAW_COLUMNS = (
    "open_time", "open", "high", "low", "close", "volume_base",
    "close_time", "volume_quote", "trade_count", "taker_buy_volume_base",
    "taker_buy_volume_quote", "ignore",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def fetch(url: str) -> tuple[bytes, dict]:
    """Bounded retries for transport/429/5xx errors; fail on permanent HTTP errors."""
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "AlphaCouncilData/0.1"})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                return body, {
                    "url": url,
                    "retrieved_at_utc": utc_now().isoformat(),
                    "http_status": response.status,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "bytes": len(body),
                    "sha256": sha256(body),
                }
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            retry_after = error.headers.get("Retry-After", "")
            delay = min(float(retry_after), 15) if retry_after.isdigit() else 2 ** attempt
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
            delay = 2 ** attempt
        time.sleep(delay)
    raise RuntimeError("Download exhausted retries")


@dataclass(frozen=True)
class Archive:
    symbol: str
    interval: str
    frequency: str
    period: str

    @property
    def relative_path(self) -> Path:
        return Path("spot") / self.frequency / "klines" / self.symbol / self.interval / (
            f"{self.symbol}-{self.interval}-{self.period}.zip"
        )

    @property
    def url(self) -> str:
        return f"{BASE_URL}/data/{self.relative_path.as_posix()}"


def plan_archives(symbol: str, interval: str, start: date, end: date) -> list[Archive]:
    """Cover [start, end); overfetch boundary months, then filter exact rows later."""
    if not re.fullmatch(r"[A-Z0-9]+USDT", symbol):
        raise ValueError(f"Expected an explicit USDT spot pair, got {symbol!r}")
    if interval not in INTERVALS or start >= end:
        raise ValueError("Unsupported interval or empty date range")
    if end > utc_now().date():
        raise ValueError("End date must exclude today and future days")
    current = start.replace(day=1)
    archives = []
    while current < end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        # Monthly files are published after month end; allow a full week for publication.
        if next_month <= end and next_month <= utc_now().date() - timedelta(days=7):
            archives.append(Archive(symbol, interval, "monthly", current.strftime("%Y-%m")))
        else:
            day = max(start, current)
            while day < min(end, next_month):
                archives.append(Archive(symbol, interval, "daily", day.isoformat()))
                day += timedelta(days=1)
        current = next_month
    return archives


def download_archive(archive: Archive, raw_root: Path) -> dict:
    """Keep immutable source bytes and original retrieval metadata; recheck cached hashes."""
    path = raw_root / "binance" / archive.relative_path
    checksum_path = path.with_name(path.name + ".CHECKSUM")
    metadata_path = path.with_name(path.name + ".metadata.json")
    if path.exists() and checksum_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        if metadata["url"] != archive.url:
            raise ValueError(f"Cached source URL mismatch: {path}")
    else:
        checksum, checksum_metadata = fetch(archive.url + ".CHECKSUM")
        body, metadata = fetch(archive.url)
        expected = checksum.decode("ascii").split()
        if len(expected) != 2 or expected[1].lstrip("*") != path.name:
            raise ValueError(f"Unexpected checksum format: {archive.url}")
        if sha256(body) != expected[0].lower():
            raise ValueError(f"Provider SHA-256 mismatch: {archive.url}")
        with zipfile.ZipFile(io.BytesIO(body)) as zipped:
            bad_member = zipped.testzip()
            if bad_member:
                raise ValueError(f"ZIP CRC mismatch: {bad_member}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        temporary.write_bytes(body)
        temporary.replace(path)
        checksum_path.write_bytes(checksum)
        metadata["checksum_response"] = checksum_metadata
        write_json(metadata_path, metadata)

    expected = checksum_path.read_text().split()
    actual = file_sha256(path)
    if (len(expected) != 2 or expected[1].lstrip("*") != path.name
            or actual != expected[0].lower() or actual != metadata["sha256"]):
        raise ValueError(f"Cached archive failed integrity verification: {path}")
    return {
        **metadata,
        "symbol": archive.symbol,
        "interval": archive.interval,
        "frequency": archive.frequency,
        "period": archive.period,
        "relative_raw_path": str(Path("binance") / archive.relative_path),
        "provider_checksum_verified": True,
    }


def source_timestamps(values: pd.Series) -> pd.Series:
    """Spot files use milliseconds before 2025, microseconds from 2025 onward."""
    numbers = pd.to_numeric(values, errors="raise").astype("int64")
    microseconds = numbers.where(numbers >= 100_000_000_000_000, numbers * 1000)
    return pd.to_datetime(microseconds, unit="us", utc=True)


def parse_archive(record: dict, raw_root: Path, start: date, end: date) -> pd.DataFrame:
    path = raw_root / record["relative_raw_path"]
    with zipfile.ZipFile(path) as zipped:
        members = zipped.namelist()
        if members != [path.stem + ".csv"]:
            raise ValueError(f"Unexpected ZIP contents: {path}: {members}")
        with zipped.open(members[0]) as handle:
            raw = pd.read_csv(handle, header=None, dtype=str, keep_default_na=False)
    if len(raw.columns) != len(RAW_COLUMNS) or raw.empty:
        raise ValueError(f"Unexpected or empty kline schema: {path}")
    raw.columns = RAW_COLUMNS
    opened = source_timestamps(raw["open_time"])
    source_closed = source_timestamps(raw["close_time"])
    closed = opened + INTERVALS[record["interval"]]
    original = pd.to_numeric(raw["close_time"])
    precision = pd.to_timedelta(original.ge(100_000_000_000_000).map({True: 1, False: 1000}), unit="us")
    if not (source_closed + precision).eq(closed).all():
        raise ValueError(f"Source close time inconsistent with interval: {path}")
    mask = opened.ge(pd.Timestamp(start, tz="UTC")) & closed.le(pd.Timestamp(end, tz="UTC"))
    raw = raw.loc[mask].copy()
    frame = pd.DataFrame(index=raw.index)
    frame["venue"] = "binance"
    frame["instrument_id"] = record["symbol"]
    frame["instrument_type"] = "spot"
    frame["base_currency"] = record["symbol"].removesuffix("USDT")
    frame["quote_currency"] = "USDT"
    frame["interval"] = record["interval"]
    frame["open_time_utc"] = opened.loc[mask]
    # Exclusive bar-end time: a bar is complete at exactly this timestamp.
    frame["close_time_utc"] = closed.loc[mask]
    frame["source_close_time_utc"] = source_closed.loc[mask]
    for column in DECIMAL_COLUMNS:
        frame[column] = raw[column].map(Decimal)
    frame["trade_count"] = pd.to_numeric(raw["trade_count"], errors="raise").astype("int64")
    frame["ingested_at_utc"] = pd.Timestamp(record["retrieved_at_utc"])
    frame["source_url"] = record["url"]
    frame["source_sha256"] = record["sha256"]
    frame["is_complete"] = frame["close_time_utc"].le(utc_now())
    return frame.reset_index(drop=True)


def save_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Preserve source numeric precision rather than coercing prices to float."""
    table = pa.Table.from_pandas(frame, preserve_index=False)
    for column in DECIMAL_COLUMNS:
        index = table.schema.get_field_index(column)
        table = table.set_column(index, column, table[column].cast(pa.decimal128(38, 18)))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)
