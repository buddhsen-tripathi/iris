"""Only public GET market data, with request receipts and explicit observation times."""

import json
import math
import sqlite3
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from alphacouncil.data.archive import RAW_COLUMNS, sha256, utc_now

ALLOWED = {"time", "klines", "ticker/bookTicker", "exchangeInfo"}


class PublicFeed:
    def __init__(self, session: Path, db: sqlite3.Connection):
        self.session, self.db = session, db
        self.sequence = 0
        (session / "raw").mkdir(exist_ok=True)

    def get(self, endpoint: str, **parameters) -> tuple[object, dict]:
        if endpoint not in ALLOWED:
            raise ValueError("Only whitelisted public market GET endpoints are supported")
        url = "https://data-api.binance.vision/api/v3/" + endpoint
        if parameters:
            url += "?" + urlencode(parameters)
        for attempt in range(3):
            started = utc_now()
            error_text = None
            headers = {}
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "AlphaCouncilForwardPaper/0.1", "Cache-Control": "no-cache"})
                with urllib.request.urlopen(request, timeout=8) as response:
                    body, status = response.read(), response.status
                    headers = {key: response.headers.get(key) for key in ("Date", "Age", "X-MBX-USED-WEIGHT-1M")}
            except urllib.error.HTTPError as error:
                body, status, error_text = error.read(), error.code, str(error)
                headers = {"Retry-After": error.headers.get("Retry-After")}
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                body, status, error_text = str(error).encode(), None, str(error)
            finished = utc_now()
            self.sequence += 1
            relative = Path("raw") / f"{finished.strftime('%Y%m%dT%H%M%S%fZ')}_{self.sequence:06d}.json"
            (self.session / relative).write_bytes(body)
            receipt = {"url": url, "request_started_utc": started.isoformat(), "observed_at_utc": finished.isoformat(),
                "rtt_seconds": (finished - started).total_seconds(), "http_status": status,
                "sha256": sha256(body), "path": str(relative), "headers": headers, "error": error_text}
            self.db.execute("INSERT INTO requests(observed_at_utc, receipt_json) VALUES (?,?)", (receipt["observed_at_utc"], json.dumps(receipt)))
            self.db.commit()
            if status == 200:
                return json.loads(body), receipt
            if status not in {None, 429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"Public market GET failed ({status}): {error_text}; receipt {relative}")
            retry_after = headers.get("Retry-After")
            time.sleep(min(float(retry_after), 15) if retry_after and retry_after.isdigit() else 2 ** attempt)
        raise RuntimeError("Market fetch exhausted retries")


def canonical_klines(rows: list, symbol: str, interval: str, server_ms: int, receipt: dict) -> pd.DataFrame:
    if interval not in {"5m", "1h"} or symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
        raise ValueError("Unsupported live candle identity")
    duration_ms = 300_000 if interval == "5m" else 3_600_000
    result = []
    for row in rows:
        if len(row) != 12 or int(row[0]) >= 100_000_000_000_000:
            raise ValueError("Unexpected REST kline schema/time units")
        opened, last_tick = int(row[0]), int(row[6])
        if last_tick + 1 != opened + duration_ms:
            raise ValueError("Unexpected REST candle duration")
        if opened + duration_ms > server_ms:
            continue
        values = dict(zip(RAW_COLUMNS, row))
        result.append({
            "venue": "binance", "instrument_id": symbol, "instrument_type": "spot",
            "base_currency": symbol.removesuffix("USDT"), "quote_currency": "USDT", "interval": interval,
            "open_time_utc": pd.to_datetime(opened, unit="ms", utc=True),
            "close_time_utc": pd.to_datetime(opened + duration_ms, unit="ms", utc=True),
            "source_close_time_utc": pd.to_datetime(last_tick, unit="ms", utc=True),
            **{name: Decimal(str(values[name])) for name in ("open", "high", "low", "close", "volume_base", "volume_quote", "taker_buy_volume_base", "taker_buy_volume_quote")},
            "trade_count": int(values["trade_count"]), "ingested_at_utc": pd.Timestamp(receipt["observed_at_utc"]),
            "source_url": receipt["url"], "source_sha256": receipt["sha256"], "is_complete": True,
        })
    return pd.DataFrame(result)


def merge_observations(previous: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if incoming.empty:
        return previous
    key = "open_time_utc"
    old = previous.set_index(key)
    new = incoming.set_index(key)
    if new.index.has_duplicates:
        raise ValueError("Duplicate incoming candle")
    overlap = old.index.intersection(new.index)
    for column in ("open", "high", "low", "close", "volume_base", "volume_quote", "trade_count", "taker_buy_volume_base", "taker_buy_volume_quote"):
        if not old.loc[overlap, column].eq(new.loc[overlap, column]).all():
            raise ValueError(f"Provider revised a completed candle ({column}); refusing a silent replacement")
    # Preserve the first observation and its source hash for existing candles.
    appended = new.loc[~new.index.isin(old.index)].reset_index()
    return pd.concat([previous, appended], ignore_index=True).sort_values(key).reset_index(drop=True)


def observed_quote(payload: dict, receipt: dict, maximum_rtt: float) -> dict:
    if payload.get("symbol") != "BTCUSDT" or receipt["rtt_seconds"] > maximum_rtt:
        raise ValueError("Wrong instrument or slow quote response")
    age = receipt["headers"].get("Age")
    if age and float(age) > maximum_rtt:
        raise ValueError("Cached quote is too old")
    bid, ask = float(payload["bidPrice"]), float(payload["askPrice"])
    bid_size, ask_size = float(payload["bidQty"]), float(payload["askQty"])
    if not all(math.isfinite(value) for value in (bid, ask, bid_size, ask_size)) or not 0 < bid <= ask or min(bid_size, ask_size) <= 0:
        raise ValueError("Invalid/crossed or empty book quote")
    return {"bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size,
            "observed_at_utc": receipt["observed_at_utc"], "request_started_utc": receipt["request_started_utc"],
            "receipt_sha256": receipt["sha256"], "exchange_event_time_available": False}
