# Live-data paper forward test

Session `20261024T143100422313Z` — **completed**.

Updated 2026-10-24T16:00:10.520761+00:00. PID 85829. Public Binance BTCUSDT spot data; no real orders.

Forecast collection ends 2026-10-24T15:31:00.422313+00:00; settlement deadline 2026-10-24T16:01:00.422313+00:00.

Forecast bundles: 12 (three horizons each). Matured outcomes: 36; pending: 0.

| Paper policy | Cash USDT | Open | Closed trades | Realized P&L USDT |
|---|---:|---:|---:|---:|
| five_minute_only | 50.000000 | 0 | 0 | 0.000000 |
| with_15m_30m_confirmation | 50.000000 | 0 | 0 | 0.000000 |

Cash excludes the value of any open positions; realized P&L covers closed paper trades only.

| Horizon | Matured forecasts | Committee MAE (log bps) | MSE skill vs zero |
|---|---:|---:|---:|
| 5m | 12 | 17.1939 | -0.0001946516903170714 |
| 15m | 12 | 33.9308 | 0.009848968889111687 |
| 30m | 12 | 64.3327 | 0.0038142576046722443 |

No matured outcomes means no forward performance result yet. Small, overlapping samples cannot establish an edge.

Frozen checkpoints and 20% expert weights are unchanged. Historical candles supply causal context only; no past forecast is inserted into this run. Publication lag is recorded; forecasts over 30 seconds late are skipped. Outcomes are anchored at the completed bar close plus 5/15/30 minutes.

Paper entries use the first requested fresh observed ask after forecast persistence; exits use an observed bid requested at/after five minutes from actual entry. Ten basis points of assumed fees and two of assumed slippage apply on each side, plus a two-basis-point entry buffer. These are assumptions, not verified account fees/fills. Book quotes lack an exchange event timestamp; receipt time and HTTP latency are recorded. Independent paper portfolios may consume the same displayed liquidity; this is a policy comparison, not a combined portfolio.

A missing/late exit remains open until a usable quote arrives. At the deadline, missing outcomes and unresolved positions remain explicitly pending. This local process requires the Mac to remain awake and online. A dead process can leave an old status snapshot; the status command checks PID and heartbeat.

Ledger and raw receipts: `data/forward/20261024T143100422313Z`. Logs: `.context/forward_20261024T143059Z.log`.

```sh
uv run --group training python scripts/forward_status.py
# Stop new forecasts and drain pending observations:
touch data/forward/20261024T143100422313Z/STOP
```

[Public market-data endpoint documentation](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only).
