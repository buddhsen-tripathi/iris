#!/usr/bin/env python3
"""Run a separate forced-entry, 20-second live-data paper experiment."""

import argparse
import json
import os
import signal
import time
from pathlib import Path

import pandas as pd

from alphacouncil.data.archive import file_sha256, utc_now, write_json
from alphacouncil.forward.feed import PublicFeed, observed_quote
from alphacouncil.forward.interval import claim, force_tick, initialize, interval_summary, next_slot
from alphacouncil.forward.ledger import connect, event, symbol_rules


def validate(config):
    if config["mode"] != "FORCED_ENTRY_PAPER_DIAGNOSTIC" or config["policy"] != "forced_long_20s" or config["interval_seconds"] != 20:
        raise ValueError("Only forced 20-second long-only paper mode is supported")
    for key, low, high in [("duration_minutes", 1, 60), ("exit_grace_seconds", 20, 180),
                           ("initial_paper_cash_usdt", 1, 50), ("maximum_paper_cash_per_position_usdt", 1, 10),
                           ("maximum_tick_delay_seconds", .1, 5), ("maximum_quote_rtt_seconds", .1, 3),
                           ("fee_bps_per_side_assumed", 0, 100), ("slippage_bps_per_side_assumed", 0, 100)]:
        if not low <= config[key] <= high:
            raise ValueError(f"Invalid bounded paper configuration: {key}")


