# Optional causal regime context

Regime support is available as an opt-in research primitive. It does not change the running global committee or either paper trader. Conditional weights remain disabled, and no gain has been validated.

`classify_regime` in `src/alphacouncil/committee/regime.py` consumes one completed, already observed feature row. It requires timezone-aware timestamps with `source_anchor <= observed_at <= as_of` and rejects incomplete or future observations. It does not estimate thresholds or inspect later rows. All thresholds are fixed design choices recorded in `configs/regime.json`.

| Label | Fixed rule, in priority order |
|---|---|
| `high_vol` | Four-hour realized log-return volatility at least 0.02, or short/long five-minute return volatility ratio at least 1.5 |
| `trend` | Absolute 60-minute log return at least 0.002, and normalized strength at least 1.0 |
| `range` | Remaining completed observations |

Normalized strength is `abs(return_60m) / (0.5 * realized_vol_48)`. The 0.5 factor is `sqrt(12/48)`: an explicit square-root time scaling heuristic from four hours to one hour, not a fitted model. A positive 1e-12 denominator floor makes flat windows deterministic. High volatility takes precedence even when the trend threshold is met. The label is broad context; it is not a prediction of the next market move. A separate diagnostic records the past return's direction.

`shrink_regime_weights` provides research-only conditional mixing:

`w_effective = alpha * w_bucket + (1 - alpha) * w_global`

Once at least 30 matured, actually observed bucket outcomes exist, `alpha = n / (n + 100)`. Below 30, effective weights exactly equal global weights. This function validates common expert sets, finite nonnegative shares summing to one, nonnegative integer counts and observation timestamps no later than `as_of`. The caller must construct bucket counts and bucket learning state using independently audited, matured outcomes; this helper does not train buckets or certify external counts. A convex blend preserves normalization and any common weight bounds. It returns a new dictionary and cannot mutate the active committee.

Six focused tests cover fixed label precedence, future/incomplete observation rejection, future-row invariance, insufficient-count global fallback, normalization, deterministic shrinkage and future-weight rejection.

Run `uv run --group training python scripts/regime_context.py` for a one-time snapshot using the original forward ledger opened read-only. The snapshot is written to `data/manifests/regime_latest.json`, includes its source anchor and actual as-of time, and must not be presented as continuously refreshed or as an executable signal. The initial snapshot at 2026-10-24 15:22:37 UTC classified the 15:20 anchor as `high_vol` because short/long volatility ratio was 1.638. This observation is descriptive, not evidence of predictive value.
