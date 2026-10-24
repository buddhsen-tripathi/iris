#!/usr/bin/env python3
"""Build unlabeled features, audit observed stability, and draft their proposed usage."""

import argparse
import json
import platform
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow

from alphacouncil.data.archive import file_sha256, utc_now, write_json
from alphacouncil.features.audit import audit_features, normalize_after_calibration, population_stability
from alphacouncil.features.build import FEATURES, NAMES, VERSION, build_features, definitions


def plot_audit(audit: dict, output: Path, images: Path, run_id: str) -> list[Path]:
    metrics = audit["metrics"]
    weights = metrics["priority_weight"] * 100
    low = metrics["sensitivity_min_weight"] * 100
    high = metrics["sensitivity_max_weight"] * 100
    paths = []
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none", "savefig.facecolor": "white"}):
        fig, ax = plt.subplots(figsize=(12, 10), layout="constrained")
        y = np.arange(len(NAMES))
        ax.barh(y, weights, color="#0072B2", height=0.65)
        # Sensitivity bounds need not be symmetric about the baseline.
        ax.hlines(y, low, high, color="#222222", linewidth=1.3)
        ax.plot(low, y, "|", color="#222222", markersize=5)
        ax.plot(high, y, "|", color="#222222", markersize=5)
        ax.set_yticks(y, [f"{feature.family}: {feature.name}" for feature in FEATURES], fontsize=8)
        for i, value in enumerate(weights):
            ax.text(max(value, high.iloc[i]) + 0.08, i, f"{value:.2f}%", va="center", fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(0, max(high.max(), weights.max()) * 1.22)
        ax.set_xlabel("Engineering priority allocation (%) — not predictive importance")
        ax.set_title("Unlabeled BTC feature priorities\nEqual family budgets; within-family quality, drift and redundancy adjustments", loc="left", fontsize=12)
        fig.get_layout_engine().set(rect=(0, 0.04, 1, 0.96))
        fig.text(0.99, 0.01, "Black ranges: heuristic sensitivity, not confidence intervals. Final 30 days excluded from audit.", ha="right", fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        svg = output / "feature_priorities.svg"
        png = images / f"feature_priorities_{run_id}.png"
        fig.savefig(svg, facecolor="white")
        fig.savefig(png, dpi=160, facecolor="white")
        paths.extend([svg, png])
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(14, 12), layout="constrained")
        matrix = audit["correlation"]
        im = ax.imshow(matrix, vmin=-1, vmax=1, cmap="RdBu_r", interpolation="nearest")
        ax.set_xticks(range(len(NAMES)), NAMES, rotation=90, fontsize=8)
        ax.set_yticks(range(len(NAMES)), NAMES, fontsize=8)
        ax.set_title("Feature redundancy: calibration-period Spearman correlation\nContemporaneous association only; no future returns or labels", loc="left", fontsize=12)
        fig.colorbar(im, ax=ax, shrink=0.7, label="Spearman rank correlation (−1 to +1)")
        svg = output / "feature_correlations.svg"
        png = images / f"feature_correlations_{run_id}.png"
        fig.savefig(svg, facecolor="white")
        fig.savefig(png, dpi=160, facecolor="white")
        paths.extend([svg, png])
        plt.close(fig)
    return paths


def draft(audit: dict, manifest: dict, output: Path) -> str:
    metrics = audit["metrics"]
    periods = audit["periods"]
    lines = [
        "# Iris feature-engineering draft", "",
        "Built from the collected market data, without creating future-return labels, fitting forecasting models, or running trading backtests.", "",
        "## What the weights mean", "",
        "The percentages below are **provisional engineering priorities**, not learned predictive coefficients, expected-return contributions, confidence levels, or model/expert weights. Unlabeled data can test availability, causal construction, distribution stability, and redundancy. It cannot establish which feature predicts the next 15/30/60-minute return. A stable feature can be useless for prediction; a changing volatility feature can still be essential for risk.", "",
        "Each of eight feature families receives a 12.5% budget by design. Within a family, priorities increase with finite coverage and decrease with extreme-value frequency, distribution drift, and correlation redundancy. These family budgets are a transparent initial prior, not an empirical discovery about market importance.", "",
        "```text",
        "q_i = coverage_i * (1 - extreme_fraction_i) * exp(-median_PSI_i)",
        "redundancy_i = sum_j abs(Spearman(i,j)), for j != i and abs(correlation) >= 0.8",
        "s_i = q_i / (1 + redundancy_i)",
        "w_i = (1 / eligible_family_count) * s_i / sum(s_j within feature i's family)",
        "```", "",
        "Coverage is measured after a common 48-hour warm-up. Extreme values are more than eight calibration IQRs from the calibration median; they remain in the raw feature table. PSI uses calibration deciles, a 0.5 pseudocount per bin, and 28-day audit blocks. These are fixed diagnostic choices, not validated financial cutoffs. No standalone PSI threshold is interpreted as evidence of predictive failure.", "",
        "## Data and chronology", "",
        "The table has one row per completed BTC 5-minute candle. BTCUSDT/ETHUSDT/SOLUSDT Binance spot series provide 5-minute inputs; the two-year BTCUSDT hourly series supplies slower context. All prices are USDT-quoted. True Markets data are excluded from these inputs because their source venue/quote currency are unspecified and their histories contain gaps.", "",
        f"- Feature rows: **{manifest['feature_rows']:,}**, with **{manifest['complete_feature_rows']:,}** rows where all 26 candidates are available.",
        f"- Calibration reference: after `{periods['warmup_end_utc']}` and before `{periods['calibration_end_utc_exclusive']}`; **{periods['calibration_rows']:,}** rows.",
        f"- Stability audit: from `{periods['calibration_end_utc_exclusive']}` to `{periods['audit_end_utc_exclusive']}`, exclusive; **{periods['audit_rows']:,}** rows.",
        f"- Reserved period: the last **{periods['holdout_rows_not_profiled']:,}** feature rows (the final 30 UTC days plus their initial decision boundary), excluded from normalization fitting, correlations, drift calculations, eligibility, and priority weighting.", "",
        "Raw causal features are materialized for the entire source range, including the reserved period. Only pre-reservation observations are profiled. The median/IQR normalization is fitted on the early calibration interval and emitted only for decision times at or after that interval ends. Earlier normalized rows stay missing; later model training must fit its own scaler within each chronological training fold.", "",
        "Decision time is the exclusive candle-close boundary, under the offline assumption that the completed bar is immediately available. A real collector must also enforce actual arrival latency. Current completed OHLCV is usable; an order fill would be later. Hourly features are joined backward on **hourly close time**, with a maximum age of 55 minutes. No future candles, centered windows, negative shifts, backfilled features, or interpolation are used.", "",
        "## Candidate features and their respective priorities", "",
        "Every feature is retained as a candidate. Eligibility below is structural, not evidence of predictive skill. Percentages are rounded for display; exact weights are in the JSON artifact.", "",
        "| Feature | Family | Priority | Sensitivity range | Audit coverage | Median PSI | Strongest absolute correlation |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for feature in FEATURES:
        row = metrics.loc[feature.name]
        lines.append(f"| `{feature.name}` | {feature.family} | {100*row['priority_weight']:.2f}% | {100*row['sensitivity_min_weight']:.2f}–{100*row['sensitivity_max_weight']:.2f}% | {100*row['audit_coverage']:.2f}% | {row['median_psi']:.4f} | {row['max_absolute_spearman']:.3f} with `{row['most_correlated_feature']}` |")
    lines.extend([
        "", "Sensitivity ranges vary the redundancy threshold to 0.7/0.9 and omit each audit block from the PSI median in turn. They are **not confidence intervals**. The rows overlap in time and are autocorrelated; no independent-sample significance or profitability claim is made.", "",
        "## Redundancy found in the actual data", "",
        "These pairs had absolute Spearman correlation at least 0.8 in calibration or audit. This is contemporaneous feature-to-feature correlation, not correlation with a future outcome.", "",
        "| Pair | Calibration correlation | Audit correlation |",
        "| --- | ---: | ---: |",
    ])
    for pair in sorted(audit["redundant_pairs"], key=lambda pair: -abs(pair["calibration_spearman"])):
        lines.append(f"| `{pair['feature_a']}` / `{pair['feature_b']}` | {pair['calibration_spearman']:.3f} | {pair['audit_spearman']:.3f} |")
    lines.extend([
        "", "Highly correlated inputs should be tested as groups or alternatives when targets are eventually introduced. Similar indicators must not be counted as independent confirmation. The UTC sine/cosine pair is a joint encoding, even if their measured correlation is low.", "",
        "## Suggested lean first experiment", "",
        "Start with **14 inputs**, retaining the remaining candidates for later ablations:", "",
        "- Trend: `return_5m`, `return_30m`.",
        "- Displacement: `price_z_48`.",
        "- Risk state: `realized_vol_48`, `vol_ratio_12_48`.",
        "- Candle shape: `close_location`.",
        "- Activity: `log_quote_volume_z_288`, `taker_buy_imbalance`, `log_illiquidity_48`.",
        "- Relative strength: `btc_eth_relative_60m`, `btc_sol_relative_60m`.",
        "- Slower trend: `hourly_return_6h`.",
        "- Calendar context: `utc_time_sin`, `utc_time_cos` together.", "",
        "This is a proposed compact input set, not an optimized or predictively validated selection. Test RSI as an alternative to price z-score, ATR as an alternative to realized volatility, and body fraction as an alternative to the 5m return; the observed correlations support testing alternatives instead of treating these as independent votes. Extra return windows, EMA gap, trade-count surprise, cross-asset correlation, and daily volatility remain available as additions. The full-table priorities are experiment-order hints, not a weighted prediction formula for this subset.", "",
        "## Distribution checks against raw-state controls", "",
        "The controls below were evaluated over exactly the same calibration/audit dates and blocks. These comparisons describe how much each representation changes distribution over time; smaller PSI does not prove retained information or predictive usefulness.", "",
        "| Raw-state control | Median PSI | Transformed candidate | Median PSI |", "| --- | ---: | --- | ---: |",
        *[f"| `{control['control']}` | {control['control_median_psi']:.4f} | `{control['candidate']}` | {control['candidate_median_psi']:.4f} |" for control in audit["control_checks"]], "",
        "Calendar variables have near-zero drift largely by construction: each full UTC day contains the same cycle. Their allocated budget is a design choice, not discovered market signal. Absolute volatility can drift because the market regime changes; preserve it for risk context rather than assuming that stationarity is always preferable. Pairwise rank correlation also cannot detect every nonlinear redundancy.", "",
        "## Proposed use in the investment committee", "",
        "| Component | Inputs to start with | How to use them |",
        "| --- | --- | --- |",
        "| Nonlinear expert | All eligible candidates, tested in family ablations | Supply native feature values and missingness handling; trees learn splits. Multiplying columns by these positive priorities does not encode meaningful importance in a tree. |",
        "| Ridge expert | Standardized returns, trend, reversion, activity and cross-asset features; time pair as context | Fit scaling and coefficients only on the training fold once targets exist. Use these priorities for experiment order, not as regression coefficients. |",
        "| Momentum expert | Return windows, EMA gap, completed hourly trend | Compare a small set of trailing trend rules; the combination and sign still need predictive evaluation. |",
        "| Reversion expert | Price z-score, centered RSI, volatility ratio | Test whether extreme displacement actually reverses in the relevant regime; do not assume that high RSI means sell. |",
        "| Kalman expert | Log price observations; volatility as a possible noise-scale context | Preserve the state-space model's observation contract; do not replace its price input with an arbitrary weighted indicator sum. |",
        "| Independent risk officer | Realized volatility, ATR fraction, volume and price-impact proxies | Use as context for future calibrated risk estimates. These proxies do not establish fees, executable liquidity, or permissible leverage. |", "",
        "**Do not calculate predicted return as `sum(priority_weight * feature)`**: these quantities have different units and roles. For initial development, add one feature family at a time, use the priorities to order within-family ablations, and compare the family-balanced baseline with a simpler minimal input set. Once targets are authorized, assess horizon-specific out-of-sample performance and grouped feature importance on chronological validation. Committee expert weights are a separate mechanism updated only after future outcomes mature.", "",
        "## Feature formulas and interpretation", "",
        "`r` is the completed-bar log return; `C/O/H/L` are close/open/high/low. Windows count 5-minute bars unless explicitly hourly. Return features describe the past and are not future labels. Standard deviations use `ddof=1`; EWM uses `adjust=False` and full stated minimum periods. RSI/ATR use alpha 1/14 seeded from the first valid observation (a Wilder-style EWM, not a claim of exact TA-Lib seeding).", "",
        "| Feature | Exact construction | Proposed interpretation |",
        "| --- | --- | --- |",
    ])
    for feature in FEATURES:
        lines.append(f"| `{feature.name}` | {feature.formula} | {feature.use} |")
    relative = output.relative_to(Path("reports"))
    lines.extend([
        "", "Zero denominators remain missing except for explicitly neutral flat-bar location/body and fully flat RSI. Zero-volume activity is not treated as a valid zero imbalance. Strict source validation rejects missing candle intervals rather than treating a row-based rolling window as elapsed time across an outage. Diagnostic outliers are retained, not winsorized away.", "",
        "## Files and reproduction", "",
        f"- [Full metrics CSV]({relative}/feature_metrics.csv)",
        f"- [Exact feature priorities and method]({relative}/feature_weights.json)",
        f"- [Calibration correlation matrix]({relative}/calibration_correlations.csv)",
        f"- [Audit correlation matrix]({relative}/audit_correlations.csv)",
        f"- [Distribution drift by time block]({relative}/drift_by_block.csv)",
        f"- [Input/output hashes and provenance]({relative}/manifest.json)",
        f"- [Priority figure, SVG]({relative}/feature_priorities.svg)",
        f"- [Correlation figure, SVG]({relative}/feature_correlations.svg)",
        f"- Raw feature Parquet: `{manifest['feature_path']}` (local, gitignored).",
        f"- Normalized feature Parquet: `{manifest['normalized_feature_path']}` (local, gitignored).", "",
        "```sh", "uv sync --locked --group analysis", "uv run --group analysis python scripts/engineer_features.py", "uv run pytest -q", "```", "",
        "## Methods sources and software credit", "",
        "- [pandas rolling windows](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.rolling.html): trailing construction; current completed observation is included where stated.",
        "- [pandas backward as-of join](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html): the last hourly close at or before decision time.",
        "- [scikit-learn feature-importance documentation](https://scikit-learn.org/stable/modules/permutation_importance.html): predictive importance is evaluated for a fitted model and a prediction task; this unlabeled audit does not estimate it.",
        "- Figure workflow used the scientific-visualization skill. Software credit: Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026). [Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065), current record reviewed October 24, 2026.", "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    source_manifest_path = args.data_dir / "manifests/latest.json"
    source = json.loads(source_manifest_path.read_text())
    if source["status"] != "complete":
        raise ValueError("Require a complete source manifest")
    inputs = []

    def load(symbol, interval):
        entry = next(item for item in source["datasets"] if item["symbol"] == symbol and item["interval"] == interval)
        path = args.data_dir / entry["path"]
        if file_sha256(path) != entry["sha256"]:
            raise ValueError(f"Input hash mismatch: {path}")
        inputs.append({"path": str(path), "sha256": entry["sha256"]})
        return pd.read_parquet(path)

    btc = load("BTCUSDT", "5m")
    frame = build_features(btc, load("ETHUSDT", "5m"), load("SOLUSDT", "5m"), load("BTCUSDT", "1h"))
    first_decision = frame["decision_time_utc"].iloc[0]
    calibration_end = first_decision.normalize() + pd.Timedelta(days=180)
    # A 5m bar opening at 23:55 closes at 00:00; reserve that boundary too.
    holdout_start = pd.Timestamp(source["end_date_utc_exclusive"], tz="UTC") - pd.Timedelta(days=30)
    print(f"Built {len(frame):,} rows x {len(NAMES)} unlabeled features; auditing before {holdout_start}", flush=True)
    audit = audit_features(frame, calibration_end, holdout_start)
    # Unlabeled raw-state controls, excluded from the candidate feature weights.
    controls = pd.DataFrame({
        "log_close": np.log(btc["close"].astype(float)).to_numpy(),
        "log_quote_volume": np.log1p(btc["volume_quote"].astype(float)).to_numpy(),
        "log_trade_count": np.log1p(btc["trade_count"].astype(float)).to_numpy(),
    })
    times = frame["decision_time_utc"]
    reference_mask = times.ge(pd.Timestamp(audit["periods"]["warmup_end_utc"])) & times.lt(calibration_end)
    blocks = audit["drift_blocks"][["block_start_utc", "block_end_utc_exclusive"]].drop_duplicates()
    audit["control_checks"] = []
    for control, candidate in [("log_close", "price_z_48"), ("log_quote_volume", "log_quote_volume_z_288"), ("log_trade_count", "log_trade_count_z_288")]:
        psis = [population_stability(controls.loc[reference_mask, control], controls.loc[
            times.ge(pd.Timestamp(block.block_start_utc)) & times.lt(pd.Timestamp(block.block_end_utc_exclusive)), control,
        ]) for block in blocks.itertuples(index=False)]
        audit["control_checks"].append({"control": control, "control_median_psi": float(np.median(psis)),
            "candidate": candidate, "candidate_median_psi": float(audit["metrics"].loc[candidate, "median_psi"])})
    normalized = normalize_after_calibration(frame, audit["scaler"], calibration_end)
    run_id = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    features_root = args.data_dir / "features" / run_id
    output = Path("reports/feature_audit") / run_id
    images = Path(".context")
    features_root.mkdir(parents=True)
    output.mkdir(parents=True)
    images.mkdir(exist_ok=True)
    feature_path = features_root / "BTCUSDT_5m_features.parquet"
    normalized_path = features_root / "BTCUSDT_5m_normalized.parquet"
    frame.to_parquet(feature_path, index=False, compression="zstd")
    normalized.to_parquet(normalized_path, index=False, compression="zstd")
    audit["metrics"].to_csv(output / "feature_metrics.csv")
    audit["correlation"].to_csv(output / "calibration_correlations.csv")
    audit["audit_correlation"].to_csv(output / "audit_correlations.csv")
    audit["drift_blocks"].to_csv(output / "drift_by_block.csv", index=False)
    write_json(output / "feature_definitions.json", definitions())
    write_json(output / "raw_state_control_checks.json", audit["control_checks"])
    write_json(output / "feature_weights.json", {
        "feature_version": VERSION, "method": audit["method"], "periods": audit["periods"],
        "weights": audit["metrics"]["priority_weight"].to_dict(), "scaler": audit["scaler"],
        "note": "Engineering priorities only. No future labels, forecasting model, or predictive importance estimated.",
    })
    figures = plot_audit(audit, output, images, run_id)
    manifest = {
        "run_id": run_id, "created_at_utc": utc_now().isoformat(), "feature_version": VERSION,
        "feature_rows": len(frame), "feature_count": len(NAMES),
        "complete_feature_rows": int(frame["all_features_available"].sum()),
        "labels_created": False, "forecasting_models_fitted": False,
        "feature_path": str(feature_path), "normalized_feature_path": str(normalized_path),
        "source_manifest": str(source_manifest_path), "source_manifest_sha256": file_sha256(source_manifest_path),
        "source_inputs": inputs, "periods": audit["periods"], "method": audit["method"],
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
            "pyarrow": pyarrow.__version__, "matplotlib": matplotlib.__version__},
        "code_sha256": {str(path): file_sha256(path) for path in [Path("scripts/engineer_features.py"),
            Path("src/alphacouncil/features/build.py"), Path("src/alphacouncil/features/audit.py"), Path("uv.lock")]},
        "outputs": {str(path): file_sha256(path) for path in [feature_path, normalized_path, *sorted(output.glob("*")), *[path for path in figures if path.suffix == ".png"]]},
        "figure_notes": {"weights": "All 26 priorities with heuristic sensitivity ranges, not confidence intervals; zero baseline.",
            "correlations": "Calibration contemporaneous Spearman correlation; symmetric -1 to +1 color limits; numeric CSV provided."},
    }
    write_json(output / "manifest.json", manifest)
    report = Path("reports/feature_engineering_draft.md")
    report.write_text(draft(audit, manifest, output))
    write_json(args.data_dir / "manifests/features_latest.json", {**manifest, "report": str(report), "audit_directory": str(output)})
    print(audit["metrics"][["family", "priority_weight", "median_psi", "audit_coverage"]].to_string())
    print(f"Saved draft: {report}", flush=True)
    print(f"Artifacts: {output}\nFeature table: {feature_path}", flush=True)


if __name__ == "__main__":
    main()
