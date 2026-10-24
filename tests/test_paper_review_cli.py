"""CLI paper review transitions use fixture risk evidence, never real order calls."""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("paper_review_cli", Path(__file__).parents[1]/"scripts/paper_review.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
NOW = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    context = {
        "now": NOW.isoformat(), "clock_offset_seconds": "0.1",
        "quote": {"symbol":"BTCUSDT", "bid":"99.99", "ask":"100.01", "bid_size":"10", "ask_size":"10",
                  "requested_at":(NOW-timedelta(seconds=1)).isoformat(), "observed_at":NOW.isoformat(),
                  "round_trip_seconds":"1", "receipt_sha256":"a"*64},
        "account": {"account_id":"cli-fixture", "cash":"50", "equity":"50"},
        "venue": {"symbol":"BTCUSDT", "trading_enabled":True, "spot_allowed":True, "minimum_quantity":"0.001",
                  "maximum_quantity":"100", "quantity_step":"0.001", "minimum_notional":"5", "maximum_notional":"100000"},
        "forecast": {"forecast_id":"cli-forecast-fixture", "symbol":"BTCUSDT",
                     "published_at":(NOW-timedelta(seconds=2)).isoformat(), "expires_at":(NOW+timedelta(minutes=5)).isoformat(),
                     "reference_price":"100", "expected_return_fraction":"0.01", "uncertainty_fraction":"0.001",
                     "uncertainty_validation_id":"test-fixture-uncertainty", "downside_fraction":"0.04",
                     "downside_validation_id":"test-fixture-downside"},
    }
    path = tmp_path/"fresh_context.json"
    path.write_text(json.dumps(context))
    return {"context":context, "path":path, "ledger":tmp_path/"risk"/"ledger.sqlite3"}


def invoke(capsys, command, inputs, *args):
    argv = [command, "--ledger", str(inputs["ledger"])]
    if command in {"review", "propose", "submit"}:
        argv += ["--context", str(inputs["path"])]
    result = cli.main(argv+list(args))
    response = json.loads(capsys.readouterr().out)
    assert response["paper_only"] is True
    return result, response


def test_review_does_not_create_ledger_or_autoapprove(inputs, capsys):
    code, response = invoke(capsys, "review", inputs)
    assert code == 0
    assert response["persisted"] is response["approved"] is False
    assert response["review"]["allowed"]
    assert not inputs["ledger"].exists()
    code, response = invoke(capsys, "status", inputs)
    assert code == 0 and response["status"] == "ledger_not_created"
    assert not inputs["ledger"].exists()


def test_cli_explicit_propose_approve_submit_and_idempotency(inputs, capsys):
    code, response = invoke(capsys, "propose", inputs)
    assert code == 0
    assert response["approved"] is response["submitted"] is False
    proposal_id = response["review"]["proposal"]["proposal_id"]
    code, response = invoke(capsys, "submit", inputs, "--proposal-id", proposal_id)
    assert code == 2 and "approved proposal" in response["error"]
    code, response = invoke(capsys, "status", inputs, "--proposal-id", proposal_id)
    assert response["proposals"][0]["state"] == "awaiting_human_approval"
    code, response = invoke(capsys, "approve", inputs, "--proposal-id", proposal_id, "--reviewer", "local human")
    assert code == 0 and response["submitted"] is False
    code, response = invoke(capsys, "approve", inputs, "--proposal-id", proposal_id, "--reviewer", "local human")
    assert code == 2 and "already" in response["error"]
    code, first = invoke(capsys, "submit", inputs, "--proposal-id", proposal_id)
    assert code == 0 and first["receipt"]["paper_only"]
    code, second = invoke(capsys, "submit", inputs, "--proposal-id", proposal_id)
    assert code == 0 and first["receipt"] == second["receipt"]
    code, response = invoke(capsys, "status", inputs)
    assert response["proposal_count"] == 1
    assert response["accounts"][0]["open_positions"] == 1
    assert response["proposals"][0]["state"] == "submitted"


def test_approval_expiry_uses_process_clock_not_input_context(inputs, capsys, monkeypatch):
    _, response = invoke(capsys, "propose", inputs)
    proposal_id = response["review"]["proposal"]["proposal_id"]
    monkeypatch.setattr(cli, "utc_now", lambda: NOW+timedelta(seconds=20))
    code, response = invoke(capsys, "approve", inputs, "--proposal-id", proposal_id, "--reviewer", "human")
    assert code == 2 and "expiry" in response["error"]
    _, response = invoke(capsys, "status", inputs)
    assert response["proposals"][0]["state"] == "expired"


def test_submit_needs_fresh_context_and_refuses_live(inputs, capsys, monkeypatch):
    _, response = invoke(capsys, "propose", inputs)
    proposal_id = response["review"]["proposal"]["proposal_id"]
    invoke(capsys, "approve", inputs, "--proposal-id", proposal_id, "--reviewer", "human")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW+timedelta(seconds=4))
    code, response = invoke(capsys, "submit", inputs, "--proposal-id", proposal_id)
    assert code == 2 and "quote_stale_or_future" in response["review"]["reasons"]
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    inputs["context"]["permissions"] = {"mode":"live"}
    inputs["path"].write_text(json.dumps(inputs["context"]))
    code, response = invoke(capsys, "submit", inputs, "--proposal-id", proposal_id)
    assert code == 2 and "live_execution_unsupported" in response["review"]["reasons"]
    _, response = invoke(capsys, "status", inputs)
    assert response["accounts"][0]["cash"] == "50"


