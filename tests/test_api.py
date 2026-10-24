"""Read-only observatory contracts, validation, and unavailable data behavior."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from alphacouncil.api.app import Store, age_seconds, create_app


@pytest.fixture
def workspace(tmp_path):
    manifests = tmp_path / "data/manifests"
    manifests.mkdir(parents=True)
    session = tmp_path / "data/forward/test"
    session.mkdir(parents=True)
    db = sqlite3.connect(session / "ledger.sqlite3")
    db.executescript('''
    CREATE TABLE requests(id INTEGER PRIMARY KEY, observed_at_utc TEXT,receipt_json TEXT);
    CREATE TABLE candles(symbol TEXT,interval TEXT,close_time_utc TEXT,close TEXT,observed_at_utc TEXT);
    CREATE TABLE forecasts(id INTEGER PRIMARY KEY,anchor_utc TEXT,published_at_utc TEXT,horizon INTEGER,maturity_utc TEXT,reference_close REAL,publication_lag_seconds REAL,predictions_json TEXT,features_json TEXT);
    CREATE TABLE outcomes(forecast_id INTEGER PRIMARY KEY,observed_at_utc TEXT,actual_close REAL,actual_log_return REAL);
    CREATE TABLE accounts(policy TEXT,cash REAL);
    CREATE TABLE decisions(id INTEGER PRIMARY KEY,forecast_id INTEGER,policy TEXT,time_utc TEXT,action TEXT,reason TEXT,expected_net_return REAL,quote_json TEXT);
    CREATE TABLE positions(id INTEGER PRIMARY KEY,policy TEXT,forecast_id INTEGER,quantity REAL,entry_utc TEXT,due_utc TEXT,entry_price REAL,entry_cost REAL,entry_quote_json TEXT,exit_utc TEXT,exit_price REAL,exit_proceeds REAL,net_pnl REAL,exit_quote_json TEXT);
    ''')
    now = datetime.now(timezone.utc).isoformat()
    quote = {"bid": 99, "ask": 100, "observed_at_utc": now}
    raw = session / "raw/quote.json"
    raw.parent.mkdir()
    raw.write_text(json.dumps({"bidPrice": "99", "askPrice": "100"}))
    receipt = {"path": "raw/quote.json", "url": "https://data-api.binance.vision/api/v3/ticker/bookTicker?symbol=BTCUSDT", "observed_at_utc": now, "rtt_seconds": .2, "sha256": "abc"}
    db.execute("INSERT INTO requests VALUES (1,?,?)", (now, json.dumps(receipt)))
    db.execute("INSERT INTO accounts VALUES ('forced_long_20s',49.9)")
    db.execute("INSERT INTO candles VALUES ('BTCUSDT','5m',?,'100',?)", (now, now))
    predictions = {"experts": {"ridge": .001}, "committee_mu": .0002}
    db.execute("INSERT INTO forecasts VALUES (1,?,?,5,?,100,1,?,'{}')", (now,now,now,json.dumps(predictions)))
    db.execute("INSERT INTO decisions VALUES (1,NULL,'forced_long_20s',?,'PAPER_BUY','forced_entry_signal_ignored',NULL,?)", (now,json.dumps(quote)))
    db.execute("INSERT INTO positions VALUES (1,'forced_long_20s',NULL,.1,?,?,100,10.01,?,?,99,9.89,-.12,?)", (now,now,json.dumps(quote),now,json.dumps(quote)))
    db.commit();db.close()
    snapshot = {"session_id":"test", "session_directory":"data/forward/test", "status":"running", "heartbeat_utc":now, "started_at_utc":now, "config":{"initial_paper_cash_usdt":50,"fee_bps_per_side_assumed":10,"slippage_bps_per_side_assumed":2}}
    for name in ("forward", "forced"):
        (manifests / f"{name}_latest.json").write_text(json.dumps(snapshot))
    return tmp_path


def test_empty_workspace_is_honest(tmp_path):
    client=TestClient(create_app(tmp_path))
    assert client.get('/health').json()['live_trading_enabled'] is False
    overview=client.get('/api/v1/overview').json()
    assert overview['sessions']['model']['freshness']['status']=='unavailable'
    assert overview['sessions']['model']['quote'] is None
    assert client.get('/api/v1/forecasts/BTCUSDT').json()['forecasts']==[]
    assert client.get('/api/v1/performance').json()['accounts']==[]
    assert client.get('/api/v1/news/BTCUSDT').json()['status']=='unavailable'
    assert client.get('/api/v1/committee/BTCUSDT/weights/history').json()['available'] is False
    assert client.get('/api/v1/risk/latest').json()['action']=='HOLD'


def test_ledger_api_and_receipts(workspace):
    client=TestClient(create_app(workspace))
    overview=client.get('/api/v1/overview').json()
    assert overview['sessions']['forced']['quote']['mid']==99.5
    assert overview['sessions']['model']['counts']['forecasts']==1
    assert overview['sessions']['model']['freshness']['stale'] is False
    assert client.get('/api/v1/market/BTCUSDT/candles').json()['available_fields']==['close']
    assert client.get('/api/v1/forecasts/BTCUSDT').json()['forecasts'][0]['predictions']['committee_mu']==.0002
    autopsy=client.get('/api/v1/decisions/1/autopsy?mode=forced').json()
    assert autopsy['position']['entry_fee_usdt_assumed']==pytest.approx(.01)
    assert autopsy['forecast'] is None
    perf=client.get('/api/v1/performance?mode=forced').json()
    assert perf['realized_equity'][0]['realized_equity_usdt']==pytest.approx(49.88)
    assert perf['accounts'][0]['realized_pnl_usdt']==-.12


def test_validation_and_not_found(workspace):
    client=TestClient(create_app(workspace))
    assert client.get('/api/v1/market/ETHUSDT/candles').status_code==404
    assert client.get('/api/v1/forecasts/BTCUSDT?limit=501').status_code==422
    assert client.get('/api/v1/decisions?mode=real').status_code==422
    assert client.get('/api/v1/decisions/999/autopsy').status_code==404
    assert client.post('/api/v1/decisions').status_code==405
    assert client.get('/static/%2e%2e/app.py').status_code==404
    assert client.get('/unknown').status_code==404


def test_store_refuses_writes_and_escapes(workspace):
    store=Store(workspace)
    with store.database('model') as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM forecasts")
        assert db.execute('SELECT count(*) FROM forecasts').fetchone()[0]==1
    snapshot=workspace/'data/manifests/forward_latest.json'
    snapshot.write_text(json.dumps({'session_directory':'../../outside'}))
    assert TestClient(create_app(workspace)).get('/api/v1/overview').status_code==503


def test_freshness_and_invalid_snapshots(workspace):
    store=Store(workspace)
    old=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    assert store.freshness({'status':'running','heartbeat_utc':old})['stale'] is True
    assert store.freshness({'status':'running','heartbeat_utc':'invalid'})['stale'] is True
    assert age_seconds('2026-01-01T00:00:00') is None
    snapshot=workspace/'data/manifests/forward_latest.json'
    snapshot.write_text('{incomplete')
    assert TestClient(create_app(workspace)).get('/api/v1/overview').status_code==503


def test_static_security_headers(tmp_path):
    client=TestClient(create_app(tmp_path))
    response=client.get('/')
    assert response.status_code==200
    assert 'PAPER ONLY' in response.text
    assert response.headers['cache-control']=='no-store'
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert client.get('/static/app.js').status_code==200
    assert client.get('/static/style.css').status_code==200


def test_read_transaction_keeps_a_consistent_snapshot(workspace):
    path=workspace/'data/forward/test/ledger.sqlite3'
    writer=sqlite3.connect(path)
    writer.execute('PRAGMA journal_mode=WAL')
    with Store(workspace).database('model') as reader:
        assert reader.execute('SELECT count(*) FROM forecasts').fetchone()[0]==1
        writer.execute("INSERT INTO forecasts SELECT 2,anchor_utc,published_at_utc,horizon,maturity_utc,reference_close,publication_lag_seconds,predictions_json,features_json FROM forecasts WHERE id=1")
        writer.commit()
        assert reader.execute('SELECT count(*) FROM forecasts').fetchone()[0]==1
    writer.close()
    with Store(workspace).database('model') as reader:
        assert reader.execute('SELECT count(*) FROM forecasts').fetchone()[0]==2


@pytest.mark.parametrize('payload,rtt', [({'bidPrice':'0','askPrice':'1'},.1),({'bidPrice':'101','askPrice':'100'},.1),({'bidPrice':'NaN','askPrice':'100'},.1),({'bidPrice':'99','askPrice':'100'},float('nan')),({'bidPrice':'99','askPrice':'100'},4)])
def test_invalid_or_slow_quote_is_unavailable(workspace,payload,rtt):
    raw=workspace/'data/forward/test/raw/quote.json'
    raw.write_text(json.dumps(payload))
    path=workspace/'data/forward/test/ledger.sqlite3'
    with sqlite3.connect(path) as db:
        receipt=json.loads(db.execute('SELECT receipt_json FROM requests WHERE id=1').fetchone()[0])
        receipt['rtt_seconds']=rtt
        db.execute('UPDATE requests SET receipt_json=? WHERE id=1',(json.dumps(receipt),))
    response=TestClient(create_app(workspace)).get('/api/v1/overview')
    assert response.status_code==200
    assert response.json()['sessions']['model']['quote'] is None
