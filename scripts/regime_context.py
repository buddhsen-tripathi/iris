#!/usr/bin/env python3
"""Read completed forward features without changing active committee weights."""

import argparse
import json
import sqlite3
from pathlib import Path

from alphacouncil.committee.regime import classify_regime
from alphacouncil.data.archive import utc_now, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=Path("data/manifests/forward_latest.json"))
    args = parser.parse_args()
    original = json.loads(args.source_manifest.read_text())
    source_path = Path(original["session_directory"])/"ledger.sqlite3"
    source = sqlite3.connect(source_path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA query_only=ON")
    row = source.execute("SELECT id,anchor_utc,published_at_utc,features_json FROM forecasts WHERE horizon=5 ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        raise ValueError("No completed prospective feature row is available")
    config = json.loads(Path("configs/regime.json").read_text())
    snapshot = classify_regime(json.loads(row["features_json"]), row["anchor_utc"], row["published_at_utc"], utc_now(), config)
    snapshot.update(source_session_directory=original["session_directory"], source_forecast_id=row["id"],
                    threshold_version=config["version"], source="Existing completed features in read-only live forward ledger")
    write_json(Path("data/manifests/regime_latest.json"), snapshot)
    source.close()
    print(json.dumps(snapshot, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
