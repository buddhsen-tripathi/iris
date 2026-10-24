# Adaptive committee development comparison

This is a chronological **development replay**, not untouched validation or a live result. The feature audit previously saw development distributions. No reserved outcomes were read and no orders were placed.

Each horizon keeps its own discounted squared-error score. Weights are exponential in the negative score, shrunk 10% toward equal, and projected onto a 5% floor / 50% cap. Fixed loss scales are 10, 17.32 and 24.49 log bps; loss clipping is 25, learning rate 0.05 and score retention 0.995 per update. These are engineering defaults, not parameters selected for favorable results. No regime-dependent gain is claimed.

A forecast records its exact weights before updates. Only already matured and observed outcomes can update scores, once per immutable source forecast ID. Historical receipt times do not exist: replay assumes observation at maturity and excludes outcomes with maturity equal to the current decision boundary. Live shadow instead records its actual publication and application timestamps, never backfills past forecasts, and reads the original paper ledger without modifying it.

| Horizon | Method | Rows | MAE (log bps) | RMSE (log bps) | MSE skill vs zero |
|---|---|---:|---:|---:|---:|
| 5m | adaptive | 17,274 | 6.9321 | 10.9889 | +0.0256% |
| 5m | equal_weight | 17,274 | 6.9322 | 10.9890 | +0.0229% |
| 15m | adaptive | 17,274 | 11.9911 | 18.9812 | -0.0719% |
| 15m | equal_weight | 17,274 | 11.9911 | 18.9815 | -0.0746% |
| 30m | adaptive | 17,274 | 17.0529 | 26.9743 | -0.0546% |
| 30m | equal_weight | 17,274 | 17.0536 | 26.9746 | -0.0571% |

These overlapping errors are not independent. A lower replay error alone does not establish reliable future improvement, trading returns or profitability. Three specialists currently emit zero or very small amplitudes; adapted forecasting shares are not capital allocations. Keep the frozen equal committee as a baseline while collecting prospective outcomes.

Machine-readable comparison: `reports/committee/comparison.json`. Full immutable forecast/update ledger and per-origin weights: `data/forward/committee_development_20261024T151706339788Z`. Live shadow status: `data/manifests/committee_latest.json`.

Run `uv run --group training python scripts/compare_committees.py` to reproduce. Start `uv run --group training python scripts/committee_shadow.py --minutes 60` to watch new forecasts without changing either paper trader.
