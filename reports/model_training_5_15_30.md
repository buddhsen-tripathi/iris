# 5/15/30-minute model training and paper comparison

**Development experiment, simulated spot only.** No live orders, account access, real balances, or verified execution quotes are involved.

## Observed result

Across 17,274 decisions, the strongest positive five-minute committee forecast was **1.502 log bps**. The zero-cost diagnostic still requires a 2 bps extra entry buffer; the base-cost case requires 25.995 log bps including its buffer. Both policies made **zero trades in all four configured cost cases**. This is abstention; their relative trading performance is uninformative.

The committee's MSE skill versus zero return is **+0.023% at 5m, -0.075% at 15m, and -0.057% at 30m**. These observed differences do not establish statistical edge. Zero-amplitude fits: kalman (5m), momentum (5m), kalman (15m), momentum (15m), kalman (30m), momentum (30m). Zero forecasts retain their predeclared committee shares, shrinking the mean; these are forecasting weights, not capital allocations.

## What was trained

Five specialists each predict cumulative BTC log return over **5, 15, and 30 minutes** (1, 3, and 6 completed bars): LightGBM, standardized Ridge, Kalman local trend, mean reversion, and momentum. Their committee uses **20% per expert**, fixed in advance. Adaptive weights are not implemented in this experiment.

Ridge and LightGBM use the 14-input starter set from the feature draft. Statistical experts use their own observed-price/return contracts. The earlier unlabeled priority weights are not multiplied into model inputs or substituted for learned coefficients.

Mean-reversion/momentum/Kalman amplitude coefficients are fitted by zero-intercept least squares and constrained to [0,1]. A coefficient of zero means that specialist earns no amplitude under this constrained fit. This is disclosed rather than replaced with a hand-picked nonzero forecast. Kalman noise is estimated on prices available before each fit boundary; its state then advances using observations only, without refitting on replay outcomes.

## Chronology and label maturity

- Source start: `2025-10-24T00:00:00+00:00`; 48-hour common feature warm-up.
- Initial fitting: `2025-10-26T00:05:00+00:00` to `2026-06-21T00:00:00+00:00`, excluding targets maturing at or after the boundary.
- Hyperparameter selection: `2026-06-21T00:00:00+00:00` to `2026-07-26T00:00:00+00:00`, with the same maturity purge.
- Refit selected configurations using all mature labels before `2026-07-26T00:00:00+00:00`.
- Development paper replay: `2026-07-26T00:00:00+00:00` to `2026-09-24T00:00:00+00:00`, exclusive.
- **Reserved final test:** `2026-09-24T00:00:00+00:00` onward. Outcomes were not loaded, labeled, scored, or used to fit/select models or policies.

The feature-design audit previously examined pre-reservation input distributions, including this development replay period. Model parameters are selected using earlier labels, but this replay is not claimed to be a completely untouched research test. The independent final 30 days remain reserved.

Labels are `log(close[t+h]/close[t])`, each paired with its actual maturity timestamp. Every partition requires all three outcomes to mature strictly before its end: six boundary origins are purged. Base models are frozen during the development replay; there is no hidden retraining on its labels. Normalization is fitted separately inside the initial training and final refit partitions.

## Forecast quality in the development replay

Errors below are log-return basis points (log return ×10,000). MSE skill is `1 - model_MSE/zero_forecast_MSE`; positive is better than zero return. Directional hit rate is conditional on nonzero forecast and outcome; coverage is supplied in the metrics CSV. These overlapping time-series errors are not independent samples, and no significance or annualized performance claim is made.

| Horizon | Forecaster | MAE (log bps) | RMSE (log bps) | MSE skill vs zero |
| --- | --- | ---: | ---: | ---: |
| 5m | lightgbm | 6.941 | 10.991 | -0.021% |
| 5m | ridge | 6.936 | 10.994 | -0.076% |
| 5m | kalman | 6.933 | 10.990 | 0.000% |
| 5m | mean_reversion | 6.931 | 10.991 | -0.013% |
| 5m | momentum | 6.933 | 10.990 | 0.000% |
| 5m | committee_equal_weight | 6.932 | 10.989 | 0.023% |
| 5m | zero_return | 6.933 | 10.990 | 0.000% |
| 5m | unscaled_return_persistence | 10.048 | 15.527 | -99.609% |
| 15m | lightgbm | 11.997 | 19.009 | -0.363% |
| 15m | ridge | 11.995 | 18.990 | -0.163% |
| 15m | kalman | 11.997 | 18.974 | 0.000% |
| 15m | mean_reversion | 11.987 | 18.979 | -0.050% |
| 15m | momentum | 11.997 | 18.974 | 0.000% |
| 15m | committee_equal_weight | 11.991 | 18.981 | -0.075% |
| 15m | zero_return | 11.997 | 18.974 | 0.000% |
| 15m | unscaled_return_persistence | 17.478 | 26.700 | -98.007% |
| 30m | lightgbm | 17.081 | 27.018 | -0.376% |
| 30m | ridge | 17.072 | 26.994 | -0.198% |
| 30m | kalman | 17.061 | 26.967 | 0.000% |
| 30m | mean_reversion | 17.041 | 26.975 | -0.061% |
| 30m | momentum | 17.061 | 26.967 | 0.000% |
| 30m | committee_equal_weight | 17.054 | 26.975 | -0.057% |
| 30m | zero_return | 17.061 | 26.967 | 0.000% |
| 30m | unscaled_return_persistence | 25.277 | 38.144 | -100.078% |

## Paper execution assumptions

