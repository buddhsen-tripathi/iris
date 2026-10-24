"""Explicitly timestamped targets that cannot cross the reserved data boundary."""

import numpy as np
import pandas as pd

HORIZONS = (5, 15, 30)


def build_targets(candles: pd.DataFrame, before: pd.Timestamp) -> pd.DataFrame:
    # Filter before accessing close values: reserved outcomes are never constructed.
    source = candles.loc[candles["close_time_utc"].lt(before)].copy()
    times = pd.DatetimeIndex(source["close_time_utc"])
    if str(times.tz) != "UTC" or times.hasnans or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError("Target source must have unique ascending UTC close times")
    if len(times) > 1 and not times.to_series().diff().iloc[1:].eq(pd.Timedelta(minutes=5)).all():
        raise ValueError("Targets cannot bridge missing source bars")
    if not source["is_complete"].eq(True).all():
        raise ValueError("Incomplete target candle")
    values = pd.Series(source["close"].to_numpy(dtype=float), index=times)
    if not np.isfinite(values).all() or not values.gt(0).all():
        raise ValueError("Invalid target source price")
    result = pd.DataFrame({"decision_time_utc": times})
    for horizon in HORIZONS:
        maturity = times + pd.Timedelta(minutes=horizon)
        future = values.reindex(maturity).to_numpy()
        result[f"target_{horizon}m"] = np.log(future / values.to_numpy())
        result[f"matures_{horizon}m_utc"] = pd.Series(maturity).where(np.isfinite(future), pd.NaT)
    return result


def matured_mask(table: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """All horizons must be labeled strictly before the partition boundary."""
    times = table["decision_time_utc"]
    result = times.ge(start) & times.lt(end)
    for horizon in HORIZONS:
        result &= table[f"target_{horizon}m"].notna() & table[f"matures_{horizon}m_utc"].lt(end)
    return result
