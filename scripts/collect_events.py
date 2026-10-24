#!/usr/bin/env python3
"""Capture primary-source macro context without mapping sentiment to returns."""

import json
import sqlite3
from pathlib import Path

from alphacouncil.data.archive import utc_now, write_json
from alphacouncil.integrations.events import parse_feed, store_events, visible_events
from alphacouncil.integrations.public import capture


def main():
    directory = Path("data/events") / utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    body, receipt = capture("https://www.federalreserve.gov/feeds/press_all.xml", directory, "fed_press")
    db = sqlite3.connect("data/events/events.sqlite3")
    error = receipt.get("error")
    try:
        events = parse_feed(body, receipt["observed_at_utc"], receipt["sha256"]) if body else []
        store_events(db, events)
    except Exception as exc:
        error = str(exc)
        store_events(db, [])
    now = utc_now().isoformat()
    manifest = {"schema_version": 1, "created_at_utc": now, "status": "complete" if body and not error else "partial",
                "mode": "SOURCE_BACKED_CONTEXT_ONLY", "events": visible_events(db, now),
                "feeds": [{**receipt, "status": "available" if body and not error else "unavailable", "error": error}],
                "llm_connectors": {"grok": "not_connected", "jev": "not_connected"},
                "use_for_forecasting": False, "update_mode": "manual_collection_snapshot", "maximum_event_age_days": 7}
    db.close()
    write_json(directory / "manifest.json", manifest)
    write_json(Path("data/manifests/events_latest.json"), manifest)
    print(json.dumps({"status": manifest["status"], "visible_events": len(manifest["events"]), "error": error}))


if __name__ == "__main__":
    main()
