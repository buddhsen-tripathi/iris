import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

from alphacouncil.backtest.paper import edge_threshold_log, simulate_policy
from alphacouncil.models.experts import (
    export_expert, fit_expert, fit_coefficient, kalman_drift, mix_forecasts, predict_expert,
)
from alphacouncil.models.targets import HORIZONS, build_targets, matured_mask


def target_candles():
    times = pd.date_range("2026-01-01T00:05:00Z", periods=100, freq="5min")
    return pd.DataFrame({"open_time_utc": times - pd.Timedelta(minutes=5), "close_time_utc": times,
                         "open": np.exp(np.arange(100) * 0.001) * 100,
                         "close": np.exp(np.arange(100) * 0.001) * 100, "is_complete": True})


def test_targets_use_exact_future_prices_and_record_separate_maturity():
    candles = target_candles()
    before = candles["close_time_utc"].iloc[-1] + pd.Timedelta(minutes=5)
    targets = build_targets(candles, before)
    for horizon in HORIZONS:
        bars = horizon // 5
        assert targets.iloc[0][f"target_{horizon}m"] == pytest.approx(0.001 * bars)
        assert targets.iloc[0][f"matures_{horizon}m_utc"] == targets.iloc[0]["decision_time_utc"] + pd.Timedelta(minutes=horizon)
        assert targets[f"target_{horizon}m"].tail(bars).isna().all()


def test_reserved_outcomes_cannot_change_training_labels():
    candles = target_candles()
    reserved = candles["close_time_utc"].iloc[80]
    first = build_targets(candles, reserved)
    changed = candles.copy()
    changed.loc[changed["close_time_utc"].ge(reserved), "close"] = 1e12
    pd.testing.assert_frame_equal(first, build_targets(changed, reserved))
    for horizon in HORIZONS:
        assert first[f"matures_{horizon}m_utc"].dropna().lt(reserved).all()


def test_partition_masks_purge_labels_crossing_boundary():
    candles = target_candles()
    targets = build_targets(candles, pd.Timestamp("2026-01-02T00:00:00Z"))
    boundary = pd.Timestamp("2026-01-01T05:00:00Z")
    mask = matured_mask(targets, pd.Timestamp("2026-01-01T00:00:00Z"), boundary)
    assert targets.loc[mask, "matures_30m_utc"].lt(boundary).all()
    crossing = targets["decision_time_utc"].ge(boundary - pd.Timedelta(minutes=30)) & targets["decision_time_utc"].lt(boundary)
    assert not mask.loc[crossing].any()
    with pytest.raises(ValueError, match="missing"):
        build_targets(candles.drop(index=40), pd.Timestamp("2026-01-02T00:00:00Z"))


def test_kalman_is_forward_only_and_reproducible():
    prices = np.log(100 + np.arange(200) * 0.1)
    original = kalman_drift(prices, 0.001, 0.0001)
    altered = prices.copy()
    altered[100:] += 1
    np.testing.assert_array_equal(original[:100], kalman_drift(altered, 0.001, 0.0001)[:100])
    np.testing.assert_array_equal(original[:100], kalman_drift(prices[:100], 0.001, 0.0001))
    assert fit_coefficient(np.array([1., 2., 3.]), np.array([-1., -2., -3.])) == 0


def test_committee_uses_exact_saved_weights():
    experts = {"a": np.array([0.01, -0.02]), "b": np.array([-0.03, 0.01])}
    np.testing.assert_allclose(mix_forecasts(experts, {"a": 0.25, "b": 0.75}), [-0.02, 0.0025])
    with pytest.raises(ValueError, match="sum"):
        mix_forecasts(experts, {"a": 1., "b": 1.})


