"""Prospective forecasts and independent, quote-based paper accounts. No orders."""

import json
import math
import sqlite3
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pandas as pd

from alphacouncil.models.experts import forecast_metrics


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE requests(id INTEGER PRIMARY KEY, observed_at_utc TEXT, receipt_json TEXT);
        CREATE TABLE events(id INTEGER PRIMARY KEY, time_utc TEXT, kind TEXT, detail TEXT);
        CREATE TABLE candles(symbol TEXT, interval TEXT, close_time_utc TEXT, close TEXT,
            observed_at_utc TEXT, receipt_sha256 TEXT, PRIMARY KEY(symbol,interval,close_time_utc));
        CREATE TABLE forecasts(id INTEGER PRIMARY KEY, anchor_utc TEXT, published_at_utc TEXT,
            horizon INTEGER, maturity_utc TEXT, reference_close REAL, publication_lag_seconds REAL,
            predictions_json TEXT, features_json TEXT, UNIQUE(anchor_utc,horizon));
        CREATE TABLE outcomes(forecast_id INTEGER PRIMARY KEY REFERENCES forecasts(id),
            observed_at_utc TEXT, actual_close REAL, actual_log_return REAL);
        CREATE TABLE accounts(policy TEXT PRIMARY KEY, cash REAL);
        CREATE TABLE decisions(id INTEGER PRIMARY KEY, forecast_id INTEGER REFERENCES forecasts(id),
            policy TEXT, time_utc TEXT, action TEXT, reason TEXT, expected_net_return REAL, quote_json TEXT,
            UNIQUE(forecast_id,policy));
        CREATE TABLE positions(id INTEGER PRIMARY KEY, policy TEXT REFERENCES accounts(policy),
            forecast_id INTEGER REFERENCES forecasts(id), quantity REAL, entry_utc TEXT, due_utc TEXT,
            entry_price REAL, entry_cost REAL, entry_quote_json TEXT, exit_utc TEXT, exit_price REAL,
            exit_proceeds REAL, net_pnl REAL, exit_quote_json TEXT);
        CREATE UNIQUE INDEX one_open_position ON positions(policy) WHERE exit_utc IS NULL;
    """)
    return db


def event(db, now, kind, detail):
    db.execute("INSERT INTO events(time_utc,kind,detail) VALUES (?,?,?)", (pd.Timestamp(now).isoformat(), kind, str(detail)))
    db.commit()


def publish(db, anchor, now, started, predictions, features, reference, maximum_delay):
    """Commit every horizon before a quote can be requested or an outcome scored."""
    anchor, now, started = map(pd.Timestamp, (anchor, now, started))
    lag = (now - anchor).total_seconds()
    if anchor <= started or not 0 <= lag <= maximum_delay:
        raise ValueError("Historical, future or late forecast; cannot backfill forward results")
    if set(predictions) != {"5", "15", "30"} or not math.isfinite(reference) or reference <= 0:
        raise ValueError("Invalid forecast bundle/reference")
    with db:
        for horizon, prediction in predictions.items():
            # JSON forbids NaN/Infinity and pins all expert outputs and inference inputs.
            db.execute("""INSERT INTO forecasts(anchor_utc,published_at_utc,horizon,maturity_utc,
                reference_close,publication_lag_seconds,predictions_json,features_json) VALUES (?,?,?,?,?,?,?,?)""",
                (anchor.isoformat(), now.isoformat(), int(horizon), (anchor + pd.Timedelta(minutes=int(horizon))).isoformat(),
                 reference, lag, json.dumps(prediction, allow_nan=False), json.dumps(features, allow_nan=False)))
    return db.execute("SELECT id FROM forecasts WHERE anchor_utc=? AND horizon=5", (anchor.isoformat(),)).fetchone()[0]


def settle(db, prices: dict, observed_at):
    now = pd.Timestamp(observed_at)
    pending = db.execute("SELECT f.* FROM forecasts f LEFT JOIN outcomes o ON f.id=o.forecast_id WHERE o.forecast_id IS NULL").fetchall()
    with db:
        for row in pending:
            maturity = pd.Timestamp(row["maturity_utc"])
            if now < maturity or maturity not in prices:
                continue
            if pd.Timestamp(row["published_at_utc"]) >= maturity:
                raise ValueError("Forecast was not published before maturity")
            close = float(prices[maturity])
            if not math.isfinite(close) or close <= 0:
                raise ValueError("Invalid realized close")
            db.execute("INSERT INTO outcomes VALUES (?,?,?,?)", (row["id"], now.isoformat(), close, math.log(close / row["reference_close"])))


def symbol_rules(payload):
    symbols = payload.get("symbols", [])
    if len(symbols) != 1 or symbols[0]["symbol"] != "BTCUSDT" or symbols[0]["status"] != "TRADING" or not symbols[0].get("isSpotTradingAllowed"):
        raise ValueError("BTCUSDT spot trading rules unavailable")
    filters = {row["filterType"]: row for row in symbols[0]["filters"]}
    lot = filters["LOT_SIZE"]
    market = filters.get("MARKET_LOT_SIZE", {})
    notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
    if not notional or "minNotional" not in notional:
        raise ValueError("Missing minimum notional rule")
    return {"min_qty": max(float(lot["minQty"]), float(market.get("minQty", 0))),
            "max_qty": min(float(lot["maxQty"]), float(market.get("maxQty", lot["maxQty"]))),
            "step": lot["stepSize"], "market_step": market.get("stepSize", "0"),
            "min_notional": float(notional["minNotional"]), "max_notional": float(notional.get("maxNotional", "inf"))}


def quantity_for_budget(budget, price, fee, rules):
    quantity = Decimal(str(min(budget / (price * (1 + fee)), rules["max_qty"])))
    # Both venue lot grids must hold. Binance grids are powers of ten.
    step = max(Decimal(rules["step"]), Decimal(rules["market_step"]))
    if step <= 0:
        raise ValueError("Invalid lot step")
    quantity = (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step
    result = float(quantity)
    if result < rules["min_qty"] or not rules["min_notional"] <= result * price <= rules["max_notional"]:
        return 0.0
    return result


def execute_entries(db, forecast_id, quote, rules, config):
    forecast = db.execute("SELECT * FROM forecasts WHERE id=?", (forecast_id,)).fetchone()
    if forecast is None or forecast["horizon"] != 5:
        raise ValueError("An existing committed 5m forecast is required")
    observed = pd.Timestamp(quote["observed_at_utc"])
    if pd.Timestamp(quote["request_started_utc"]) < pd.Timestamp(forecast["published_at_utc"]):
        raise ValueError("Entry quote must be requested after forecast persistence")
    if observed >= pd.Timestamp(forecast["maturity_utc"]):
        raise ValueError("Cannot enter using an expired prediction")
    predictions = {row["horizon"]: json.loads(row["predictions_json"])["committee_mu"] for row in db.execute(
        "SELECT horizon,predictions_json FROM forecasts WHERE anchor_utc=?", (forecast["anchor_utc"],))}
    fee = config["fee_bps_per_side_assumed"] / 10000
    slip = config["slippage_bps_per_side_assumed"] / 10000
    entry = quote["ask"] * (1 + slip)
    mid = (quote["bid"] + quote["ask"]) / 2
    projected_bid = forecast["reference_close"] * math.exp(predictions[5]) * quote["bid"] / mid
    expected = projected_bid * (1 - slip) * (1 - fee) / (entry * (1 + fee)) - 1
    with db:
        for policy in config["policies"]:
            reason, action = "edge_below_costs_and_buffer", "HOLD"
            cash = db.execute("SELECT cash FROM accounts WHERE policy=?", (policy,)).fetchone()[0]
            open_position = db.execute("SELECT id FROM positions WHERE policy=? AND exit_utc IS NULL", (policy,)).fetchone()
            quantity = quantity_for_budget(min(cash, config["maximum_paper_cash_per_position_usdt"]), entry, fee, rules) if rules else 0
            if open_position:
                reason = "existing_position"
            elif rules is None:
                reason = "venue_rules_unavailable"
            elif quantity == 0:
                reason = "cash_or_venue_size_constraint"
            elif quote["ask_size"] < quantity:
                reason = "insufficient_observed_ask_size"
            elif policy == "with_15m_30m_confirmation" and not (predictions[15] > 0 and predictions[30] > 0):
                reason = "longer_horizons_do_not_confirm"
            elif expected > config["extra_edge_buffer_bps"] / 10000:
                action, reason = "PAPER_BUY", "cost_adjusted_edge"
                cost = quantity * entry * (1 + fee)
                db.execute("UPDATE accounts SET cash=cash-? WHERE policy=?", (cost, policy))
                db.execute("""INSERT INTO positions(policy,forecast_id,quantity,entry_utc,due_utc,entry_price,entry_cost,entry_quote_json)
                    VALUES (?,?,?,?,?,?,?,?)""", (policy, forecast_id, quantity, observed.isoformat(),
                    (observed + pd.Timedelta(minutes=config["paper_holding_minutes"])).isoformat(), entry, cost, json.dumps(quote)))
            db.execute("""INSERT INTO decisions(forecast_id,policy,time_utc,action,reason,expected_net_return,quote_json)
                VALUES (?,?,?,?,?,?,?)""", (forecast_id, policy, observed.isoformat(), action, reason, expected, json.dumps(quote)))


def exit_due(db, quote, config):
    """A late/missing exit stays open until a fresh quote arrives. Never backfill."""
    now = pd.Timestamp(quote["observed_at_utc"])
    request_time = pd.Timestamp(quote["request_started_utc"])
    fee, slip = config["fee_bps_per_side_assumed"] / 10000, config["slippage_bps_per_side_assumed"] / 10000
    with db:
        for row in db.execute("SELECT * FROM positions WHERE exit_utc IS NULL").fetchall():
            if request_time < pd.Timestamp(row["due_utc"]) or quote["bid_size"] < row["quantity"]:
                continue
            price = quote["bid"] * (1 - slip)
            proceeds = row["quantity"] * price * (1 - fee)
            db.execute("UPDATE positions SET exit_utc=?,exit_price=?,exit_proceeds=?,net_pnl=?,exit_quote_json=? WHERE id=?",
                       (now.isoformat(), price, proceeds, proceeds-row["entry_cost"], json.dumps(quote), row["id"]))
            db.execute("UPDATE accounts SET cash=cash+? WHERE policy=?", (proceeds, row["policy"]))


def summary(db):
    counts = {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("requests", "forecasts", "outcomes", "decisions", "positions")}
    counts["forecast_bundles"] = db.execute("SELECT count(DISTINCT anchor_utc) FROM forecasts").fetchone()[0]
    counts["pending_outcomes"] = counts["forecasts"] - counts["outcomes"]
    accounts = []
    for account in db.execute("SELECT * FROM accounts"):
        policy = account["policy"]
        positions = db.execute("SELECT * FROM positions WHERE policy=?", (policy,)).fetchall()
        accounts.append({**dict(account), "open_positions": sum(row["exit_utc"] is None for row in positions),
            "completed_trades": sum(row["exit_utc"] is not None for row in positions),
            "realized_pnl_usdt": sum(row["net_pnl"] or 0 for row in positions)})
    metrics = []
    for horizon in (5, 15, 30):
        rows = db.execute("SELECT predictions_json,actual_log_return FROM forecasts JOIN outcomes ON id=forecast_id WHERE horizon=?", (horizon,)).fetchall()
        if rows:
            actual = [row["actual_log_return"] for row in rows]
            for name in (*json.loads(rows[0]["predictions_json"])["experts"], "committee"):
                prediction = [json.loads(row["predictions_json"])["committee_mu"] if name == "committee" else json.loads(row["predictions_json"])["experts"][name] for row in rows]
                metrics.append({"horizon_minutes": horizon, "model": name, **forecast_metrics(actual, prediction)})
    latest = [dict(row) for row in db.execute("SELECT anchor_utc,published_at_utc,horizon,maturity_utc,publication_lag_seconds,predictions_json FROM forecasts WHERE anchor_utc=(SELECT max(anchor_utc) FROM forecasts) ORDER BY horizon")]
    for row in latest:
        row["predictions"] = json.loads(row.pop("predictions_json"))
    return {"counts": counts, "accounts": accounts, "forecast_metrics": metrics, "latest_forecasts": latest,
            "recent_events": [dict(row) for row in db.execute("SELECT time_utc,kind,detail FROM events ORDER BY id DESC LIMIT 5")]}
