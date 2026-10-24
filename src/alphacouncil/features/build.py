"""Causal BTC features from completed, explicitly identified Binance spot candles."""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

VERSION = "btc-causal-v1"


@dataclass(frozen=True)
class Feature:
    name: str
    family: str
    formula: str
    use: str


FEATURES = (
    Feature("return_5m", "trend", "log(C[t]/C[t-1])", "Recent direction; large magnitude also signals a shock."),
    Feature("return_15m", "trend", "log(C[t]/C[t-3])", "Short trend input to momentum and linear experts."),
    Feature("return_30m", "trend", "log(C[t]/C[t-6])", "Intermediate trend; compare with shorter returns."),
    Feature("return_60m", "trend", "log(C[t]/C[t-12])", "One-hour trend; overlaps shorter returns."),
    Feature("ema_gap_12_48", "trend", "(EMA12(log C)-EMA48(log C))/(std48(r)*sqrt(12))", "Volatility-scaled trend strength, not a forecast."),
    Feature("price_z_48", "reversion", "(log C[t]-mean(log C[t-48:t-1]))/std(log C[t-48:t-1])", "Distance from the preceding 4h price distribution; snapback is a hypothesis."),
    Feature("rsi_14_centered", "reversion", "2*WilderEWMA14(gains)/(WilderEWMA14(gains)+WilderEWMA14(losses))-1", "Bounded price pressure; trend persistence and reversal are both possible."),
    Feature("realized_vol_12", "volatility", "std12(r)*sqrt(12), sample std", "Trailing 1h risk context; no direction implied."),
    Feature("realized_vol_48", "volatility", "std48(r)*sqrt(48), sample std", "Trailing 4h risk context; no direction implied."),
    Feature("vol_ratio_12_48", "volatility", "std12(r)/std48(r)", "Short volatility expansion relative to the 4h window."),
    Feature("atr_14_fraction", "volatility", "WilderEWMA14(max(H-L,abs(H-Cprev),abs(L-Cprev)))/C", "Typical range relative to price; a risk input, not spread or a guaranteed stop distance."),
    Feature("close_location", "candle", "2*(C-L)/(H-L)-1; flat bar=0", "Where the close sits inside the completed candle."),
    Feature("body_fraction", "candle", "(C-O)/(H-L); flat bar=0", "Signed body relative to candle range."),
    Feature("range_fraction", "candle", "(H-L)/C", "Single-bar price expansion, not executable spread."),
    Feature("log_quote_volume_z_288", "activity", "(log1p(Vquote[t])-prior_mean288(log1p Vquote))/prior_std288(log1p Vquote)", "Unusual USDT turnover relative to the preceding day."),
    Feature("log_trade_count_z_288", "activity", "(log1p(N[t])-prior_mean288(log1p N))/prior_std288(log1p N)", "Unusual activity; often redundant with turnover."),
    Feature("taker_buy_imbalance", "activity", "2*taker_buy_base_volume/base_volume-1; zero volume=missing", "Aggressor-buy share of executed volume; not order-book imbalance."),
    Feature("log_illiquidity_48", "activity", "log1p(1e6*mean48(abs(r)/Vquote)); zero volume=missing", "Backward price-impact proxy per USDT of volume; not a fill/slippage estimate."),
    Feature("btc_eth_relative_60m", "cross_asset", "BTC_return60m-ETH_return60m", "Relative BTC strength; the sign is not a proven trading rule."),
    Feature("eth_return_15m", "cross_asset", "log(ETH_C[t]/ETH_C[t-3])", "Contemporaneous ETH market context available at the same bar close."),
    Feature("btc_eth_correlation_288", "cross_asset", "corr288(BTC_r,ETH_r)", "Trailing 24h co-movement; no causation or lead/lag claim."),
    Feature("btc_sol_relative_60m", "cross_asset", "BTC_return60m-SOL_return60m", "Relative BTC/SOL strength; controls overlap via the redundancy audit."),
    Feature("hourly_return_6h", "hourly_context", "log(last completed BTC hourly C / hourly C six bars earlier)", "Slower trend context, joined backward on hourly close time."),
    Feature("hourly_realized_vol_24", "hourly_context", "std24(completed hourly log returns)*sqrt(24)", "Trailing daily volatility context from completed hourly bars."),
    Feature("utc_time_sin", "calendar", "sin(2*pi*UTC decision minute_of_day/1440)", "Time-of-day context; always use with the cosine partner."),
    Feature("utc_time_cos", "calendar", "cos(2*pi*UTC decision minute_of_day/1440)", "Time-of-day context; no standalone buy/sell interpretation."),
)
NAMES = [feature.name for feature in FEATURES]


def definitions() -> list[dict]:
    return [asdict(feature) for feature in FEATURES]


