#!/usr/bin/env python3
"""Train 5/15/30m experts and compare predefined paper policies before the reserved test."""

import argparse
import json
import platform
from pathlib import Path

import lightgbm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn

from alphacouncil.backtest.paper import simulate_policy
from alphacouncil.data.archive import file_sha256, utc_now, write_json
from alphacouncil.models.experts import (
    MODEL_NAMES, export_expert, fit_expert, forecast_metrics, kalman_drift, mix_forecasts, predict_expert,
)
from alphacouncil.models.targets import HORIZONS, build_targets, matured_mask


def verified_parquet(path: Path, expected: str, time_column: str, before: pd.Timestamp) -> pd.DataFrame:
    if file_sha256(path) != expected:
        raise ValueError(f"Input checksum mismatch: {path}")
    return pd.read_parquet(path, filters=[(time_column, "<", before.to_pydatetime())])


def benchmark(candles: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, scenario: dict, paper: dict) -> dict:
    """A single passive spot allocation under the same per-side cost assumptions."""
    prices = candles.loc[candles["open_time_utc"].ge(start) & candles["open_time_utc"].lt(end), "open"].astype(float)
    if len(prices) < 2:
        raise ValueError("Insufficient passive benchmark prices")
    fee, impact = scenario["fee_bps_per_side"] / 10000, scenario["impact_bps_per_side"] / 10000
    allocation = min(paper["maximum_cash_per_position_usdt"], paper["initial_cash_usdt"])
    quantity = allocation / (prices.iloc[0] * (1 + impact) * (1 + fee))
    pnl = quantity * prices.iloc[-1] * (1 - impact) * (1 - fee) - allocation
    return {"cost_scenario": scenario["name"], "no_trade_net_pnl_usdt": 0.0,
            "buy_hold_cash_allocated_usdt": allocation, "buy_hold_net_pnl_usdt": float(pnl),
            "buy_hold_final_equity_usdt": float(paper["initial_cash_usdt"] + pnl),
            "note": "One passive allocation, purchased at first evaluation open and sold at last available open before end; same assumed costs."}


def plot_results(results: list[dict], output: Path, run_id: str, initial_cash: float) -> list[Path]:
    base = [result for result in results if result["summary"]["cost_scenario"] == "24bps_round_trip_base"]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"}):
        fig, axes = plt.subplots(2, 1, figsize=(11, 8), layout="constrained")
        colors = {"five_minute_only": "#0072B2", "with_15m_30m_confirmation": "#D55E00"}
        styles = {"five_minute_only": "-", "with_15m_30m_confirmation": "--"}
        for result in base:
            name = result["summary"]["policy"]
            axes[0].plot(result["equity"]["time_utc"], result["equity"]["equity_usdt"],
                         color=colors[name], linestyle=styles[name], label=f"{name}: {result['summary']['completed_trades']} trades")
        axes[0].axhline(initial_cash, color="#222222", linestyle=":", label="No trade")
        axes[0].set(ylabel="Simulated equity (USDT)", title="Development replay: base assumed costs ≈24 bps round trip")
        axes[0].legend(fontsize=9)
        if all(result["summary"]["completed_trades"] == 0 for result in base):
            axes[0].text(0.5, 0.65, "Both policies abstained: 0 trades", transform=axes[0].transAxes,
                         ha="center", fontsize=11)
        axes[0].tick_params(axis="x", rotation=15)
        scenarios = list(dict.fromkeys(result["summary"]["cost_scenario"] for result in results))
        x = np.arange(len(scenarios))
        for i, policy in enumerate(colors):
            counts = [next(result["summary"]["completed_trades"] for result in results if result["summary"]["policy"] == policy and result["summary"]["cost_scenario"] == scenario) for scenario in scenarios]
            bars = axes[1].bar(x + (i - 0.5) * 0.36, counts, width=0.36, color=colors[policy],
                               hatch="" if i == 0 else "//", label=policy)
            axes[1].bar_label(bars, padding=3, fontsize=9)
        axes[1].set_xticks(x, ["0 bps diagnostic", "≈12 bps", "≈24 bps (base)", "≈40 bps"])
        maximum = max(result["summary"]["completed_trades"] for result in results)
        axes[1].set_ylim(0, max(maximum * 1.18, 1))
        axes[1].set(ylabel="Completed simulated round trips", xlabel="Assumed round-trip friction; same 2 bps extra entry buffer",
                    title="Trade count responds to costs; no hourly trade quota")
        axes[1].legend(fontsize=9)
        for ax in axes:
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle("SIMULATED · 5/15/30-minute forecasts · reserved final 30 days not evaluated", fontsize=12)
        png = Path(".context") / f"training_paper_replay_{run_id}.png"
        svg = output / "paper_comparison.svg"
        fig.savefig(png, dpi=160, facecolor="white")
        fig.savefig(svg, facecolor="white")
        plt.close(fig)
    return [png, svg]


