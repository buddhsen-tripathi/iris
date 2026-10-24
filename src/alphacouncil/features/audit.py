"""Unsupervised feature diagnostics and explicitly provisional priority allocations."""

import numpy as np
import pandas as pd

from alphacouncil.features.build import FEATURES, NAMES


def population_stability(reference: pd.Series, current: pd.Series) -> float:
    """Decile-bin Jeffreys divergence with 0.5 pseudocount per bin; descriptive only."""
    ref = reference.dropna().to_numpy()
    cur = current.dropna().to_numpy()
    if len(ref) == 0 or len(cur) == 0:
        return float("nan")
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, 11)))
    if len(edges) < 3:
        return float("nan")
    edges[0], edges[-1] = -np.inf, np.inf
    reference_hist = np.histogram(ref, bins=edges)[0] + 0.5
    current_hist = np.histogram(cur, bins=edges)[0] + 0.5
    p = reference_hist / reference_hist.sum()
    q = current_hist / current_hist.sum()
    return float(np.sum((q - p) * np.log(q / p)))


def allocate_priorities(metrics: pd.DataFrame, correlation: pd.DataFrame, threshold: float = 0.8) -> pd.Series:
    """Equal family budgets; quality/drift/redundancy determine only within-family shares."""
    eligible = metrics["eligible"]
    corr = correlation.loc[eligible.index[eligible], eligible.index[eligible]].abs().copy()
    np.fill_diagonal(corr.values, 0)
    redundancy = corr.where(corr.ge(threshold), 0).sum(axis=1)
    quality = metrics["audit_coverage"] * (1 - metrics["audit_outlier_fraction"])
    scores = quality * np.exp(-metrics["median_psi"].clip(lower=0)) / (1 + redundancy.reindex(metrics.index, fill_value=0))
    scores = scores.where(eligible, 0).fillna(0)
    families = metrics.loc[eligible, "family"].unique()
    weights = pd.Series(0.0, index=metrics.index)
    if len(families) == 0:
        raise ValueError("No eligible feature families")
    for family in families:
        mask = metrics["family"].eq(family) & eligible
        family_scores = scores.loc[mask]
        if family_scores.sum() <= 0:
            raise ValueError(f"No usable scores in {family}")
        weights.loc[mask] = family_scores / family_scores.sum() / len(families)
    return weights


