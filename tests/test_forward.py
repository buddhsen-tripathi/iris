import copy
import json
import math
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

from alphacouncil.forward.feed import PublicFeed, canonical_klines, merge_observations, observed_quote
from alphacouncil.forward.ledger import connect, execute_entries, exit_due, publish, settle, summary

ANCHOR = pd.Timestamp("2026-10-24T15:00:00Z")
START = ANCHOR - pd.Timedelta(minutes=1)
PUBLISHED = ANCHOR + pd.Timedelta(seconds=2)


@pytest.fixture
def ledger(tmp_path):
    config = json.loads(Path("configs/forward_paper.json").read_text())
    db = connect(tmp_path / "ledger.sqlite3")
    db.executemany("INSERT INTO accounts VALUES (?,?)", [(name, 50.) for name in config["policies"]])
    db.commit()
    yield db, config
    db.close()


def forecasts(mu=0.01):
    return {str(h): {"experts": {"test": mu}, "committee_mu": mu, "dispersion": 0.} for h in (5, 15, 30)}


def save(db, mu=0.01):
    return publish(db, ANCHOR, PUBLISHED, START, forecasts(mu), {"x": 1.}, 100., 30)


def quote(at=PUBLISHED + pd.Timedelta(seconds=1), bid=100., ask=100.01):
    return {"bid": bid, "ask": ask, "bid_size": 1., "ask_size": 1.,
            "request_started_utc": at.isoformat(), "observed_at_utc": (at + pd.Timedelta(milliseconds=100)).isoformat()}


RULES = {"min_qty": .00001, "max_qty": 1000., "step": "0.00001", "market_step": "0", "min_notional": 5., "max_notional": 1000000.}


def test_no_backfilled_or_late_forecasts_and_atomic_bundle(ledger):
    db, _ = ledger
    for now, started in ((PUBLISHED, ANCHOR), (ANCHOR + pd.Timedelta(seconds=31), START), (ANCHOR - pd.Timedelta(seconds=1), START)):
        with pytest.raises(ValueError, match="backfill"):
            publish(db, ANCHOR, now, started, forecasts(), {}, 100, 30)
    bad = forecasts()
    bad["15"]["committee_mu"] = float("nan")
    with pytest.raises(ValueError):
        publish(db, ANCHOR, PUBLISHED, START, bad, {}, 100, 30)
    assert summary(db)["counts"]["forecasts"] == 0


def test_realized_prices_cannot_score_early_or_without_committed_forecasts(ledger):
    db, _ = ledger
    save(db)
    prices = {ANCHOR + pd.Timedelta(minutes=h): 101. for h in (5, 15, 30)}
    settle(db, prices, ANCHOR + pd.Timedelta(minutes=4))
    assert summary(db)["counts"]["outcomes"] == 0
    settle(db, prices, ANCHOR + pd.Timedelta(minutes=5))
    settle(db, prices, ANCHOR + pd.Timedelta(minutes=5))
    result = summary(db)
    assert result["counts"]["outcomes"] == 1
    assert result["counts"]["pending_outcomes"] == 2
    row = db.execute("SELECT * FROM outcomes").fetchone()
    assert row["actual_log_return"] == pytest.approx(math.log(1.01))
    assert all(item["horizon_minutes"] == 5 for item in result["forecast_metrics"])


def test_entries_require_post_publication_quote_and_saved_forecast(ledger):
    db, config = ledger
    with pytest.raises(ValueError, match="committed"):
        execute_entries(db, 999, quote(), RULES, config)
    forecast_id = save(db)
    with pytest.raises(ValueError, match="after forecast"):
        execute_entries(db, forecast_id, quote(ANCHOR), RULES, config)
    with pytest.raises(ValueError, match="expired"):
        execute_entries(db, forecast_id, quote(ANCHOR + pd.Timedelta(minutes=5)), RULES, config)
    assert summary(db)["counts"]["positions"] == 0


