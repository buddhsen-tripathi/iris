import json
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from alphacouncil.data.true_reference import normalize_candles, normalize_funding, save_reference


def fixture_candles(tmp_path):
    candles = [
        {"t": value.isoformat(), "open": "10.123456789123", "high": "11", "low": "9", "close": "10"}
        for value in pd.date_range("2026-10-23T00:00:00Z", periods=289, freq="5min")
    ]
    payload = {"symbol": "BTC", "asset_id": "asset-123", "resolution": "5m", "candles": candles}
    path = tmp_path / "response.json"
    path.write_text(json.dumps(payload))
    record = {"path": path.name, "url": "https://api.truemarkets.co/example", "sha256": "a" * 64,
              "retrieved_at_utc": "2026-10-24T12:00:00Z", "day_end_utc": "2026-10-24"}
    return payload, record, path


def test_reference_excludes_partial_end_bucket_and_keeps_unknowns_null(tmp_path):
    _, record, _ = fixture_candles(tmp_path)
    frame, report = normalize_candles([record], tmp_path, "BTC", date(2026, 10, 23), date(2026, 10, 24))
    assert len(frame) == 288
    assert report["excluded_out_of_window_or_incomplete"] == 1
    assert report["coverage"] == "complete"
    assert frame["volume_base"].isna().all()
    assert frame["quote_currency"].isna().all()
    assert frame["venue"].isna().all()
    path = tmp_path / "reference.parquet"
    save_reference(frame, path)
    loaded = pd.read_parquet(path)
    assert loaded.iloc[0]["open"] == Decimal("10.123456789123")
    assert loaded["volume_base"].isna().all()


def test_reference_gaps_are_reported_without_interpolation(tmp_path):
    payload, record, path = fixture_candles(tmp_path)
    del payload["candles"][12]
    path.write_text(json.dumps(payload))
    frame, report = normalize_candles([record], tmp_path, "BTC", date(2026, 10, 23), date(2026, 10, 24))
    assert len(frame) == 287
    assert report["missing_count"] == 1
    assert report["coverage"] == "gapped"


@pytest.mark.parametrize("mutation", ["duplicate", "ohlc", "asset"])
def test_reference_rejects_corruption(tmp_path, mutation):
    payload, record, path = fixture_candles(tmp_path)
    if mutation == "duplicate":
        payload["candles"].insert(0, payload["candles"][0])
    elif mutation == "ohlc":
        payload["candles"][0]["high"] = "1"
    else:
        payload["symbol"] = "SOL"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        normalize_candles([record], tmp_path, "BTC", date(2026, 10, 23), date(2026, 10, 24))


def test_funding_preserves_units_negative_rates_and_gaps():
    payload = {"symbol": "BTC", "asset_id": "perp-123", "resolution": "1h", "points": [
        {"t": "2026-10-24T09:00:00Z", "funding_rate": "-0.0000125", "open_interest": "100.5"},
        {"t": "2026-10-24T11:00:00Z", "funding_rate": "0.0000125", "open_interest": "101.5"},
    ]}
    record = {"symbol": "BTC", "url": "https://api.truemarkets.co/example", "sha256": "a" * 64,
              "retrieved_at_utc": "2026-10-24T12:00:00Z"}
    frame, report = normalize_funding(payload, record)
    assert frame.iloc[0]["funding_rate"] == Decimal("-0.0000125")
    assert frame.iloc[0]["funding_rate_unit"] == "hourly_decimal_fraction"
    assert frame.iloc[0]["open_interest_unit"] == "base_asset_coin_count"
    assert report["missing_count_between_endpoints"] == 1
    assert len(frame) == 2
    payload["points"][1]["t"] = "2026-10-24T13:00:00Z"
    with pytest.raises(ValueError, match="future"):
        normalize_funding(payload, record)