Both policies consume the same frozen five-expert committee forecasts. Policy A enters on positive 5m edge after costs and a 2 bps extra buffer. Policy B additionally requires both 15m and 30m committee forecasts to be strictly positive. Confirmation thresholds, model grids, position size, costs, and rules were recorded in configuration before scoring the replay.

- Long-only Binance spot counterfactual, 1x exposure, one open position at a time.
- 50 USDT simulated cash; at most 10 USDT cash allocated per entry, including its assumed fee.
- Fixed five-minute hold; a position exits before a possible new entry at the same boundary.
- Fill proxy: Next-bar-open proxy at the decision boundary, processed after the close/forecast event; zero latency, adverse spread/slippage on each side. Not verified executable quotes.
- Entry and exit fees are charged separately on filled notional. Adverse price impact is charged on both sides, and the entry threshold uses the exact multiplicative break-even cost plus the extra buffer.
- No funding/borrow costs because this is long-only spot; lot sizes, actual minimum orders, queueing, and real liquidity are not modeled.
- Drawdown is measured at closed-trade exits, not the worst price inside each candle. Intrabar stops and liquidation are not simulated.

The next-bar open shares the candle-close timestamp as a grid boundary, but is processed after the forecast event. This is explicitly an idealized **zero-latency proxy**; five-minute candles cannot establish a real post-computation fill. The target is a close-to-close mark return; realized paper P&L instead uses the next-open proxies plus costs. One-minute/tick/quote data would be needed for stronger execution claims.

## Trading results and frequency

A trade means one completed entry-and-exit round trip. Hourly counts use the entry's UTC hour. The theoretical ceiling is 12 entries per hour with a five-minute hold; actual counts follow the fixed entry rules. Zero trades is a valid result.

| Cost case | Policy | Trades | Trades/hour (all clock hours) | Peak entries/hour | Net P&L (USDT) | Fees (USDT) | Exit-mark drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| zero_cost_diagnostic | five_minute_only | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |
| zero_cost_diagnostic | with_15m_30m_confirmation | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |
| 12bps_round_trip | five_minute_only | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |
| 12bps_round_trip | with_15m_30m_confirmation | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |
| 24bps_round_trip_base | five_minute_only | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |
| 24bps_round_trip_base | with_15m_30m_confirmation | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |
| 40bps_round_trip | five_minute_only | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |
| 40bps_round_trip | with_15m_30m_confirmation | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.000% |

The frictionless case is a diagnostic only. All costs are **assumptions**, not a fetched Binance or True Markets fee quote. Comparing thresholds across scenarios also changes which entries occur, not just the costs deducted from an identical trade list.

### Passive/no-trade references

No trade retains the initial 50 USDT. Buy-and-hold allocates the same 10 USDT cash cap once, with the corresponding cost case, and closes at the last available open before the replay ends.

| Cost case | Buy-and-hold P&L (USDT) | No-trade P&L |
| --- | ---: | ---: |
| zero_cost_diagnostic | 3.1150 | 0.0000 |
| 12bps_round_trip | 3.0993 | 0.0000 |
| 24bps_round_trip_base | 3.0836 | 0.0000 |
| 40bps_round_trip | 3.0627 | 0.0000 |

## Selected configurations

| Horizon | Expert | Selected parameter | Amplitude coefficient if statistical |
| --- | --- | --- | ---: |
| 5m | lightgbm | `15` | — |
| 5m | ridge | `10000.0` | — |
| 5m | kalman | `0.0001` | 0.000000 |
| 5m | mean_reversion | `None` | 0.007793 |
| 5m | momentum | `None` | 0.000000 |
| 15m | lightgbm | `7` | — |
| 15m | ridge | `10000.0` | — |
| 15m | kalman | `0.0001` | 0.000000 |
| 15m | mean_reversion | `None` | 0.011816 |
| 15m | momentum | `None` | 0.000000 |
| 30m | lightgbm | `7` | — |
| 30m | ridge | `10000.0` | — |
| 30m | kalman | `0.0001` | 0.000000 |
| 30m | mean_reversion | `None` | 0.014934 |
| 30m | momentum | `None` | 0.000000 |

## Artifacts and reproduction

- [Forecast metrics](training/20261024T141034220601Z/forecast_metrics.csv)
- [Paper summaries and rejection reasons](training/20261024T141034220601Z/paper_summaries.json)
- [Candidate validation scores](training/20261024T141034220601Z/model_selection.json)
- [Exact configuration](training/20261024T141034220601Z/config.json)
- [Input, code, and output hashes](training/20261024T141034220601Z/manifest.json)
- [Paper comparison figure](training/20261024T141034220601Z/paper_comparison.svg)
- Saved models: `models/20261024T141034220601Z` (local and gitignored; JSON coefficients/scalers and native LightGBM text, no pickle).
- Labels and replay forecasts: `data/training/20261024T141034220601Z` (local and gitignored).
- Trade ledgers, per-decision reasons, exit-mark equity curves, and hourly counts are CSV files inside the per-policy subdirectories alongside this report's artifacts.

```sh
uv sync --locked --group training --group analysis
uv run --group training --group analysis python scripts/train_models.py
uv run --group training pytest -q
```

The reserved final test should be opened once, after deciding whether to retain these models and execution rules. More frequent forecasts do not establish a profitable five-minute strategy.

## Primary implementation references and figure credit

- [Ridge regression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)
- [Time-series validation](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split)
- [LightGBM deterministic parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html)
- Figure workflow uses the scientific-visualization skill; software credit: Kassis et al. (2026), [Scientific Agent Skills](https://doi.org/10.48550/arXiv.2609.00065).
