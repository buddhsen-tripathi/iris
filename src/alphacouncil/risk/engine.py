"""Pure, deterministic pre-trade assessment. No network or execution capability."""

import hashlib
import json
import math
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN

from .contracts import Proposal, RiskConfig, RiskContext, RiskDecision, json_value

D = Decimal
BPS = D("10000")


def fingerprint(value):
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _finite(*values):
    return all(isinstance(value, Decimal) and value.is_finite() for value in values)


def _aware(value):
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


def _common_step(*steps):
    """LCM of exact decimal grids, including non-nested venue lot grids."""
    scale = max(max(0, -step.as_tuple().exponent) for step in steps)
    multiplier = D(10) ** scale
    integers = [int(step * multiplier) for step in steps if step > 0]
    return D(math.lcm(*integers)) / multiplier


def assess(context: RiskContext, config: RiskConfig = RiskConfig()) -> RiskDecision:
    reasons = []
    permission = context.permissions
    if permission.mode != "paper":
        reasons.append("live_execution_unsupported")
    if not permission.paper_enabled:
        reasons.append("paper_permission_disabled")
    if permission.kill_switch:
        reasons.append("kill_switch_active")
    if permission.side != "BUY" or permission.instrument != "spot" or permission.leverage != D(1):
        reasons.append("only_long_spot_one_times_supported")
    if not _aware(context.now):
        reasons.append("aware_current_time_required")
    if context.clock_offset_seconds is None or not _finite(context.clock_offset_seconds):
        reasons.append("clock_measurement_required")
    elif abs(context.clock_offset_seconds) > config.maximum_clock_offset_seconds:
        reasons.append("clock_offset_exceeded")
    quote, account, venue, forecast = context.quote, context.account, context.venue, context.forecast
    if quote is None:
        reasons.append("quote_required")
    if account is None:
        reasons.append("account_required")
    if venue is None:
        reasons.append("venue_rules_required")
    if not permission.forced_paper_diagnostic and forecast is None:
        reasons.append("forecast_required")
    decimal_config = (config.maximum_entry_cost, config.maximum_planned_loss, config.maximum_account_loss_fraction,
                      config.fee_bps_per_side, config.slippage_bps_per_side, config.minimum_net_edge_bps,
                      config.maximum_uncertainty_fraction, config.maximum_spread_bps)
    if not _finite(*decimal_config) or any(value < 0 for value in decimal_config) or not (
        config.maximum_entry_cost > 0 and config.maximum_planned_loss > 0 and
        0 < config.maximum_account_loss_fraction <= 1 and config.fee_bps_per_side < BPS and
        config.slippage_bps_per_side < BPS and config.proposal_lifetime_seconds > 0 and
        config.maximum_quote_age_seconds > 0 and config.maximum_quote_rtt_seconds > 0 and
        config.maximum_clock_offset_seconds >= 0
    ):
        reasons.append("invalid_risk_configuration")
    if reasons:
        return RiskDecision(False, tuple(reasons))

    if not all(_aware(time) for time in (quote.requested_at, quote.observed_at)):
        reasons.append("aware_quote_times_required")
    else:
        age = D(str((context.now - quote.observed_at).total_seconds()))
        measured_rtt = D(str((quote.observed_at - quote.requested_at).total_seconds()))
        if age < 0 or age > config.maximum_quote_age_seconds:
            reasons.append("quote_stale_or_future")
        if measured_rtt < 0 or measured_rtt > config.maximum_quote_rtt_seconds:
            reasons.append("quote_request_latency_exceeded")
        if _finite(quote.round_trip_seconds) and abs(measured_rtt - quote.round_trip_seconds) > D("0.01"):
            reasons.append("quote_latency_inconsistent")
    if not _finite(quote.bid, quote.ask, quote.bid_size, quote.ask_size, quote.round_trip_seconds) or not (
        0 < quote.bid <= quote.ask and min(quote.bid_size, quote.ask_size) > 0 and
        0 <= quote.round_trip_seconds <= config.maximum_quote_rtt_seconds
    ):
        reasons.append("invalid_quote")
    if not quote.receipt_sha256 or len(quote.receipt_sha256) != 64 or any(character not in "0123456789abcdef" for character in quote.receipt_sha256.lower()):
        reasons.append("quote_receipt_required")
    if not _finite(account.cash, account.equity, account.reserved_cash, account.reserved_planned_loss) or min(
        account.cash, account.equity, account.reserved_cash, account.reserved_planned_loss
    ) < 0:
        reasons.append("invalid_account")
    if account.open_positions != 0:
        reasons.append("one_position_limit")
    if not account.account_id:
        reasons.append("account_identity_required")
    if not venue.trading_enabled or not venue.spot_allowed:
        reasons.append("venue_spot_unavailable")
    if quote.symbol != venue.symbol or (forecast is not None and forecast.symbol != quote.symbol):
        reasons.append("symbol_mismatch")
    if not _finite(venue.minimum_quantity, venue.maximum_quantity, venue.quantity_step,
                   venue.minimum_notional, venue.maximum_notional, venue.market_quantity_step) or not (
        0 <= venue.minimum_quantity <= venue.maximum_quantity and venue.maximum_quantity > 0 and
        venue.quantity_step > 0 and venue.market_quantity_step >= 0 and
        0 <= venue.minimum_notional <= venue.maximum_notional
    ):
        reasons.append("invalid_venue_rules")
    if not permission.forced_paper_diagnostic and forecast is not None:
        if not _aware(forecast.published_at) or not _aware(forecast.expires_at):
            reasons.append("aware_forecast_times_required")
        elif not forecast.published_at <= context.now < forecast.expires_at:
            reasons.append("forecast_future_or_expired")
        elif _aware(quote.requested_at) and quote.requested_at < forecast.published_at:
            reasons.append("quote_predates_forecast")
        if not forecast.forecast_id or not _finite(forecast.reference_price, forecast.expected_return_fraction) or not (
            forecast.reference_price > 0 and forecast.expected_return_fraction > -1
        ):
            reasons.append("invalid_forecast")
        if forecast.uncertainty_fraction is None or not forecast.uncertainty_validation_id:
            reasons.append("validated_uncertainty_required")
        elif not _finite(forecast.uncertainty_fraction) or not 0 <= forecast.uncertainty_fraction <= config.maximum_uncertainty_fraction:
            reasons.append("uncertainty_exceeded_or_invalid")
        if forecast.downside_fraction is None or not forecast.downside_validation_id:
            reasons.append("validated_independent_downside_required")
        elif not _finite(forecast.downside_fraction) or not 0 < forecast.downside_fraction <= 1:
            reasons.append("invalid_downside_bound")
        elif forecast.downside_validation_id == forecast.uncertainty_validation_id:
            reasons.append("separate_downside_validation_required")
    if reasons:
        return RiskDecision(False, tuple(reasons))

    spread_bps = (quote.ask - quote.bid) / ((quote.ask + quote.bid) / 2) * BPS
    if spread_bps > config.maximum_spread_bps:
        return RiskDecision(False, ("spread_limit_exceeded",))
    fee, slip = config.fee_bps_per_side / BPS, config.slippage_bps_per_side / BPS
    entry_unit = quote.ask * (1 + slip) * (1 + fee)
    diagnostic = permission.forced_paper_diagnostic
    # Signal downside is a validated scenario, never a guaranteed market loss cap.
    # Diagnostic explicitly assumes complete loss of the position (no model input).
    downside = D(1) if diagnostic else forecast.downside_fraction
    downside_exit_price = quote.bid * (1 - downside)
    downside_proceeds_unit = downside_exit_price * (1 - slip) * (1 - fee)
    loss_per_unit = max(D(0), entry_unit - downside_proceeds_unit)
    available_cash = account.cash - account.reserved_cash
    loss_budget = min(config.maximum_planned_loss, account.equity * config.maximum_account_loss_fraction) - account.reserved_planned_loss
    if available_cash <= 0:
        reasons.append("insufficient_available_cash")
    if loss_budget <= 0:
        reasons.append("planned_loss_budget_exhausted")
    if reasons:
        return RiskDecision(False, tuple(reasons))
    cap = min(config.maximum_entry_cost, available_cash)
    unrounded = min(cap / entry_unit, loss_budget / loss_per_unit, venue.maximum_quantity,
                    venue.maximum_notional / (quote.ask * (1 + slip)), quote.ask_size, quote.bid_size)
    step = _common_step(venue.quantity_step, venue.market_quantity_step)
    quantity = (unrounded / step).to_integral_value(rounding=ROUND_DOWN) * step
    notional = quantity * quote.ask * (1 + slip)
    if quantity <= 0 or quantity < venue.minimum_quantity or notional < venue.minimum_notional:
        return RiskDecision(False, ("size_below_venue_minimum_after_risk_caps",))
    net_edge = None
    if not diagnostic:
        expected_exit = forecast.reference_price * (1 + forecast.expected_return_fraction - forecast.uncertainty_fraction)
        # Carry observed spread into forecast exit; do not assume free midpoint execution.
        expected_exit *= quote.bid / ((quote.bid + quote.ask) / 2)
        net_edge = expected_exit * (1 - slip) * (1 - fee) / entry_unit - 1
        if net_edge <= config.minimum_net_edge_bps / BPS:
            return RiskDecision(False, ("net_edge_below_costs_uncertainty_and_buffer",), measurements=(("net_edge_fraction", str(net_edge)),))
    expires = context.now + timedelta(seconds=config.proposal_lifetime_seconds)
    if not diagnostic:
        expires = min(expires, forecast.expires_at)
    context_hash = fingerprint({"context": context, "configuration": config})
    proposal = Proposal(
        proposal_id=context_hash, created_at=context.now, expires_at=expires, mode="paper",
        strategy="forced_paper_diagnostic" if diagnostic else "validated_signal",
        account_id=account.account_id, symbol=quote.symbol, side="BUY", quantity=quantity,
        entry_price_with_slippage=quote.ask * (1 + slip), entry_cost_including_fee=quantity * entry_unit,
        planned_loss_including_costs=quantity * loss_per_unit,
        planned_loss_basis="complete_position_loss" if diagnostic else forecast.downside_validation_id,
        net_edge_after_uncertainty_fraction=net_edge, forecast_id=None if diagnostic else forecast.forecast_id,
        quote_receipt_sha256=quote.receipt_sha256, context_sha256=context_hash,
    )
    return RiskDecision(True, ("paper_proposal_ready_for_review",), proposal,
                        (("spread_bps", str(spread_bps)), ("available_loss_budget", str(loss_budget))))
