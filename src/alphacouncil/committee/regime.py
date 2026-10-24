"""Optional causal regime context and past-observation bucket shrinkage.

No fitted thresholds, learning, trading or modification of the active committee.
"""

import math
from collections.abc import Mapping

from alphacouncil.committee.online import timestamp

REGIME_FEATURES = ("return_60m", "realized_vol_48", "vol_ratio_12_48")


def classify_regime(features: Mapping, source_anchor_utc, observed_at_utc, as_of_utc, config: Mapping, *, completed=True):
    """Use one already observed completed feature row; reject future context."""
    anchor, observed, now = map(timestamp, (source_anchor_utc, observed_at_utc, as_of_utc))
    if not completed or not anchor <= observed <= now:
        raise ValueError("Regime features must be completed and already observed as of the decision")
    values = {name: float(features[name]) for name in REGIME_FEATURES}
    if not all(math.isfinite(value) for value in values.values()) or values["realized_vol_48"] < 0 or values["vol_ratio_12_48"] < 0:
        raise ValueError("Finite features and nonnegative volatility are required")
    keys = ("high_vol_4h_log_return_threshold", "high_vol_short_long_ratio_threshold",
            "trend_minimum_absolute_60m_log_return", "trend_minimum_normalized_strength", "trend_60m_vol_scale")
    thresholds = {name: float(config[name]) for name in keys}
    if not all(math.isfinite(value) and value > 0 for value in thresholds.values()):
        raise ValueError("Positive finite fixed thresholds are required")
    trend_strength = abs(values["return_60m"]) / max(values["realized_vol_48"]*thresholds["trend_60m_vol_scale"], 1e-12)
    if values["realized_vol_48"] >= thresholds["high_vol_4h_log_return_threshold"] or values["vol_ratio_12_48"] >= thresholds["high_vol_short_long_ratio_threshold"]:
        label = "high_vol"
    elif abs(values["return_60m"]) >= thresholds["trend_minimum_absolute_60m_log_return"] and trend_strength >= thresholds["trend_minimum_normalized_strength"]:
        label = "trend"
    else:
        label = "range"
    direction = "up" if values["return_60m"] > 0 else "down" if values["return_60m"] < 0 else "flat"
    return {"schema_version": 1, "as_of_utc": now.isoformat(), "source_anchor_utc": anchor.isoformat(),
            "source_observed_at_utc": observed.isoformat(), "regime": label, "features": values,
            "diagnostics": {"trend_strength": trend_strength, "trend_direction": direction},
            "thresholds": thresholds, "conditional_weights_enabled": False,
            "note": "Fixed causal research context only; no validated gain or automatic change to active global weights."}


def _validated_weights(weights):
    if not weights:
        raise ValueError("Nonempty normalized expert weights are required")
    result = {name: float(value) for name, value in weights.items()}
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in result.values()) or not math.isclose(sum(result.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Expert weights must be finite, nonnegative and sum to one")
    return result


def shrink_regime_weights(global_weights: Mapping, bucket_weights: Mapping | None, bucket_count: int,
                         global_observed_at_utc, bucket_observed_at_utc, as_of_utc, config: Mapping):
    """Research-only effective weights from already observed matured bucket outcomes.

    The caller must count only immutable outcomes whose maturity and actual receipt
    precede as_of. This pure function additionally validates the supplied latest
    observation times; it does not construct or validate an external training ledger.
    """
    now, global_observed = map(timestamp, (as_of_utc, global_observed_at_utc))
    if global_observed > now:
        raise ValueError("Global weights contain future observations")
    if isinstance(bucket_count, bool) or not isinstance(bucket_count, int) or bucket_count < 0:
        raise ValueError("Bucket count must be a nonnegative integer")
    prior, minimum = float(config["prior_outcome_count"]), config["minimum_bucket_outcomes"]
    if not math.isfinite(prior) or prior <= 0 or isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError("Positive prior count and minimum bucket count are required")
    global_valid = _validated_weights(global_weights)
    bucket_valid = None
    if bucket_weights is not None:
        bucket_valid = _validated_weights(bucket_weights)
        if set(bucket_valid) != set(global_valid):
            raise ValueError("Global and regime expert sets must match")
        if bucket_observed_at_utc is None or timestamp(bucket_observed_at_utc) > now:
            raise ValueError("Bucket weights must be already observed")
    elif bucket_count > 0:
        raise ValueError("Nonzero bucket count requires auditable bucket weights")
    enabled = bucket_valid is not None and bucket_count >= minimum
    alpha = bucket_count/(bucket_count+prior) if enabled else 0.0
    effective = {name: alpha*bucket_valid[name]+(1-alpha)*value if enabled else value for name, value in global_valid.items()}
    _validated_weights(effective)
    return {"as_of_utc": now.isoformat(), "weights": effective, "alpha": alpha,
            "bucket_count": bucket_count, "minimum_bucket_outcomes": minimum, "prior_outcome_count": prior,
            "reason": "past_bucket_shrunk_to_global" if enabled else "insufficient_bucket_outcomes_global_fallback",
            "research_only": True}