def test_ridge_scaling_is_fitted_only_on_training_rows_and_json_matches():
    config = json.loads(Path("configs/training_5_15_30.json").read_text())
    rng = np.random.default_rng(2)
    table = pd.DataFrame(rng.normal(size=(200, len(config["features"]))), columns=config["features"])
    table["target_5m"] = table["return_5m"] * 0.001
    mask = pd.Series(np.arange(200) < 100)
    model = fit_expert("ridge", 1., table, mask, 5, config)
    changed = table.copy()
    changed.loc[~mask, config["features"]] = 1e10
    changed.loc[~mask, "target_5m"] = -1e10
    second = fit_expert("ridge", 1., changed, mask, 5, config)
    # pandas block layouts can change reduction rounding at machine precision.
    np.testing.assert_allclose(model.steps[0][1].mean_, second.steps[0][1].mean_, rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(model.steps[1][1].coef_, second.steps[1][1].coef_, rtol=1e-12, atol=1e-14)
    payload = json.loads(json.dumps(export_expert("ridge", model, config["features"])))
    expected = ((table[config["features"]].to_numpy() - payload["scaler_mean"]) / payload["scaler_scale"]) @ np.asarray(payload["coefficients"]) + payload["intercept"]
    np.testing.assert_allclose(expected, predict_expert("ridge", model, table, config, 5), atol=1e-15)


@pytest.fixture
def paper_inputs():
    times = pd.date_range("2026-01-01T00:00:00Z", periods=13, freq="5min")
    predictions = pd.DataFrame({"decision_time_utc": times[:-1], "committee_5m": 0.01,
                                "committee_15m": 0.02, "committee_30m": 0.03})
    candles = pd.DataFrame({"open_time_utc": times, "open": 100.0,
                            "close": 999.0})  # Deliberately different: fills must use next opens.
    config = json.loads(Path("configs/training_5_15_30.json").read_text())
    scenario = {"name": "test", "fee_bps_per_side": 10., "impact_bps_per_side": 2.}
    return predictions, candles, times[0], times[-1] + pd.Timedelta(seconds=1), scenario, config["paper"]


def replay(inputs, policy="five_minute_only"):
    p, c, start, end, scenario, settings = inputs
    return simulate_policy(p, c, start, end, policy, scenario, settings)


def test_paper_fills_use_next_opens_with_two_sided_costs_and_no_overlap(paper_inputs):
    result = replay(paper_inputs)
    trades = result["trades"]
    assert len(trades) == 12
    assert result["summary"]["maximum_entries_in_utc_hour"] == 12
    assert trades["entry_open_proxy"].eq(100).all()
    assert trades["assumed_entry_fill"].gt(100).all()
    assert trades["assumed_exit_fill"].lt(100).all()
    assert trades["cash_allocated_usdt"].le(10).all()
    assert trades["entry_time_utc"].iloc[1:].reset_index(drop=True).ge(trades["exit_time_utc"].iloc[:-1].reset_index(drop=True)).all()
    expected = trades["gross_mid_pnl_usdt"] - trades["execution_impact_usdt"] - trades["entry_fee_usdt"] - trades["exit_fee_usdt"]
    np.testing.assert_allclose(trades["net_pnl_usdt"], expected, atol=1e-12)
    assert result["summary"]["net_pnl_usdt"] < 0


def test_confirmation_vetoes_an_opposed_longer_horizon(paper_inputs):
    paper_inputs[0]["committee_15m"] = -0.01
    assert replay(paper_inputs)["summary"]["completed_trades"] == 12
    confirmed = replay(paper_inputs, "with_15m_30m_confirmation")
    assert confirmed["summary"]["completed_trades"] == 0
    assert confirmed["summary"]["reason_counts"] == {"LONGER_HORIZON_DISAGREEMENT": 12}


def test_small_edge_or_missing_execution_prices_abstain(paper_inputs):
    paper_inputs[0]["committee_5m"] = 0.0001
    result = replay(paper_inputs)
    assert result["summary"]["completed_trades"] == 0
    assert {"entry_time_utc", "net_pnl_usdt"}.issubset(result["trades"].columns)
    paper_inputs[0]["committee_5m"] = 0.01
    paper_inputs[1].drop(index=paper_inputs[1].index, inplace=True)
    assert replay(paper_inputs)["summary"]["completed_trades"] == 0


def test_missing_future_exit_is_not_used_as_a_foreknown_entry_veto(paper_inputs):
    paper_inputs[1].drop(index=1, inplace=True)
    with pytest.raises(ValueError, match="cannot settle"):
        replay(paper_inputs)


def test_future_exit_price_cannot_change_first_entry_and_replay_is_deterministic(paper_inputs):
    original = replay(paper_inputs)
    pd.testing.assert_frame_equal(original["trades"], replay(paper_inputs)["trades"])
    altered = list(paper_inputs)
    altered[1] = altered[1].copy()
    altered[1].loc[1:, "open"] = 1000
    changed = replay(altered)
    for column in ["entry_time_utc", "entry_open_proxy", "assumed_entry_fill", "quantity_btc", "cash_allocated_usdt"]:
        assert original["trades"].iloc[0][column] == changed["trades"].iloc[0][column]
    assert original["trades"].iloc[0]["net_pnl_usdt"] != changed["trades"].iloc[0]["net_pnl_usdt"]


def test_cost_threshold_matches_exact_flat_round_trip_break_even():
    fee, impact = 0.001, 0.0002
    threshold = np.expm1(edge_threshold_log(10, 2, 0))
    ratio_after_costs = (1 + threshold) * (1 - impact) * (1 - fee) / ((1 + impact) * (1 + fee))
    assert ratio_after_costs == pytest.approx(1)