def test_actual_entry_quote_two_sided_costs_size_and_delayed_exit(ledger):
    db, config = ledger
    forecast_id = save(db)
    execute_entries(db, forecast_id, quote(), RULES, config)
    rows = db.execute("SELECT * FROM positions").fetchall()
    assert len(rows) == 2  # Independent policy portfolios.
    for row in rows:
        assert row["entry_price"] == pytest.approx(100.01 * 1.0002)
        assert row["entry_cost"] <= 10
        assert row["entry_cost"] == pytest.approx(row["quantity"] * row["entry_price"] * 1.001)
        assert (pd.Timestamp(row["due_utc"]) - pd.Timestamp(row["entry_utc"])).total_seconds() == 300
    due = pd.Timestamp(rows[0]["due_utc"])
    exit_due(db, quote(due - pd.Timedelta(seconds=1)), config)
    assert summary(db)["accounts"][0]["open_positions"] == 1
    # A missing quote does not invent a timely fill: first later observation wins.
    exit_due(db, quote(due + pd.Timedelta(seconds=30), bid=99., ask=99.01), config)
    closed = db.execute("SELECT * FROM positions").fetchall()
    for row in closed:
        assert row["exit_price"] == pytest.approx(99. * .9998)
        assert row["exit_proceeds"] == pytest.approx(row["quantity"] * 99. * .9998 * .999)
        assert pd.Timestamp(row["exit_utc"]) > due
        assert row["net_pnl"] < 0
    assert summary(db)["accounts"][0]["cash"] == pytest.approx(50 + closed[0]["net_pnl"])


def test_quote_move_and_costs_can_veto_positive_forecast(ledger):
    db, config = ledger
    forecast_id = save(db, .001)
    execute_entries(db, forecast_id, quote(bid=101, ask=101.01), RULES, config)
    assert summary(db)["counts"]["positions"] == 0
    assert {row[0] for row in db.execute("SELECT reason FROM decisions")} == {"edge_below_costs_and_buffer"}


def test_missing_rules_cannot_open_positions(ledger):
    db, config = ledger
    forecast_id = save(db)
    execute_entries(db, forecast_id, quote(), None, config)
    assert summary(db)["counts"]["positions"] == 0
    assert {row[0] for row in db.execute("SELECT reason FROM decisions")} == {"venue_rules_unavailable"}


def test_confirmation_and_duplicate_decisions_do_not_double_spend(ledger):
    db, config = ledger
    bundle = forecasts()
    bundle["15"]["committee_mu"] = -.01
    forecast_id = publish(db, ANCHOR, PUBLISHED, START, bundle, {}, 100., 30)
    execute_entries(db, forecast_id, quote(), RULES, config)
    assert summary(db)["counts"]["positions"] == 1
    before = summary(db)["accounts"]
    with pytest.raises(Exception):
        execute_entries(db, forecast_id, quote(), RULES, config)
    assert summary(db)["accounts"] == before


def receipt():
    return {"observed_at_utc": PUBLISHED.isoformat(), "request_started_utc": ANCHOR.isoformat(),
            "rtt_seconds": 2., "headers": {}, "url": "https://example.test", "sha256": "test"}


def test_rest_candles_exclude_incomplete_bars_and_reject_revisions():
    opened = int(ANCHOR.timestamp() * 1000)
    row = [opened, "100", "102", "99", "101", "2", opened + 299999, "202", 12, "1", "101", "0"]
    assert canonical_klines([row], "BTCUSDT", "5m", opened + 299999, receipt()).empty
    complete = canonical_klines([row], "BTCUSDT", "5m", opened + 300000, receipt())
    assert complete["close_time_utc"].iloc[0] == ANCHOR + pd.Timedelta(minutes=5)
    assert len(merge_observations(complete, complete)) == 1
    changed = complete.copy()
    changed["close"] = 999
    with pytest.raises(ValueError, match="revised"):
        merge_observations(complete, changed)


@pytest.mark.parametrize("field,value", [("bidPrice", "nan"), ("askQty", "inf"), ("askPrice", "99")])
def test_bad_quotes_rejected(field, value):
    payload = {"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "101", "bidQty": "2", "askQty": "2"}
    payload[field] = value
    with pytest.raises(ValueError):
        observed_quote(payload, receipt(), 3)


def test_cached_or_slow_quote_and_order_endpoint_rejected(tmp_path):
    payload = {"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "101", "bidQty": "2", "askQty": "2"}
    for r in ({**receipt(), "rtt_seconds": 4}, {**receipt(), "headers": {"Age": "4"}}):
        with pytest.raises(ValueError):
            observed_quote(payload, r, 3)
    db = connect(tmp_path / "ledger.sqlite3")
    feed = PublicFeed(tmp_path, db)
    with pytest.raises(ValueError, match="whitelisted"):
        feed.get("order", symbol="BTCUSDT")
    assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    db.close()
