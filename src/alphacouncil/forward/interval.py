"""Forced paper turnover on a fixed clock, separate from model performance."""

import json
import math

import pandas as pd

from alphacouncil.forward.ledger import quantity_for_budget


def next_slot(now, period=20):
    """Choose a future slot; missed slots never produce catch-up trades."""
    now = pd.Timestamp(now)
    return now.floor(f"{period}s") + pd.Timedelta(seconds=period)


def initialize(db, config):
    db.execute("CREATE TABLE ticks(scheduled_utc TEXT PRIMARY KEY, claimed_at_utc TEXT, status TEXT, detail TEXT)")
    db.execute("INSERT INTO accounts VALUES (?,?)", (config["policy"], config["initial_paper_cash_usdt"]))
    db.commit()


def claim(db, scheduled, now):
    with db:
        cursor = db.execute("INSERT OR IGNORE INTO ticks VALUES (?,?,?,?)", (pd.Timestamp(scheduled).isoformat(), pd.Timestamp(now).isoformat(), "pending", ""))
    return cursor.rowcount == 1


def force_tick(db, scheduled, quote, rules, config, open_new=True):
    scheduled = pd.Timestamp(scheduled)
    request, observed = pd.Timestamp(quote["request_started_utc"]), pd.Timestamp(quote["observed_at_utc"])
    tick = db.execute("SELECT status FROM ticks WHERE scheduled_utc=?", (scheduled.isoformat(),)).fetchone()
    if tick is None:
        raise ValueError("Persist a scheduled tick before requesting the quote")
    if tick[0] != "pending":
        return False
    if not scheduled <= request <= observed:
        raise ValueError("Quote must be requested at/after the scheduled tick")
    if not all(math.isfinite(quote[key]) for key in ("bid", "ask", "bid_size", "ask_size")) or not 0 < quote["bid"] <= quote["ask"] or min(quote["bid_size"], quote["ask_size"]) <= 0:
        raise ValueError("Invalid paper execution quote")
    fee, slip = config["fee_bps_per_side_assumed"] / 10000, config["slippage_bps_per_side_assumed"] / 10000
    policy = config["policy"]
    with db:
        position = db.execute("SELECT * FROM positions WHERE policy=? AND exit_utc IS NULL", (policy,)).fetchone()
        if position and request >= pd.Timestamp(position["due_utc"]) and quote["bid_size"] >= position["quantity"]:
            price = quote["bid"] * (1 - slip)
            proceeds = position["quantity"] * price * (1 - fee)
            db.execute("UPDATE positions SET exit_utc=?,exit_price=?,exit_proceeds=?,net_pnl=?,exit_quote_json=? WHERE id=?",
                       (observed.isoformat(), price, proceeds, proceeds-position["entry_cost"], json.dumps(quote), position["id"]))
            db.execute("UPDATE accounts SET cash=cash+? WHERE policy=?", (proceeds, policy))
            position = None
        action, reason = "HOLD", "session_draining"
        if position:
            reason = "previous_position_not_exitable"
        elif open_new:
            if (observed - scheduled).total_seconds() > config["maximum_tick_delay_seconds"]:
                reason = "late_tick_no_backfill"
            elif rules is None:
                reason = "venue_rules_unavailable"
            else:
                cash = db.execute("SELECT cash FROM accounts WHERE policy=?", (policy,)).fetchone()[0]
                entry = quote["ask"] * (1 + slip)
                quantity = quantity_for_budget(min(cash, config["maximum_paper_cash_per_position_usdt"]), entry, fee, rules)
                if quantity == 0:
                    reason = "cash_or_venue_size_constraint"
                elif quote["ask_size"] < quantity:
                    reason = "insufficient_observed_ask_size"
                else:
                    action, reason = "PAPER_BUY", "forced_entry_signal_ignored"
                    cost = quantity * entry * (1 + fee)
                    db.execute("UPDATE accounts SET cash=cash-? WHERE policy=?", (cost, policy))
                    db.execute("""INSERT INTO positions(policy,forecast_id,quantity,entry_utc,due_utc,entry_price,entry_cost,entry_quote_json)
                        VALUES (?,NULL,?,?,?,?,?,?)""", (policy, quantity, observed.isoformat(),
                        (scheduled + pd.Timedelta(seconds=config["interval_seconds"])).isoformat(), entry, cost, json.dumps(quote)))
        db.execute("INSERT INTO decisions(forecast_id,policy,time_utc,action,reason,expected_net_return,quote_json) VALUES (NULL,?,?,?,?,NULL,?)",
                   (policy, observed.isoformat(), action, reason, json.dumps(quote)))
        db.execute("UPDATE ticks SET status='processed',detail=? WHERE scheduled_utc=?", (f"{action}: {reason}", scheduled.isoformat()))
    return True


def interval_summary(db, config, quote=None):
    positions = db.execute("SELECT * FROM positions ORDER BY id").fetchall()
    closed = [row for row in positions if row["exit_utc"] is not None]
    active = [row for row in positions if row["exit_utc"] is None]
    cash = db.execute("SELECT cash FROM accounts WHERE policy=?", (config["policy"],)).fetchone()[0]
    fee, slip = config["fee_bps_per_side_assumed"] / 10000, config["slippage_bps_per_side_assumed"] / 10000
    fees = sum(row["quantity"] * row["entry_price"] * fee for row in positions) + sum(row["quantity"] * row["exit_price"] * fee for row in closed)
    slippage = sum(row["quantity"] * (row["entry_price"] - json.loads(row["entry_quote_json"])["ask"]) for row in positions)
    slippage += sum(row["quantity"] * (json.loads(row["exit_quote_json"])["bid"] - row["exit_price"]) for row in closed)
    equity = cash if not active else cash + sum(row["quantity"] * quote["bid"] * (1-slip) * (1-fee) for row in active) if quote else None
    return {"paper_entries": len(positions), "completed_trades": len(closed), "open_positions": len(active), "cash_usdt": cash,
            "realized_pnl_usdt": sum(row["net_pnl"] for row in closed), "liquidation_equity_usdt_estimate": equity,
            "equity_quote_observed_at_utc": quote["observed_at_utc"] if quote else None,
            "assumed_fees_paid_usdt": fees, "assumed_slippage_cost_usdt": slippage,
            "wins": sum(row["net_pnl"] > 0 for row in closed),
            "mean_actual_holding_seconds": sum((pd.Timestamp(row["exit_utc"])-pd.Timestamp(row["entry_utc"])).total_seconds() for row in closed)/len(closed) if closed else None,
            "tick_status_counts": {row[0]: row[1] for row in db.execute("SELECT status,count(*) FROM ticks GROUP BY status")},
            "decision_reasons": {row[0]: row[1] for row in db.execute("SELECT reason,count(*) FROM decisions GROUP BY reason")},
            "latest_trades": [dict(row) for row in positions[-5:]],
            "recent_events": [dict(row) for row in db.execute("SELECT time_utc,kind,detail FROM events ORDER BY id DESC LIMIT 5")]}
