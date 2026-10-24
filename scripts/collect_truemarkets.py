#!/usr/bin/env python3
"""Collect public historical reference candles and optional funding snapshots."""

import argparse
import json
import platform
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from alphacouncil.data.archive import file_sha256, sha256, utc_now, write_json
from alphacouncil.data.true_reference import (
    HOST, candle_url, capture, normalize_candles, normalize_funding, save_reference,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", type=date.fromisoformat, default=utc_now().date())
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--symbols", nargs="+", choices=["BTC", "ETH", "SOL"], default=["BTC", "ETH", "SOL"])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    if args.days <= 0 or args.end > utc_now().date():
        parser.error("Use a positive history length ending no later than today's UTC date")
    start = args.end - timedelta(days=args.days)
    root = args.data_dir
    run_id = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    manifest = {
        "schema_version": 1, "run_id": run_id, "status": "collecting",
        "started_at_utc": utc_now().isoformat(), "source": "True Markets public reference API",
        "mode": "REFERENCE_DATA_ONLY", "start_date_utc": start.isoformat(),
        "end_date_utc_exclusive": args.end.isoformat(),
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__, "pyarrow": pa.__version__, "numpy": np.__version__},
        "source_docs": "https://docs.truemarkets.co/api/market-data/get-candles.md",
        "limitations": [
            "Source venue, quote currency and volumes are absent from candle responses and stay null.",
            "Reference OHLC is not an executable order quote; do not concatenate with Binance spot data.",
            "Candle as_of is a historical query boundary, not evidence of historical first availability.",
            "Funding snapshots are collected as of retrieval; missing buckets are not interpolated.",
        ],
        "collection_code_sha256": {
            str(path): file_sha256(path) for path in [
                Path("scripts/collect_truemarkets.py"), Path("src/alphacouncil/data/true_reference.py"),
                Path("src/alphacouncil/data/archive.py"), Path("uv.lock"),
            ]
        },
        "responses": [], "datasets": [], "errors": [], "optional_errors": [], "unavailable_days": [],
    }
    manifest_path = root / "manifests" / f"truemarkets_{run_id}.json"

    def get_day(symbol, day_end):
        path = Path("raw/truemarkets/candles/spot") / symbol / f"{day_end.isoformat()}_5m.json"
        url = candle_url(symbol, day_end)
        if not (root / path).exists():
            time.sleep(0.25)  # Bound load on dynamic API; cached reads need no throttle.
        try:
            metadata = capture(root / path, url)
        except urllib.error.HTTPError as error:
            body = error.read()
            path = Path("raw/truemarkets") / run_id / "errors" / f"{symbol}_{day_end}.json"
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(body)
            metadata = {"http_status": error.code, "url": url, "sha256": sha256(body),
                "retrieved_at_utc": utc_now().isoformat(), "error": str(error)}
        return {**metadata, "path": str(path), "symbol": symbol, "day_end_utc": day_end.isoformat(), "kind": "candles"}

    symbols = list(dict.fromkeys(args.symbols))
    print(f"Collecting {args.days} days of 5m reference candles for {symbols}", flush=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(get_day, symbol, start + timedelta(days=day + 1)): (symbol, day)
            for symbol in symbols for day in range(args.days)
        }
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                if result["http_status"] == 200:
                    manifest["responses"].append(result)
                elif result["http_status"] == 404:
                    manifest["unavailable_days"].append(result)
                else:
                    manifest["errors"].append(result)
            except Exception as error:
                symbol, day = futures[future]
                manifest["errors"].append({"symbol": symbol, "day_end_utc": (start + timedelta(days=day + 1)).isoformat(), "error": str(error)})
            if i % 60 == 0 or i == len(futures):
                print(f"Processed {i}/{len(futures)} requests ({len(manifest['errors'])} errors, {len(manifest['unavailable_days'])} unavailable days)", flush=True)
                write_json(manifest_path, manifest)
    for symbol in symbols:
        records = sorted(
            (item for item in manifest["responses"] if item["symbol"] == symbol), key=lambda item: item["day_end_utc"],
        )
        if not records:
            manifest["errors"].append({"symbol": symbol, "error": "No candle data available"})
            continue
        try:
            frame, report = normalize_candles(records, root, symbol, start, args.end)
            path = Path("clean") / run_id / "truemarkets_reference" / f"{symbol}_5m.parquet"
            save_reference(frame, root / path)
            manifest["datasets"].append({
                "symbol": symbol, "kind": "candles", "path": str(path),
                "sha256": file_sha256(root / path), "bytes": (root / path).stat().st_size,
                "validation": report,
            })
            print(f"PASS {symbol}: {len(frame):,} reference candles; {report['missing_count']} missing", flush=True)
        except Exception as error:
            manifest["errors"].append({"symbol": symbol, "error": str(error)})
    for symbol in symbols:
        try:
            path = Path("raw/truemarkets") / run_id / f"{symbol}_funding_30d_1h.json"
            url = HOST + "/v1/defi/market/market-data/perp/history?" + urlencode({
                "symbol": symbol, "window": "30d", "resolution": "1h",
            })
            record = {**capture(root / path, url), "path": str(path), "symbol": symbol, "kind": "funding"}
            manifest["responses"].append(record)
            payload = json.loads((root / path).read_text())
            frame, report = normalize_funding(payload, record)
            clean = Path("clean") / run_id / "truemarkets_reference" / f"{symbol}_funding_1h.parquet"
            # Funding has its own schema, separate from candle data.
            table = pa.Table.from_pandas(frame, preserve_index=False)
            for column in ("funding_rate", "open_interest"):
                table = table.set_column(table.schema.get_field_index(column), column, table[column].cast(pa.decimal128(38, 18)))
            (root / clean).parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, root / clean, compression="zstd")
            manifest["datasets"].append({"symbol": symbol, "kind": "funding", "path": str(clean),
                "sha256": file_sha256(root / clean), "bytes": (root / clean).stat().st_size, "validation": report})
            print(f"PASS {symbol}: {len(frame)} funding/open-interest observations", flush=True)
        except Exception as error:
            manifest["optional_errors"].append({"symbol": symbol, "kind": "funding", "error": str(error)})
    manifest["responses"].sort(key=lambda item: item["url"])
    manifest["unavailable_days"].sort(key=lambda item: item["url"])
    manifest["status"] = "complete" if not manifest["errors"] else "failed"
    manifest["candle_coverage"] = "gapped" if any(
        item["kind"] == "candles" and item["validation"]["coverage"] == "gapped"
        for item in manifest["datasets"]
    ) else "complete"
    manifest["finished_at_utc"] = utc_now().isoformat()
    write_json(manifest_path, manifest)
    if manifest["status"] == "complete":
        write_json(root / "manifests" / "truemarkets_latest.json", manifest)
    print(f"{manifest['status'].upper()}: {manifest_path}", flush=True)
    return 0 if not manifest["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