def numeric_candles(frame: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
    """Reject gaps, duplicates, mixed venues, and incomplete bars before rolling."""
    if frame.empty:
        raise ValueError("Empty candle input")
    for column, expected in {
        "instrument_id": symbol, "interval": interval, "venue": "binance",
        "instrument_type": "spot", "quote_currency": "USDT",
    }.items():
        if not frame[column].eq(expected).all():
            raise ValueError(f"Unexpected {column}; expected {expected}")
    times = pd.DatetimeIndex(frame["close_time_utc"])
    if str(times.tz) != "UTC" or times.hasnans or not times.is_monotonic_increasing or times.has_duplicates:
        raise ValueError("Candle times must be unique, sorted UTC timestamps")
    step = pd.Timedelta(minutes=5) if interval == "5m" else pd.Timedelta(hours=1)
    if len(times) > 1 and not times.to_series().diff().iloc[1:].eq(step).all():
        raise ValueError("Gaps in candle input; rolling features must not bridge outages")
    if not (frame["close_time_utc"] - frame["open_time_utc"]).eq(step).all():
        raise ValueError("Incorrect candle duration")
    if not frame["is_complete"].eq(True).all():
        raise ValueError("Incomplete candle input")
    columns = ["open", "high", "low", "close", "volume_base", "volume_quote", "trade_count", "taker_buy_volume_base"]
    values = frame[columns].astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("Nonfinite candle value")
    if not values[["open", "high", "low", "close"]].gt(0).all().all():
        raise ValueError("Nonpositive price")
    if not (values["high"].ge(values[["open", "close"]].max(axis=1)) & values["low"].le(values[["open", "close"]].min(axis=1))).all():
        raise ValueError("Invalid OHLC bounds")
    if not values[columns[4:]].ge(0).all().all() or not values["taker_buy_volume_base"].le(values["volume_base"] + 1e-8).all():
        raise ValueError("Invalid volume/trade count")
    values.index = times
    return values


def prior_z(series: pd.Series, window: int) -> pd.Series:
    previous = series.shift(1).rolling(window, min_periods=window)
    return (series - previous.mean()) / previous.std(ddof=1).replace(0, np.nan)


def build_features(btc: pd.DataFrame, eth: pd.DataFrame, sol: pd.DataFrame, hourly_btc: pd.DataFrame) -> pd.DataFrame:
    b = numeric_candles(btc, "BTCUSDT", "5m")
    e = numeric_candles(eth, "ETHUSDT", "5m").reindex(b.index)
    s = numeric_candles(sol, "SOLUSDT", "5m").reindex(b.index)
    h = numeric_candles(hourly_btc, "BTCUSDT", "1h")
    log_close = np.log(b["close"])
    returns = log_close.diff()
    vol12 = returns.rolling(12, min_periods=12).std(ddof=1)
    vol48 = returns.rolling(48, min_periods=48).std(ddof=1)
    result = pd.DataFrame(index=b.index)
    for minutes, bars in ((5, 1), (15, 3), (30, 6), (60, 12)):
        result[f"return_{minutes}m"] = log_close.diff(bars)
    fast = log_close.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = log_close.ewm(span=48, adjust=False, min_periods=48).mean()
    result["ema_gap_12_48"] = (fast - slow) / (vol48.replace(0, np.nan) * np.sqrt(12))
    result["price_z_48"] = prior_z(log_close, 48)
    change = b["close"].diff()
    gain = change.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    total_move = gain + loss
    result["rsi_14_centered"] = (2 * gain / total_move.replace(0, np.nan) - 1).mask(total_move.eq(0), 0)
    result["realized_vol_12"] = vol12 * np.sqrt(12)
    result["realized_vol_48"] = vol48 * np.sqrt(48)
    result["vol_ratio_12_48"] = vol12 / vol48.replace(0, np.nan)
    true_range = pd.concat([
        b["high"] - b["low"], (b["high"] - b["close"].shift(1)).abs(),
        (b["low"] - b["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    result["atr_14_fraction"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / b["close"]
    bar_range = b["high"] - b["low"]
    result["close_location"] = (2 * (b["close"] - b["low"]) / bar_range.replace(0, np.nan) - 1).mask(bar_range.eq(0), 0)
    result["body_fraction"] = ((b["close"] - b["open"]) / bar_range.replace(0, np.nan)).mask(bar_range.eq(0), 0)
    result["range_fraction"] = bar_range / b["close"]
    result["log_quote_volume_z_288"] = prior_z(np.log1p(b["volume_quote"]), 288)
    result["log_trade_count_z_288"] = prior_z(np.log1p(b["trade_count"]), 288)
    result["taker_buy_imbalance"] = 2 * b["taker_buy_volume_base"] / b["volume_base"].replace(0, np.nan) - 1
    impact = returns.abs() / b["volume_quote"].replace(0, np.nan)
    result["log_illiquidity_48"] = np.log1p(1e6 * impact.rolling(48, min_periods=48).mean())
    eth_returns = np.log(e["close"]).diff()
    result["btc_eth_relative_60m"] = log_close.diff(12) - np.log(e["close"]).diff(12)
    result["eth_return_15m"] = np.log(e["close"]).diff(3)
    result["btc_eth_correlation_288"] = returns.rolling(288, min_periods=288).corr(eth_returns)
    result["btc_sol_relative_60m"] = log_close.diff(12) - np.log(s["close"]).diff(12)
    hourly_log = np.log(h["close"])
    hourly = pd.DataFrame({
        "hourly_return_6h": hourly_log.diff(6),
        "hourly_realized_vol_24": hourly_log.diff().rolling(24, min_periods=24).std(ddof=1) * np.sqrt(24),
    }, index=h.index).rename_axis("hourly_context_close_time_utc").reset_index()
    result = result.rename_axis("decision_time_utc").reset_index()
    result = pd.merge_asof(
        result, hourly, left_on="decision_time_utc", right_on="hourly_context_close_time_utc",
        direction="backward", tolerance=pd.Timedelta(minutes=55), allow_exact_matches=True,
    )
    minutes = result["decision_time_utc"].dt.hour * 60 + result["decision_time_utc"].dt.minute
    result["utc_time_sin"] = np.sin(2 * np.pi * minutes / 1440)
    result["utc_time_cos"] = np.cos(2 * np.pi * minutes / 1440)
    result[NAMES] = result[NAMES].replace([np.inf, -np.inf], np.nan)
    result["all_features_available"] = result[NAMES].notna().all(axis=1)
    return result[["decision_time_utc", "hourly_context_close_time_utc", "all_features_available", *NAMES]]
