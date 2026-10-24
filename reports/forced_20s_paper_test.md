# Forced 20-second live-data paper experiment

Session `20261024T145826734708Z_forced_20s` — **completed**.

Updated 2026-10-24T15:58:41.573575+00:00. PID 3900. Paper entry interval: **20 seconds**.

This is forced long-only paper turnover, independent of the 5/15/30-minute model test. Entries ignore model signals and profitability thresholds. It does not measure a 20-second forecast model or a proven trading edge.

New entries end 2026-10-24T15:58:40+00:00; final exit deadline 2026-10-24T16:01:40+00:00.

| Measurement | Value |
|---|---:|
| Paper entries | 180 |
| Completed round trips | 180 |
| Open positions | 0 |
| Cash (USDT) | 45.819062 |
| Realized net P&L (USDT) | -4.180938 |
| Estimated liquidation equity (USDT) | 45.819062 |
| Assumed fees paid (USDT) | 3.440053 |
| Assumed slippage cost (USDT) | 0.688011 |

Start cash: 50 USDT; total entry cost cap: 10 USDT; one position at a time. At each UTC 20-second boundary, request a new public quote, close the previous position at observed bid, then reopen at observed ask. Holding time is approximately 20 seconds and actual timestamps are retained. Add 10 bps assumed fees and 2 bps assumed slippage on each side. Fees/slippage are unverified assumptions. Cash excludes open inventory; estimated liquidation equity uses the last valid quote and assumed exit costs.

Venue lot/minimum-notional rules and displayed size still apply. An invalid/missing quote or unexitable old position can prevent an entry. Late ticks are never backfilled; a delayed valid quote can still close an overdue position. At the deadline any unresolved position stays explicitly open. Quotes lack an exchange event timestamp; request/receipt times and response hashes are retained.

Raw responses and SQLite ledger: `data/forward/20261024T145826734708Z_forced_20s`. Log: `.context/forced_20s_20261024T145825Z.log`.

```sh
uv run --group training python scripts/forward_status.py --forced
touch data/forward/20261024T145826734708Z_forced_20s/STOP  # stop entries and drain the open paper position
```

The Mac must remain awake and online. [Public market-data API](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only).
