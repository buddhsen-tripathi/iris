#!/usr/bin/env python3
"""Prospective adaptive shadow: read the existing paper ledger, never place orders."""

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

import pandas as pd

from alphacouncil.committee import CommitteeLedger
from alphacouncil.data.archive import file_sha256, utc_now, write_json
from alphacouncil.models.experts import forecast_metrics


def open_read_only(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def poll(source, ledger, started, now, config):
    """Publish only post-start source forecasts; ingest outcomes on actual read time."""
    now, started = pd.Timestamp(now), pd.Timestamp(started)
    # New forecasts precede this poll's outcomes: conservative if receipts coincide.
    for row in source.execute("SELECT * FROM forecasts ORDER BY id").fetchall():
        anchor = pd.Timestamp(row["anchor_utc"])
        published = pd.Timestamp(row["published_at_utc"])
        maturity = pd.Timestamp(row["maturity_utc"])
        if anchor <= started or published < started or published > now or now >= maturity:
            continue
        if (now-anchor).total_seconds() > config["maximum_shadow_publication_delay_seconds"]:
            continue
        ledger.publish(row["id"], row["horizon"], row["anchor_utc"], published, now, maturity,
                       json.loads(row["predictions_json"])["experts"], "LIVE_SHADOW")
    for row in source.execute("SELECT * FROM outcomes ORDER BY observed_at_utc,forecast_id").fetchall():
        ledger.observe(row["forecast_id"], row["actual_log_return"], row["observed_at_utc"], now)
    ledger.db.commit()


def current_metrics(ledger):
    rows = ledger.db.execute("SELECT f.horizon,f.adaptive_mu,f.equal_mu,u.actual_log_return FROM forecasts f JOIN updates u USING(source_forecast_id)").fetchall()
    frame = pd.DataFrame([dict(row) for row in rows])
    metrics = []
    if not frame.empty:
        for horizon, group in frame.groupby("horizon"):
            for name, column in (("adaptive", "adaptive_mu"), ("equal_weight", "equal_mu")):
                metrics.append({"horizon_minutes": int(horizon), "model": name,
                    **forecast_metrics(group["actual_log_return"], group[column])})
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=Path("data/manifests/forward_latest.json"))
    parser.add_argument("--minutes", type=float, default=60)
    parser.add_argument("--once", action="store_true", help="One prospective poll, useful for checking connectivity")
    args = parser.parse_args()
    if not 0 < args.minutes <= 1440:
        raise ValueError("Bounded duration must be between zero and 1440 minutes")
    config = json.loads(Path("configs/committee.json").read_text())
    original = json.loads(args.source_manifest.read_text())
    source_path = Path(original["session_directory"])/"ledger.sqlite3"
    # Existing sessions call this ledger.sqlite3; fail clearly rather than opening a new source.
    source = open_read_only(source_path)
    started = pd.Timestamp(utc_now())
    directory = Path("data/forward")/f"committee_shadow_{started.strftime('%Y%m%dT%H%M%S%fZ')}"
    directory.mkdir(parents=True)
    db = sqlite3.connect(directory/"committee.sqlite")
    db.execute("PRAGMA journal_mode=WAL")
    ledger = CommitteeLedger(db, config)
    deadline = min(started+pd.Timedelta(minutes=args.minutes), pd.Timestamp(original["hard_stop_utc"]))
    status = {"schema_version": 1, "mode": "LIVE_SHADOW_ADAPTIVE_ONLY", "status": "running", "pid": os.getpid(),
        "started_at_utc": started.isoformat(), "hard_stop_utc": deadline.isoformat(),
        "source_session_directory": original["session_directory"], "shadow_session_directory": str(directory),
        "source_manifest_sha256_at_start": file_sha256(args.source_manifest), "config": config,
        "code_sha256": {str(path): file_sha256(path) for path in (Path(__file__), Path("src/alphacouncil/committee/online.py"))},
        "live_trading_enabled": False, "note": "Shadow forecasts only; existing equal-weight and forced paper traders unchanged. Only anchors and source forecasts after shadow start are eligible; shadow publication over 30 seconds after the anchor is skipped. Requires Mac awake and online."}
    try:
        while True:
            now = pd.Timestamp(utc_now())
            if now >= deadline or (directory/"STOP").exists():
                status["status"] = "stopped"
                break
            poll(source, ledger, started, now, config)
            status.update(ledger.snapshot(), heartbeat_utc=utc_now().isoformat(), forecast_metrics=current_metrics(ledger))
            write_json(directory/"status.json", status)
            write_json(Path("data/manifests/committee_latest.json"), status)
            if args.once:
                status["status"] = "completed_single_poll"
                break
            time.sleep(config["shadow_poll_seconds"])
    except Exception as error:
        status.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        status.update(ledger.snapshot(), heartbeat_utc=utc_now().isoformat(), forecast_metrics=current_metrics(ledger))
        write_json(directory/"status.json", status)
        write_json(Path("data/manifests/committee_latest.json"), status)
        db.close()
        source.close()
    print(json.dumps(status, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
