"""Read-only, same-origin API over paper ledgers. No exchange credentials or orders."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from alphacouncil.api.knowledge import knowledge_router

Mode = Literal["model", "forced"]
EXPERTS = ("lightgbm", "ridge", "kalman", "mean_reversion", "momentum")
STATIC = Path(__file__).parent / "static"


def utc_now():
    return datetime.now(timezone.utc)


def age_seconds(value, now=None):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return round(((now or utc_now()) - stamp).total_seconds(), 3)
    except (ValueError, TypeError):
        return None


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def safe_path(self, value):
        path = (self.root / str(value)).resolve()
        if not path.is_relative_to(self.root):
            raise HTTPException(503, "Configured data path is outside the workspace")
        return path

    def manifest(self, name):
        path = self.root / "data" / "manifests" / f"{name}_latest.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            raise HTTPException(503, f"{name} snapshot is temporarily unavailable")

    def session(self, mode):
        return self.manifest("forward" if mode == "model" else "forced")

    @contextmanager
    def database(self, mode):
        manifest = self.session(mode)
        if not manifest or not manifest.get("session_directory"):
            yield None
            return
        path = self.safe_path(manifest["session_directory"]) / "ledger.sqlite3"
        if not path.is_file():
            yield None
            return
        db = None
        try:
            # mode=ro and query_only prevent accidental writes; BEGIN pins one consistent snapshot.
            db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            yield db
        except sqlite3.Error:
            raise HTTPException(503, "Paper ledger is temporarily unavailable")
        finally:
            if db is not None:
                db.close()

    def freshness(self, manifest):
        if not manifest:
            return {"status": "unavailable", "heartbeat_age_seconds": None, "stale": True}
        age = age_seconds(manifest.get("heartbeat_utc"))
        threshold = max(45, manifest.get("config", {}).get("poll_seconds", 10) * 3)
        active = manifest.get("status") in ("running", "starting", "draining")
        return {"status": manifest.get("status", "unknown"), "heartbeat_utc": manifest.get("heartbeat_utc"),
                "heartbeat_age_seconds": age, "stale": age is None or age < -5 or age > threshold,
                "active": active, "warning": "Heartbeat stale; displayed records are historical" if active and (age is None or age > threshold) else None}

    def quote(self, db, manifest):
        if db is None:
            return None
        row = db.execute("SELECT receipt_json FROM requests WHERE receipt_json LIKE '%ticker/bookTicker%' ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        receipt = json.loads(row[0])
        raw = self.safe_path(str(Path(manifest["session_directory"]) / receipt["path"]))
        if not raw.is_file():
            return None
        try:
            payload = json.loads(raw.read_text())
            bid, ask = float(payload["bidPrice"]), float(payload["askPrice"])
        except (ValueError, KeyError, TypeError):
            return None
        rtt = receipt.get("rtt_seconds")
        if not all(math.isfinite(value) for value in (bid, ask)) or not 0 < bid <= ask:
            return None
        if not isinstance(rtt, (int, float)) or not math.isfinite(rtt) or not 0 <= rtt <= 3:
            return None
        age = age_seconds(receipt.get("observed_at_utc"))
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2, "spread_bps": (ask / bid - 1) * 10000,
                "observed_at_utc": receipt.get("observed_at_utc"), "receipt_age_seconds": age,
                "rtt_seconds": receipt.get("rtt_seconds"), "stale": age is None or age < -5 or age > 30,
                "exchange_event_time_available": False, "receipt_sha256": receipt.get("sha256")}


def decode_row(row):
    result = dict(row)
    for key in tuple(result):
        if key.endswith("_json"):
            try:
                result[key[:-5]] = json.loads(result.pop(key)) if result[key] is not None else None
            except (ValueError, TypeError):
                result[key[:-5]] = None
    return result


def create_app(root=None):
    store = Store(root or Path.cwd())
    app = FastAPI(title="Iris paper observatory", version="0.1.0", docs_url="/api/docs")
    app.state.store = store
    app.include_router(knowledge_router(store.root))

    @app.middleware("http")
    async def local_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "read_only": True, "live_trading_enabled": False, "server_time_utc": utc_now().isoformat()}

    @app.get("/api/v1/overview")
    def overview():
        sessions = {}
        for mode in ("model", "forced"):
            manifest = store.session(mode)
            with store.database(mode) as db:
                counts = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("forecasts", "outcomes", "decisions", "positions")} if db else {}
                sessions[mode] = {"session_id": (manifest or {}).get("session_id"), "freshness": store.freshness(manifest),
                    "counts": counts, "quote": store.quote(db, manifest), "started_at_utc": (manifest or {}).get("started_at_utc"),
                    "stop_at_utc": (manifest or {}).get("entry_until_utc", (manifest or {}).get("forecast_until_utc")),
                    "config": (manifest or {}).get("config", {}), "recent_events": (manifest or {}).get("recent_events", [])}
        adaptive = store.manifest("committee")
        return clean({"as_of_utc": utc_now().isoformat(), "sessions": sessions, "adaptive": adaptive,
                      "live_trading_enabled": False, "disclaimer": "Simulated portfolios. Forced entries ignore model signals. Forecast dispersion is not calibrated confidence."})

    def valid_symbol(symbol):
        if symbol != "BTCUSDT":
            raise HTTPException(404, "Only BTCUSDT is available")

    @app.get("/api/v1/market/{symbol}/candles")
    @app.get("/market/{symbol}/candles", include_in_schema=False)
    def candles(symbol: str, limit: int = Query(72, ge=1, le=500)):
        valid_symbol(symbol)
        with store.database("model") as db:
            rows = db.execute("SELECT close_time_utc,close,observed_at_utc FROM candles WHERE symbol=? AND interval='5m' ORDER BY close_time_utc DESC LIMIT ?", (symbol, limit)).fetchall() if db else []
        return {"symbol": symbol, "interval": "5m", "available_fields": ["close"], "candles": [dict(row) for row in reversed(rows)], "note": "Ledger stores completed candle closes, not OHLC; displayed as a line."}

    @app.get("/api/v1/forecasts/{symbol}")
    @app.get("/forecasts/{symbol}", include_in_schema=False)
    def forecasts(symbol: str, limit: int = Query(90, ge=1, le=500)):
        valid_symbol(symbol)
        with store.database("model") as db:
            rows = db.execute("SELECT f.*,o.observed_at_utc AS outcome_observed_at_utc,o.actual_close,o.actual_log_return FROM forecasts f LEFT JOIN outcomes o ON o.forecast_id=f.id ORDER BY f.id DESC LIMIT ?", (limit,)).fetchall() if db else []
        return clean({"symbol": symbol, "forecasts": [decode_row(row) for row in rows]})

    @app.get("/api/v1/committee/{symbol}/latest")
    @app.get("/committee/{symbol}/latest", include_in_schema=False)
    def committee(symbol: str):
        valid_symbol(symbol)
        forward, shadow = store.session("model") or {}, store.manifest("committee")
        return clean({"fixed_weights": {expert: .2 for expert in EXPERTS}, "fixed_forecasts": forward.get("latest_forecasts", []),
                      "adaptive": shadow, "adaptive_freshness": store.freshness(shadow), "mode": "shadow_only", "live_trading_enabled": False})

    @app.get("/api/v1/committee/{symbol}/weights/history")
    @app.get("/committee/{symbol}/weights/history", include_in_schema=False)
    def weight_history(symbol: str, limit: int = Query(100, ge=1, le=500)):
        valid_symbol(symbol)
        shadow = store.manifest("committee")
        if not shadow or not shadow.get("shadow_session_directory"):
            return {"updates": [], "available": False}
        path = store.safe_path(shadow["shadow_session_directory"]) / "committee.sqlite"
        if not path.is_file():
            return {"updates": [], "available": False}
        try:
            with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                rows = db.execute("SELECT horizon,applied_at_utc,weights_after_json,update_count,source_forecast_id FROM updates ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
            return {"available": True, "updates": [decode_row(row) for row in rows]}
        except sqlite3.Error:
            raise HTTPException(503, "Committee history is temporarily unavailable")

    @app.get("/api/v1/decisions")
    @app.get("/decisions", include_in_schema=False)
    def decisions(mode: Mode = "model", limit: int = Query(100, ge=1, le=500)):
        with store.database(mode) as db:
            rows = db.execute("SELECT d.*,p.id AS position_id,p.entry_price,p.exit_price,p.net_pnl FROM decisions d LEFT JOIN positions p ON p.policy=d.policy AND p.entry_utc=d.time_utc ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall() if db else []
        return clean({"mode": mode, "decisions": [decode_row(row) for row in rows]})

    @app.get("/api/v1/decisions/{decision_id}/autopsy")
    @app.get("/decisions/{decision_id}/autopsy", include_in_schema=False)
    def autopsy(decision_id: int, mode: Mode = "model"):
        with store.database(mode) as db:
            row = db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone() if db else None
            if row is None:
                raise HTTPException(404, "Decision not found in this paper mode")
            decision = decode_row(row)
            position = db.execute("SELECT * FROM positions WHERE policy=? AND entry_utc=?", (row["policy"], row["time_utc"])).fetchone()
            forecast = db.execute("SELECT * FROM forecasts WHERE id=?", (row["forecast_id"],)).fetchone() if row["forecast_id"] else None
        manifest = store.session(mode) or {}
        trade = decode_row(position) if position else None
        fee = manifest.get("config", {}).get("fee_bps_per_side_assumed", 0) / 10000
        if trade:
            trade["entry_fee_usdt_assumed"] = trade["quantity"] * trade["entry_price"] * fee
            trade["exit_fee_usdt_assumed"] = trade["quantity"] * trade["exit_price"] * fee if trade["exit_price"] else None
        return clean({"mode": mode, "decision": decision, "position": trade, "forecast": decode_row(forecast) if forecast else None,
                      "cost_assumptions": manifest.get("config", {}), "execution": "Observed quotes with assumed fees and slippage. No exchange fill."})

    @app.get("/api/v1/performance")
    @app.get("/performance", include_in_schema=False)
    def performance(mode: Mode = "model"):
        manifest = store.session(mode) or {}
        with store.database(mode) as db:
            accounts = [dict(row) for row in db.execute("SELECT * FROM accounts")] if db else []
            positions = [decode_row(row) for row in db.execute("SELECT * FROM positions ORDER BY id")] if db else []
        config = manifest.get("config", {})
        initial = config.get("initial_paper_cash_usdt", config.get("initial_paper_cash_usdt_per_policy", 50))
        series, results = [], []
        for account in accounts:
            trades = [row for row in positions if row["policy"] == account["policy"]]
            closed = sorted((row for row in trades if row["exit_utc"]), key=lambda row: row["exit_utc"])
            cumulative = 0
            for row in closed:
                cumulative += row["net_pnl"]
                series.append({"policy": account["policy"], "time_utc": row["exit_utc"], "realized_equity_usdt": initial + cumulative})
            results.append({**account, "initial_cash_usdt": initial, "realized_pnl_usdt": cumulative, "completed_trades": len(closed), "open_positions": len(trades)-len(closed)})
        return clean({"mode": mode, "simulated": True, "accounts": results, "realized_equity": series, "positions": positions[-100:],
                      "forecast_metrics": manifest.get("forecast_metrics", []), "liquidation_equity_usdt_estimate": manifest.get("liquidation_equity_usdt_estimate"),
                      "equity_quote_observed_at_utc": manifest.get("equity_quote_observed_at_utc"), "assumed_fees_paid_usdt": manifest.get("assumed_fees_paid_usdt"),
                      "assumed_slippage_cost_usdt": manifest.get("assumed_slippage_cost_usdt"), "freshness": store.freshness(manifest),
                      "note": "Realized equity excludes open positions. Mark-to-liquidation estimate, when supplied, uses the recorded quote timestamp."})

    @app.get("/api/v1/news/{symbol}")
    @app.get("/news/{symbol}", include_in_schema=False)
    def news(symbol: str):
        valid_symbol(symbol)
        return store.manifest("events") or store.manifest("news") or {"status": "unavailable", "articles": [], "note": "News ingestion is not configured; it does not influence forecasts."}

    @app.get("/api/v1/regime/latest")
    def regime_latest():
        return store.manifest("regime") or {"status": "unavailable", "conditional_weights_enabled": False}

    @app.get("/api/v1/risk/latest")
    def risk_latest():
        return store.manifest("risk") or {"status": "unavailable", "action": "HOLD", "note": "Independent risk review has not published a snapshot"}

    @app.get("/api/v1/venue/latest")
    def venue_latest():
        return store.manifest("venue") or {"status": "unavailable", "live_order_transport_implemented": False}

    @app.get("/api/v1/capabilities")
    @app.get("/capabilities", include_in_schema=False)
    def capabilities():
        return {"read_only": True, "paper_trading": True, "live_trading": False, "order_submission": False,
                "risk": {"status": "independent_engine_available_separately", "approvals": False},
                "news_influences_models": False, "adaptive_affects_execution": False,
                "data_sources": ["Binance public market data", "local prospective paper ledgers"], "refresh_seconds": 10}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
