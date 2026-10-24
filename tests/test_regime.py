import json
from pathlib import Path

import pandas as pd
import pytest

from alphacouncil.committee.regime import classify_regime, shrink_regime_weights

CONFIG = json.loads(Path("configs/regime.json").read_text())
T = pd.Timestamp("2026-10-24T15:00:00Z")
FEATURES = {"return_60m": .003, "realized_vol_48": .004, "vol_ratio_12_48": 1.0}
GLOBAL = {"a": .2, "b": .8}
BUCKET = {"a": .8, "b": .2}


def classify(features, **kwargs):
    return classify_regime(features, T, T, T, CONFIG, **kwargs)


def mix(count, **kwargs):
    return shrink_regime_weights(GLOBAL, BUCKET, count, T, T, T, CONFIG, **kwargs)


def test_fixed_regimes_and_priority():
    assert classify(FEATURES)["regime"] == "trend"
    assert classify({**FEATURES,"return_60m": -.003})["diagnostics"]["trend_direction"] == "down"
    assert classify({**FEATURES,"return_60m": .0001})["regime"] == "range"
    assert classify({**FEATURES,"realized_vol_48": .02})["regime"] == "high_vol"
    assert classify({**FEATURES,"vol_ratio_12_48": 1.5})["regime"] == "high_vol"
    assert classify(FEATURES)["conditional_weights_enabled"] is False


def test_future_or_incomplete_features_are_rejected():
    with pytest.raises(ValueError, match="completed"):
        classify(FEATURES, completed=False)
    with pytest.raises(ValueError, match="already observed"):
        classify_regime(FEATURES,T,T+pd.Timedelta(seconds=1),T,CONFIG)
    with pytest.raises(ValueError, match="already observed"):
        classify_regime(FEATURES,T+pd.Timedelta(seconds=1),T,T,CONFIG)
    for field in FEATURES:
        with pytest.raises(ValueError, match="Finite"):
            classify({**FEATURES,field:float("nan")})


def test_future_rows_cannot_change_historical_regime():
    history = [(T, FEATURES), (T+pd.Timedelta(minutes=5), {**FEATURES,"return_60m": .1})]
    selected = max((row for row in history if row[0] <= T), key=lambda row:row[0])
    first = classify(selected[1])
    history[1] = (history[1][0], {**FEATURES,"realized_vol_48": 100})
    selected = max((row for row in history if row[0] <= T), key=lambda row:row[0])
    assert classify(selected[1]) == first


def test_insufficient_bucket_count_falls_back_to_global():
    for count in (0,1,29):
        snapshot = mix(count)
        assert snapshot["alpha"] == 0
        assert snapshot["weights"] == GLOBAL
    empty = shrink_regime_weights(GLOBAL,None,0,T,None,T,CONFIG)
    assert empty["weights"] == GLOBAL


def test_bucket_shrinkage_normalized_and_deterministic():
    result = mix(100)
    assert result["alpha"] == .5
    assert result["weights"] == pytest.approx({"a":.5,"b":.5})
    assert sum(result["weights"].values()) == pytest.approx(1)
    assert result == mix(100)
    assert mix(30)["alpha"] == pytest.approx(30/130)


def test_future_weights_and_bad_normalization_rejected():
    for global_time,bucket_time in ((T+pd.Timedelta(seconds=1),T),(T,T+pd.Timedelta(seconds=1))):
        with pytest.raises(ValueError, match="future|already observed"):
            shrink_regime_weights(GLOBAL,BUCKET,100,global_time,bucket_time,T,CONFIG)
    for invalid in ({"a":.5,"b":.6},{"a":float("nan"),"b":1},{"a":-1,"b":2}):
        with pytest.raises(ValueError, match="sum to one"):
            shrink_regime_weights(invalid,BUCKET,100,T,T,T,CONFIG)
    with pytest.raises(ValueError, match="sets must match"):
        shrink_regime_weights(GLOBAL,{"a":.2,"c":.8},100,T,T,T,CONFIG)
    with pytest.raises(ValueError, match="nonnegative integer"):
        mix(-1)
    with pytest.raises(ValueError, match="auditable"):
        shrink_regime_weights(GLOBAL,None,100,T,None,T,CONFIG)
