"""Independent risk rules and local review transitions, without exchange requests."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from alphacouncil.risk import (Account, Forecast, PaperReviewLedger, Permissions, Quote, ReviewError,
                              RiskConfig, RiskContext, VenueRules, assess, assess_payload)
from alphacouncil.risk.contracts import json_value

D = Decimal
NOW = datetime(2026, 10, 24, 17, tzinfo=timezone.utc)


@pytest.fixture
def context():
    return RiskContext(
        now=NOW, clock_offset_seconds=D("0.1"),
        quote=Quote("BTCUSDT", D("99.99"), D("100.01"), D("10"), D("10"), NOW-timedelta(seconds=1), NOW,
                    D("1"), "a"*64),
        account=Account("paper-review", D("50"), D("50")),
        venue=VenueRules("BTCUSDT", True, True, D("0.001"), D("100"), D("0.001"), D("5"), D("100000")),
        forecast=Forecast("forecast-1", "BTCUSDT", NOW-timedelta(seconds=2), NOW+timedelta(minutes=5), D("100"), D("0.01"),
                          D("0.001"), "uncertainty-validation-1", D("0.04"), "independent-downside-1"),
    )


def test_cost_sizing_accounts_for_both_sides_and_keeps_caps(context):
    decision = assess(context)
    assert decision.allowed
    proposal = decision.proposal
    assert proposal.quantity == D("0.099")
    assert proposal.entry_cost_including_fee <= D("10")
    assert proposal.planned_loss_including_costs <= D("0.50")
    entry_unit = D("100.01") * D("1.0002") * D("1.001")
    downside_exit = D("99.99") * D("0.96") * D("0.9998") * D("0.999")
    assert proposal.planned_loss_including_costs == proposal.quantity * (entry_unit-downside_exit)
    assert proposal.entry_cost_including_fee == proposal.quantity * entry_unit
    assert assess(context).proposal == proposal
    assert proposal.to_dict()["quantity"] == "0.099"


def test_loss_budget_resizes_independently_of_notional(context):
    context = replace(context, forecast=replace(context.forecast, downside_fraction=D("0.08")))
    proposal = assess(context).proposal
    assert D("5") < proposal.entry_cost_including_fee < D("7")
    assert proposal.planned_loss_including_costs <= D("0.5")
    next_qty = proposal.quantity + D("0.001")
    assert proposal.planned_loss_including_costs / proposal.quantity * next_qty > D("0.5")


@pytest.mark.parametrize("field,value,reason", [
    ("uncertainty_fraction", None, "validated_uncertainty_required"),
    ("uncertainty_validation_id", None, "validated_uncertainty_required"),
    ("uncertainty_fraction", D("0.5"), "uncertainty_exceeded_or_invalid"),
    ("downside_fraction", None, "validated_independent_downside_required"),
    ("downside_validation_id", None, "validated_independent_downside_required"),
    ("downside_fraction", D("0"), "invalid_downside_bound"),
])
def test_missing_or_uncalibrated_signal_evidence_fails_closed(context, field, value, reason):
    result = assess(replace(context, forecast=replace(context.forecast, **{field:value})))
    assert not result.allowed
    assert reason in result.reasons


@pytest.mark.parametrize("change,reason", [
    ({"now": NOW+timedelta(seconds=4)}, "quote_stale_or_future"),
    ({"now": NOW-timedelta(seconds=1)}, "quote_stale_or_future"),
    ({"clock_offset_seconds": None}, "clock_measurement_required"),
    ({"clock_offset_seconds": D("6")}, "clock_offset_exceeded"),
    ({"quote": None}, "quote_required"),
    ({"venue": None}, "venue_rules_required"),
    ({"account": None}, "account_required"),
    ({"forecast": None}, "forecast_required"),
])
def test_current_inputs_required(context, change, reason):
    result = assess(replace(context, **change))
    assert not result.allowed
    assert reason in result.reasons


def test_live_kill_short_leverage_and_one_position_refused(context):
    for permissions, reason in [
        (Permissions(mode="live"), "live_execution_unsupported"),
        (Permissions(kill_switch=True), "kill_switch_active"),
        (Permissions(side="SELL"), "only_long_spot_one_times_supported"),
        (Permissions(leverage=D("2")), "only_long_spot_one_times_supported"),
        (Permissions(paper_enabled=False), "paper_permission_disabled"),
    ]:
        assert reason in assess(replace(context, permissions=permissions)).reasons
    assert "one_position_limit" in assess(replace(context, account=replace(context.account, open_positions=1))).reasons


def test_low_cash_and_reserved_loss_prevent_overcommitment(context):
    for account in [replace(context.account, cash=D("4")), replace(context.account, equity=D("10")),
                    replace(context.account, reserved_cash=D("48"))]:
        assert "size_below_venue_minimum_after_risk_caps" in assess(replace(context, account=account)).reasons
    assert "planned_loss_budget_exhausted" in assess(replace(context, account=replace(context.account, reserved_planned_loss=D("0.5")))).reasons


def test_non_nested_quantity_grids_use_exact_common_multiple(context):
    venue = replace(context.venue, quantity_step=D("0.003"), market_quantity_step=D("0.002"))
    quantity = assess(replace(context, venue=venue)).proposal.quantity
    assert quantity == D("0.096")
    assert quantity % D("0.003") == quantity % D("0.002") == 0


def test_expired_forecast_cannot_be_reused_and_quote_must_follow_publication(context):
    assert "forecast_future_or_expired" in assess(replace(context, forecast=replace(context.forecast, expires_at=NOW))).reasons
    assert "forecast_future_or_expired" in assess(replace(context, forecast=replace(context.forecast, published_at=NOW+timedelta(seconds=1)))).reasons
    assert "quote_predates_forecast" in assess(replace(context, forecast=replace(context.forecast, published_at=NOW))).reasons


def test_net_edge_includes_uncertainty_spread_and_two_sided_costs(context):
    forecast = replace(context.forecast, expected_return_fraction=D("0.003"))
    assert "net_edge_below_costs_uncertainty_and_buffer" in assess(replace(context, forecast=forecast)).reasons
    quote = replace(context.quote, bid=D("99"))
    assert "spread_limit_exceeded" in assess(replace(context, quote=quote)).reasons


def test_forced_diagnostic_can_never_authorize_live_and_uses_full_loss(context):
    permissions = Permissions(forced_paper_diagnostic=True)
    diagnostic = replace(context, forecast=None, permissions=permissions)
    # Conservative full-loss budget is below BTCUSDT minimum notional.
    assert "size_below_venue_minimum_after_risk_caps" in assess(diagnostic).reasons
    diagnostic = replace(diagnostic, venue=replace(diagnostic.venue, minimum_notional=D("0.1")))
    proposal = assess(diagnostic).proposal
    assert proposal.strategy == "forced_paper_diagnostic"
    assert proposal.planned_loss_basis == "complete_position_loss"
    assert proposal.entry_cost_including_fee == proposal.planned_loss_including_costs <= D("0.5")
    assert proposal.net_edge_after_uncertainty_fraction is None
    assert "live_execution_unsupported" in assess(replace(diagnostic, permissions=replace(permissions, mode="live"))).reasons


@pytest.mark.parametrize("payload", [{}, {"now":"not-a-time"}, {"permissions":{"kill_switch":"false"}}, None])
def test_json_boundary_refuses_malformed_input(payload):
    assert not assess_payload(payload)["allowed"]


def test_json_contract_roundtrip_and_nonfinite_refusal(context):
    assert assess_payload(json_value(context))["allowed"]
    payload = json_value(context)
    payload["quote"]["ask"] = "NaN"
    assert not assess_payload(payload)["allowed"]
    payload = json_value(context)
    payload["permissions"]["kill_switch"] = "false"
    assert not assess_payload(payload)["allowed"]


def test_downside_requires_separate_provenance_and_quote_receipt_is_hex(context):
    forecast = replace(context.forecast, downside_validation_id=context.forecast.uncertainty_validation_id)
    assert "separate_downside_validation_required" in assess(replace(context, forecast=forecast)).reasons
    assert "quote_receipt_required" in assess(replace(context, quote=replace(context.quote, receipt_sha256="z"*64))).reasons


def test_approval_requires_explicit_review_and_idempotent_submission(context, tmp_path):
    ledger = PaperReviewLedger(tmp_path/"review.sqlite3")
    ledger.initialize_account(context.account)
    proposal = ledger.propose(context).proposal
    assert ledger.propose(context).proposal == proposal
    with pytest.raises(ReviewError, match="approved"):
        ledger.submit_paper(proposal.proposal_id, context)
    ledger.approve(proposal.proposal_id, reviewer="local-human", now=NOW)
    with pytest.raises(ReviewError, match="already"):
        ledger.approve(proposal.proposal_id, reviewer="local-human", now=NOW)
    first = ledger.submit_paper(proposal.proposal_id, context)
    second = ledger.submit_paper(proposal.proposal_id, context)
    assert first == second
    stored = ledger.db.execute("SELECT * FROM risk_accounts").fetchone()
    assert Decimal(stored["cash"]) == D("50") - proposal.entry_cost_including_fee
    assert stored["open_positions"] == 1
    assert ledger.db.execute("SELECT COUNT(*) FROM risk_events WHERE kind='paper_filled'").fetchone()[0] == 1
    with pytest.raises(ReviewError, match="cannot be reset"):
        ledger.initialize_account(context.account)
    ledger.close()


def test_future_approval_expiry_kill_and_config_changes(context, tmp_path):
    ledger = PaperReviewLedger(tmp_path/"review.sqlite3")
    ledger.initialize_account(context.account)
    proposal = ledger.propose(context).proposal
    for when in [NOW-timedelta(seconds=1), NOW+timedelta(seconds=20)]:
        with pytest.raises(ReviewError, match="before proposal|expiry"):
            ledger.approve(proposal.proposal_id, reviewer="human", now=when)
    ledger.approve(proposal.proposal_id, reviewer="human", now=NOW+timedelta(seconds=1))
    with pytest.raises(ReviewError, match="future dated"):
        ledger.submit_paper(proposal.proposal_id, context)
    later = replace(context, now=NOW+timedelta(seconds=2))
    with pytest.raises(ReviewError, match="kill_switch"):
        ledger.submit_paper(proposal.proposal_id, replace(later, permissions=Permissions(kill_switch=True)))
    with pytest.raises(ReviewError, match="configuration changed"):
        ledger.submit_paper(proposal.proposal_id, later, replace(RiskConfig(), maximum_entry_cost=D("9")))
    with pytest.raises(ReviewError, match="expired"):
        ledger.submit_paper(proposal.proposal_id, replace(later, now=NOW+timedelta(seconds=20)))
    assert ledger.db.execute("SELECT cash FROM risk_accounts").fetchone()[0] == "50"
    ledger.close()


def test_changed_market_or_ledger_state_cannot_spend_old_approval(context, tmp_path):
    ledger = PaperReviewLedger(tmp_path/"review.sqlite3")
    ledger.initialize_account(context.account)
    proposal = ledger.propose(context).proposal
    ledger.approve(proposal.proposal_id, reviewer="human", now=NOW)
    moved = replace(context, quote=replace(context.quote, ask=D("100.02")))
    with pytest.raises(ReviewError, match="Cost|size cap"):
        ledger.submit_paper(proposal.proposal_id, moved)
    ledger.db.execute("UPDATE risk_accounts SET cash='40'")
    with pytest.raises(ReviewError, match="context differs"):
        ledger.submit_paper(proposal.proposal_id, context)
    ledger.close()
