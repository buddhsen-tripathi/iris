"""Causal horizon-specific exponential-loss aggregation with an immutable audit trail."""

import json
import math
import sqlite3

import numpy as np
import pandas as pd


def timestamp(value):
    result = pd.Timestamp(value)
    if result.tzinfo is None or pd.isna(result):
        raise ValueError("A timezone-aware timestamp is required")
    return result.tz_convert("UTC")


def bounded_weights(scores, config):
    """Softmax discounted losses, shrink to equal, then project onto box simplex."""
    scores = np.asarray(scores, dtype=float)
    if not np.isfinite(scores).all() or scores.ndim != 1 or len(scores) != len(config["experts"]):
        raise ValueError("Invalid expert scores")
    floor, cap = config["minimum_expert_weight"], config["maximum_expert_weight"]
    if not 0 <= floor <= cap <= 1 or len(scores) * floor > 1 or len(scores) * cap < 1:
        raise ValueError("Infeasible weight bounds")
    logits = -config["learning_rate"] * scores
    weights = np.exp(logits - logits.max())
    weights /= weights.sum()
    shrink = config["equal_weight_shrinkage"]
    weights = (1 - shrink) * weights + shrink / len(weights)
    if np.all(weights >= floor) and np.all(weights <= cap):
        return weights
    # Euclidean projection onto sum(w)=1 and floor<=w<=cap. Stable, deterministic.
    low, high = float((weights-cap).min()), float((weights-floor).max())
    for _ in range(70):
        middle = (low + high) / 2
        if np.clip(weights-middle, floor, cap).sum() > 1:
            low = middle
        else:
            high = middle
    return np.clip(weights-(low+high)/2, floor, cap)