def write_report(manifest: dict, metrics: pd.DataFrame, selections: list[dict], results: list[dict], benchmarks: list[dict], output: Path) -> str:
    config, split = manifest["config"], manifest["splits"]
    skill = metrics.loc[metrics["model"].eq("committee_equal_weight")].set_index("horizon_minutes")["mse_skill_vs_zero"]
    all_abstained = all(result["summary"]["completed_trades"] == 0 for result in results)
    result_statement = (
        "Both policies made **zero trades in all four configured cost cases**. This is abstention; their relative trading performance is uninformative."
        if all_abstained else
        "The completed trade counts and cost-adjusted returns for each policy are reported below; they are simulated development results."
    )
    zero_amplitudes = [f"{row['model']} ({row['horizon_minutes']}m)" for row in selections if row.get("coefficient") == 0]
    base_threshold = next(result["summary"]["required_log_edge"] * 10000 for result in results
                          if result["summary"]["cost_scenario"] == "24bps_round_trip_base")
    lines = [
        "# 5/15/30-minute model training and paper comparison", "",
        "**Development experiment, simulated spot only.** No live orders, account access, real balances, or verified execution quotes are involved.", "",
        "## Observed result", "",
        f"Across {split['development_rows']:,} decisions, the strongest positive five-minute committee forecast was **{manifest['signal_diagnostics']['maximum_committee_5m_log_bps']:.3f} log bps**. The zero-cost diagnostic still requires a {config['paper']['extra_edge_buffer_bps']:g} bps extra entry buffer; the base-cost case requires {base_threshold:.3f} log bps including its buffer. {result_statement}", "",
        f"The committee's MSE skill versus zero return is **{skill.loc[5]:+.3%} at 5m, {skill.loc[15]:+.3%} at 15m, and {skill.loc[30]:+.3%} at 30m**. These observed differences do not establish statistical edge. Zero-amplitude fits: {', '.join(zero_amplitudes) if zero_amplitudes else 'none'}. Zero forecasts retain their predeclared committee shares, shrinking the mean; these are forecasting weights, not capital allocations.", "",
        "## What was trained", "",
        "Five specialists each predict cumulative BTC log return over **5, 15, and 30 minutes** (1, 3, and 6 completed bars): LightGBM, standardized Ridge, Kalman local trend, mean reversion, and momentum. Their committee uses **20% per expert**, fixed in advance. Adaptive weights are not implemented in this experiment.", "",
        "Ridge and LightGBM use the 14-input starter set from the feature draft. Statistical experts use their own observed-price/return contracts. The earlier unlabeled priority weights are not multiplied into model inputs or substituted for learned coefficients.", "",
        "Mean-reversion/momentum/Kalman amplitude coefficients are fitted by zero-intercept least squares and constrained to [0,1]. A coefficient of zero means that specialist earns no amplitude under this constrained fit. This is disclosed rather than replaced with a hand-picked nonzero forecast. Kalman noise is estimated on prices available before each fit boundary; its state then advances using observations only, without refitting on replay outcomes.", "",
        "## Chronology and label maturity", "",
        f"- Source start: `{split['source_start_utc']}`; 48-hour common feature warm-up.",
        f"- Initial fitting: `{split['warmup_end_utc']}` to `{split['training_end_utc_exclusive']}`, excluding targets maturing at or after the boundary.",
        f"- Hyperparameter selection: `{split['training_end_utc_exclusive']}` to `{split['model_selection_end_utc_exclusive']}`, with the same maturity purge.",
        f"- Refit selected configurations using all mature labels before `{split['model_selection_end_utc_exclusive']}`.",
        f"- Development paper replay: `{split['model_selection_end_utc_exclusive']}` to `{split['reserved_start_utc']}`, exclusive.",
        f"- **Reserved final test:** `{split['reserved_start_utc']}` onward. Outcomes were not loaded, labeled, scored, or used to fit/select models or policies.", "",
        "The feature-design audit previously examined pre-reservation input distributions, including this development replay period. Model parameters are selected using earlier labels, but this replay is not claimed to be a completely untouched research test. The independent final 30 days remain reserved.", "",
        "Labels are `log(close[t+h]/close[t])`, each paired with its actual maturity timestamp. Every partition requires all three outcomes to mature strictly before its end: six boundary origins are purged. Base models are frozen during the development replay; there is no hidden retraining on its labels. Normalization is fitted separately inside the initial training and final refit partitions.", "",
        "## Forecast quality in the development replay", "",
        "Errors below are log-return basis points (log return ×10,000). MSE skill is `1 - model_MSE/zero_forecast_MSE`; positive is better than zero return. Directional hit rate is conditional on nonzero forecast and outcome; coverage is supplied in the metrics CSV. These overlapping time-series errors are not independent samples, and no significance or annualized performance claim is made.", "",
        "| Horizon | Forecaster | MAE (log bps) | RMSE (log bps) | MSE skill vs zero |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in metrics.itertuples(index=False):
        lines.append(f"| {row.horizon_minutes}m | {row.model} | {row.mae_log_bps:.3f} | {row.rmse_log_bps:.3f} | {row.mse_skill_vs_zero:.3%} |")
    lines.extend([
        "", "## Paper execution assumptions", "",
        "Both policies consume the same frozen five-expert committee forecasts. Policy A enters on positive 5m edge after costs and a 2 bps extra buffer. Policy B additionally requires both 15m and 30m committee forecasts to be strictly positive. Confirmation thresholds, model grids, position size, costs, and rules were recorded in configuration before scoring the replay.", "",
        "- Long-only Binance spot counterfactual, 1x exposure, one open position at a time.",
        "- 50 USDT simulated cash; at most 10 USDT cash allocated per entry, including its assumed fee.",
        "- Fixed five-minute hold; a position exits before a possible new entry at the same boundary.",
        f"- Fill proxy: {config['paper']['fill_assumption']}",
        "- Entry and exit fees are charged separately on filled notional. Adverse price impact is charged on both sides, and the entry threshold uses the exact multiplicative break-even cost plus the extra buffer.",
        "- No funding/borrow costs because this is long-only spot; lot sizes, actual minimum orders, queueing, and real liquidity are not modeled.",
        "- Drawdown is measured at closed-trade exits, not the worst price inside each candle. Intrabar stops and liquidation are not simulated.", "",
        "The next-bar open shares the candle-close timestamp as a grid boundary, but is processed after the forecast event. This is explicitly an idealized **zero-latency proxy**; five-minute candles cannot establish a real post-computation fill. The target is a close-to-close mark return; realized paper P&L instead uses the next-open proxies plus costs. One-minute/tick/quote data would be needed for stronger execution claims.", "",
        "## Trading results and frequency", "",
        "A trade means one completed entry-and-exit round trip. Hourly counts use the entry's UTC hour. The theoretical ceiling is 12 entries per hour with a five-minute hold; actual counts follow the fixed entry rules. Zero trades is a valid result.", "",
        "| Cost case | Policy | Trades | Trades/hour (all clock hours) | Peak entries/hour | Net P&L (USDT) | Fees (USDT) | Exit-mark drawdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for result in results:
        row = result["summary"]
        lines.append(f"| {row['cost_scenario']} | {row['policy']} | {row['completed_trades']} | {row['average_trades_per_hour']:.4f} | {row['maximum_entries_in_utc_hour']} | {row['net_pnl_usdt']:.4f} | {row['entry_and_exit_fees_usdt']:.4f} | {100*row['maximum_exit_mark_drawdown']:.3f}% |")
    lines.extend(["", "The frictionless case is a diagnostic only. All costs are **assumptions**, not a fetched Binance or True Markets fee quote. Comparing thresholds across scenarios also changes which entries occur, not just the costs deducted from an identical trade list.", "",
        "### Passive/no-trade references", "", "No trade retains the initial 50 USDT. Buy-and-hold allocates the same 10 USDT cash cap once, with the corresponding cost case, and closes at the last available open before the replay ends.", "",
        "| Cost case | Buy-and-hold P&L (USDT) | No-trade P&L |", "| --- | ---: | ---: |"])
    for row in benchmarks:
        lines.append(f"| {row['cost_scenario']} | {row['buy_hold_net_pnl_usdt']:.4f} | 0.0000 |")
    lines.extend(["", "## Selected configurations", "", "| Horizon | Expert | Selected parameter | Amplitude coefficient if statistical |", "| --- | --- | --- | ---: |"])
    for row in selections:
        coefficient = "—" if row.get("coefficient") is None else f"{row['coefficient']:.6f}"
        lines.append(f"| {row['horizon_minutes']}m | {row['model']} | `{row['selected_parameter']}` | {coefficient} |")
    relative = output.relative_to(Path("reports"))
    lines.extend([
        "", "## Artifacts and reproduction", "",
        f"- [Forecast metrics]({relative}/forecast_metrics.csv)",
        f"- [Paper summaries and rejection reasons]({relative}/paper_summaries.json)",
        f"- [Candidate validation scores]({relative}/model_selection.json)",
        f"- [Exact configuration]({relative}/config.json)",
        f"- [Input, code, and output hashes]({relative}/manifest.json)",
        f"- [Paper comparison figure]({relative}/paper_comparison.svg)",
        f"- Saved models: `{manifest['models_directory']}` (local and gitignored; JSON coefficients/scalers and native LightGBM text, no pickle).",
        f"- Labels and replay forecasts: `{manifest['training_directory']}` (local and gitignored).",
        "- Trade ledgers, per-decision reasons, exit-mark equity curves, and hourly counts are CSV files inside the per-policy subdirectories alongside this report's artifacts.", "",
        "```sh", "uv sync --locked --group training --group analysis", "uv run --group training --group analysis python scripts/train_models.py", "uv run --group training pytest -q", "```", "",
        "The reserved final test should be opened once, after deciding whether to retain these models and execution rules. More frequent forecasts do not establish a profitable five-minute strategy.", "",
        "## Primary implementation references and figure credit", "",
        "- [Ridge regression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)",
        "- [Time-series validation](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split)",
        "- [LightGBM deterministic parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html)",
        "- Figure workflow uses the scientific-visualization skill; software credit: Kassis et al. (2026), [Scientific Agent Skills](https://doi.org/10.48550/arXiv.2609.00065).", "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/training_5_15_30.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if tuple(config["horizons_minutes"]) != HORIZONS:
        raise ValueError("This run supports exactly 5/15/30-minute targets")
    feature_manifest_path = args.data_dir / "manifests/features_latest.json"
    source_manifest_path = args.data_dir / "manifests/latest.json"
    fm = json.loads(feature_manifest_path.read_text())
    source = json.loads(source_manifest_path.read_text())
    if file_sha256(source_manifest_path) != fm["source_manifest_sha256"]:
        raise ValueError("Source data manifest changed since feature generation")
    source_start = pd.Timestamp(next(item for item in source["datasets"] if item["symbol"] == "BTCUSDT" and item["interval"] == "5m")["start_date_utc"], tz="UTC")
    holdout_start = pd.Timestamp(source["end_date_utc_exclusive"], tz="UTC") - pd.Timedelta(days=config["reserved_final_days"])
    training_end = source_start + pd.Timedelta(days=config["initial_training_days"])
    selection_end = training_end + pd.Timedelta(days=config["model_selection_days"])
    warmup_end = source_start + pd.Timedelta(days=config["common_warmup_days"], minutes=5)
    if not warmup_end < training_end < selection_end < holdout_start:
        raise ValueError("Insufficient chronological data for configured partitions")
    feature_path = Path(fm["feature_path"])
    features = verified_parquet(feature_path, fm["outputs"][str(feature_path)], "decision_time_utc", holdout_start)
    candle_entry = next(item for item in source["datasets"] if item["symbol"] == "BTCUSDT" and item["interval"] == "5m")
    candle_path = args.data_dir / candle_entry["path"]
    candles = verified_parquet(candle_path, candle_entry["sha256"], "close_time_utc", holdout_start)
    targets = build_targets(candles, holdout_start)
    table = features.merge(targets, on="decision_time_utc", how="left", validate="one_to_one")
    table = table.loc[table["decision_time_utc"].ge(warmup_end)].reset_index(drop=True)
    if not np.isfinite(table[config["features"]].to_numpy()).all():
        raise ValueError("Missing/nonfinite selected feature after warm-up")
    train = matured_mask(table, warmup_end, training_end)
    validation = matured_mask(table, training_end, selection_end)
    refit = matured_mask(table, warmup_end, selection_end)
    replay = matured_mask(table, selection_end, holdout_start)
    if min(train.sum(), validation.sum(), refit.sum(), replay.sum()) < 1000:
        raise ValueError("Insufficient fitting/scoring rows")
    print(f"Rows: fit={train.sum():,}, model selection={validation.sum():,}, refit={refit.sum():,}, replay={replay.sum():,}", flush=True)
    print(f"Reserved outcomes at/after {holdout_start} are not loaded or labeled.", flush=True)
    run_id = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    output = Path("reports/training") / run_id
    models_dir = Path("models") / run_id
    training_dir = args.data_dir / "training" / run_id
    for path in (output, models_dir, training_dir):
        path.mkdir(parents=True)
    write_json(output / "config.json", config)  # Record fixed decisions before any fitting/scoring.
    table.to_parquet(training_dir / "labeled_features_before_reserved_test.parquet", index=False, compression="zstd")
    price_times = pd.DatetimeIndex(candles["close_time_utc"])
    log_prices = np.log(candles["close"].to_numpy(dtype=float))

    def observation_variance(boundary):
        history = log_prices[price_times < boundary]
        return max(float(np.var(np.diff(history), ddof=1)), 1e-12)

    drift_cache = {}

    def drift_for(boundary, ratio):
        key = (boundary, ratio)
        if key not in drift_cache:
            filtered = kalman_drift(log_prices, observation_variance(boundary), ratio)
            drift_cache[key] = pd.Series(filtered, index=price_times).reindex(table["decision_time_utc"]).to_numpy()
        return drift_cache[key]

    candidates = {"ridge": config["ridge_alphas"], "lightgbm": config["lightgbm_leaves"],
                  "kalman": config["kalman_process_to_observation_ratios"], "mean_reversion": [None], "momentum": [None]}
    selection_records, selected = [], []
    predictions = table.loc[replay, ["decision_time_utc", *[f"target_{h}m" for h in HORIZONS], *[f"matures_{h}m_utc" for h in HORIZONS]]].copy().reset_index(drop=True)
    metrics_rows = []
    ridge_coefficients = []
    reload_max_error = 0.0
    for horizon in HORIZONS:
        horizon_predictions = {}
        for name in MODEL_NAMES:
            scored = []
            for parameter in candidates[name]:
                drift = drift_for(training_end, parameter) if name == "kalman" else None
                model = fit_expert(name, parameter, table, train, horizon, config, drift)
                forecast = predict_expert(name, model, table, config, horizon, drift)
                score = forecast_metrics(table.loc[validation, f"target_{horizon}m"].to_numpy(), forecast[validation.to_numpy()])
                record = {"horizon_minutes": horizon, "model": name, "parameter": parameter, **score}
                selection_records.append(record)
                scored.append((score["rmse_log_bps"], parameter))
            _, parameter = min(scored, key=lambda item: item[0])
            drift = drift_for(selection_end, parameter) if name == "kalman" else None
            model = fit_expert(name, parameter, table, refit, horizon, config, drift)
            forecast = predict_expert(name, model, table, config, horizon, drift)[replay.to_numpy()]
            horizon_predictions[name] = forecast
            predictions[f"{name}_{horizon}m"] = forecast
            payload = {**export_expert(name, model, config["features"]), "horizon_minutes": horizon,
                "selected_parameter": parameter, "fitted_at_boundary_utc": selection_end.isoformat(),
                "latest_training_outcome_utc": table.loc[refit, "matures_30m_utc"].max().isoformat()}
            if name == "lightgbm":
                path = models_dir / f"lightgbm_{horizon}m.txt"
                model.booster_.save_model(str(path))
                payload["native_model_path"] = str(path)
                reloaded = lightgbm.Booster(model_file=str(path)).predict(table.loc[replay, config["features"]])
                reload_max_error = max(reload_max_error, float(np.max(np.abs(reloaded - forecast))))
            elif name == "ridge":
                x = table.loc[replay, config["features"]].to_numpy()
                reloaded = ((x - payload["scaler_mean"]) / payload["scaler_scale"]) @ np.asarray(payload["coefficients"]) + payload["intercept"]
                reload_max_error = max(reload_max_error, float(np.max(np.abs(reloaded - forecast))))
                ridge_coefficients.extend({"horizon_minutes": horizon, "feature": feature,
                    "coefficient_per_training_standard_deviation": coefficient} for feature, coefficient in zip(config["features"], payload["coefficients"]))
            elif name == "kalman":
                payload.update({"observation_variance": observation_variance(selection_end), "process_to_observation_ratio": parameter,
                    "state_rule": "Run forward on observed log prices, with this fixed noise estimate; do not smooth backward."})
            write_json(models_dir / f"{name}_{horizon}m.json", payload)
            selected.append({"horizon_minutes": horizon, "model": name, "selected_parameter": parameter,
                             "coefficient": payload.get("coefficient")})
            print(f"FIT {name} {horizon}m; selected={parameter}; coefficient={payload.get('coefficient', 'learned model')}", flush=True)
        committee = mix_forecasts(horizon_predictions, config["ensemble"])
        predictions[f"committee_{horizon}m"] = committee
        all_forecasts = {**horizon_predictions, "committee_equal_weight": committee,
            "zero_return": np.zeros(len(committee)), "unscaled_return_persistence": table.loc[replay, f"return_{horizon}m"].to_numpy()}
        for name, forecast in all_forecasts.items():
            metrics_rows.append({"horizon_minutes": horizon, "model": name,
                **forecast_metrics(predictions[f"target_{horizon}m"].to_numpy(), forecast)})
    if reload_max_error > 1e-12:
        raise ValueError(f"Saved-model inference mismatch: {reload_max_error}")
    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(output / "forecast_metrics.csv", index=False)
    pd.DataFrame(ridge_coefficients).to_csv(output / "ridge_coefficients.csv", index=False)
    write_json(output / "model_selection.json", selection_records)
    write_json(output / "selected_configurations.json", selected)
    predictions.to_parquet(training_dir / "development_forecasts.parquet", index=False, compression="zstd")
    diagnostics = {
        "maximum_committee_5m_log_bps": float(predictions["committee_5m"].max() * 10000),
        "minimum_committee_5m_log_bps": float(predictions["committee_5m"].min() * 10000),
        "positive_committee_5m_decisions": int(predictions["committee_5m"].gt(0).sum()),
        "exceeds_2bps_simple_return_buffer": int(np.expm1(predictions["committee_5m"]).gt(0.0002).sum()),
        "policy_comparison_interpretation": "If both policies abstain, their relative trading performance is uninformative.",
    }
    write_json(output / "signal_diagnostics.json", diagnostics)
    results, references = [], []
    for scenario in config["paper"]["cost_scenarios"]:
        references.append(benchmark(candles, selection_end, holdout_start, scenario, config["paper"]))
        for policy in ("five_minute_only", "with_15m_30m_confirmation"):
            result = simulate_policy(predictions, candles, selection_end, holdout_start, policy, scenario, config["paper"])
            path = output / scenario["name"] / policy
            path.mkdir(parents=True)
            for key in ("trades", "decisions", "equity", "hourly"):
                result[key].to_csv(path / f"{key}.csv", index=False)
            results.append(result)
            print(f"PAPER {scenario['name']} {policy}: {result['summary']['completed_trades']} trades; P&L {result['summary']['net_pnl_usdt']:.4f} USDT", flush=True)
    write_json(output / "paper_summaries.json", [result["summary"] for result in results])
    write_json(output / "passive_benchmarks.json", references)
    figures = plot_results(results, output, run_id, config["paper"]["initial_cash_usdt"])
    manifest = {
        "run_id": run_id, "created_at_utc": utc_now().isoformat(), "status": "complete", "config": config,
        "mode": "DEVELOPMENT_REPLAY_SIMULATED", "labels_created": True, "reserved_test_evaluated": False,
        "reserved_outcomes_loaded": False, "live_trading_enabled": False,
        "splits": {"source_start_utc": source_start.isoformat(), "warmup_end_utc": warmup_end.isoformat(),
            "training_end_utc_exclusive": training_end.isoformat(), "model_selection_end_utc_exclusive": selection_end.isoformat(),
            "reserved_start_utc": holdout_start.isoformat(), "fit_rows": int(train.sum()), "selection_rows": int(validation.sum()),
            "refit_rows": int(refit.sum()), "development_rows": int(replay.sum()),
            "maximum_fitted_target_maturity_utc": table.loc[refit, "matures_30m_utc"].max().isoformat(),
            "maximum_labeled_maturity_utc": table["matures_30m_utc"].max().isoformat()},
        "models_directory": str(models_dir), "training_directory": str(training_dir), "report_directory": str(output),
        "inputs": {str(path): file_sha256(path) for path in [feature_manifest_path, source_manifest_path, feature_path, candle_path, args.config]},
        "code_sha256": {str(path): file_sha256(path) for path in [Path("scripts/train_models.py"), Path("uv.lock"),
            *sorted(Path("src/alphacouncil/models").glob("*.py")), *sorted(Path("src/alphacouncil/backtest").glob("*.py"))]},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__, "lightgbm": lightgbm.__version__, "matplotlib": matplotlib.__version__},
        "saved_model_max_absolute_prediction_error": reload_max_error,
        "signal_diagnostics": diagnostics,
        "outputs": {str(path): file_sha256(path) for path in [*sorted(output.rglob("*")), *sorted(models_dir.glob("*")),
            *sorted(training_dir.glob("*")), figures[0]] if path.is_file()},
    }
    write_json(output / "manifest.json", manifest)
    report = Path("reports/model_training_5_15_30.md")
    report.write_text(write_report(manifest, metrics, selected, results, references, output))
    write_json(args.data_dir / "manifests/training_latest.json", {**manifest, "report": str(report)})
    print(metrics.loc[metrics["model"].isin(["committee_equal_weight", "zero_return"])].to_string(index=False))
    print(f"Report: {report}\nModels: {models_dir}", flush=True)


if __name__ == "__main__":
    main()
