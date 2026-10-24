import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

from alphacouncil.forward.interval import claim, force_tick, initialize, interval_summary, next_slot
from alphacouncil.forward.ledger import connect

TICK = pd.Timestamp("2026-10-24T15:00:00Z")
RULES = {"min_qty": .00001, "max_qty": 1000., "step": "0.00001", "market_step": "0", "min_notional": 5., "max_notional": 1000000.}


@pytest.fixture
def setup(tmp_path):
    config = json.loads(Path("configs/forced_20s_paper.json").read_text())
    db = connect(tmp_path / "ledger.sqlite3")
    initialize(db, config)
    yield db, config
    db.close()


def quote(scheduled, lag=1., bid_size=1.):
    return {"bid": 100., "ask": 100.01, "bid_size": bid_size, "ask_size": 1.,
            "request_started_utc": scheduled.isoformat(), "observed_at_utc": (scheduled + pd.Timedelta(seconds=lag)).isoformat()}


def tick(db, config, scheduled, **kwargs):
    assert claim(db, scheduled, scheduled)
    return force_tick(db, scheduled, quote(scheduled), RULES, config, **kwargs)


def test_forces_entry_without_forecast_or_edge_and_rotates_every_20_seconds(setup):
    db, config = setup
    for i in range(3):
        tick(db, config, TICK + pd.Timedelta(seconds=i * 20))
    status = interval_summary(db, config, quote(TICK + pd.Timedelta(seconds=40)))
    assert status["paper_entries"] == 3
    assert status["completed_trades"] == 2
    assert status["open_positions"] == 1
    assert status["mean_actual_holding_seconds"] == 20
    assert status["realized_pnl_usdt"] < 0
    assert status["assumed_fees_paid_usdt"] > 0
    assert status["assumed_slippage_cost_usdt"] > 0
    assert db.execute("SELECT count(*) FROM forecasts").fetchone()[0] == 0
    assert db.execute("SELECT max(entry_cost) FROM positions").fetchone()[0] <= 10
    for row in db.execute("SELECT * FROM positions"):
        assert row["entry_cost"] == pytest.approx(row["quantity"] * 100.01 * 1.0002 * 1.001)
        if row["exit_utc"]:
            assert row["exit_proceeds"] == pytest.approx(row["quantity"] * 100. * .9998 * .999)


def test_duplicate_tick_is_idempotent_and_cannot_double_spend(setup):
    db, config = setup
    tick(db, config, TICK)
    assert not claim(db, TICK, TICK)
    assert not force_tick(db, TICK, quote(TICK), RULES, config)
    assert interval_summary(db, config)["paper_entries"] == 1


def test_unexitable_position_prevents_overlap(setup):
    db, config = setup
    tick(db, config, TICK)
    following = TICK + pd.Timedelta(seconds=20)
    claim(db, following, following)
    force_tick(db, following, quote(following, bid_size=.00001), RULES, config)
    status = interval_summary(db, config)
    assert status["paper_entries"] == status["open_positions"] == 1
    assert status["completed_trades"] == 0
    assert status["decision_reasons"]["previous_position_not_exitable"] == 1


def test_late_tick_closes_overdue_position_without_backfilled_entry(setup):
    db, config = setup
    tick(db, config, TICK)
    following = TICK + pd.Timedelta(seconds=20)
    claim(db, following, following)
    force_tick(db, following, quote(following, lag=8), RULES, config)
    status = interval_summary(db, config)
    assert status["paper_entries"] == status["completed_trades"] == 1
    assert status["open_positions"] == 0
    assert status["mean_actual_holding_seconds"] == 27
    assert status["decision_reasons"]["late_tick_no_backfill"] == 1


def test_stop_drains_without_reopening(setup):
    db, config = setup
    tick(db, config, TICK)
    tick(db, config, TICK + pd.Timedelta(seconds=20), open_new=False)
    status = interval_summary(db, config)
    assert status["open_positions"] == 0
    assert status["paper_entries"] == status["completed_trades"] == 1
    assert status["cash_usdt"] == pytest.approx(50 + status["realized_pnl_usdt"])
    assert status["cash_usdt"] == status["liquidation_equity_usdt_estimate"]


def test_missing_venue_rules_do_not_force_invalid_size(setup):
    db, config = setup
    claim(db, TICK, TICK)
    force_tick(db, TICK, quote(TICK), None, config)
    assert interval_summary(db, config)["paper_entries"] == 0


def test_no_past_quote_no_unclaimed_execution_or_catch_up_slots(setup):
    db, config = setup
    with pytest.raises(ValueError, match="Persist"):
        force_tick(db, TICK, quote(TICK), RULES, config)
    claim(db, TICK, TICK)
    with pytest.raises(ValueError, match="at/after"):
        force_tick(db, TICK, quote(TICK - pd.Timedelta(seconds=1)), RULES, config)
    assert next_slot(TICK) == TICK + pd.Timedelta(seconds=20)
    assert next_slot(TICK + pd.Timedelta(seconds=87)) == TICK + pd.Timedelta(seconds=100)