class CommitteeLedger:
    """Each forecast pins weights before any later outcome can change them.

    Callers supply wall-clock observation/application timestamps. Historical replay must
    explicitly label its assumed observation times and must never masquerade as live.
    Source IDs are stable within one source session; outcomes are applied once only.
    The caller owns transaction boundaries (commit after a processing batch).
    """

    def __init__(self, db: sqlite3.Connection, config: dict):
        self.db, self.config = db, config
        self.names = tuple(config["experts"])
        if len(set(self.names)) != len(self.names) or not self.names:
            raise ValueError("Unique expert names required")
        if not 0 < config["learning_rate"] or not 0 < config["discount_per_update"] <= 1 or not 0 <= config["equal_weight_shrinkage"] <= 1:
            raise ValueError("Invalid learning configuration")
        if not config["maximum_scaled_squared_loss"] > 0 or any(not value > 0 for value in config["loss_scale_log_bps"].values()):
            raise ValueError("Positive loss limits and scales required")
        bounded_weights(np.zeros(len(self.names)), config)
        db.row_factory = sqlite3.Row
        db.executescript("""
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS states(horizon INTEGER PRIMARY KEY, scores_json TEXT NOT NULL, update_count INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS forecasts(source_forecast_id INTEGER PRIMARY KEY, horizon INTEGER NOT NULL,
            anchor_utc TEXT NOT NULL, source_published_at_utc TEXT NOT NULL, published_at_utc TEXT NOT NULL,
            maturity_utc TEXT NOT NULL, experts_json TEXT NOT NULL, weights_json TEXT NOT NULL,
            adaptive_mu REAL NOT NULL, equal_mu REAL NOT NULL, mode TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS updates(source_forecast_id INTEGER PRIMARY KEY REFERENCES forecasts(source_forecast_id),
            horizon INTEGER NOT NULL, maturity_utc TEXT NOT NULL, source_observed_at_utc TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL, actual_log_return REAL NOT NULL, loss_json TEXT NOT NULL,
            scores_after_json TEXT NOT NULL, weights_after_json TEXT NOT NULL, update_count INTEGER NOT NULL);
        """)
        config_json = json.dumps(config, sort_keys=True, allow_nan=False)
        saved = db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
        if saved and saved[0] != config_json:
            raise ValueError("Configuration changed for an existing committee ledger")
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('config',?)", (config_json,))
        for horizon in config["horizons_minutes"]:
            db.execute("INSERT OR IGNORE INTO states VALUES (?,?,0)", (horizon, json.dumps([0.0]*len(self.names))))

    def state(self, horizon):
        row = self.db.execute("SELECT * FROM states WHERE horizon=?", (int(horizon),)).fetchone()
        if row is None:
            raise ValueError("Unsupported horizon")
        scores = json.loads(row["scores_json"])
        return scores, dict(zip(self.names, map(float, bounded_weights(scores, self.config)))), row["update_count"]

    def _advance_clock(self, now):
        previous = self.db.execute("SELECT value FROM metadata WHERE key='last_operation_utc'").fetchone()
        if previous and now < timestamp(previous[0]):
            raise ValueError("Cannot apply an event before the committee's current clock")
        self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_operation_utc',?)", (now.isoformat(),))

    def publish(self, source_id, horizon, anchor, source_published, published, maturity, experts, mode):
        existing = self.db.execute("SELECT * FROM forecasts WHERE source_forecast_id=?", (int(source_id),)).fetchone()
        if existing:
            expected = (int(horizon), timestamp(anchor).isoformat(), timestamp(source_published).isoformat(),
                        timestamp(maturity).isoformat(), json.dumps(experts, sort_keys=True, allow_nan=False), mode)
            actual = tuple(existing[key] for key in ("horizon", "anchor_utc", "source_published_at_utc", "maturity_utc", "experts_json", "mode"))
            if actual != expected:
                raise ValueError("An immutable source forecast was revised")
            return dict(existing)
        anchor, source_published, published, maturity = map(timestamp, (anchor, source_published, published, maturity))
        if not anchor <= source_published <= published < maturity or maturity != anchor + pd.Timedelta(minutes=int(horizon)):
            raise ValueError("Forecast must be published prospectively, before its exact maturity")
        if set(experts) != set(self.names) or not all(math.isfinite(float(value)) for value in experts.values()):
            raise ValueError("Finite predictions for exactly the configured experts required")
        if mode not in {"DEVELOPMENT_REPLAY", "LIVE_SHADOW"}:
            raise ValueError("Explicit forecast provenance is required")
        _, weights, _ = self.state(horizon)
        self._advance_clock(published)
        adaptive = sum(weights[name]*float(experts[name]) for name in self.names)
        equal = sum(float(experts[name]) for name in self.names)/len(self.names)
        self.db.execute("INSERT INTO forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?)", (source_id, horizon,
            anchor.isoformat(), source_published.isoformat(), published.isoformat(), maturity.isoformat(),
            json.dumps(experts, sort_keys=True, allow_nan=False), json.dumps(weights, sort_keys=True), adaptive, equal, mode))
        return dict(self.db.execute("SELECT * FROM forecasts WHERE source_forecast_id=?", (source_id,)).fetchone())

    def observe(self, source_id, actual, source_observed, applied_at):
        source_observed, applied_at = map(timestamp, (source_observed, applied_at))
        if not math.isfinite(float(actual)):
            raise ValueError("Finite realized return required")
        previous = self.db.execute("SELECT * FROM updates WHERE source_forecast_id=?", (source_id,)).fetchone()
        if previous:
            if previous["actual_log_return"] != float(actual) or timestamp(previous["source_observed_at_utc"]) != source_observed:
                raise ValueError("An immutable outcome was revised")
            return False
        row = self.db.execute("SELECT * FROM forecasts WHERE source_forecast_id=?", (source_id,)).fetchone()
        if row is None:
            return False
        maturity = timestamp(row["maturity_utc"])
        if source_observed < maturity:
            raise ValueError("Outcome observation cannot predate maturity")
        if applied_at < source_observed or applied_at < maturity:
            return False
        if timestamp(row["published_at_utc"]) >= maturity:
            raise ValueError("Forecast was not prospective")
        self._advance_clock(applied_at)
        scores, _, count = self.state(row["horizon"])
        experts = json.loads(row["experts_json"])
        scale = self.config["loss_scale_log_bps"][str(row["horizon"])] / 10000
        losses = np.minimum(np.square([(experts[name]-actual)/scale for name in self.names]), self.config["maximum_scaled_squared_loss"])
        updated_scores = self.config["discount_per_update"]*np.array(scores) + losses
        weights = dict(zip(self.names, map(float, bounded_weights(updated_scores, self.config))))
        scores_json = json.dumps(updated_scores.tolist(), allow_nan=False)
        self.db.execute("UPDATE states SET scores_json=?,update_count=? WHERE horizon=?", (scores_json, count+1, row["horizon"]))
        self.db.execute("INSERT INTO updates VALUES (?,?,?,?,?,?,?,?,?,?)", (source_id, row["horizon"], maturity.isoformat(),
            source_observed.isoformat(), applied_at.isoformat(), float(actual), json.dumps(dict(zip(self.names, map(float, losses)))),
            scores_json, json.dumps(weights, sort_keys=True), count+1))
        return True

    def snapshot(self):
        weights, updates = {}, {}
        for horizon in self.config["horizons_minutes"]:
            _, weights[str(horizon)], updates[str(horizon)] = self.state(horizon)
        counts = {"forecasts": self.db.execute("SELECT count(*) FROM forecasts").fetchone()[0],
                  "outcomes": self.db.execute("SELECT count(*) FROM updates").fetchone()[0]}
        counts["pending_outcomes"] = counts["forecasts"]-counts["outcomes"]
        latest = [dict(row) for row in self.db.execute("SELECT * FROM forecasts WHERE anchor_utc=(SELECT max(anchor_utc) FROM forecasts) ORDER BY horizon")]
        for row in latest:
            row["weights"] = json.loads(row.pop("weights_json"))
            row["experts"] = json.loads(row.pop("experts_json"))
        return {"weights_by_horizon": weights, "equal_weights": {name: 1/len(self.names) for name in self.names},
                "updates_by_horizon": updates, "counts": counts, "latest_forecasts": latest}
