# Iris feature-engineering draft

Built from the collected market data, without creating future-return labels, fitting forecasting models, or running trading backtests.

## What the weights mean

The percentages below are **provisional engineering priorities**, not learned predictive coefficients, expected-return contributions, confidence levels, or model/expert weights. Unlabeled data can test availability, causal construction, distribution stability, and redundancy. It cannot establish which feature predicts the next 15/30/60-minute return. A stable feature can be useless for prediction; a changing volatility feature can still be essential for risk.

Each of eight feature families receives a 12.5% budget by design. Within a family, priorities increase with finite coverage and decrease with extreme-value frequency, distribution drift, and correlation redundancy. These family budgets are a transparent initial prior, not an empirical discovery about market importance.

```text
q_i = coverage_i * (1 - extreme_fraction_i) * exp(-median_PSI_i)
redundancy_i = sum_j abs(Spearman(i,j)), for j != i and abs(correlation) >= 0.8
s_i = q_i / (1 + redundancy_i)
w_i = (1 / eligible_family_count) * s_i / sum(s_j within feature i's family)
```

Coverage is measured after a common 48-hour warm-up. Extreme values are more than eight calibration IQRs from the calibration median; they remain in the raw feature table. PSI uses calibration deciles, a 0.5 pseudocount per bin, and 28-day audit blocks. These are fixed diagnostic choices, not validated financial cutoffs. No standalone PSI threshold is interpreted as evidence of predictive failure.

## Data and chronology

The table has one row per completed BTC 5-minute candle. BTCUSDT/ETHUSDT/SOLUSDT Binance spot series provide 5-minute inputs; the two-year BTCUSDT hourly series supplies slower context. All prices are USDT-quoted. True Markets data are excluded from these inputs because their source venue/quote currency are unspecified and their histories contain gaps.

- Feature rows: **105,120**, with **104,832** rows where all 26 candidates are available.
- Calibration reference: after `2025-10-26T00:05:00+00:00` and before `2026-04-22T00:00:00+00:00`; **51,263** rows.
- Stability audit: from `2026-04-22T00:00:00+00:00` to `2026-09-24T00:00:00+00:00`, exclusive; **44,640** rows.
- Reserved period: the last **8,641** feature rows (the final 30 UTC days plus their initial decision boundary), excluded from normalization fitting, correlations, drift calculations, eligibility, and priority weighting.

Raw causal features are materialized for the entire source range, including the reserved period. Only pre-reservation observations are profiled. The median/IQR normalization is fitted on the early calibration interval and emitted only for decision times at or after that interval ends. Earlier normalized rows stay missing; later model training must fit its own scaler within each chronological training fold.

Decision time is the exclusive candle-close boundary, under the offline assumption that the completed bar is immediately available. A real collector must also enforce actual arrival latency. Current completed OHLCV is usable; an order fill would be later. Hourly features are joined backward on **hourly close time**, with a maximum age of 55 minutes. No future candles, centered windows, negative shifts, backfilled features, or interpolation are used.

## Candidate features and their respective priorities

Every feature is retained as a candidate. Eligibility below is structural, not evidence of predictive skill. Percentages are rounded for display; exact weights are in the JSON artifact.

