import sqlite3

import pytest

from alphacouncil.integrations.events import parse_feed, store_events, visible_events
from alphacouncil.integrations.public import capture

BODY = b'''<rss><channel><item><title>FOMC announces policy decision</title>
<link>https://www.federalreserve.gov/newsevents/test.htm</link>
<pubDate>Sat, 24 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'''


def test_headline_is_not_visible_before_first_observed_and_first_seen_is_immutable():
    db = sqlite3.connect(":memory:")
    first = "2026-10-24T12:11:00+00:00"
    events = parse_feed(BODY, first, "sourcehash")
    store_events(db, events)
    assert visible_events(db, "2026-10-24T12:05:00Z") == []
    visible = visible_events(db, first)
    assert len(visible) == 1
    assert visible[0]["use_for_forecasting"] is False
    assert visible[0]["polarity"] == "uncertain"
    store_events(db, parse_feed(BODY, "2026-10-24T12:20:00Z", "laterhash"))
    assert len(visible_events(db, "2026-10-24T12:20:00Z")) == 1
    assert visible_events(db, "2026-10-24T12:20:00Z")[0]["first_observed_at_utc"] == first
    assert visible_events(db, "2026-11-03T00:00:00Z") == []


def test_feed_rejects_future_articles_off_publisher_links_and_xml_entities():
    assert parse_feed(BODY, "2026-10-24T11:59:00Z", "hash") == []
    assert parse_feed(BODY.replace(b"www.federalreserve.gov", b"example.test"), "2026-10-24T12:11:00Z", "hash") == []
    with pytest.raises(ValueError, match="DTD/entity"):
        parse_feed(b'<!DOCTYPE a [<!ENTITY x "unsafe">]><rss/>', "2026-10-24T12:11:00Z", "hash")


def test_public_connector_only_allows_fixed_read_only_sources(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        capture("https://api.truemarkets.co/v1/gateway/orders", tmp_path, "orders")
    with pytest.raises(ValueError, match="Unsupported"):
        capture("http://localhost/private", tmp_path, "local")
    assert list(tmp_path.iterdir()) == []