def snapshot(session, manifest, db, config, quote):
    status = {**manifest, "heartbeat_utc": utc_now().isoformat(), **interval_summary(db, config, quote)}
    write_json(session / "status.json", status)
    write_json(Path("data/manifests/forced_latest.json"), status)
    equity = status["liquidation_equity_usdt_estimate"]
    lines = ["# Forced 20-second live-data paper experiment", "", f"Session `{manifest['session_id']}` — **{manifest['status']}**.", "",
             f"Updated {status['heartbeat_utc']}. PID {status['pid']}. Paper entry interval: **20 seconds**.", "",
             "This is forced long-only paper turnover, independent of the 5/15/30-minute model test. Entries ignore model signals and profitability thresholds. It does not measure a 20-second forecast model or a proven trading edge.", "",
             f"New entries end {manifest['entry_until_utc']}; final exit deadline {manifest['hard_stop_utc']}.", "",
             "| Measurement | Value |", "|---|---:|",
             f"| Paper entries | {status['paper_entries']} |", f"| Completed round trips | {status['completed_trades']} |",
             f"| Open positions | {status['open_positions']} |", f"| Cash (USDT) | {status['cash_usdt']:.6f} |",
             f"| Realized net P&L (USDT) | {status['realized_pnl_usdt']:.6f} |",
             f"| Estimated liquidation equity (USDT) | {f'{equity:.6f}' if equity is not None else 'Unavailable'} |",
             f"| Assumed fees paid (USDT) | {status['assumed_fees_paid_usdt']:.6f} |",
             f"| Assumed slippage cost (USDT) | {status['assumed_slippage_cost_usdt']:.6f} |", "",
             "Start cash: 50 USDT; total entry cost cap: 10 USDT; one position at a time. At each UTC 20-second boundary, request a new public quote, close the previous position at observed bid, then reopen at observed ask. Holding time is approximately 20 seconds and actual timestamps are retained. Add 10 bps assumed fees and 2 bps assumed slippage on each side. Fees/slippage are unverified assumptions. Cash excludes open inventory; estimated liquidation equity uses the last valid quote and assumed exit costs.", "",
             "Venue lot/minimum-notional rules and displayed size still apply. An invalid/missing quote or unexitable old position can prevent an entry. Late ticks are never backfilled; a delayed valid quote can still close an overdue position. At the deadline any unresolved position stays explicitly open. Quotes lack an exchange event timestamp; request/receipt times and response hashes are retained.", "",
             f"Raw responses and SQLite ledger: `{session}`. Log: `{manifest['log_path']}`.", "",
             "```sh", "uv run --group training python scripts/forward_status.py --forced", f"touch {session}/STOP  # stop entries and drain the open paper position", "```", "",
             "The Mac must remain awake and online. [Public market-data API](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only)."]
    Path("reports/forced_20s_paper_test.md").write_text("\n".join(lines) + "\n")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/forced_20s_paper.json"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate(config)
    latest = Path("data/manifests/forced_latest.json")
    if latest.exists():
        previous = json.loads(latest.read_text())
        if previous["status"] in {"starting", "running", "draining"}:
            try:
                os.kill(previous["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError("A forced-entry session is already active")
    started = pd.Timestamp(utc_now())
    session = Path("data/forward") / (started.strftime("%Y%m%dT%H%M%S%fZ") + "_forced_20s")
    session.mkdir(parents=True)
    db = connect(session / "ledger.sqlite3")
    initialize(db, config)
    first_tick = next_slot(started)
    cutoff = first_tick + pd.Timedelta(minutes=config["duration_minutes"])
    hard_stop = cutoff + pd.Timedelta(seconds=config["exit_grace_seconds"])
    manifest = {"session_id": session.name, "session_directory": str(session), "status": "starting", "pid": os.getpid(),
                "started_at_utc": started.isoformat(), "entry_until_utc": cutoff.isoformat(), "hard_stop_utc": hard_stop.isoformat(),
                "config": config, "config_sha256": file_sha256(args.config), "log_path": os.environ.get("ALPHACOUNCIL_FORWARD_LOG", "stdout"),
                "code_sha256": {str(p): file_sha256(p) for p in [Path(__file__).resolve().relative_to(Path.cwd()),
                                *sorted(Path("src/alphacouncil/forward").glob("*.py")), Path("uv.lock")]}}
    write_json(session / "config.json", config)
    quote = None
    snapshot(session, manifest, db, config, quote)
    signal.signal(signal.SIGTERM, lambda *_: (session / "STOP").touch())
    signal.signal(signal.SIGINT, lambda *_: (session / "STOP").touch())
    try:
        feed = PublicFeed(session, db)
        payload, receipt = feed.get("exchangeInfo", symbol="BTCUSDT")
        rules = symbol_rules(payload)
        manifest["exchange_rules_receipt_sha256"] = receipt["sha256"]
        manifest["status"] = "running"
        scheduled = next_slot(utc_now())
        last_snapshot = 0.
        while pd.Timestamp(utc_now()) < hard_stop:
            now = pd.Timestamp(utc_now())
            if (session / "STOP").exists() and manifest["status"] != "draining":
                cutoff = min(cutoff, now)
                hard_stop = min(hard_stop, now + pd.Timedelta(seconds=config["exit_grace_seconds"]))
                manifest.update(status="draining", entry_until_utc=cutoff.isoformat(), hard_stop_utc=hard_stop.isoformat())
                event(db, now, "stop_requested", "Drain existing paper position; no new entries")
            if now >= cutoff:
                manifest["status"] = "draining"
            if now < scheduled:
                if time.monotonic() - last_snapshot >= 5:
                    snapshot(session, manifest, db, config, quote)
                    last_snapshot = time.monotonic()
                time.sleep(min(1., (scheduled-now).total_seconds()))
                continue
            if claim(db, scheduled, now):
                try:
                    server, receipt = feed.get("time")
                    midpoint = pd.Timestamp(receipt["request_started_utc"]) + (pd.Timestamp(receipt["observed_at_utc"]) - pd.Timestamp(receipt["request_started_utc"])) / 2
                    offset = (pd.to_datetime(server["serverTime"], unit="ms", utc=True)-midpoint).total_seconds()
                    if abs(offset) > 5:
                        raise ValueError(f"Exchange/local clock offset too large: {offset}s")
                    manifest["clock_offset_seconds"] = offset
                    payload, receipt = feed.get("ticker/bookTicker", symbol="BTCUSDT")
                    fresh = observed_quote(payload, receipt, config["maximum_quote_rtt_seconds"])
                    quote = fresh
                    open_new = manifest["status"] == "running" and pd.Timestamp(fresh["observed_at_utc"]) < cutoff and not (session/"STOP").exists()
                    force_tick(db, scheduled, fresh, rules, config, open_new=open_new)
                    manifest["last_successful_tick_utc"] = utc_now().isoformat()
                    manifest.pop("last_error", None)
                    print(json.dumps({"tick": scheduled.isoformat(), "observed_at_utc": fresh["observed_at_utc"],
                                      "action": db.execute("SELECT detail FROM ticks WHERE scheduled_utc=?", (scheduled.isoformat(),)).fetchone()[0]}), flush=True)
                except Exception as error:
                    db.rollback()
                    with db:
                        db.execute("UPDATE ticks SET status='failed',detail=? WHERE scheduled_utc=?", (str(error), scheduled.isoformat()))
                    event(db, utc_now(), "tick_error", error)
                    manifest["last_error"] = str(error)
                    print(f"TICK_ERROR {utc_now().isoformat()} {error}", flush=True)
            status = snapshot(session, manifest, db, config, quote)
            last_snapshot = time.monotonic()
            if manifest["status"] == "draining" and status["open_positions"] == 0:
                break
            following = scheduled + pd.Timedelta(seconds=config["interval_seconds"])
            now = pd.Timestamp(utc_now())
            while following <= now:
                with db:
                    db.execute("INSERT OR IGNORE INTO ticks VALUES (?,?,?,?)", (following.isoformat(), now.isoformat(), "missed", "No catch-up entry"))
                following += pd.Timedelta(seconds=config["interval_seconds"])
            scheduled = following
        manifest["status"] = "completed" if interval_summary(db, config, quote)["open_positions"] == 0 else "stopped_with_open_position"
        manifest["finished_at_utc"] = utc_now().isoformat()
    except Exception as error:
        manifest.update(status="failed", last_error=str(error), finished_at_utc=utc_now().isoformat())
        event(db, utc_now(), "fatal_error", error)
        raise
    finally:
        snapshot(session, manifest, db, config, quote)
        db.close()


if __name__ == "__main__":
    main()
