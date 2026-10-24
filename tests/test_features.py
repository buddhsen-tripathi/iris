import numpy as np
import pandas as pd
import pytest

from alphacouncil.features.audit import audit_features, normalize_after_calibration
from alphacouncil.features.build import NAMES, build_features, prior_z


def candles(symbol, times, step, seed):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(times))))
    opened = np.r_[close[0], close[:-1]]
    volume = rng.uniform(1, 10, len(times))
    return pd.DataFrame({
        "venue": "binance", "instrument_id": symbol, "instrument_type": "spot", "quote_currency": "USDT",
        "interval": "5m" if step == pd.Timedelta(minutes=5) else "1h",
        "open_time_utc": times - step, "close_time_utc": times, "is_complete": True,
        "open": opened, "close": close, "high": np.maximum(opened, close) * 1.001,
        "low": np.minimum(opened, close) * 0.999, "volume_base": volume,
        "volume_quote": volume * close, "trade_count": rng.integers(10, 100, len(times)),
        "taker_buy_volume_base": volume * rng.uniform(0.1, 0.9, len(times)),
    })


@pytest.fixture
def inputs():
    times = pd.date_range("2026-01-04T00:05:00Z", periods=4032, freq="5min")
    hours = pd.date_range("2026-01-01T01:00:00Z", "2026-01-18T00:00:00Z", freq="1h")
    return [
        candles("BTCUSDT", times, pd.Timedelta(minutes=5), 1),
        candles("ETHUSDT", times, pd.Timedelta(minutes=5), 2),
        candles("SOLUSDT", times, pd.Timedelta(minutes=5), 3),
        candles("BTCUSDT", hours, pd.Timedelta(hours=1), 4),
    ]


def test_future_prices_volumes_and_hourly_bars_cannot_change_past_features(inputs):
    original = build_features(*inputs)
    cutoff = original["decision_time_utc"].iloc[2500]
    perturbed = [frame.copy() for frame in inputs]
    for frame in perturbed:
        mask = frame["close_time_utc"].gt(cutoff)
        frame.loc[mask, ["open", "close", "high", "low"]] *= 2
        frame.loc[mask, ["volume_base", "volume_quote", "taker_buy_volume_base", "trade_count"]] *= 3
    actual = build_features(*perturbed)
    past = original["decision_time_utc"].le(cutoff)
    pd.testing.assert_frame_equal(original.loc[past], actual.loc[past])
    prefixes = [frame.loc[frame["close_time_utc"].le(cutoff)].copy() for frame in inputs]
    pd.testing.assert_frame_equal(original.loc[past], build_features(*prefixes))


def test_hourly_features_never_see_an_uncompleted_hour(inputs):
    result = build_features(*inputs)
    age = result["decision_time_utc"] - result["hourly_context_close_time_utc"]
    assert age.ge(pd.Timedelta(0)).all()
    assert age.le(pd.Timedelta(minutes=55)).all()
    row = result.loc[result["decision_time_utc"].eq(pd.Timestamp("2026-01-04T10:55:00Z"))].iloc[0]
    assert row["hourly_context_close_time_utc"] == pd.Timestamp("2026-01-04T10:00:00Z")


def test_candle_gaps_and_incomplete_inputs_are_rejected(inputs):
    bad = inputs.copy()
    bad[0] = bad[0].drop(index=400)
    with pytest.raises(ValueError, match="Gaps"):
        build_features(*bad)
    bad[0] = inputs[0].copy()
    bad[0].loc[400, "is_complete"] = False
    with pytest.raises(ValueError, match="Incomplete"):
        build_features(*bad)


def test_zero_volume_and_flat_bar_remain_explicit(inputs):
    b = inputs[0].copy()
    last = b.index[-1]
    b.loc[last, ["open", "high", "low"]] = b.loc[last, "close"]
    b.loc[last, ["volume_base", "volume_quote", "taker_buy_volume_base"]] = 0
    result = build_features(b, *inputs[1:])
    assert result.iloc[-1]["close_location"] == 0
    assert result.iloc[-1]["body_fraction"] == 0
    assert pd.isna(result.iloc[-1]["taker_buy_imbalance"])
    assert not np.isinf(result[NAMES].to_numpy()).any()


def test_prior_z_excludes_current_observation_from_reference():
    series = pd.Series(np.arange(60, dtype=float))
    series.iloc[-1] = 1000
    expected = (1000 - series.iloc[11:59].mean()) / series.iloc[11:59].std(ddof=1)
    assert prior_z(series, 48).iloc[-1] == pytest.approx(expected)


def test_priority_weights_and_scaler_ignore_reserved_future(inputs):
    frame = build_features(*inputs)
    fit_end = pd.Timestamp("2026-01-10T00:00:00Z")
    holdout = pd.Timestamp("2026-01-14T00:00:00Z")
    first = audit_features(frame, fit_end, holdout)
    perturbed = frame.copy()
    perturbed.loc[perturbed["decision_time_utc"].ge(holdout), NAMES] = 1e12
    second = audit_features(perturbed, fit_end, holdout)
    pd.testing.assert_frame_equal(first["metrics"], second["metrics"])
    assert first["scaler"] == second["scaler"]
    weights = first["metrics"]["priority_weight"]
    assert weights.sum() == pytest.approx(1)
    assert weights.ge(0).all()
    family_totals = first["metrics"].groupby("family")["priority_weight"].sum()
    assert np.allclose(family_totals, 1 / len(family_totals))
    normalized = normalize_after_calibration(frame, first["scaler"], fit_end)
    assert normalized.loc[normalized["decision_time_utc"].lt(fit_end), NAMES].isna().all().all()
    assert set(frame.columns) == {"decision_time_utc", "hourly_context_close_time_utc", "all_features_available", *NAMES}
