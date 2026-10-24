"""Load native/JSON checkpoints without fitting or needing prediction labels."""

import json
from pathlib import Path

import lightgbm
import numpy as np
import pandas as pd

from alphacouncil.data.archive import file_sha256
from alphacouncil.models.experts import MODEL_NAMES, kalman_drift, mix_forecasts, statistical_signal
from alphacouncil.models.targets import HORIZONS


class FrozenCommittee:
    def __init__(self, manifest: dict):
        if manifest["status"] != "complete":
            raise ValueError("Require completed model training")
        self.manifest = manifest
        self.config = manifest["config"]
        self.payloads, self.trees = {}, {}
        root = Path(manifest["models_directory"])
        for horizon in HORIZONS:
            for name in MODEL_NAMES:
                path = root / f"{name}_{horizon}m.json"
                if file_sha256(path) != manifest["outputs"][str(path)]:
                    raise ValueError(f"Checkpoint hash mismatch: {path}")
                payload = json.loads(path.read_text())
                self.payloads[name, horizon] = payload
                if name == "lightgbm":
                    native = Path(payload["native_model_path"])
                    if file_sha256(native) != manifest["outputs"][str(native)]:
                        raise ValueError(f"Native checkpoint hash mismatch: {native}")
                    self.trees[horizon] = lightgbm.Booster(model_file=str(native))

    def predict(self, feature_row: pd.DataFrame, btc_history: pd.DataFrame) -> dict:
        if len(feature_row) != 1:
            raise ValueError("Supply exactly one observed feature row")
        time = feature_row["decision_time_utc"].iloc[0]
        if not btc_history["close_time_utc"].le(time).all():
            raise ValueError("Future prices in inference context")
        for payload in self.payloads.values():
            if time < pd.Timestamp(payload["fitted_at_boundary_utc"]):
                raise ValueError("Checkpoint was not available at this decision time")
        x = feature_row[self.config["features"]]
        if not np.isfinite(x.to_numpy()).all():
            raise ValueError("Missing/nonfinite inference features")
        result = {}
        drift_cache = {}
        for horizon in HORIZONS:
            expert = {}
            for name in MODEL_NAMES:
                payload = self.payloads[name, horizon]
                if name == "ridge":
                    value = (((x.to_numpy() - payload["scaler_mean"]) / payload["scaler_scale"])
                             @ np.asarray(payload["coefficients"]) + payload["intercept"])[0]
                elif name == "lightgbm":
                    value = self.trees[horizon].predict(x, num_threads=1)[0]
                elif name == "kalman":
                    if payload["coefficient"] == 0:
                        value = 0.0
                    else:
                        key = (payload["observation_variance"], payload["process_to_observation_ratio"])
                        if key not in drift_cache:
                            drift_cache[key] = kalman_drift(np.log(btc_history["close"].to_numpy(dtype=float)), *key)[-1]
                        value = payload["coefficient"] * drift_cache[key] * (horizon / 5)
                else:
                    value = payload["coefficient"] * statistical_signal(name, feature_row, horizon)[0]
                if not np.isfinite(value):
                    raise ValueError(f"Nonfinite forecast from {name}")
                expert[name] = float(value)
            mean = float(mix_forecasts(expert, self.config["ensemble"]))
            dispersion = float(np.sqrt(sum(self.config["ensemble"][name] * (value - mean) ** 2 for name, value in expert.items())))
            result[str(horizon)] = {"experts": expert, "committee_mu": mean, "dispersion": dispersion}
        return result
