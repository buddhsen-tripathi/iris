# Collected market data

Generated from saved collection manifests. Source data have been downloaded, normalized, and checked. Subsequent model training is documented separately in the [training report](../reports/model_training_5_15_30.md).

## Primary dataset: Binance spot

Collection finished: 2026-10-24T12:22:46.065654+00:00. End date: **2026-10-24 00:00 UTC, exclusive**.

| Instrument | Interval | UTC start | UTC end (exclusive) | Candles | Missing | Duplicates |
| --- | --- | --- | --- | ---: | ---: | ---: |
| BTCUSDT | 5m | 2025-10-24 | 2026-10-24 | 105,120 | 0 | 0 |
| ETHUSDT | 5m | 2025-10-24 | 2026-10-24 | 105,120 | 0 | 0 |
| SOLUSDT | 5m | 2025-10-24 | 2026-10-24 | 105,120 | 0 | 0 |
| BTCUSDT | 1h | 2024-10-24 | 2026-10-24 | 17,520 | 0 | 0 |
| ETHUSDT | 1h | 2024-10-24 | 2026-10-24 | 17,520 | 0 | 0 |

**350,400 candles**, 31.89 MiB of current Parquet files, from **199 provider-checksummed archives**. All primary datasets passed complete-grid, UTC, duplicate, OHLC, volume, completion-time, and provenance checks.

[Pinned manifest](manifests/20261024T122241389043Z.json) · [Current manifest](manifests/latest.json)

These are Binance spot prices quoted in USDT. They are not True Markets execution prices.

## True Markets reference data

Requested candle coverage: **2026-04-27 to 2026-10-24 UTC, exclusive**. Collection finished: 2026-10-24T12:25:47.195167+00:00.

| Asset | Data | Rows | First observation (UTC) | Last observation / bar end (UTC) | Missing buckets |
| --- | --- | ---: | --- | --- | ---: |
| BTC | 5m reference OHLC | 51,835 | 2026-04-27T00:00:00+00:00 | 2026-10-24T00:00:00+00:00 | 5 |
| ETH | 5m reference OHLC | 46,992 | 2026-05-13T19:40:00+00:00 | 2026-10-24T00:00:00+00:00 | 4,848 |
| SOL | 5m reference OHLC | 51,769 | 2026-04-27T00:00:00+00:00 | 2026-10-24T00:00:00+00:00 | 71 |
| BTC | 1h funding + open interest | 718 | 2026-09-24T13:00:00+00:00 | 2026-10-24T12:00:00+00:00 | 2 |
| ETH | 1h funding + open interest | 718 | 2026-09-24T13:00:00+00:00 | 2026-10-24T12:00:00+00:00 | 2 |
| SOL | 1h funding + open interest | 718 | 2026-09-24T13:00:00+00:00 | 2026-10-24T12:00:00+00:00 | 2 |

**16 requested whole days were unavailable**. Candle missing counts cover the full requested 180-day grid, including missing early ETH history. Funding missing counts cover the range between each series' observed endpoints. No gaps were filled.

Validation passing means the returned values passed structural checks; it does **not** mean coverage is complete. Use contiguous windows when adding features and labels later.

The candle API omits volume, trade count, quote currency, and the underlying source venue. Those fields remain null. Asset UUIDs, decimal prices, source URLs, hashes, and retrieval timestamps are preserved. Reference prices are kept separate from exchange candles and are not executable quotes.

Funding is an hourly decimal fraction; open interest is a base-asset coin count. Negative funding is allowed. These observations do not prove account access to perps or represent actual funding paid.

[Pinned reference manifest](manifests/truemarkets_20261024T122541742972Z.json) · [Current reference manifest](manifests/truemarkets_latest.json)

## Current Parquet files

Paths are relative to this directory. Raw and clean data are local and gitignored.

- [BTCUSDT_5m.parquet](clean/20261024T122241389043Z/binance/spot/BTCUSDT_5m.parquet) — SHA-256 `d1ff9cfd32f7b63bda496e27b105c71cfd5a87caf730a50d7308301ecd167e10`
- [ETHUSDT_5m.parquet](clean/20261024T122241389043Z/binance/spot/ETHUSDT_5m.parquet) — SHA-256 `e0a6dc84764c04dffb2bd3824b4869b4cd768342cf11b8bec3b6947f7a78b145`
- [SOLUSDT_5m.parquet](clean/20261024T122241389043Z/binance/spot/SOLUSDT_5m.parquet) — SHA-256 `bd8a32500724a471eb09843a37b93575d0142911d19616231fd098d9e037ce7b`
- [BTCUSDT_1h.parquet](clean/20261024T122241389043Z/binance/spot/BTCUSDT_1h.parquet) — SHA-256 `5cd4841603868626c2cfc6506e729cc159c92a92ada168b7a83ca8c77971ef07`
- [ETHUSDT_1h.parquet](clean/20261024T122241389043Z/binance/spot/ETHUSDT_1h.parquet) — SHA-256 `bfe70d4860a2f02656c63a291bff5863643bec7d6b3ae5755681083699903a69`
- [BTC_5m.parquet](clean/20261024T122541742972Z/truemarkets_reference/BTC_5m.parquet) — SHA-256 `05c3ddd1684c0893e53f14f1362478c1022bd567c8f23b533feb002577a8f292`
- [ETH_5m.parquet](clean/20261024T122541742972Z/truemarkets_reference/ETH_5m.parquet) — SHA-256 `158ac0bb0bbe257c6fe8f3347e0fcb82f60940f96a73f146e3fe2373a65bd359`
- [SOL_5m.parquet](clean/20261024T122541742972Z/truemarkets_reference/SOL_5m.parquet) — SHA-256 `3ce1c2040ea8b1a47f94e6ca59b85dfaba47d711a7e908969c809f8d41973af8`
- [BTC_funding_1h.parquet](clean/20261024T122541742972Z/truemarkets_reference/BTC_funding_1h.parquet) — SHA-256 `4f6a5a5a99d2b6cf9e8cd00bb970278018feb5d63c40ccb70dba769c6b265fec`
- [ETH_funding_1h.parquet](clean/20261024T122541742972Z/truemarkets_reference/ETH_funding_1h.parquet) — SHA-256 `f466b7e8a8e11fa2f99a387e8a5089daec49bd55fa6f91864737034352da36e0`
- [SOL_funding_1h.parquet](clean/20261024T122541742972Z/truemarkets_reference/SOL_funding_1h.parquet) — SHA-256 `0f3c025a43b22bd13e5e9f5d5068c109721ceef2f729176408749547bc4c5839`

## Recheck and refresh

Run from the repository root:

```sh
uv run python scripts/verify_data.py
uv run pytest -q
uv run python scripts/collect_data.py --end 2026-10-24
uv run python scripts/collect_truemarkets.py --end 2026-10-24
uv run python scripts/summarize_data.py
```

Omit `--end` to collect through the latest completed UTC day. Cached source responses preserve original retrieval timestamps and hashes. Rolling funding windows depend on the collection time.

## Not collected

Point-in-time news, executable bid/ask quotes, fee schedules, balances, or trading permissions. The collection commands do not generate features, prediction labels, checkpoints, backtests, or orders. Subsequent feature work is documented in the [feature-engineering draft](../reports/feature_engineering_draft.md).
