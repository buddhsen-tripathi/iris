"""Immutable risk review contracts. Monetary quantities use Decimal, never float."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


def json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (datetime, Decimal)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class RiskConfig:
    maximum_entry_cost: Decimal = Decimal("10")
    maximum_planned_loss: Decimal = Decimal("0.50")
    maximum_account_loss_fraction: Decimal = Decimal("0.01")
    fee_bps_per_side: Decimal = Decimal("10")
    slippage_bps_per_side: Decimal = Decimal("2")
    minimum_net_edge_bps: Decimal = Decimal("2")
    maximum_uncertainty_fraction: Decimal = Decimal("0.05")
    maximum_spread_bps: Decimal = Decimal("25")
    maximum_quote_age_seconds: int = 3
    maximum_quote_rtt_seconds: int = 3
    maximum_clock_offset_seconds: int = 5
    proposal_lifetime_seconds: int = 20


@dataclass(frozen=True)
class Forecast:
    forecast_id: str
    symbol: str
    published_at: datetime
    expires_at: datetime
    reference_price: Decimal
    expected_return_fraction: Decimal
    # These are independently validated inputs, not expert disagreement proxies.
    uncertainty_fraction: Decimal | None = None
    uncertainty_validation_id: str | None = None
    downside_fraction: Decimal | None = None
    downside_validation_id: str | None = None


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    requested_at: datetime
    observed_at: datetime
    round_trip_seconds: Decimal
    receipt_sha256: str


@dataclass(frozen=True)
class Account:
    account_id: str
    cash: Decimal
    equity: Decimal
    open_positions: int = 0
    reserved_cash: Decimal = Decimal("0")
    reserved_planned_loss: Decimal = Decimal("0")


@dataclass(frozen=True)
class VenueRules:
    symbol: str
    trading_enabled: bool
    spot_allowed: bool
    minimum_quantity: Decimal
    maximum_quantity: Decimal
    quantity_step: Decimal
    minimum_notional: Decimal
    maximum_notional: Decimal
    market_quantity_step: Decimal = Decimal("0")


@dataclass(frozen=True)
class Permissions:
    mode: str = "paper"
    paper_enabled: bool = True
    kill_switch: bool = False
    side: str = "BUY"
    instrument: str = "spot"
    leverage: Decimal = Decimal("1")
    # Explicitly separate from signal trading; cannot authorize live submission.
    forced_paper_diagnostic: bool = False


@dataclass(frozen=True)
class RiskContext:
    now: datetime
    clock_offset_seconds: Decimal | None
    quote: Quote | None
    account: Account | None
    venue: VenueRules | None
    forecast: Forecast | None = None
    permissions: Permissions = Permissions()


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    created_at: datetime
    expires_at: datetime
    mode: str
    strategy: str
    account_id: str
    symbol: str
    side: str
    quantity: Decimal
    entry_price_with_slippage: Decimal
    entry_cost_including_fee: Decimal
    planned_loss_including_costs: Decimal
    planned_loss_basis: str
    net_edge_after_uncertainty_fraction: Decimal | None
    forecast_id: str | None
    quote_receipt_sha256: str
    context_sha256: str

    def to_dict(self):
        return json_value(self)


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]
    proposal: Proposal | None = None
    measurements: tuple[tuple[str, str], ...] = ()

    def to_dict(self):
        result = json_value(self)
        result["measurements"] = dict(self.measurements)
        return result