def audit_features(frame: pd.DataFrame, calibration_end: pd.Timestamp, holdout_start: pd.Timestamp) -> dict:
    times = frame["decision_time_utc"]
    warmup_end = times.iloc[0] + pd.Timedelta(days=2)
    if not warmup_end < calibration_end < holdout_start <= times.iloc[-1]:
        raise ValueError("Invalid chronological audit boundaries")
    calibration = frame.loc[times.ge(warmup_end) & times.lt(calibration_end), NAMES]
    audit = frame.loc[times.ge(calibration_end) & times.lt(holdout_start), NAMES]
    if min(len(calibration), len(audit)) < 1000:
        raise ValueError("Insufficient calibration/audit rows")
    median = calibration.median()
    iqr = calibration.quantile(0.75) - calibration.quantile(0.25)
    scaled_audit = (audit - median) / iqr.replace(0, np.nan)
    # Spearman is calculated directly from ranks, avoiding an optional scipy dependency.
    correlation = calibration.rank().corr(method="pearson")
    audit_correlation = audit.rank().corr(method="pearson")
    block_rows = []
    block_start = calibration_end
    while block_start < holdout_start:
        block_end = min(block_start + pd.Timedelta(days=28), holdout_start)
        sample = frame.loc[times.ge(block_start) & times.lt(block_end), NAMES]
        for name in NAMES:
            block_rows.append({"feature": name, "block_start_utc": block_start.isoformat(),
                "block_end_utc_exclusive": block_end.isoformat(), "rows": len(sample),
                "psi": population_stability(calibration[name], sample[name])})
        block_start = block_end
    blocks = pd.DataFrame(block_rows)
    metrics = pd.DataFrame(index=pd.Index(NAMES, name="feature"))
    metrics["family"] = [feature.family for feature in FEATURES]
    metrics["calibration_coverage"] = calibration.notna().mean()
    metrics["audit_coverage"] = audit.notna().mean()
    metrics["calibration_median"] = median
    metrics["calibration_iqr"] = iqr
    metrics["audit_unique_values"] = audit.nunique()
    metrics["audit_outlier_fraction"] = scaled_audit.abs().gt(8).sum() / audit.notna().sum().replace(0, np.nan)
    metrics["median_psi"] = blocks.groupby("feature")["psi"].median()
    metrics["max_psi"] = blocks.groupby("feature")["psi"].max()
    metrics["lag1_autocorrelation"] = [audit[name].autocorr(lag=1) for name in NAMES]
    metrics["eligible"] = (
        metrics["calibration_coverage"].ge(0.995) & metrics["audit_coverage"].ge(0.995)
        & metrics["calibration_iqr"].gt(0) & metrics["audit_unique_values"].ge(10)
        & metrics["median_psi"].notna()
    )
    abs_corr = correlation.abs().copy()
    np.fill_diagonal(abs_corr.values, -np.inf)
    metrics["most_correlated_feature"] = abs_corr.idxmax()
    metrics["max_absolute_spearman"] = abs_corr.max()
    metrics["priority_weight"] = allocate_priorities(metrics, correlation)
    variants = [allocate_priorities(metrics, correlation, threshold) for threshold in (0.7, 0.9)]
    block_starts = blocks["block_start_utc"].unique()
    if len(block_starts) > 1:
        for excluded in block_starts:
            alternate = metrics.copy()
            alternate["median_psi"] = blocks.loc[blocks["block_start_utc"].ne(excluded)].groupby("feature")["psi"].median()
            variants.append(allocate_priorities(alternate, correlation))
    sensitivity = pd.DataFrame([metrics["priority_weight"], *variants])
    metrics["sensitivity_min_weight"] = sensitivity.min()
    metrics["sensitivity_max_weight"] = sensitivity.max()
    pairs = [
        {"feature_a": name, "feature_b": other, "calibration_spearman": float(correlation.loc[name, other]),
         "audit_spearman": float(audit_correlation.loc[name, other])}
        for i, name in enumerate(NAMES) for other in NAMES[i + 1:]
        if abs(correlation.loc[name, other]) >= 0.8 or abs(audit_correlation.loc[name, other]) >= 0.8
    ]
    return {
        "metrics": metrics, "correlation": correlation, "audit_correlation": audit_correlation,
        "drift_blocks": blocks, "redundant_pairs": pairs,
        "scaler": {name: {"median": float(median[name]), "iqr": float(iqr[name])} for name in NAMES},
        "periods": {
            "warmup_end_utc": warmup_end.isoformat(), "calibration_end_utc_exclusive": calibration_end.isoformat(),
            "audit_end_utc_exclusive": holdout_start.isoformat(), "calibration_rows": len(calibration),
            "audit_rows": len(audit), "holdout_rows_not_profiled": int(times.ge(holdout_start).sum()),
        },
        "method": {
            "weight_type": "unsupervised_engineering_priority_not_predictive_importance",
            "family_budgets": "equal across eligible families; an explicit design prior",
            "score": "coverage*(1-outlier_fraction)*exp(-median_PSI)/(1+sum(abs(Spearman)>=0.8))",
            "outlier": "abs((x-calibration_median)/calibration_IQR)>8; raw values retained",
            "PSI": "reference deciles, 0.5 pseudocount per bin; median across 28-day audit blocks",
            "eligibility": "calibration and audit coverage>=99.5%, IQR>0, >=10 distinct audit values",
            "sensitivity": "redundancy thresholds 0.7 and 0.9; leave-one-audit-block-out PSI; ranges are not confidence intervals",
        },
    }


def normalize_after_calibration(frame: pd.DataFrame, scaler: dict, calibration_end: pd.Timestamp) -> pd.DataFrame:
    """Do not apply a future-fitted transform to earlier historical decisions."""
    result = frame[["decision_time_utc"]].copy()
    for name in NAMES:
        iqr = scaler[name]["iqr"]
        result[name] = (frame[name] - scaler[name]["median"]) / iqr if iqr > 0 else np.nan
    result.loc[result["decision_time_utc"].lt(calibration_end), NAMES] = np.nan
    return result
