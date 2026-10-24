# Iris paper observatory

The local dashboard reads prospective paper records, with separate model-driven and forced 20-second experiment views. It never writes to a paper ledger, submits an order, changes weights, or approves a risk proposal.

Run from the workspace:

```sh
uv run --group training --group web python scripts/serve_dashboard.py --port 8000
```

Open <http://127.0.0.1:8000>. The launcher accepts only loopback hosts. API documentation is at `/api/docs`; the UI and assets share the same origin and use no CDN, external fonts, or remote scripts. Dashboard data refreshes every 10 seconds while the page is open. The dashboard does not start or prolong any experiment.

## Evidence shown

- Exact expert forecasts at 0, 5, 15, and 30 minutes, measured in log-return basis points. Connecting lines are visual guides, not intermediate forecasts. Dispersion is not presented as calibrated confidence.
- Equal committee weights and prospective adaptive shadow weights. Shadow learning remains separate from execution.
- Latest observed bid/ask receipts, request latency and receipt age. Binance bookTicker does not provide an exchange event timestamp. Quotes older than 30 seconds are marked recorded/stale.
- Actual ledger decisions and inspectable autopsies, including observed quotes, assumed fills, fees, quantity, holding duration and realized paper P&L. Forced entries explicitly ignore model forecasts.
- Separate simulated policy accounts. The equity chart displays initial capital plus realized P&L and excludes open positions. A separately labelled mark-to-liquidation estimate includes its quote observation timestamp when available.
- Matured fixed-committee forecast errors, sample counts, directional accuracy, and pending outcomes. No prediction score is invented for unavailable horizons.
- Primary-source event context when available; no historical headline is presented as fresh. Headlines do not influence current models. Independent risk review reasons are read from its latest snapshot.

## API contracts

The versioned API is read-only:

| Route | Content |
|---|---|
| `/health` | Server liveness, paper-only capability |
| `/api/v1/overview` | Session state, actual counts, quotes and heartbeat ages |
| `/api/v1/market/BTCUSDT/candles` | Completed 5m close observations; OHLC is unavailable in this ledger |
| `/api/v1/forecasts/BTCUSDT` | Prospectively published forecasts and observed outcomes |
| `/api/v1/committee/BTCUSDT/latest` | Fixed and adaptive shadow snapshots |
| `/api/v1/committee/BTCUSDT/weights/history` | Auditable shadow updates |
| `/api/v1/decisions?mode=model\|forced` | Mode-specific decision tape |
| `/api/v1/decisions/{id}/autopsy?mode=model\|forced` | Decision, linked paper position and costs |
| `/api/v1/performance?mode=model\|forced` | Accounts, realized equity and forecast metrics |
| `/api/v1/news/BTCUSDT` | Source-backed contextual events or honest unavailable state |
| `/api/v1/risk/latest` | Independent review snapshot; no approval mutation |
| `/api/v1/regime/latest` | Causal, fixed-threshold market context; no conditional execution |
| `/api/v1/venue/latest` | Public capability snapshot; private account eligibility unverified |
| `/api/v1/capabilities` | Explicit operating boundaries |

For convenience the market, forecast, committee, decision, performance, news and capabilities routes also have aliases without `/api/v1`. Unsupported symbols return 404, invalid modes and limits return 422, and unknown decisions return 404.

## Storage and freshness

Data sources are `data/manifests/{forward,forced,committee,events,risk,venue,regime}_latest.json`. Model/forced manifests point to their local `session_directory/ledger.sqlite3`; adaptive history reads `shadow_session_directory/committee.sqlite`. Paths are resolved within the workspace and rejected if they escape it, including via symlinks.

Each paper-ledger request opens SQLite with `mode=ro`, applies `query_only=ON`, and begins a read transaction. Related queries within an endpoint see one consistent snapshot even if the experiment writes concurrently. Manifests are atomic snapshots from their producer; there is no atomic transaction across separate producers or separate HTTP endpoints. Empty and missing sources return explicit unavailable states. A running session with a heartbeat older than 45 seconds, or three poll periods if longer, is marked stale. API failures retain the last rendered values with a visible stale-data warning.

## Verification

Twelve API cases cover empty workspaces, real receipt resolution, mature/pending contracts, mode validation, missing decisions, unsupported symbols, static path traversal, workspace escape rejection, write refusal, concurrent SQLite snapshot isolation, stale heartbeats, invalid snapshots, malformed/crossed/nonfinite quotes, slow quote receipts and security headers.

A native Python Playwright smoke exercise verified model rendering, five expert rows, switching to forced mode, opening a real decision autopsy, a 390px mobile viewport, no document overflow and no JavaScript page errors. Desktop, forced-mode and mobile screenshots were visually inspected under `.context/`.
