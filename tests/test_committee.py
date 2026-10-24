import importlib.util
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alphacouncil.committee import CommitteeLedger, bounded_weights

CONFIG = json.loads(Path("configs/committee.json").read_text())
T = pd.Timestamp("2026-10-24T12:00:00Z")
EXPERTS = dict(zip(CONFIG["experts"], [0.001, -0.001, 0.0, 0.0002, 0.0003]))


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path("scripts")/(name+".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ledger():
    return CommitteeLedger(sqlite3.connect(":memory:"), CONFIG)


def publish(target, source_id=1, horizon=5, anchor=T):
    return target.publish(source_id, horizon, anchor, anchor, anchor, anchor+pd.Timedelta(minutes=horizon), EXPERTS, "DEVELOPMENT_REPLAY")


def test_bounds_discount_and_equal_start():
    item = ledger()
    assert np.array(list(item.state(5)[1].values())) == pytest.approx([0.2]*5)
    for scores in ([0,100,100,100,100], [100,0,0,0,0], [1e8,0,0,0,0]):
        weights = bounded_weights(scores, CONFIG)
        assert weights.sum() == pytest.approx(1)
        assert min(weights) >= 0.05-1e-12
        assert max(weights) <= 0.5+1e-12
    publish(item)
    item.observe(1, .001, T+pd.Timedelta(minutes=5), T+pd.Timedelta(minutes=5))
    assert item.state(5)[1]["lightgbm"] > item.state(5)[1]["ridge"]
    assert item.state(15)[2] == 0


def test_maturity_and_actual_observation_gate():
    item = ledger()
    publish(item)
    maturity = T+pd.Timedelta(minutes=5)
    observed = maturity+pd.Timedelta(seconds=20)
    assert not item.observe(1, .001, observed, maturity)
    assert item.state(5)[2] == 0
    with pytest.raises(ValueError, match="predate maturity"):
        item.observe(1, .001, T, maturity)
    assert item.observe(1, .001, observed, observed)
    assert item.state(5)[2] == 1


def test_idempotent_immutable_outcome_and_pinned_prediction():
    item = ledger()
    first = publish(item)
    time = T+pd.Timedelta(minutes=5)
    item.observe(1, .001, time, time)
    before = item.snapshot()
    assert not item.observe(1, .001, time, time+pd.Timedelta(seconds=5))
    assert item.snapshot() == before
    assert item.db.execute("SELECT count(*) FROM updates").fetchone()[0] == 1
    assert json.loads(first["weights_json"]) == pytest.approx({name: .2 for name in CONFIG["experts"]})
    with pytest.raises(ValueError, match="revised"):
        item.observe(1, .002, time, time)


def test_no_time_travel_or_late_forecast():
    item = ledger()
    publish(item)
    item.observe(1, .001, T+pd.Timedelta(minutes=5), T+pd.Timedelta(minutes=5))
    with pytest.raises(ValueError, match="current clock"):
        publish(item, 2, anchor=T+pd.Timedelta(minutes=1))
    with pytest.raises(ValueError, match="prospectively"):
        item.publish(3, 5, T, T, T+pd.Timedelta(minutes=5), T+pd.Timedelta(minutes=5), EXPERTS, "LIVE_SHADOW")


def test_configuration_is_pinned_on_restart():
    db = sqlite3.connect(":memory:")
    first = CommitteeLedger(db, CONFIG)
    publish(first)
    second = CommitteeLedger(db, CONFIG)
    assert second.snapshot() == first.snapshot()
    with pytest.raises(ValueError, match="Configuration changed"):
        CommitteeLedger(db, {**CONFIG, "learning_rate": .1})


def replay_frame():
    records = []
    for offset in range(0, 60, 5):
        now = T+pd.Timedelta(minutes=offset)
        row = {"decision_time_utc": now}
        for horizon in CONFIG["horizons_minutes"]:
            row.update({f"matures_{horizon}m_utc": now+pd.Timedelta(minutes=horizon), f"target_{horizon}m": .001})
            row.update({f"{name}_{horizon}m": value for name, value in EXPERTS.items()})
        records.append(row)
    return pd.DataFrame(records)


def test_replay_deterministic_and_future_outcome_invariant():
    module = script("compare_committees")
    frame = replay_frame()
    first, _ = module.replay(frame, CONFIG, sqlite3.connect(":memory:"))
    second, _ = module.replay(frame, CONFIG, sqlite3.connect(":memory:"))
    pd.testing.assert_frame_equal(first, second)
    changed = frame.copy()
    for horizon in CONFIG["horizons_minutes"]:
        changed.loc[changed["decision_time_utc"] >= T+pd.Timedelta(minutes=30), f"target_{horizon}m"] = -.5
    later, _ = module.replay(changed, CONFIG, sqlite3.connect(":memory:"))
    causal = first["decision_time_utc"] <= T+pd.Timedelta(minutes=30)
    pd.testing.assert_frame_equal(first.loc[causal].drop(columns="actual_log_return"), later.loc[causal].drop(columns="actual_log_return"))
    at_first_maturity = first[(first.decision_time_utc == T+pd.Timedelta(minutes=5)) & first.horizon_minutes.eq(5)].iloc[0]
    assert json.loads(at_first_maturity.weights_json) == pytest.approx({name: .2 for name in CONFIG["experts"]})


def test_live_shadow_never_backfills_or_reads_future_observations(tmp_path):
    module = script("committee_shadow")
    source_path = tmp_path/"original.sqlite3"
    source = sqlite3.connect(source_path)
    source.executescript("CREATE TABLE forecasts(id INTEGER,anchor_utc TEXT,published_at_utc TEXT,horizon INTEGER,maturity_utc TEXT,predictions_json TEXT); CREATE TABLE outcomes(forecast_id INTEGER,observed_at_utc TEXT,actual_log_return REAL);")
    for source_id, anchor in ((1, T-pd.Timedelta(minutes=5)), (2,T+pd.Timedelta(minutes=5))):
        source.execute("INSERT INTO forecasts VALUES (?,?,?,?,?,?)", (source_id,anchor.isoformat(),(anchor+pd.Timedelta(seconds=5)).isoformat(),5,(anchor+pd.Timedelta(minutes=5)).isoformat(),json.dumps({"experts":EXPERTS})))
    observed = T+pd.Timedelta(minutes=10,seconds=5)
    source.execute("INSERT INTO outcomes VALUES (?,?,?)", (2,observed.isoformat(),.001))
    source.commit()
    source.close()
    readonly = module.open_read_only(source_path)
    item = ledger()
    now = T+pd.Timedelta(minutes=5,seconds=10)
    module.poll(readonly, item, T, now, CONFIG)
    assert item.snapshot()["counts"] == {"forecasts":1,"outcomes":0,"pending_outcomes":1}
    emitted = item.db.execute("SELECT * FROM forecasts").fetchone()
    assert emitted["published_at_utc"] == now.isoformat()
    module.poll(readonly, item, T, observed, CONFIG)
    module.poll(readonly, item, T, observed+pd.Timedelta(seconds=2), CONFIG)
    assert item.snapshot()["counts"]["outcomes"] == 1
    with pytest.raises(sqlite3.OperationalError):
        readonly.execute("DELETE FROM forecasts")


def test_source_forecast_is_immutable_even_on_duplicate_id():
    item = ledger()
    original = publish(item)
    assert publish(item) == original
    with pytest.raises(ValueError, match="source forecast was revised"):
        item.publish(1, 5, T, T, T, T+pd.Timedelta(minutes=5), {**EXPERTS, "ridge": 1.0}, "DEVELOPMENT_REPLAY")


def test_live_shadow_skips_late_anchor_even_if_source_publication_is_recent():
    module = script("committee_shadow")
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    source.executescript("CREATE TABLE forecasts(id INTEGER,anchor_utc TEXT,published_at_utc TEXT,horizon INTEGER,maturity_utc TEXT,predictions_json TEXT); CREATE TABLE outcomes(forecast_id INTEGER,observed_at_utc TEXT,actual_log_return REAL);")
    source.execute("INSERT INTO forecasts VALUES (?,?,?,?,?,?)", (1,T.isoformat(),(T+pd.Timedelta(seconds=29)).isoformat(),5,(T+pd.Timedelta(minutes=5)).isoformat(),json.dumps({"experts": EXPERTS})))
    item = ledger()
    module.poll(source,item,T-pd.Timedelta(seconds=1),T+pd.Timedelta(seconds=31),CONFIG)
    assert item.snapshot()["counts"]["forecasts"] == 0
