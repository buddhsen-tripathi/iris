#!/usr/bin/env python3
"""Build a readable inventory directly from the current collection manifests."""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    root = args.data_dir
    primary = json.loads((root / "manifests/latest.json").read_text())
    lines = [
        "# Collected market data", "",
        "Generated from saved collection manifests. Source data have been downloaded, normalized, and checked. Subsequent model training is documented separately in the [training report](../reports/model_training_5_15_30.md).", "",
        "## Primary dataset: Binance spot", "",
        f"Collection finished: {primary['finished_at_utc']}. End date: **{primary['end_date_utc_exclusive']} 00:00 UTC, exclusive**.", "",
        "| Instrument | Interval | UTC start | UTC end (exclusive) | Candles | Missing | Duplicates |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for dataset in primary["datasets"]:
        report = dataset["validation"]
        lines.append(f"| {dataset['symbol']} | {dataset['interval']} | {dataset['start_date_utc']} | {dataset['end_date_utc_exclusive']} | {report['row_count']:,} | {report['missing_count']:,} | {report['duplicate_count']:,} |")
    total = sum(item["validation"]["row_count"] for item in primary["datasets"])
    size = sum(item["bytes"] for item in primary["datasets"]) / 1024 ** 2
    lines.extend([
        "", f"**{total:,} candles**, {size:.2f} MiB of current Parquet files, from **{len(primary['archives'])} provider-checksummed archives**. All primary datasets passed complete-grid, UTC, duplicate, OHLC, volume, completion-time, and provenance checks.", "",
        f"[Pinned manifest](manifests/{primary['run_id']}.json) · [Current manifest](manifests/latest.json)", "",
        "These are Binance spot prices quoted in USDT. They are not True Markets execution prices.", "",
        "## True Markets reference data", "",
    ])
    path = root / "manifests/truemarkets_latest.json"
    reference = json.loads(path.read_text()) if path.exists() else None
    if reference:
        lines.extend([
            f"Requested candle coverage: **{reference['start_date_utc']} to {reference['end_date_utc_exclusive']} UTC, exclusive**. Collection finished: {reference['finished_at_utc']}.", "",
            "| Asset | Data | Rows | First observation (UTC) | Last observation / bar end (UTC) | Missing buckets |",
            "| --- | --- | ---: | --- | --- | ---: |",
        ])
        for dataset in reference["datasets"]:
            report = dataset["validation"]
            is_candle = dataset["kind"] == "candles"
            first = report["first_open_utc"] if is_candle else report["first_observed_utc"]
            last = report["last_close_utc_exclusive"] if is_candle else report["last_observed_utc"]
            missing = report["missing_count"] if is_candle else report["missing_count_between_endpoints"]
            label = "5m reference OHLC" if is_candle else "1h funding + open interest"
            lines.append(f"| {dataset['symbol']} | {label} | {report['row_count']:,} | {first} | {last} | {missing:,} |")
        lines.extend([
            "", f"**{len(reference.get('unavailable_days', []))} requested whole days were unavailable**. Candle missing counts cover the full requested 180-day grid, including missing early ETH history. Funding missing counts cover the range between each series' observed endpoints. No gaps were filled.", "",
            "Validation passing means the returned values passed structural checks; it does **not** mean coverage is complete. Use contiguous windows when adding features and labels later.", "",
            "The candle API omits volume, trade count, quote currency, and the underlying source venue. Those fields remain null. Asset UUIDs, decimal prices, source URLs, hashes, and retrieval timestamps are preserved. Reference prices are kept separate from exchange candles and are not executable quotes.", "",
            "Funding is an hourly decimal fraction; open interest is a base-asset coin count. Negative funding is allowed. These observations do not prove account access to perps or represent actual funding paid.", "",
            f"[Pinned reference manifest](manifests/truemarkets_{reference['run_id']}.json) · [Current reference manifest](manifests/truemarkets_latest.json)", "",
        ])
    else:
        lines.extend(["No successful reference collection is currently published.", ""])
    lines.extend(["## Current Parquet files", "", "Paths are relative to this directory. Raw and clean data are local and gitignored.", ""])
    for manifest in [primary] + ([reference] if reference else []):
        for dataset in manifest["datasets"]:
            lines.append(f"- [{Path(dataset['path']).name}]({dataset['path']}) — SHA-256 `{dataset['sha256']}`")
    lines.extend([
        "", "## Recheck and refresh", "",
        "Run from the repository root:", "", "```sh",
        "uv run python scripts/verify_data.py",
        "uv run pytest -q",
        "uv run python scripts/collect_data.py --end 2026-10-24",
        "uv run python scripts/collect_truemarkets.py --end 2026-10-24",
        "uv run python scripts/summarize_data.py", "```", "",
        "Omit `--end` to collect through the latest completed UTC day. Cached source responses preserve original retrieval timestamps and hashes. Rolling funding windows depend on the collection time.", "",
        "## Not collected", "",
        "Point-in-time news, executable bid/ask quotes, fee schedules, balances, or trading permissions. The collection commands do not generate features, prediction labels, checkpoints, backtests, or orders. Subsequent feature work is documented in the [feature-engineering draft](../reports/feature_engineering_draft.md).", "",
    ])
    output = root / "README.md"
    output.write_text("\n".join(lines))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