def test_missing_calibration_is_not_filled_in_by_cli(inputs, capsys):
    inputs["context"]["forecast"].pop("uncertainty_validation_id")
    inputs["context"]["forecast"].pop("downside_fraction")
    inputs["path"].write_text(json.dumps(inputs["context"]))
    code, response = invoke(capsys, "propose", inputs)
    assert code == 2
    assert "validated_uncertainty_required" in response["review"]["reasons"]
    assert "validated_independent_downside_required" in response["review"]["reasons"]
    assert not inputs["ledger"].exists()


def test_approval_requires_full_id_named_reviewer_and_existing_ledger(inputs, capsys):
    code, response = invoke(capsys, "approve", inputs, "--proposal-id", "abc", "--reviewer", "human")
    assert code == 2 and "64-character" in response["error"]
    code, response = invoke(capsys, "approve", inputs, "--proposal-id", "a"*64, "--reviewer", "human")
    assert code == 2 and "Existing proposal ledger" in response["error"]
    assert not inputs["ledger"].exists()
    _, response = invoke(capsys, "propose", inputs)
    proposal_id = response["review"]["proposal"]["proposal_id"]
    code, response = invoke(capsys, "approve", inputs, "--proposal-id", proposal_id, "--reviewer", " ")
    assert code == 2 and "Named reviewer" in response["error"]


def test_malformed_json_and_historical_now_cannot_authorize(inputs, capsys, monkeypatch):
    inputs["path"].write_text('{"now":"2026-10-24T18:00:00Z","now":"2026-10-24T18:00:00Z"}')
    code, response = invoke(capsys, "review", inputs)
    assert code == 2 and "Duplicate" in response["error"]
    inputs["path"].write_text(json.dumps(inputs["context"]))
    monkeypatch.setattr(cli, "utc_now", lambda: NOW+timedelta(seconds=10))
    code, response = invoke(capsys, "review", inputs)
    assert code == 2 and "quote_stale_or_future" in response["review"]["reasons"]


def test_cli_config_is_explicit_and_pinned(inputs, capsys, tmp_path):
    config = tmp_path/"risk.json"
    config.write_text('{"maximum_entry_cost":"8"}')
    _, response = invoke(capsys, "propose", inputs, "--risk-config", str(config))
    proposal_id = response["review"]["proposal"]["proposal_id"]
    invoke(capsys, "approve", inputs, "--proposal-id", proposal_id, "--reviewer", "human")
    code, response = invoke(capsys, "submit", inputs, "--proposal-id", proposal_id)
    assert code == 2 and "configuration changed" in response["error"]
    code, response = invoke(capsys, "submit", inputs, "--proposal-id", proposal_id, "--risk-config", str(config))
    assert code == 0


def test_argparse_requires_explicit_context_and_reviewer(inputs, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["review"])
    assert error.value.code == 2
    assert "--context" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        cli.main(["approve", "--proposal-id", "a"*64])
    assert error.value.code == 2
    assert "--reviewer" in capsys.readouterr().err
