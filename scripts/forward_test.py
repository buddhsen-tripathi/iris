#!/usr/bin/env python3
"""Bounded local public-data forward test. Uses no keys or order endpoints."""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

import pandas as pd

from alphacouncil.data.archive import file_sha256, utc_now, write_json
from alphacouncil.features.build import NAMES, build_features, numeric_candles
from alphacouncil.forward.feed import PublicFeed, canonical_klines, merge_observations, observed_quote
from alphacouncil.forward.ledger import connect, event, execute_entries, exit_due, publish, settle, summary, symbol_rules
from alphacouncil.models.frozen import FrozenCommittee


def validate_config(config):
    if config["mode"] != "LIVE_DATA_PAPER_ONLY" or config["api_base"] != "https://data-api.binance.vision":
        raise ValueError("Only the fixed public-data paper mode is implemented")
    if config["symbol"] != "BTCUSDT" or config["policies"] != ["five_minute_only", "with_15m_30m_confirmation"]:
        raise ValueError("Unsupported symbol/policies")
    bounds = {"forecast_minutes": (1, 1440), "settlement_grace_minutes": (30, 60), "poll_seconds": (5, 60),
              "maximum_forecast_delay_seconds": (1, 30), "maximum_clock_offset_seconds": (0.1, 5),
              "maximum_quote_rtt_seconds": (0.1, 3), "initial_paper_cash_usdt_per_policy": (1, 50),
              "maximum_paper_cash_per_position_usdt": (1, 10), "fee_bps_per_side_assumed": (0, 100),
              "slippage_bps_per_side_assumed": (0, 100), "extra_edge_buffer_bps": (0, 100), "paper_holding_minutes": (5, 5)}
    for key, (low, high) in bounds.items():
        if not low <= config[key] <= high:
            raise ValueError(f"Invalid bounded configuration: {key}")


