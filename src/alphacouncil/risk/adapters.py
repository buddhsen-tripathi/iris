"""JSON boundary for local API/UI risk reviews; no inferred risk evidence."""

from dataclasses import fields
from datetime import datetime
from decimal import Decimal

from .contracts import Account, Forecast, Permissions, Quote, RiskConfig, RiskContext, RiskDecision, VenueRules
from .engine import assess


DECIMALS = {
    "reference_price", "expected_return_fraction", "uncertainty_fraction", "downside_fraction",
    "bid", "ask", "bid_size", "ask_size", "round_trip_seconds", "cash", "equity", "reserved_cash",
    "reserved_planned_loss", "minimum_quantity", "maximum_quantity", "quantity_step", "minimum_notional",
    "maximum_notional", "market_quantity_step", "leverage", "clock_offset_seconds",
    "maximum_entry_cost", "maximum_planned_loss", "maximum_account_loss_fraction", "fee_bps_per_side",
    "slippage_bps_per_side", "minimum_net_edge_bps", "maximum_uncertainty_fraction", "maximum_spread_bps",
}
TIMES = {"now", "published_at", "expires_at", "requested_at", "observed_at"}
BOOLEANS = {"trading_enabled", "spot_allowed", "paper_enabled", "kill_switch", "forced_paper_diagnostic"}
INTEGERS = {"open_positions", "maximum_quote_age_seconds", "maximum_quote_rtt_seconds", "maximum_clock_offset_seconds", "proposal_lifetime_seconds"}


def decode_contract(cls, payload):
    if not isinstance(payload, dict):
        raise ValueError("Contract must be a JSON object")
    allowed = {field.name for field in fields(cls)}
    if set(payload) - allowed:
        raise ValueError(f"Unknown {cls.__name__} fields")
    result = {}
    for key, value in payload.items():
        if value is None:
            result[key] = None
        elif key in DECIMALS:
            if isinstance(value, bool):
                raise ValueError("Boolean is not a decimal")
            result[key] = Decimal(str(value))
        elif key in TIMES:
            result[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif key in BOOLEANS:
            if type(value) is not bool:
                raise ValueError("Boolean contract field required")
            result[key] = value
        elif key in INTEGERS:
            if type(value) is not int:
                raise ValueError("Integer contract field required")
            result[key] = value
        else:
            if not isinstance(value, str):
                raise ValueError("String contract field required")
            result[key] = value
    return cls(**result)


def context_from_payload(payload):
    if not isinstance(payload, dict) or set(payload) - {"now", "clock_offset_seconds", "quote", "account", "venue", "forecast", "permissions"}:
        raise ValueError("Invalid risk context fields")
    return RiskContext(
        now=datetime.fromisoformat(payload["now"].replace("Z", "+00:00")),
        clock_offset_seconds=None if payload.get("clock_offset_seconds") is None else Decimal(str(payload["clock_offset_seconds"])),
        quote=decode_contract(Quote, payload["quote"]) if payload.get("quote") is not None else None,
        account=decode_contract(Account, payload["account"]) if payload.get("account") is not None else None,
        venue=decode_contract(VenueRules, payload["venue"]) if payload.get("venue") is not None else None,
        forecast=decode_contract(Forecast, payload["forecast"]) if payload.get("forecast") is not None else None,
        permissions=decode_contract(Permissions, payload.get("permissions", {})),
    )


def assess_payload(payload, configuration=None):
    """Return a JSON-safe refusal for malformed or absent inputs, never authorize by default."""
    try:
        return assess(context_from_payload(payload), decode_contract(RiskConfig, configuration or {})).to_dict()
    except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError):
        return RiskDecision(False, ("malformed_or_missing_risk_input",)).to_dict()
