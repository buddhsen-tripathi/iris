# Iris research and paper trading lab

Historical data, causal features, and a reproducible model-training/paper-replay pipeline for the attached Iris design. Current targets are **5, 15, and 30 minutes**. Live execution is not enabled.

## Broad US stock relationship data

The first [evidence graph dataset](reports/knowledge_foundation.md) is collected: 7,481 US-listed non-ETF securities, 1,814 accounting consolidation records, 26 full annual reports/filings, five issuer announcements and one annual overview. Candidate mentions remain separate from reviewed publisher claims; accounting links are not supply-chain links. The [complete graph explorer](http://localhost:5180/?view=relationships) loads **all 16,911 nodes and 15,411 assertions from Neon** into a WebGL map, including disconnected companies. Search the full directory by company, ticker or material; select an entity to highlight its connections and browse every source assertion in the paginated ledger. All three assertion statuses are shown initially and can be filtered. All **12,441 passages are embedded in pgvector** for semantic/keyword source search. Click **Asset graph** in the trading desk to open it. Automated news-to-graph enrichment and validated financial impact modeling remain future work. [Neon implementation and validation](reports/knowledge_neon.md).

```sh
uv sync --locked --group knowledge
uv run --group knowledge python scripts/collect_knowledge.py --phase all --limit-issuers 105
uv run --group knowledge python scripts/index_knowledge.py
uv run python scripts/export_knowledge.py
uv run python scripts/query_knowledge.py 'NVIDIA TSMC Micron packaging' --entity equity:NASDAQ:NVDA --max-hops 3
# Publish the pinned local corpus to the configured Neon database and embed missing passages:
uv run --group knowledge python scripts/publish_knowledge_neon.py --embed
```

The graph snapshot is saved for **24 hours** in browser IndexedDB and a private server disk cache; saved layout positions are reused across reloads. It does not poll or automatically refetch on focus/reconnect. **Refresh data** explicitly revalidates Neon; unchanged data returns HTTP 304 and keeps the layout. The saved graph remains usable when API reads are unavailable.

**Ask the graph** opens a source-grounded OpenRouter agent for relationship questions, industry themes and stock research shortlists. It retrieves graph links and semantic report passages, cites sources, validates listed company identities, and includes risks/missing checks with suggestions. Identical conversations against the same snapshot reuse answers for 30 minutes in server memory. It uses the collected corpus, not live prices or a validated stock-return model. [Caching, analyst details and validation](reports/graph_cache_and_agent.md).

**Research people & backgrounds** in a company's graph details uses the server-side `EXA_API_KEY` to find public professional profiles, company roles, previous experience, education and research. Each returned claim includes an exact source excerpt and citation. Exa sources are cached for 24 hours; profiles remain research leads separate from accepted graph relationships. [People research implementation and validation](reports/people_research.md).

The Python API on port 8000 retains the local SQLite reference implementation; the web explorer uses its own same-origin read-only `/knowledge/*` endpoints backed by Neon and `/graph-agent/*` for cited research. The importer reads `DATABASE_URL` and `OPENROUTER_API_KEY` from `web/.env.local`, creates a schema-scoped SELECT-only login, and stores its connection string as `KNOWLEDGE_DATABASE_URL` in the same ignored file. Unprefixed secrets stay server-side. Preserve the gitignored `data/knowledge/` directory for raw snapshots, local graph storage, private cache and typed JSONL exports. See the [coverage and caveats](reports/knowledge_foundation.md).

## Trading desk (new web app)

```sh
cd web && npm install && npm run dev   # http://localhost:5180
npm test && npm run build              # unit tests, typecheck + production build
```

`web/` is a React + Tailwind v4 + Lightweight Charts trading view built only on True Markets' **public** market-data API: no account, keys, or order endpoints. Its parts and data sources:

- **Price chart:** candles at 1m–1D, with SMA, EMA, Bollinger, RSI and MACD computed by True Markets. Live ticks from the WebSocket update the latest bar.
- **Perp order book:** live Hyperliquid perp book.
- **Composite reference:** the per-exchange quotes and weights behind True Markets' reference price.
- **Header stats:** 24h range, market cap, funding and open interest.
- **Watchlist and ticker tape:** live prices.
- **Movers:** surging, trending and top market-cap lists.
- **Search:** finds any listed instrument.
- **AI news read:** the instrument's own Live news tab scores its latest 10 headlines by their likely effect on it, from −1 to +1. Each headline gets a green, red or grey bar, a score and a one-line reason, with an overall read (positive, negative, mixed or neutral) above the list. Haiku 5.5 does the scoring through a strict-schema tool call. A read runs each time the tab is opened or returned to, and on every instrument change. If the same 10 headlines were scored in the last 6 hours, the stored read is reused at no model cost; ↻ forces a fresh one. The Markets tab is not scored.
- **Order flow:** live taker buy vs sell volume over 1, 5 or 15 minutes, laid out like a prediction market. A buy-share line is drawn around 50%, Buyers and Sellers outcome buttons show $ volume and trade counts and filter the feed, and an Activity feed highlights large trades. It's built from Hyperliquid's public perp trade stream, the venue behind the order book: True Markets' CeFi `TRADE` channel had no prints in the last 24h. Flow builds from page load, and it is a measure of recent volume, not a forecast.
- **Live news:** headlines for the selected instrument, plus a Markets tab, merged from Yahoo Finance and Google News RSS. No key is needed, and the panel refreshes every minute.

News feeds are fetched server-side by the dev server's `/news` endpoint (`web/server/news.ts`), because neither feed allows browser requests. Each feed is cached for 60 seconds, and the last good copy is served if a feed fails. Yahoo's per-ticker feed drifts off-topic, so its stories are kept only when they mention the instrument. Both feeds are for personal, non-commercial use under their providers' terms.

**AI layer:** **Ask analyst** (⌘J) opens a desk-analyst agent built on the [OpenRouter Agent SDK](https://openrouter.ai/docs/agent-sdk/overview) (`@openrouter/agent`, `callModel`). It runs in the dev server (`web/server/ai.ts`) with six read-only tools:
- the user's live screen snapshot (price, Hyperliquid order flow, book, reference)
- True Markets candles, indicators, funding/open interest, and movers
- the news feeds

Answers and tool steps stream to the drawer. Limits are 6 tool rounds and $0.25 per question, and a run stops when the drawer is closed or Stop is pressed. The agent cannot place orders.

**Point & ask:** click **Point & ask** in the masthead, or ⌥-click anywhere, then pick any element on the desk to ask about it. An order-book row, a stat, the chart, a news headline or a trade all work.
- **What's sent:** the element's text, its panel and its label go to `/ai/ask` as clearly marked page data, along with the live desk snapshot. A row or control is picked whole, and a bare number brings its label with it.
- **Model:** answers always come from Haiku 5.5, enforced on the server, with up to 3 tool rounds and $0.05 per question.
- **The popover** opens beside the element and supports follow-up questions. Esc or clicking elsewhere closes it.

The server routes each question; the browser never chooses a model. Analysis and open-ended questions go to Sonnet 5.5, quick lookups to Haiku 5.5. Routing uses fixed keyword rules (`routeQuestion` in `web/server/ai.ts`), and unclear cases go to Sonnet. Each answer is labelled with the model that wrote it.

To enable it: `cp web/.env.example web/.env.local`, set `OPENROUTER_API_KEY`, then restart `npm run dev`.

**Portfolio & trading (True Markets):** **Portfolio** (top left) shows your account's total value, holdings and recent orders. **Trade** (top right) places market orders on the selected asset.
- **How an order works:** **Preview** creates a binding quote that expires in about 2 minutes, without moving anything. **Buy/Sell**, then **Confirm: real order**, signs it with your key on the dev server and executes it. The result links to the on-chain transaction.
- **Rules enforced in `web/server/trading.ts`:**
  - orders are refused unless `TM_TRADING_ENABLED=true`;
  - only spot crypto that your account's country allows (no stocks or perps in the US; CeFi listings need CeFi trading enabled);
  - market orders only;
  - at most `TM_MAX_ORDER_USD` (default $10) per order and `TM_DAILY_LIMIT_USD` (default $25) per 24 hours;
  - each preview can be executed once, and only while it's fresh;
  - requests must come from this app.
- **Key handling and logging:** the key file never reaches the browser. Every preview and order is logged to Neon (`trade_orders`; run `npm run db:migrate`).
- **To trade:** set the variables from `web/.env.example` in `web/.env.local` and restart the dev server. Every order moves real funds; start with $1.

**Storage (Neon Postgres):** set `DATABASE_URL` in `web/.env.local`, then run `npm run db:migrate`. Migrations live in `web/server/migrations/`. There are two tables:
- `news_articles`: each headline seen per instrument, with its first-seen time.
- `news_sentiment_runs`: every AI news read, with scores, model, tokens and cost.

Without `DATABASE_URL` the AI read still works, but nothing is reused or kept as history.

Perp-only listings such as XRP and DOGE have no OHLC candles, so they chart as a sampled price line. True Markets' REST CORS policy only allows its own origin, so `/tm/*` is proxied by the Vite dev/preview server. The public WebSocket is opened directly.

## Local dashboard and remaining MVP components

```sh
uv sync --locked --group training --group analysis --group web
uv run --group training --group web python scripts/serve_dashboard.py --port 8000
```

Open <http://127.0.0.1:8000> for the local paper observatory; read-only API documentation is at <http://127.0.0.1:8000/api/docs>. It displays actual expert forecasts, the adaptive shadow, separate model/forced-paper portfolios, observed quote freshness, matured errors, paper equity, and decision autopsies. It reads the existing sessions without starting or prolonging them. [Dashboard/API details](reports/dashboard.md).

The adaptive committee learns separate 5/15/30-minute weights only from matured, actually observed outcomes. Its ledger records exact weights, losses and application timestamps, with equal-weight shrinkage and bounded expert shares. A prospective shadow runs alongside the fixed baseline; it does not change either existing paper trader. [Development comparison and limitations](reports/adaptive_committee.md).

```sh
# Requires an existing model forward session and local model/data artifacts:
uv run --group training python scripts/committee_shadow.py --minutes 60
# Reproduce development-only comparison; excludes reserved outcomes:
uv run --group training python scripts/compare_committees.py
```

The independent [risk engine](reports/risk_engine.md) reviews cash, position limits, venue constraints, quote freshness, fees, downside and uncertainty before producing a paper proposal. Missing genuine validation evidence refuses a signal proposal. A separate local proposal ledger supports explicit expiring human approval and idempotent paper submission; the dashboard has no approval or order mutation routes. This engine does not silently change already running experiments. Live order transport is not implemented.

```sh
# One independent review of the latest fixed forecast against a fresh public quote:
uv run --group training python scripts/review_risk.py
# Or bounded 20-second reviews; snapshots only, no orders:
uv run --group training python scripts/review_risk.py --watch-minutes 30
# Inspect the local paper approval workflow (never sends exchange orders):
uv run python scripts/paper_review.py --help
uv run python scripts/paper_review.py status
```

Optional source context and venue discovery use fixed public GET endpoints, save raw responses and hashes, and never submit orders:

```sh
uv run python scripts/collect_events.py
uv run python scripts/check_venue.py
```

Event context currently uses the Federal Reserve's primary-source RSS feed, with immutable first-observed times, deduplication and a seven-day freshness window. It does not influence return forecasts. Empty fresh-event lists are valid. Grok/Jev remain unconnected. True Markets discovery checks the public catalog and caller-location availability; it does not verify a private account, balances, fees, or trading permission. Public venue status is not used to substitute True Markets prices for Binance model quotes.

Optional [regime context](reports/regime_context.md) labels completed feature rows with fixed trend/range/high-volatility thresholds. `uv run python scripts/regime_context.py` refreshes the recorded snapshot; its source-anchor timestamp is displayed. Research helpers shrink sufficient past-only bucket evidence toward global weights, but regime-conditioned learning remains disabled in the active shadow and no regime gain is claimed.

All background workers are bounded local processes and require an awake, online Mac. Their manifests and reports are local snapshots; liveness/age indicators distinguish fresh data from recorded history. Tests run with `uv run --group training --group analysis --group web pytest -q`.

## Live-data paper forward testing

```sh
uv sync --locked --group training
uv run --group training python scripts/forward_test.py
# In another terminal:
uv run --group training python scripts/forward_status.py
```

The [forward configuration](configs/forward_paper.json) collects one hour of genuinely new BTCUSDT 5/15/30-minute forecasts, then allows up to 30 minutes for outcomes to mature. It uses Binance's documented public market-data domain with no keys or order endpoints. The process must stay running on an awake, online Mac. [Current session report](reports/live_forward_test.md) and `data/manifests/forward_latest.json` update each poll; the status command additionally checks the process and heartbeat. An active session blocks a second launch. To stop new forecasts and drain pending observations, create `data/forward/<session_id>/STOP`.

Saved models and equal expert weights remain frozen. Historical candles supply inference context; forward forecasts start only after launch, at a future completed candle close, with at most 30 seconds of publication delay. All forecasts are committed to SQLite before requesting an entry quote. Outcomes are scored only after their separate maturity times. Raw HTTP bodies, retrieval times, hashes, selected features, expert forecasts, decisions, and simulated fills are retained under local, gitignored `data/forward/<session_id>/`. A crash does not backfill missed forecasts; start a new session after inspecting the old ledger. Deadline expiry leaves unresolved outcomes/positions pending rather than inventing settlements.

Two independent virtual portfolios compare 5-minute-only entries with 15/30-minute confirmation. Each starts with 50 USDT and caps a position's total entry cost at 10 USDT. Paper buys use a subsequently observed ask; sells use a bid requested at/after five minutes from actual entry. Venue size/minimum-notional filters, observed quote size, two-sided assumed fees (10 bps/side), slippage (2 bps/side), and a 2 bps extra entry buffer apply. Current price movement since the forecast anchor also affects entry eligibility. Quote receipt latency is checked; the quote endpoint does not supply an exchange event timestamp. These are simulated fills and unverified cost assumptions. All-HOLD results are valid and do not establish profitability.

The earlier reserved historical interval may now supply past price context for live inference, but its historical target labels are still not evaluated. Only outcomes of forecasts published during this live session are scored.

## Forced entries every 20 seconds (paper only)

```sh
uv run --group training python scripts/paper_interval.py
uv run --group training python scripts/forward_status.py --forced
```

The [forced-entry configuration](configs/forced_20s_paper.json) starts an independent one-hour live-data paper experiment. Every UTC 20-second boundary, it closes the preceding position at a fresh observed bid and opens a new long at the observed ask, regardless of model signal. Holding duration is approximately 20 seconds, with actual timestamps recorded. This is a forced turnover experiment, not a 20-second forecast model or the performance of the signal-gated policy. It leaves the existing 5/15/30-minute forward session running separately.

The portfolio starts with 50 virtual USDT, caps total entry cost at 10 USDT, holds one position, and retains the same assumed fees (10 bps/side) and slippage (2 bps/side), spread, quote checks, and venue size constraints. A missing quote or an unexitable previous position can skip an entry. Missed slots are never backfilled. After the entry window closes, the loop attempts to liquidate the remaining position, with at most three minutes of grace; any unresolved position stays open in the ledger.

The [forced paper report](reports/forced_20s_paper_test.md), `data/manifests/forced_latest.json`, and its independent ledger show actual entries, completed round trips, costs, cash, estimated liquidation equity, and P&L. Create `data/forward/<forced_session_id>/STOP` to stop new entries and drain the remaining paper position. The Mac must remain awake and online.

See the [data inventory and quality report](data/README.md) for actual coverage, gaps, source limitations, and file locations.

See the [feature-engineering draft](reports/feature_engineering_draft.md) for 26 tested feature candidates, a proposed 14-input starter set, exact formulas, observed redundancy, and provisional engineering priority weights. These priorities measure observed coverage, stability, and overlap; they are not learned predictive importance.

See the [model-training and paper-comparison report](reports/model_training_5_15_30.md) for trained experts, target maturity, chronological partitions, prediction errors, observed trade frequency, and assumed costs. The first development run produced no trades; it has not established a tradeable five-minute edge. The final 30 days remain reserved.

## Train 5/15/30-minute models

```sh
uv sync --locked --group training --group analysis
uv run --group training --group analysis python scripts/train_models.py
uv run --group training pytest -q
```

The frozen [configuration](configs/training_5_15_30.json) defines the 14-input set, small past-only parameter grids, five experts with 20% committee weights, and two simulated long-only policies. Labels crossing each boundary are purged. Models are fitted/refitted before the development replay and remain frozen during it. Saved artifacts use JSON/native LightGBM text under `models/`; labels and forecasts are under `data/training/`. Both directories are local and gitignored. The earlier unlabeled priority weights are not used as predictive coefficients.

Full per-decision replay CSVs are also local and gitignored. Reports, metrics, configuration, trade ledgers, and hashes remain versionable. Training-specific tests require the `training` dependency group; the core data/feature tests can run without it.

## Feature audit without labels

```sh
uv sync --locked --group analysis
uv run --group analysis python scripts/engineer_features.py
uv run pytest -q
```

The audit fits normalization on the early 180-day reference interval (after warm-up), measures stability on the following 155 days, and reserves the final 30 UTC days plus their initial decision boundary from selection/weighting. Completed hourly bars join backward on their close times. Feature Parquet files are local under `data/features/`; metrics, correlations, priority weights, and method/provenance notes are under `reports/feature_audit/`.

## Reproduce the collection

Run from the repository root with [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run python scripts/collect_data.py --end 2026-10-24
uv run python scripts/collect_truemarkets.py --end 2026-10-24
uv run python scripts/verify_data.py
uv run python scripts/summarize_data.py
uv run pytest -q
```

Dates are UTC. `--end` is exclusive and defaults to today's UTC date, so today's partial day is omitted. Binance defaults to 365 days of 5-minute BTCUSDT/ETHUSDT/SOLUSDT spot candles and 730 days of hourly BTCUSDT/ETHUSDT candles. True Markets defaults to 180 days of 5-minute BTC/ETH/SOL spot **reference** candles and an optional rolling 30-day hourly funding/open-interest snapshot for each asset.

Both collectors cache exact source responses with retrieval timestamps and SHA-256 hashes. Binance files are also checked against the provider's `.CHECKSUM` files. Cached data are verified before reuse; a new run creates a new clean snapshot and manifest. A raw cache pins the originally downloaded version: it intentionally does not check for later upstream revisions. For an independent fresh download, use a different `--data-dir`. Identical historical requests can return revised vendor data, and rolling funding windows change with retrieval time.

The True Markets collector records unavailable days separately from transport errors. A completed collection can have gapped coverage; always inspect each dataset's validation report. Unavailable and incomplete candles are never interpolated. The primary Binance collector refuses to publish a successful manifest if any required candles are missing or invalid.

## Files

- `data/raw/`: source ZIPs, checksum files, JSON responses, retrieval metadata, and access-failure receipts.
- `data/clean/<run_id>/`: normalized Parquet snapshots, separated by provider and instrument.
- `data/manifests/latest.json`: current successful Binance snapshot, source hashes, and quality checks.
- `data/manifests/truemarkets_latest.json`: current True Markets reference snapshot, unavailable days, and gaps.
- `data/manifests/features_latest.json`: current feature snapshot and audit provenance.
- `data/manifests/training_latest.json`: fitted models, replay results, and reserved-test status.
- `data/manifests/<run_id>.json`: original collection runs; failed attempts remain available for audit.

Raw downloads and Parquet files are **local and gitignored**; they are not included in a Git checkout. Scripts, dependency lockfile, manifests, and the inventory are versionable. Preserve `data/raw/`, `data/clean/`, `data/features/`, `data/training/`, and `models/` to retain these exact snapshots.

## Data conventions

`open_time_utc` is the bucket start; `close_time_utc` is the **exclusive** interval boundary at which the bar becomes complete. Binance's original inclusive close timestamp is retained separately as `source_close_time_utc`. Binance spot timestamps change from milliseconds to microseconds in 2025; normalization handles both without floating-point timestamp conversion.

Prices and volumes in the source datasets use Parquet `decimal128(38,18)` to preserve source precision. Feature calculations explicitly convert them to float64 without changing the source files. Every source row retains its URL, SHA-256, and original retrieval time. Feature manifests pin the source dataset hashes.

Binance instruments are explicitly USDT-quoted spot pairs. True Markets candles retain the provider's asset UUID; missing source venue, quote currency, volume, and trade count stay null. The providers' histories are separate datasets. Reference prices do not establish executable fills, fees, spreads, or account permissions.

Funding rates are hourly decimal fractions; open interest is measured in base-asset coins. The snapshots are observations, not funding settlement receipts. Missing observations stay absent.

## Checks

Offline verification rechecks every pinned raw and clean hash and the dataset quality reports. It also reconstructs True Markets datasets from the saved raw responses and compares every value with the Parquet snapshot. The test suite covers timestamp precision changes, exact decimals, incomplete bars, gaps, duplicate keys, invalid OHLC/volume, checksum corruption, provider identity, and funding units.

Still outside this work: point-in-time news archives, verified account fees, balances, trading eligibility, and live orders. Historical paper replays use a zero-latency next-open proxy; live-data paper testing records subsequently observed bid/ask quotes. Neither establishes actual fills or profitability.

## Primary source documentation

- [Binance public data format, publication schedule, and checksums](https://github.com/binance/binance-public-data)
- [Binance unauthenticated public market-data endpoints](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only)
- [Binance dataset terms](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md)
- [True Markets candle parameters and schema](https://docs.truemarkets.co/api/market-data/get-candles.md)
- [True Markets funding and open-interest units](https://docs.truemarkets.co/api/market-data/get-perp-market-history.md)
