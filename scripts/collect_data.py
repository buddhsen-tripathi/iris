#!/usr/bin/env python3
"""Collect actual historical candles, pin sources, and publish only validated datasets."""

import argparse
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow
import numpy

from alphacouncil.data.archive import (
    download_archive, file_sha256, parse_archive, plan_archives, save_parquet, utc_now, write_json,
)
from alphacouncil.data.validate import validate_candles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", type=date.fromisoformat, default=utc_now().date(), help="Exclusive UTC end date")
    parser.add_argument("--days-5m", type=int, default=365)
    parser.add_argument("--days-1h", type=int, default=730)
    parser.add_argument("--symbols-5m", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--symbols-1h", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=6)
    args = parser.parse_args()
    if args.days_5m <= 0 or args.days_1h <= 0:
        parser.error("History lengths must be positive")
    run_id = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    root = args.data_dir
    raw_root = root / "raw"
    jobs = [
        (symbol, interval, args.end - timedelta(days=days), args.end)
        for symbols, interval, days in [
            (args.symbols_5m, "5m", args.days_5m), (args.symbols_1h, "1h", args.days_1h),
        ]
        for symbol in dict.fromkeys(symbols)
    ]
    planned = [archive for symbol, interval, start, end in jobs for archive in plan_archives(symbol, interval, start, end)]
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at_utc": utc_now().isoformat(),
        "status": "collecting",
        "mode": "HISTORICAL_DATA_ONLY",
        "source": "Binance public spot archive",
        "source_docs": "https://github.com/binance/binance-public-data",
        "end_date_utc_exclusive": args.end.isoformat(),
        "close_time_convention": "exclusive interval boundary; original inclusive timestamp retained separately",
        "numeric_storage": "decimal128(38,18); no float rounding",
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__, "pyarrow": pyarrow.__version__, "numpy": numpy.__version__},
        "collection_code_sha256": {
            str(path): file_sha256(path)
            for path in [Path("scripts/collect_data.py"), Path("uv.lock"), *sorted(Path("src/alphacouncil/data").glob("*.py"))]
        },
        "archives": [],
        "datasets": [],
        "errors": [],
    }
    manifest_path = root / "manifests" / f"{run_id}.json"
    print(f"Collecting {len(planned)} archives for {len(jobs)} datasets; run {run_id}", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_archive, archive, raw_root): archive for archive in planned}
        for i, future in enumerate(as_completed(futures), 1):
            archive = futures[future]
            try:
                manifest["archives"].append(future.result())
            except Exception as error:
                manifest["errors"].append({"source_url": archive.url, "error": str(error)})
                print(f"ERROR {archive.url}: {error}", flush=True)
            if i % 20 == 0 or i == len(planned):
                print(f"Verified {i}/{len(planned)} archives ({len(manifest['errors'])} errors)", flush=True)
                write_json(manifest_path, manifest)
    manifest["archives"].sort(key=lambda item: item["url"])
    if not manifest["errors"]:
        for symbol, interval, start, end in jobs:
            try:
                records = [item for item in manifest["archives"] if item["symbol"] == symbol and item["interval"] == interval]
                frames = [parse_archive(item, raw_root, start, end) for item in records]
                # Sort archive chronology; preserve duplicates so validation can reject them.
                frame = pd.concat(frames, ignore_index=True).sort_values("open_time_utc").reset_index(drop=True)
                report = validate_candles(frame, symbol, interval, start, end)
                dataset = {
                    "symbol": symbol, "interval": interval, "start_date_utc": start.isoformat(),
                    "end_date_utc_exclusive": end.isoformat(), "validation": report,
                }
                manifest["datasets"].append(dataset)
                if report["status"] != "passed":
                    raise ValueError(f"{symbol} {interval}: {report['errors']}")
                relative_path = Path("clean") / run_id / "binance" / "spot" / f"{symbol}_{interval}.parquet"
                path = root / relative_path
                save_parquet(frame, path)
                dataset.update({"path": str(relative_path), "sha256": file_sha256(path), "bytes": path.stat().st_size})
                print(f"PASS {symbol} {interval}: {len(frame):,} candles, {start} to {end} exclusive", flush=True)
            except Exception as error:
                manifest["errors"].append({"dataset": f"{symbol}_{interval}", "error": str(error)})
                print(f"ERROR {symbol} {interval}: {error}", flush=True)
    manifest["status"] = "complete" if not manifest["errors"] else "failed"
    manifest["finished_at_utc"] = utc_now().isoformat()
    write_json(manifest_path, manifest)
    if manifest["status"] == "complete":
        write_json(root / "manifests" / "latest.json", manifest)
    print(f"{manifest['status'].upper()}: {manifest_path}", flush=True)
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