| Feature | Family | Priority | Sensitivity range | Audit coverage | Median PSI | Strongest absolute correlation |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `return_5m` | trend | 2.07% | 1.44–2.08% | 100.00% | 0.0627 | 0.913 with `body_fraction` |
| `return_15m` | trend | 2.11% | 2.10–2.73% | 100.00% | 0.0740 | 0.857 with `eth_return_15m` |
| `return_30m` | trend | 3.91% | 2.72–4.74% | 100.00% | 0.0779 | 0.690 with `rsi_14_centered` |
| `return_60m` | trend | 2.13% | 1.85–2.70% | 100.00% | 0.0862 | 0.818 with `rsi_14_centered` |
| `ema_gap_12_48` | trend | 2.27% | 1.54–2.91% | 100.00% | 0.0119 | 0.838 with `price_z_48` |
| `price_z_48` | reversion | 6.23% | 6.22–6.25% | 100.00% | 0.0064 | 0.942 with `rsi_14_centered` |
| `rsi_14_centered` | reversion | 6.27% | 6.25–6.28% | 100.00% | 0.0068 | 0.942 with `price_z_48` |
| `realized_vol_12` | volatility | 2.03% | 1.71–2.58% | 100.00% | 0.2212 | 0.904 with `atr_14_fraction` |
| `realized_vol_48` | volatility | 1.83% | 1.82–2.31% | 100.00% | 0.3097 | 0.945 with `atr_14_fraction` |
| `vol_ratio_12_48` | volatility | 6.91% | 6.09–7.38% | 100.00% | 0.0051 | 0.455 with `realized_vol_12` |
| `atr_14_fraction` | volatility | 1.72% | 1.45–1.75% | 100.00% | 0.3471 | 0.945 with `realized_vol_48` |
| `close_location` | candle | 3.84% | 3.82–5.22% | 100.00% | 0.0392 | 0.831 with `body_fraction` |
| `body_fraction` | candle | 2.62% | 2.59–4.23% | 100.00% | 0.0166 | 0.913 with `return_5m` |
| `range_fraction` | candle | 6.03% | 3.86–6.09% | 100.00% | 0.1921 | 0.779 with `atr_14_fraction` |
| `log_quote_volume_z_288` | activity | 3.22% | 2.32–3.24% | 100.00% | 0.0034 | 0.797 with `log_trade_count_z_288` |
| `log_trade_count_z_288` | activity | 3.21% | 2.32–3.24% | 100.00% | 0.0050 | 0.797 with `log_quote_volume_z_288` |
| `taker_buy_imbalance` | activity | 3.20% | 3.17–4.14% | 100.00% | 0.0109 | 0.553 with `body_fraction` |
| `log_illiquidity_48` | activity | 2.87% | 2.80–3.72% | 100.00% | 0.1184 | 0.272 with `utc_time_cos` |
| `btc_eth_relative_60m` | cross_asset | 3.58% | 3.16–3.64% | 100.00% | 0.0919 | 0.493 with `btc_sol_relative_60m` |
| `eth_return_15m` | cross_asset | 1.96% | 1.91–3.21% | 100.00% | 0.0766 | 0.857 with `return_15m` |
| `btc_eth_correlation_288` | cross_asset | 3.12% | 2.75–3.25% | 100.00% | 0.2302 | 0.457 with `hourly_realized_vol_24` |
| `btc_sol_relative_60m` | cross_asset | 3.83% | 3.38–3.93% | 100.00% | 0.0257 | 0.493 with `btc_eth_relative_60m` |
| `hourly_return_6h` | hourly_context | 9.24% | 7.77–10.19% | 100.00% | 0.1371 | 0.722 with `ema_gap_12_48` |
| `hourly_realized_vol_24` | hourly_context | 3.26% | 2.31–4.73% | 100.00% | 1.1780 | 0.616 with `atr_14_fraction` |
| `utc_time_sin` | calendar | 6.25% | 6.25–6.25% | 100.00% | 0.0000 | 0.318 with `atr_14_fraction` |
| `utc_time_cos` | calendar | 6.25% | 6.25–6.25% | 100.00% | 0.0000 | 0.272 with `log_illiquidity_48` |

Sensitivity ranges vary the redundancy threshold to 0.7/0.9 and omit each audit block from the PSI median in turn. They are **not confidence intervals**. The rows overlap in time and are autocorrelated; no independent-sample significance or profitability claim is made.

## Redundancy found in the actual data

These pairs had absolute Spearman correlation at least 0.8 in calibration or audit. This is contemporaneous feature-to-feature correlation, not correlation with a future outcome.

| Pair | Calibration correlation | Audit correlation |
| --- | ---: | ---: |
| `realized_vol_48` / `atr_14_fraction` | 0.945 | 0.938 |
| `price_z_48` / `rsi_14_centered` | 0.942 | 0.945 |
| `return_5m` / `body_fraction` | 0.913 | 0.905 |
| `realized_vol_12` / `atr_14_fraction` | 0.904 | 0.899 |
| `return_15m` / `eth_return_15m` | 0.857 | 0.855 |
| `ema_gap_12_48` / `price_z_48` | 0.838 | 0.839 |
| `realized_vol_12` / `realized_vol_48` | 0.831 | 0.820 |
| `close_location` / `body_fraction` | 0.831 | 0.833 |
| `return_60m` / `rsi_14_centered` | 0.818 | 0.821 |

Highly correlated inputs should be tested as groups or alternatives when targets are eventually introduced. Similar indicators must not be counted as independent confirmation. The UTC sine/cosine pair is a joint encoding, even if their measured correlation is low.

## Suggested lean first experiment

Start with **14 inputs**, retaining the remaining candidates for later ablations:

- Trend: `return_5m`, `return_30m`.
- Displacement: `price_z_48`.
- Risk state: `realized_vol_48`, `vol_ratio_12_48`.
- Candle shape: `close_location`.
- Activity: `log_quote_volume_z_288`, `taker_buy_imbalance`, `log_illiquidity_48`.
- Relative strength: `btc_eth_relative_60m`, `btc_sol_relative_60m`.
- Slower trend: `hourly_return_6h`.
- Calendar context: `utc_time_sin`, `utc_time_cos` together.

