#!/usr/bin/env python3
"""Offline: verify every pinned raw/clean hash and recheck candle quality."""

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from alphacouncil.data.archive import file_sha256
from alphacouncil.data.true_reference import normalize_candles, normalize_funding
from alphacouncil.data.validate import validate_candles


def verify_reference(manifest: dict, root: Path) -> None:
    for record in manifest.get("unavailable_days", []):
        if file_sha256(root / record["path"]) != record["sha256"]:
            raise ValueError(f"Missing-day receipt hash mismatch: {record['path']}")
    for record in manifest["responses"]:
        path = root / record["path"]
        if file_sha256(path) != record["sha256"]:
            raise ValueError(f"Reference response hash mismatch: {path}")
        receipt = json.loads(path.with_name(path.name + ".metadata.json").read_text())
        if receipt["sha256"] != record["sha256"] or receipt["url"] != record["url"] or receipt["retrieved_at_utc"] != record["retrieved_at_utc"]:
            raise ValueError(f"Reference receipt mismatch: {path}")
    for dataset in manifest["datasets"]:
        path = root / dataset["path"]
        if file_sha256(path) != dataset["sha256"]:
            raise ValueError(f"Reference dataset hash mismatch: {path}")
        records = [item for item in manifest["responses"] if item["symbol"] == dataset["symbol"] and item["kind"] == dataset["kind"]]
        if dataset["kind"] == "candles":
            frame, report = normalize_candles(
                records, root, dataset["symbol"], date.fromisoformat(manifest["start_date_utc"]),
                date.fromisoformat(manifest["end_date_utc_exclusive"]),
            )
        else:
            if len(records) != 1:
                raise ValueError("Expected exactly one funding response per asset")
            frame, report = normalize_funding(json.loads((root / records[0]["path"]).read_text()), records[0])
        if report != dataset["validation"]:
            raise ValueError(f"Reference validation differs from saved report: {path}")
        pd.testing.assert_frame_equal(frame, pd.read_parquet(path), check_dtype=False)
        print(f"PASS True Markets {dataset['symbol']} {dataset['kind']}: {len(frame):,} rows")
    print(f"Verified {len(manifest['responses'])} reference responses and {len(manifest['datasets'])} datasets, entirely offline.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    manifest_paths = [args.manifest] if args.manifest else [args.data_dir / "manifests/latest.json"]
    reference = args.data_dir / "manifests/truemarkets_latest.json"
    if not args.manifest and reference.exists():
        manifest_paths.append(reference)
    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text())
        if manifest["status"] != "complete":
            raise ValueError("Refusing an incomplete manifest")
        if manifest.get("mode") == "REFERENCE_DATA_ONLY":
            verify_reference(manifest, args.data_dir)
        else:
            verify_binance(manifest, args.data_dir)
    return 0


def verify_binance(manifest: dict, root: Path) -> None:
    if manifest["status"] != "complete":
        raise ValueError("Refusing an incomplete manifest")
    for record in manifest["archives"]:
        path = root / "raw" / record["relative_raw_path"]
        checksum_path = path.with_name(path.name + ".CHECKSUM")
        expected = checksum_path.read_text().split()
        if (len(expected) != 2 or expected[1].lstrip("*") != path.name
                or file_sha256(path) != record["sha256"] or expected[0].lower() != record["sha256"]):
            raise ValueError(f"Archive/checksum hash mismatch: {path}")
        if file_sha256(checksum_path) != record["checksum_response"]["sha256"]:
            raise ValueError(f"Checksum receipt hash mismatch: {checksum_path}")
    for dataset in manifest["datasets"]:
        path = root / dataset["path"]
        if file_sha256(path) != dataset["sha256"]:
            raise ValueError(f"Dataset hash mismatch: {path}")
        report = validate_candles(
            pd.read_parquet(path), dataset["symbol"], dataset["interval"],
            date.fromisoformat(dataset["start_date_utc"]), date.fromisoformat(dataset["end_date_utc_exclusive"]),
        )
        if report["status"] != "passed" or report != dataset["validation"]:
            raise ValueError(f"Validation failed or differs from saved report: {path}: {report}")
        print(f"PASS {dataset['symbol']} {dataset['interval']}: {report['row_count']:,} candles")
    print(f"Verified {len(manifest['archives'])} raw archives and {len(manifest['datasets'])} datasets, entirely offline.")


if __name__ == "__main__":
    raise SystemExit(main())
