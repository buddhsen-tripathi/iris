"""Primary-source event context with immutable first-observed timestamps."""

import html
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pandas as pd

from alphacouncil.data.archive import sha256


def parse_feed(body: bytes, observed_at: str, source_hash: str) -> list[dict]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("DTD/entity declarations are not supported")
    observed = pd.Timestamp(observed_at)
    if observed.tzinfo is None:
        raise ValueError("Observation time must have a timezone")
    root = ET.fromstring(body)
    events = []
    for item in root.findall("./channel/item"):
        headline = " ".join(re.sub(r"<[^>]*>", "", html.unescape(item.findtext("title", ""))).split())[:500]
        source_url = item.findtext("link", "").strip()
        parsed = urlparse(source_url)
        if not headline or parsed.scheme != "https" or parsed.hostname not in {"www.federalreserve.gov", "federalreserve.gov"}:
            continue
        published_raw = item.findtext("pubDate", "")
        try:
            published = pd.Timestamp(parsedate_to_datetime(published_raw))
            if published.tzinfo is None or published > observed:
                continue
            published = published.tz_convert("UTC").isoformat()
        except (TypeError, ValueError, OverflowError):
            published = None
        events.append({"event_id": sha256(source_url.encode()), "assets": ["BTC", "ETH", "SOL"],
                       "published_at_utc": published, "first_observed_at_utc": observed.tz_convert("UTC").isoformat(),
                       "source_url": source_url, "evidence_urls": [source_url], "headline": headline,
                       "category": "monetary_policy" if any(word in headline.lower() for word in ("fomc", "interest rate", "monetary policy")) else "central_bank_context",
                       "polarity": "uncertain", "novelty": "first_seen", "source_name": "Federal Reserve Board",
                       "source_type": "primary", "classification_method": "keyword_context_only",
                       "relevance": "macro_context_only", "use_for_forecasting": False, "source_sha256": source_hash})
    return events


def store_events(db: sqlite3.Connection, events: list[dict]):
    db.execute("CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, first_observed_at_utc TEXT, event_json TEXT)")
    with db:
        for event in events:
            db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?)", (event["event_id"], event["first_observed_at_utc"], json.dumps(event, allow_nan=False)))


def visible_events(db: sqlite3.Connection, as_of, maximum_age_days=7) -> list[dict]:
    """A published date never permits earlier-than-observed historical visibility."""
    now = pd.Timestamp(as_of)
    if now.tzinfo is None:
        raise ValueError("Visibility time must have a timezone")
    events = []
    for row in db.execute("SELECT event_json FROM events"):
        event = json.loads(row[0])
        first = pd.Timestamp(event["first_observed_at_utc"])
        published = pd.Timestamp(event["published_at_utc"]) if event["published_at_utc"] else None
        dated = published if published is not None else first
        if first > now or dated > now or dated < now-pd.Timedelta(days=maximum_age_days):
            continue
        event["novelty"] = "first_seen" if first == now else "previously_observed"
        events.append(event)
    return sorted(events, key=lambda event: event["published_at_utc"] or event["first_observed_at_utc"], reverse=True)