def write_status(session, manifest, db):
    status = {**manifest, "heartbeat_utc": utc_now().isoformat(), **summary(db)}
    write_json(session / "status.json", status)
    write_json(Path("data/manifests/forward_latest.json"), status)
    lines = ["# Live-data paper forward test", "", f"Session `{status['session_id']}` — **{status['status']}**.", "",
             f"Updated {status['heartbeat_utc']}. PID {status['pid']}. Public Binance BTCUSDT spot data; no real orders.", "",
             f"Forecast collection ends {status['forecast_until_utc']}; settlement deadline {status['hard_stop_utc']}.", "",
             f"Forecast bundles: {status['counts']['forecast_bundles']} (three horizons each). Matured outcomes: {status['counts']['outcomes']}; pending: {status['counts']['pending_outcomes']}.", "",
             "| Paper policy | Cash USDT | Open | Closed trades | Realized P&L USDT |", "|---|---:|---:|---:|---:|"]
    for account in status["accounts"]:
        lines.append(f"| {account['policy']} | {account['cash']:.6f} | {account['open_positions']} | {account['completed_trades']} | {account['realized_pnl_usdt']:.6f} |")
    lines += ["", "Cash excludes the value of any open positions; realized P&L covers closed paper trades only.", "",
              "| Horizon | Matured forecasts | Committee MAE (log bps) | MSE skill vs zero |", "|---|---:|---:|---:|"]
    for metric in status["forecast_metrics"]:
        if metric["model"] == "committee":
            skill = metric["mse_skill_vs_zero"]
            lines.append(f"| {metric['horizon_minutes']}m | {metric['rows']} | {metric['mae_log_bps']:.4f} | {skill if skill is not None else 'undefined'} |")
    lines += ["", "No matured outcomes means no forward performance result yet. Small, overlapping samples cannot establish an edge.", "",
              "Frozen checkpoints and 20% expert weights are unchanged. Historical candles supply causal context only; no past forecast is inserted into this run. Publication lag is recorded; forecasts over 30 seconds late are skipped. Outcomes are anchored at the completed bar close plus 5/15/30 minutes.", "",
              "Paper entries use the first requested fresh observed ask after forecast persistence; exits use an observed bid requested at/after five minutes from actual entry. Ten basis points of assumed fees and two of assumed slippage apply on each side, plus a two-basis-point entry buffer. These are assumptions, not verified account fees/fills. Book quotes lack an exchange event timestamp; receipt time and HTTP latency are recorded. Independent paper portfolios may consume the same displayed liquidity; this is a policy comparison, not a combined portfolio.", "",
              "A missing/late exit remains open until a usable quote arrives. At the deadline, missing outcomes and unresolved positions remain explicitly pending. This local process requires the Mac to remain awake and online. A dead process can leave an old status snapshot; the status command checks PID and heartbeat.", "",
              f"Ledger and raw receipts: `{session}`. Logs: `{manifest['log_path']}`.", "",
              "```sh", "uv run --group training python scripts/forward_status.py", "# Stop new forecasts and drain pending observations:", f"touch {session}/STOP", "```", "",
              "[Public market-data endpoint documentation](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only)."]
    Path("reports/live_forward_test.md").write_text("\n".join(lines) + "\n")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/forward_paper.json"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate_config(config)
    latest = Path("data/manifests/forward_latest.json")
    if latest.exists():
        previous = json.loads(latest.read_text())
        if previous["status"] in {"starting", "running", "draining"}:
            try:
                os.kill(previous["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError("A forward session is already active; use forward_status.py")
    started = pd.Timestamp(utc_now())
    session_id = started.strftime("%Y%m%dT%H%M%S%fZ")
    session = Path("data/forward") / session_id
    session.mkdir(parents=True)
    db = connect(session / "ledger.sqlite3")
    with db:
        db.executemany("INSERT INTO accounts VALUES (?,?)", [(policy, config["initial_paper_cash_usdt_per_policy"]) for policy in config["policies"]])
    cutoff = started + pd.Timedelta(minutes=config["forecast_minutes"])
    hard_stop = cutoff + pd.Timedelta(minutes=config["settlement_grace_minutes"])
    model_path = Path("data/manifests/training_latest.json")
    training = json.loads(model_path.read_text())
    manifest = {"session_id": session_id, "session_directory": str(session), "status": "starting", "pid": os.getpid(),
                "started_at_utc": started.isoformat(), "forecast_until_utc": cutoff.isoformat(), "hard_stop_utc": hard_stop.isoformat(),
                "config": config, "config_sha256": file_sha256(args.config), "training_run_id": training["run_id"], "training_manifest_sha256": file_sha256(model_path),
                "log_path": os.environ.get("ALPHACOUNCIL_FORWARD_LOG", "stdout"),
                "code_sha256": {str(path): file_sha256(path) for path in [Path(__file__).resolve().relative_to(Path.cwd()), *sorted(Path("src/alphacouncil/forward").glob("*.py")), Path("src/alphacouncil/models/frozen.py"), Path("src/alphacouncil/models/experts.py"), Path("src/alphacouncil/features/build.py"), Path("uv.lock")]}}
    write_json(session / "config.json", config)
    write_json(session / "training_manifest.json", training)
    write_status(session, manifest, db)
    signal.signal(signal.SIGTERM, lambda *_: (session / "STOP").touch())
    signal.signal(signal.SIGINT, lambda *_: (session / "STOP").touch())
    try:
        models = FrozenCommittee(training)
        feature_manifest_path = Path("data/manifests/features_latest.json")
        if file_sha256(feature_manifest_path) != training["inputs"][str(feature_manifest_path)]:
            raise ValueError("Feature manifest changed since training")
        features_manifest = json.loads(feature_manifest_path.read_text())
        for code, expected in {"src/alphacouncil/features/build.py": features_manifest["code_sha256"]["src/alphacouncil/features/build.py"],
                               "src/alphacouncil/models/experts.py": training["code_sha256"]["src/alphacouncil/models/experts.py"]}.items():
            if file_sha256(Path(code)) != expected:
                raise ValueError(f"Feature/model implementation changed since training: {code}")
        collection_path = Path("data/manifests/latest.json")
        if file_sha256(collection_path) != training["inputs"][str(collection_path)]:
            raise ValueError("Historical collection manifest changed since training")
        collection = json.loads(collection_path.read_text())
        context, source_hashes = {}, {}
        for dataset in collection["datasets"]:
            key = dataset["symbol"], dataset["interval"]
            if key not in {("BTCUSDT", "5m"), ("ETHUSDT", "5m"), ("SOLUSDT", "5m"), ("BTCUSDT", "1h")}:
                continue
            path = Path("data") / dataset["path"]
            if file_sha256(path) != dataset["sha256"]:
                raise ValueError(f"Historical context hash mismatch: {path}")
            context[key] = pd.read_parquet(path)
            source_hashes[str(path)] = dataset["sha256"]
        manifest["historical_context_sha256"] = source_hashes
        feed = PublicFeed(session, db)
        rules = None
        try:
            payload, receipt = feed.get("exchangeInfo", symbol="BTCUSDT")
            rules = symbol_rules(payload)
            manifest["exchange_rules_receipt_sha256"] = receipt["sha256"]
        except Exception as error:
            event(db, utc_now(), "venue_rules_unavailable", error)
        last_considered = started.floor("5min")
        manifest["status"] = "running"
        failures = 0
        while pd.Timestamp(utc_now()) < hard_stop:
            iteration_start = time.monotonic()
            if (session / "STOP").exists() and manifest["status"] != "draining":
                cutoff = min(cutoff, pd.Timestamp(utc_now()))
                hard_stop = min(hard_stop, cutoff + pd.Timedelta(minutes=config["settlement_grace_minutes"]))
                manifest.update(status="draining", forecast_until_utc=cutoff.isoformat(), hard_stop_utc=hard_stop.isoformat())
                event(db, utc_now(), "stop_requested", "No further forecasts; drain existing observations/positions")
            try:
                server, receipt = feed.get("time")
                server_ms = int(server["serverTime"])
                midpoint = (pd.Timestamp(receipt["observed_at_utc"]) + (pd.Timestamp(receipt["request_started_utc"]) - pd.Timestamp(receipt["observed_at_utc"])) / 2)
                offset = (pd.to_datetime(server_ms, unit="ms", utc=True) - midpoint).total_seconds()
                if abs(offset) > config["maximum_clock_offset_seconds"]:
                    raise ValueError(f"Exchange/local clock offset exceeds limit: {offset:.3f}s")
                manifest["clock_offset_seconds"] = offset
                for (symbol, interval), previous in list(context.items()):
                    # Overlap one completed bar to detect revisions; paginate bridge gaps.
                    start_ms = int(previous["open_time_utc"].iloc[-1].timestamp() * 1000)
                    while True:
                        payload, receipt = feed.get("klines", symbol=symbol, interval=interval, startTime=start_ms, limit=1000)
                        incoming = canonical_klines(payload, symbol, interval, server_ms, receipt)
                        updated = merge_observations(context[symbol, interval], incoming)
                        numeric_candles(updated, symbol, interval)
                        context[symbol, interval] = updated
                        with db:
                            for row in incoming.itertuples():
                                db.execute("INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?)", (symbol, interval, row.close_time_utc.isoformat(), str(row.close), row.ingested_at_utc.isoformat(), row.source_sha256))
                        if len(payload) < 1000 or incoming.empty:
                            break
                        start_ms = int(incoming["close_time_utc"].iloc[-1].timestamp() * 1000)
                now = pd.Timestamp(utc_now())
                btc = context["BTCUSDT", "5m"]
                prices = dict(zip(btc["close_time_utc"], btc["close"].astype(float)))
                settle(db, prices, now)
                # Position exits are independent of whether new forecasts are permitted.
                due = db.execute("SELECT due_utc FROM positions WHERE exit_utc IS NULL").fetchall()
                if any(pd.Timestamp(row[0]) <= now for row in due):
                    payload, receipt = feed.get("ticker/bookTicker", symbol="BTCUSDT")
                    quote = observed_quote(payload, receipt, config["maximum_quote_rtt_seconds"])
                    exit_due(db, quote, config)
                anchor = btc["close_time_utc"].iloc[-1]
                if anchor > last_considered and now < cutoff and manifest["status"] != "draining":
                    # Do not skip a boundary while waiting for slower cross-asset/hourly bars.
                    ready = all(context[symbol, "5m"]["close_time_utc"].iloc[-1] >= anchor for symbol in ("ETHUSDT", "SOLUSDT"))
                    ready = ready and context["BTCUSDT", "1h"]["close_time_utc"].iloc[-1] >= anchor.floor("h")
                    delay = (now - anchor).total_seconds()
                    if anchor <= started or delay > config["maximum_forecast_delay_seconds"]:
                        last_considered = anchor
                        event(db, now, "forecast_skipped", f"{anchor.isoformat()}: not prospective or {delay:.3f}s late")
                    elif ready:
                        features = build_features(btc, context["ETHUSDT", "5m"], context["SOLUSDT", "5m"], context["BTCUSDT", "1h"]).iloc[[-1]]
                        prediction = models.predict(features, btc)
                        published = pd.Timestamp(utc_now())
                        forecast_id = publish(db, anchor, published, started, prediction,
                                              {name: float(features[name].iloc[0]) for name in NAMES},
                                              prices[anchor], config["maximum_forecast_delay_seconds"])
                        last_considered = anchor
                        event(db, published, "forecast_published", f"{anchor.isoformat()}, horizons 5/15/30, lag {(published-anchor).total_seconds():.3f}s")
                        print(f"FORECAST {anchor.isoformat()} saved {published.isoformat()} {json.dumps(prediction)}", flush=True)
                        try:
                            payload, receipt = feed.get("ticker/bookTicker", symbol="BTCUSDT")
                            quote = observed_quote(payload, receipt, config["maximum_quote_rtt_seconds"])
                            execute_entries(db, forecast_id, quote, rules, config)
                        except Exception as error:
                            event(db, utc_now(), "entry_unavailable", error)
                failures = 0
                manifest["last_successful_poll_utc"] = utc_now().isoformat()
                manifest.pop("last_error", None)
            except Exception as error:
                failures += 1
                manifest["last_error"] = str(error)
                event(db, utc_now(), "poll_error", error)
                print(f"POLL_ERROR {utc_now().isoformat()} {type(error).__name__}: {error}", flush=True)
            if pd.Timestamp(utc_now()) >= cutoff:
                manifest["status"] = "draining"
            manifest["consecutive_poll_errors"] = failures
            status = write_status(session, manifest, db)
            if manifest["status"] == "draining" and status["counts"]["pending_outcomes"] == 0 and not any(row["open_positions"] for row in status["accounts"]):
                break
            delay = max(0, config["poll_seconds"] - (time.monotonic() - iteration_start))
            time.sleep(delay)
        manifest["status"] = "completed" if summary(db)["counts"]["pending_outcomes"] == 0 and not any(row["open_positions"] for row in summary(db)["accounts"]) else "stopped_with_pending"
        manifest["finished_at_utc"] = utc_now().isoformat()
    except Exception as error:
        manifest.update(status="failed", last_error=str(error), finished_at_utc=utc_now().isoformat())
        event(db, utc_now(), "fatal_error", error)
        raise
    finally:
        status = write_status(session, manifest, db)
        print(json.dumps({"session_id": session_id, "status": status["status"], "counts": status["counts"]}), flush=True)
        db.close()


if __name__ == "__main__":
    main()
