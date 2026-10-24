#!/usr/bin/env python3
"""Read a local forward-test snapshot and check process/heartbeat liveness."""

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from alphacouncil.data.archive import utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forced", action="store_true", help="Inspect the separate forced 20-second paper experiment")
    args = parser.parse_args()
    path = Path("data/manifests/forced_latest.json" if args.forced else "data/manifests/forward_latest.json")
    status = json.loads(path.read_text())
    try:
        os.kill(status["pid"], 0)
        alive = True
    except ProcessLookupError:
        alive = False
    age = (pd.Timestamp(utc_now()) - pd.Timestamp(status["heartbeat_utc"])).total_seconds()
    status["process_alive"] = alive
    status["heartbeat_age_seconds"] = age
    status["live_status_verified"] = alive and age < 120 and status["status"] in {"running", "draining", "starting"}
    print(json.dumps(status, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
