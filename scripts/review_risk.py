#!/usr/bin/env python3
"""Independently review the latest model forecast against a fresh public quote."""

import argparse
import json
import math
import os
import sqlite3
import time
from pathlib import Path

import pandas as pd

from alphacouncil.data.archive import utc_now, write_json
from alphacouncil.forward.feed import PublicFeed, observed_quote
from alphacouncil.forward.ledger import connect, symbol_rules
from alphacouncil.risk import assess_payload


def review(directory, db):
    source = json.loads(Path("data/manifests/forward_latest.json").read_text())
    path = Path(source["session_directory"]) / "ledger.sqlite3"
    if not path.resolve().is_relative_to((Path.cwd()/"data/forward").resolve()):
        raise ValueError("Source session must be inside local forward data")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source_db:
        source_db.row_factory = sqlite3.Row
        source_db.execute("BEGIN")
        row = source_db.execute("SELECT * FROM forecasts WHERE horizon=5 ORDER BY anchor_utc DESC LIMIT 1").fetchone()
        account = source_db.execute("SELECT * FROM accounts WHERE policy='five_minute_only'").fetchone()
        positions = source_db.execute("SELECT quantity FROM positions WHERE policy='five_minute_only' AND exit_utc IS NULL").fetchall()
    feed = PublicFeed(directory, db)
    payload, _ = feed.get("exchangeInfo", symbol="BTCUSDT")
    rules = symbol_rules(payload)
    server, receipt = feed.get("time")
    midpoint = pd.Timestamp(receipt["request_started_utc"]) + (pd.Timestamp(receipt["observed_at_utc"])-pd.Timestamp(receipt["request_started_utc"])) / 2
    offset = (pd.to_datetime(server["serverTime"], unit="ms", utc=True)-midpoint).total_seconds()
    payload, receipt = feed.get("ticker/bookTicker", symbol="BTCUSDT")
    quote = observed_quote(payload, receipt, 3)
    now = utc_now().isoformat()
    forecast = {"forecast_id": f"{source['session_id']}:{row['id']}", "symbol": "BTCUSDT", "published_at": row["published_at_utc"],
                "expires_at": row["maturity_utc"], "reference_price": str(row["reference_close"]),
                "expected_return_fraction": str(math.expm1(json.loads(row["predictions_json"])["committee_mu"])),
                "uncertainty_fraction": None, "uncertainty_validation_id": None, "downside_fraction": None, "downside_validation_id": None} if row else None
    context = {"now": now, "clock_offset_seconds": str(offset), "forecast": forecast,
               "quote": {"symbol": "BTCUSDT", **{key: str(quote[key]) for key in ("bid", "ask", "bid_size", "ask_size")},
                         "requested_at": quote["request_started_utc"], "observed_at": quote["observed_at_utc"],
                         "round_trip_seconds": str(receipt["rtt_seconds"]), "receipt_sha256": receipt["sha256"]},
               "account": {"account_id": f"paper:{source['session_id']}:five_minute_only", "cash": str(account["cash"]),
                           "equity": str(account["cash"]+sum(position["quantity"] * quote["bid"] for position in positions)), "open_positions": len(positions)},
               "venue": {"symbol": "BTCUSDT", "trading_enabled": True, "spot_allowed": True,
                         "minimum_quantity": str(rules["min_qty"]), "maximum_quantity": str(rules["max_qty"]), "quantity_step": rules["step"],
                         "market_quantity_step": rules["market_step"], "minimum_notional": str(rules["min_notional"]), "maximum_notional": str(rules["max_notional"])},
               "permissions": {"mode": "paper", "paper_enabled": True, "kill_switch": (directory / "KILL").exists(), "side": "BUY", "instrument": "spot", "leverage": "1", "forced_paper_diagnostic": False}}
    configuration = json.loads(Path("configs/risk.json").read_text())
    decision = assess_payload(context, configuration)
    return {"schema_version": 1, "created_at_utc": now, "heartbeat_utc": now, "mode": "INDEPENDENT_PAPER_RISK_REVIEW", "pid": os.getpid(),
            "status": "complete", "worker_status": "running", "source_session_directory": source["session_directory"], "forecast_source": "fixed_equal_weight_baseline",
            "review_directory": str(directory), "live_trading_enabled": False, "submits_orders": False,
            "decision": decision, "context": context, "configuration": configuration,
            "interpretation": "This independent review does not alter already running paper experiments. Expert dispersion is not treated as validated predictive uncertainty. Missing validated downside and uncertainty must refuse a signal proposal."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch-minutes", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.watch_minutes <= 60:
        raise ValueError("Watch duration must be 0 through 60 minutes")
    directory = Path("data/risk") / utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    db = connect(directory / "reviews.sqlite3")
    deadline = time.monotonic() + args.watch_minutes * 60
    try:
        while True:
            started = time.monotonic()
            try:
                status = review(directory, db)
            except Exception as exc:
                status = {"schema_version": 1, "created_at_utc": utc_now().isoformat(), "heartbeat_utc": utc_now().isoformat(),
                          "mode": "INDEPENDENT_PAPER_RISK_REVIEW", "status": "unavailable", "pid": os.getpid(),
                          "review_directory": str(directory), "live_trading_enabled": False, "submits_orders": False,
                          "decision": {"allowed": False, "reasons": ["risk_review_inputs_unavailable"], "proposal": None}, "error": str(exc)}
            done = args.watch_minutes == 0 or time.monotonic() >= deadline or (directory/"STOP").exists()
            status["worker_status"] = "finished" if done else "running"
            write_json(directory / "latest.json", status)
            write_json(Path("data/manifests/risk_latest.json"), status)
            print(json.dumps({"time": status["created_at_utc"], "status": status["status"], "decision": status["decision"]}), flush=True)
            if done:
                break
            time.sleep(min(max(0, 20-(time.monotonic()-started)), max(0, deadline-time.monotonic())))
    finally:
        db.close()


if __name__ == "__main__":
    main()
