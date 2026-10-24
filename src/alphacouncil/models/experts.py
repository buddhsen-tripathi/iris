"""Five complementary forecasters, with all fitting restricted by the caller's masks."""

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_NAMES = ("lightgbm", "ridge", "kalman", "mean_reversion", "momentum")


def kalman_drift(log_prices: np.ndarray, observation_variance: float, process_ratio: float) -> np.ndarray:
    """Forward-only local linear trend filter, time step = one 5m bar."""
    values = np.asarray(log_prices, dtype=float)
    if not np.isfinite(values).all() or observation_variance <= 0 or process_ratio <= 0:
        raise ValueError("Invalid Kalman inputs")
    if len(values) == 0:
        return np.array([], dtype=float)
    r = float(observation_variance)
    q = r * process_ratio
    level, drift = float(values[0]), 0.0
    p00, p01, p11 = r, 0.0, r
    output = np.zeros(len(values))
    for i in range(1, len(values)):
        level += drift
        a = p00 + 2 * p01 + p11 + q * 0.25
        b = p01 + p11 + q * 0.5
        c = p11 + q
        k0, k1 = a / (a + r), b / (a + r)
        residual = values[i] - level
        level += k0 * residual
        drift += k1 * residual
        p00, p01, p11 = (1 - k0) * a, (1 - k0) * b, c - k1 * b
        output[i] = drift
    return output


def statistical_signal(name: str, table: pd.DataFrame, horizon: int, drift: np.ndarray | None = None) -> np.ndarray:
    if name == "momentum":
        return table[f"return_{horizon}m"].to_numpy(dtype=float)
    if name == "mean_reversion":
        return (-table["price_z_48"] * table["realized_vol_48"] / np.sqrt(48) * np.sqrt(horizon / 5)).to_numpy(dtype=float)
    if name == "kalman" and drift is not None:
        return np.asarray(drift) * (horizon / 5)
    raise ValueError(f"Unknown statistical expert {name}")


def fit_coefficient(signal: np.ndarray, target: np.ndarray, bounds=(0.0, 1.0)) -> float:
    denominator = float(np.dot(signal, signal))
    coefficient = float(np.dot(signal, target) / denominator) if denominator > 0 else 0.0
    return float(np.clip(coefficient, *bounds))


def fit_expert(name: str, parameter: float | int | None, table: pd.DataFrame, mask: pd.Series,
               horizon: int, config: dict, drift: np.ndarray | None = None):
    x = table.loc[mask, config["features"]]
    y = table.loc[mask, f"target_{horizon}m"].to_numpy(dtype=float)
    if len(x) == 0 or not np.isfinite(x.to_numpy()).all() or not np.isfinite(y).all():
        raise ValueError("Invalid fitting rows")
    if name == "ridge":
        model = make_pipeline(StandardScaler(), Ridge(alpha=float(parameter), solver="svd"))
        return model.fit(x, y)
    if name == "lightgbm":
        model = LGBMRegressor(
            objective="regression", num_leaves=int(parameter), max_depth=4,
            n_estimators=config["lightgbm_estimators"], learning_rate=config["lightgbm_learning_rate"],
            min_child_samples=config["lightgbm_min_child_samples"], reg_lambda=config["lightgbm_reg_lambda"],
            max_bin=63, n_jobs=2, random_state=config["seed"], deterministic=True,
            force_col_wise=True, verbosity=-1,
        )
        return model.fit(x, y)
    signal = statistical_signal(name, table, horizon, drift)
    coefficient = fit_coefficient(signal[mask.to_numpy()], y, tuple(config["statistical_coefficient_bounds"]))
    return {"name": name, "coefficient": coefficient}


def predict_expert(name: str, model, table: pd.DataFrame, config: dict, horizon: int,
                   drift: np.ndarray | None = None) -> np.ndarray:
    if name in {"ridge", "lightgbm"}:
        return model.predict(table[config["features"]])
    return model["coefficient"] * statistical_signal(name, table, horizon, drift)


def export_expert(name: str, model, features: list[str]) -> dict:
    if name == "ridge":
        scaler, regression = model.steps[0][1], model.steps[1][1]
        return {"name": name, "features": features, "scaler_mean": scaler.mean_.tolist(),
                "scaler_scale": scaler.scale_.tolist(), "coefficients": regression.coef_.tolist(),
                "intercept": float(regression.intercept_), "alpha": float(regression.alpha)}
    if name == "lightgbm":
        return {"name": name, "features": features, "native_model_format": "LightGBM text"}
    return dict(model)


def mix_forecasts(predictions: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    if set(predictions) != set(weights) or any(value < 0 for value in weights.values()) or not np.isclose(sum(weights.values()), 1):
        raise ValueError("Forecast weights must match experts, be nonnegative, and sum to one")
    return sum(weights[name] * predictions[name] for name in weights)


def forecast_metrics(actual: np.ndarray, prediction: np.ndarray) -> dict:
    actual, prediction = np.asarray(actual), np.asarray(prediction)
    if len(actual) == 0 or not np.isfinite(actual).all() or not np.isfinite(prediction).all():
        raise ValueError("Invalid scoring arrays")
    errors = prediction - actual
    mse = float(np.mean(errors ** 2))
    zero_mse = float(np.mean(actual ** 2))
    directional = (prediction != 0) & (actual != 0)
    return {
        "rows": len(actual), "mae_log_bps": float(np.mean(np.abs(errors)) * 10000),
        "rmse_log_bps": float(np.sqrt(mse) * 10000),
        "mse_skill_vs_zero": 1 - mse / zero_mse if zero_mse else None,
        "directional_coverage": float(directional.mean()),
        "directional_hit_rate": float((np.sign(prediction[directional]) == np.sign(actual[directional])).mean()) if directional.any() else None,
    }
