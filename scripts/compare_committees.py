#!/usr/bin/env python3
"""Chronological development-only adaptive versus equal committee comparison."""

import argparse
import hashlib
import heapq
import json
import sqlite3
from pathlib import Path

import pandas as pd

from alphacouncil.committee import CommitteeLedger
from alphacouncil.data.archive import file_sha256, utc_now, write_json
from alphacouncil.models.experts import forecast_metrics


def replay(frame, config, db):
    ledger = CommitteeLedger(db, config)
    pending, result = [], []
    sequence = 0
    for row in frame.sort_values("decision_time_utc").to_dict("records"):
        now = pd.Timestamp(row["decision_time_utc"])
        # At coincident boundaries, publish first: no assumed instantaneous close receipt.
        while pending and pending[0][0] < now:
            observed, source_id, actual = heapq.heappop(pending)
            ledger.observe(source_id, actual, observed, observed)
        for horizon in config["horizons_minutes"]:
            sequence += 1
            maturity = pd.Timestamp(row[f"matures_{horizon}m_utc"])
            experts = {name: float(row[f"{name}_{horizon}m"]) for name in config["experts"]}
            emitted = ledger.publish(sequence, horizon, now, now, now, maturity, experts, "DEVELOPMENT_REPLAY")
            result.append({"source_forecast_id": sequence, "decision_time_utc": now, "horizon_minutes": horizon,
                "maturity_utc": maturity, "actual_log_return": row[f"target_{horizon}m"],
                "adaptive_mu": emitted["adaptive_mu"], "equal_mu": emitted["equal_mu"],
                "weights_json": emitted["weights_json"]})
            heapq.heappush(pending, (maturity, sequence, float(row[f"target_{horizon}m"])))
    while pending:
        observed, source_id, actual = heapq.heappop(pending)
        ledger.observe(source_id, actual, observed, observed)
    db.commit()
    return pd.DataFrame(result), ledger


def metrics(frame):
    result = []
    for horizon, rows in frame.groupby("horizon_minutes"):
        for name, column in (("adaptive", "adaptive_mu"), ("equal_weight", "equal_mu")):
            result.append({"horizon_minutes": int(horizon), "model": name,
                           **forecast_metrics(rows["actual_log_return"], rows[column])})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-manifest", type=Path, default=Path("data/manifests/training_latest.json"))
    args = parser.parse_args()
    config = json.loads(Path("configs/committee.json").read_text())
    training = json.loads(args.training_manifest.read_text())
    source = Path(training["training_directory"])/"development_forecasts.parquet"
    digest = file_sha256(source)
    if digest != training["outputs"][str(source)]:
        raise ValueError("Development forecast checksum mismatch")
    frame = pd.read_parquet(source)
    reserved = pd.Timestamp(training["splits"]["reserved_start_utc"])
    if any(pd.to_datetime(frame[f"matures_{h}m_utc"], utc=True).ge(reserved).any() for h in config["horizons_minutes"]):
        raise ValueError("Reserved outcomes are excluded from this comparison")
    run = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    destination = Path("data/forward")/f"committee_development_{run}"
    destination.mkdir(parents=True)
    db = sqlite3.connect(destination/"committee.sqlite")
    predictions, ledger = replay(frame, config, db)
    predictions.to_parquet(destination/"comparison_forecasts.parquet", index=False)
    result = {"schema_version": 1, "mode": "DEVELOPMENT_REPLAY", "created_at_utc": utc_now().isoformat(),
              "source": str(source), "source_sha256": digest, "training_run_id": training["run_id"],
              "config": config, "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
              "ledger_directory": str(destination), "observation_assumption": "Historical maturity timestamp, processed strictly before subsequent decision timestamps; no real historical receipt times available.",
              "reserved_test_evaluated": False, "live_trading_enabled": False,
              "forecast_metrics": metrics(predictions), **ledger.snapshot()}
    write_json(Path("reports/committee/comparison.json"), result)
    lines = ["# Adaptive committee development comparison", "", "This is a chronological **development replay**, not untouched validation or a live result. The feature audit previously saw development distributions. No reserved outcomes were read and no orders were placed.", "",
             "Each horizon keeps its own discounted squared-error score. Weights are exponential in the negative score, shrunk 10% toward equal, and projected onto a 5% floor / 50% cap. Fixed loss scales are 10, 17.32 and 24.49 log bps; loss clipping is 25, learning rate 0.05 and score retention 0.995 per update. These are engineering defaults, not parameters selected for favorable results. No regime-dependent gain is claimed.", "",
             "A forecast records its exact weights before updates. Only already matured and observed outcomes can update scores, once per immutable source forecast ID. Historical receipt times do not exist: replay assumes observation at maturity and excludes outcomes with maturity equal to the current decision boundary. Live shadow instead records its actual publication and application timestamps, never backfills past forecasts, and reads the original paper ledger without modifying it.", "",
             "| Horizon | Method | Rows | MAE (log bps) | RMSE (log bps) | MSE skill vs zero |", "|---|---|---:|---:|---:|---:|"]
    for row in result["forecast_metrics"]:
        lines.append(f"| {row['horizon_minutes']}m | {row['model']} | {row['rows']:,} | {row['mae_log_bps']:.4f} | {row['rmse_log_bps']:.4f} | {row['mse_skill_vs_zero']:+.4%} |")
    lines += ["", "These overlapping errors are not independent. A lower replay error alone does not establish reliable future improvement, trading returns or profitability. Three specialists currently emit zero or very small amplitudes; adapted forecasting shares are not capital allocations. Keep the frozen equal committee as a baseline while collecting prospective outcomes.", "", "Machine-readable comparison: `reports/committee/comparison.json`. Full immutable forecast/update ledger and per-origin weights: `"+str(destination)+"`. Live shadow status: `data/manifests/committee_latest.json`.", "", "Run `uv run --group training python scripts/compare_committees.py` to reproduce. Start `uv run --group training python scripts/committee_shadow.py --minutes 60` to watch new forecasts without changing either paper trader."]
    Path("reports/adaptive_committee.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({"ledger_directory": str(destination), "forecast_metrics": result["forecast_metrics"]}, indent=2))


if __name__ == "__main__":
    main()