This is a proposed compact input set, not an optimized or predictively validated selection. Test RSI as an alternative to price z-score, ATR as an alternative to realized volatility, and body fraction as an alternative to the 5m return; the observed correlations support testing alternatives instead of treating these as independent votes. Extra return windows, EMA gap, trade-count surprise, cross-asset correlation, and daily volatility remain available as additions. The full-table priorities are experiment-order hints, not a weighted prediction formula for this subset.

## Distribution checks against raw-state controls

The controls below were evaluated over exactly the same calibration/audit dates and blocks. These comparisons describe how much each representation changes distribution over time; smaller PSI does not prove retained information or predictive usefulness.

| Raw-state control | Median PSI | Transformed candidate | Median PSI |
| --- | ---: | --- | ---: |
| `log_close` | 8.2101 | `price_z_48` | 0.0064 |
| `log_quote_volume` | 0.1262 | `log_quote_volume_z_288` | 0.0034 |
| `log_trade_count` | 0.3179 | `log_trade_count_z_288` | 0.0050 |

Calendar variables have near-zero drift largely by construction: each full UTC day contains the same cycle. Their allocated budget is a design choice, not discovered market signal. Absolute volatility can drift because the market regime changes; preserve it for risk context rather than assuming that stationarity is always preferable. Pairwise rank correlation also cannot detect every nonlinear redundancy.

## Proposed use in the investment committee

| Component | Inputs to start with | How to use them |
| --- | --- | --- |
| Nonlinear expert | All eligible candidates, tested in family ablations | Supply native feature values and missingness handling; trees learn splits. Multiplying columns by these positive priorities does not encode meaningful importance in a tree. |
| Ridge expert | Standardized returns, trend, reversion, activity and cross-asset features; time pair as context | Fit scaling and coefficients only on the training fold once targets exist. Use these priorities for experiment order, not as regression coefficients. |
| Momentum expert | Return windows, EMA gap, completed hourly trend | Compare a small set of trailing trend rules; the combination and sign still need predictive evaluation. |
| Reversion expert | Price z-score, centered RSI, volatility ratio | Test whether extreme displacement actually reverses in the relevant regime; do not assume that high RSI means sell. |
| Kalman expert | Log price observations; volatility as a possible noise-scale context | Preserve the state-space model's observation contract; do not replace its price input with an arbitrary weighted indicator sum. |
| Independent risk officer | Realized volatility, ATR fraction, volume and price-impact proxies | Use as context for future calibrated risk estimates. These proxies do not establish fees, executable liquidity, or permissible leverage. |

**Do not calculate predicted return as `sum(priority_weight * feature)`**: these quantities have different units and roles. For initial development, add one feature family at a time, use the priorities to order within-family ablations, and compare the family-balanced baseline with a simpler minimal input set. Once targets are authorized, assess horizon-specific out-of-sample performance and grouped feature importance on chronological validation. Committee expert weights are a separate mechanism updated only after future outcomes mature.

## Feature formulas and interpretation

`r` is the completed-bar log return; `C/O/H/L` are close/open/high/low. Windows count 5-minute bars unless explicitly hourly. Return features describe the past and are not future labels. Standard deviations use `ddof=1`; EWM uses `adjust=False` and full stated minimum periods. RSI/ATR use alpha 1/14 seeded from the first valid observation (a Wilder-style EWM, not a claim of exact TA-Lib seeding).

| Feature | Exact construction | Proposed interpretation |
| --- | --- | --- |
| `return_5m` | log(C[t]/C[t-1]) | Recent direction; large magnitude also signals a shock. |
| `return_15m` | log(C[t]/C[t-3]) | Short trend input to momentum and linear experts. |
| `return_30m` | log(C[t]/C[t-6]) | Intermediate trend; compare with shorter returns. |
| `return_60m` | log(C[t]/C[t-12]) | One-hour trend; overlaps shorter returns. |
| `ema_gap_12_48` | (EMA12(log C)-EMA48(log C))/(std48(r)*sqrt(12)) | Volatility-scaled trend strength, not a forecast. |
| `price_z_48` | (log C[t]-mean(log C[t-48:t-1]))/std(log C[t-48:t-1]) | Distance from the preceding 4h price distribution; snapback is a hypothesis. |
| `rsi_14_centered` | 2*WilderEWMA14(gains)/(WilderEWMA14(gains)+WilderEWMA14(losses))-1 | Bounded price pressure; trend persistence and reversal are both possible. |
| `realized_vol_12` | std12(r)*sqrt(12), sample std | Trailing 1h risk context; no direction implied. |
| `realized_vol_48` | std48(r)*sqrt(48), sample std | Trailing 4h risk context; no direction implied. |
| `vol_ratio_12_48` | std12(r)/std48(r) | Short volatility expansion relative to the 4h window. |
| `atr_14_fraction` | WilderEWMA14(max(H-L,abs(H-Cprev),abs(L-Cprev)))/C | Typical range relative to price; a risk input, not spread or a guaranteed stop distance. |
| `close_location` | 2*(C-L)/(H-L)-1; flat bar=0 | Where the close sits inside the completed candle. |
| `body_fraction` | (C-O)/(H-L); flat bar=0 | Signed body relative to candle range. |
| `range_fraction` | (H-L)/C | Single-bar price expansion, not executable spread. |
| `log_quote_volume_z_288` | (log1p(Vquote[t])-prior_mean288(log1p Vquote))/prior_std288(log1p Vquote) | Unusual USDT turnover relative to the preceding day. |
| `log_trade_count_z_288` | (log1p(N[t])-prior_mean288(log1p N))/prior_std288(log1p N) | Unusual activity; often redundant with turnover. |
| `taker_buy_imbalance` | 2*taker_buy_base_volume/base_volume-1; zero volume=missing | Aggressor-buy share of executed volume; not order-book imbalance. |
| `log_illiquidity_48` | log1p(1e6*mean48(abs(r)/Vquote)); zero volume=missing | Backward price-impact proxy per USDT of volume; not a fill/slippage estimate. |
| `btc_eth_relative_60m` | BTC_return60m-ETH_return60m | Relative BTC strength; the sign is not a proven trading rule. |
| `eth_return_15m` | log(ETH_C[t]/ETH_C[t-3]) | Contemporaneous ETH market context available at the same bar close. |
| `btc_eth_correlation_288` | corr288(BTC_r,ETH_r) | Trailing 24h co-movement; no causation or lead/lag claim. |
| `btc_sol_relative_60m` | BTC_return60m-SOL_return60m | Relative BTC/SOL strength; controls overlap via the redundancy audit. |
| `hourly_return_6h` | log(last completed BTC hourly C / hourly C six bars earlier) | Slower trend context, joined backward on hourly close time. |
| `hourly_realized_vol_24` | std24(completed hourly log returns)*sqrt(24) | Trailing daily volatility context from completed hourly bars. |
| `utc_time_sin` | sin(2*pi*UTC decision minute_of_day/1440) | Time-of-day context; always use with the cosine partner. |
| `utc_time_cos` | cos(2*pi*UTC decision minute_of_day/1440) | Time-of-day context; no standalone buy/sell interpretation. |

Zero denominators remain missing except for explicitly neutral flat-bar location/body and fully flat RSI. Zero-volume activity is not treated as a valid zero imbalance. Strict source validation rejects missing candle intervals rather than treating a row-based rolling window as elapsed time across an outage. Diagnostic outliers are retained, not winsorized away.

## Files and reproduction

- [Full metrics CSV](feature_audit/20261024T124401891777Z/feature_metrics.csv)
- [Exact feature priorities and method](feature_audit/20261024T124401891777Z/feature_weights.json)
- [Calibration correlation matrix](feature_audit/20261024T124401891777Z/calibration_correlations.csv)
- [Audit correlation matrix](feature_audit/20261024T124401891777Z/audit_correlations.csv)
- [Distribution drift by time block](feature_audit/20261024T124401891777Z/drift_by_block.csv)
- [Input/output hashes and provenance](feature_audit/20261024T124401891777Z/manifest.json)
- [Priority figure, SVG](feature_audit/20261024T124401891777Z/feature_priorities.svg)
- [Correlation figure, SVG](feature_audit/20261024T124401891777Z/feature_correlations.svg)
- Raw feature Parquet: `data/features/20261024T124401891777Z/BTCUSDT_5m_features.parquet` (local, gitignored).
- Normalized feature Parquet: `data/features/20261024T124401891777Z/BTCUSDT_5m_normalized.parquet` (local, gitignored).

```sh
uv sync --locked --group analysis
uv run --group analysis python scripts/engineer_features.py
uv run pytest -q
```

## Methods sources and software credit

- [pandas rolling windows](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.rolling.html): trailing construction; current completed observation is included where stated.
- [pandas backward as-of join](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html): the last hourly close at or before decision time.
- [scikit-learn feature-importance documentation](https://scikit-learn.org/stable/modules/permutation_importance.html): predictive importance is evaluated for a fitted model and a prediction task; this unlabeled audit does not estimate it.
- Figure workflow used the scientific-visualization skill. Software credit: Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026). [Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065), current record reviewed October 24, 2026.
