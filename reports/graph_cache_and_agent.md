# Saved graph and evidence-grounded research agent

Open <http://localhost:5180/?view=relationships>. **Refresh data** controls corpus revalidation. **Ask the graph** opens questions and stock research over the collected evidence.

## Graph caching

The full 16,911-node / 15,411-assertion snapshot is cached for 24 hours in browser IndexedDB. React Query keeps the loaded snapshot without refetching on mount, window focus or reconnect; there is no polling. Opening a new page checks the saved snapshot's age. An explicit refresh bypasses freshness and revalidates Neon. When an expired saved snapshot cannot be refreshed, it remains usable with a visible saved-data notice. A failed manual refresh keeps the displayed graph and shows the failure.

The server also caches the snapshot in a private, gitignored `data/knowledge/cache/network-<scope>.json` file, scoped by a hash of the database connection configuration. Files contain graph data, timestamps and a checksum, not connection strings. Writes are atomic, and a failed source read does not replace the previous snapshot. Cache loads validate the schema and content hash. The disk cache survives server restarts; concurrent cold requests are deduplicated. Explicit historical snapshots bypass this current-data cache.

The snapshot version / HTTP ETag derives from its node and assertion contents. An unchanged explicit refresh returns HTTP 304 with no graph body and retains the snapshot's original `as_of`. The browser updates its cache-validation time while retaining the data object and layout. Changed data receives a new version. The display distinguishes when the graph was saved from its source observation time.

Final/refined layout positions are also stored in IndexedDB, keyed by the exact snapshot version. Restoring a saved layout does not restart the force-layout worker. New versions get a new layout. User-requested layout refinement can be paused and saved. Invalid layouts are discarded. Cache/storage failures do not prevent ordinary online graph access.

Caching uses explicit saved snapshots rather than aggressive default query refetch behavior; see [TanStack Query's documented defaults](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults).

## Ask the graph

The graph-specific agent reuses the project's [OpenRouter Agent SDK](https://openrouter.ai/docs/agent-sdk/overview) and configured Sonnet 5.5 analysis model. The model ID and tool support were checked against OpenRouter's live model catalog. No new credential is required: `OPENROUTER_API_KEY` and the schema-scoped `KNOWLEDGE_DATABASE_URL` remain server-side.

Read-only tools allow the agent to:

- Search company names, tickers, materials and entity IDs in the cached complete graph.
- Retrieve source-cited connections for an exact entity, keeping reported, reference and candidate assertions distinct. Tool output is bounded and reports the total count and truncation.
- Search issuer reports and announcements using lexical + pgvector retrieval with source-resolved issuer IDs.
- Find listed companies whose own collected reports discuss a research theme, retaining evidence and treating topic relevance as a research lead.
- Submit a structured final answer and optional stock research shortlist for validation.

The agent works against the same snapshot visible in the UI. A mismatched snapshot is refused before starting a model call and the user is directed to refresh. Source queries use the snapshot's observation time. Model history does not count as evidence: citations must be retrieved again in the current run.

The server validates each final citation against sources actually returned by tools. It validates inline evidence IDs, resolves suggested companies to actual graph company records and reference-linked listed tickers, and requires each suggestion's citations to be associated with that company. Unknown companies, invented citations, raw answer URLs and unrelated source substitutions are rejected. Tool errors allow the model to correct its final submission within the remaining request budget. The UI only shows an accepted structured answer; raw draft model text is not streamed as an authoritative answer.

Each suggested company includes a **conditional research hypothesis**, downside or missing checks, and evidence IDs. Users can open the cited primary sources or select **View company in graph**. Sources retain their original assertion status; a passage mention is not promoted to a supplier relationship. The answer also carries corpus limitations and a snapshot date. All source text is treated as untrusted data; the tools have no SQL execution, arbitrary URL fetching, or order capability.

With `EXA_API_KEY` configured, the agent also supports on-demand [company people and professional background research](people_research.md). This retrieves separately dated web evidence and produces source-reported profiles with exact excerpts; it does not modify the saved graph or promote search matches to accepted relationships.

This is research over a partial corpus, not a comprehensive investment screen. The broad catalog includes varied security types and provisional company identities. Only five reviewed publisher-reported business claims are currently accepted; most detailed evidence concerns a small enriched issuer subset. Current prices, valuation, suitability, transaction exposure and expected returns are not verified. The agent may identify ideas to investigate and explain possible mechanisms as hypotheses; it does not establish that a connected stock will rise. Automatic news-to-graph enrichment remains separate work.

## Request and answer caching

### Stock performance cards

Each suggested stock now includes a historical price chart with **1M / 3M / 1Y** controls, the latest reported daily close, currency, exchange, actual displayed dates, and percentage change between the first and last displayed closes. Hover and keyboard arrow/Home/End inspection show individual observations. Multiple listed tickers can be selected independently. Charts remain separate from the agent's relationship evidence and are not forecasts or evidence that a relationship caused a price movement.

`GET /stock-performance?symbol=TSM` reads Yahoo Finance's public chart endpoint server-side, validates the returned ticker and equity/ETF instrument type, and retains missing observations as gaps. These are listed-security daily closes rather than the desk's tokenized stock markets. Yahoo describes [historical close prices](https://finance.yahoo.com/quote/MU/history/) as adjusted for splits; the displayed price return excludes dividend reinvestment. Each chart links its source and shows the final observation and fetch time. The public endpoint is unofficial and may throttle or change; unsupported listings and provider failures show an unavailable message and Retry, with no synthetic chart or token substitution.

A single one-year history supplies all three ranges, anchored to its latest available trading date. A range starts at the last valid close on or before its calendar boundary (or the earliest available close); the actual dates are always shown, including for short histories. The chart draws the actual daily observations with a linear price axis. Server history and concurrent-request deduplication are bounded to 256 symbols / 15 minutes; browser React Query and private HTTP caching also reuse history for 15 minutes. Range changes do not query Neon, refresh the graph, call the AI model, or fetch a new price series. Market history is not part of the saved graph snapshot or the model's reasoning input.

The same conversation, selected entity, model and snapshot reuse an accepted answer for 30 minutes in server memory (up to 128 entries). The UI labels reused answers and retains their original generation time. This cache is cleared by a server restart; it is separate from the persistent graph cache. Follow-up context changes the key, and changed graph versions invalidate reuse. Conversations are not automatically persisted to disk.

Each new request has a six-round stop condition, a $0.25 SDK cost-budget stop condition, a per-call output-token limit, and a 90-second provider timeout. A final accepted answer stops the loop without an extra free-text round. Two model requests can run concurrently. Closing the panel or selecting Stop aborts the request. The budget is an SDK loop stop condition, not a guarantee about provider billing. There are no background or automatic model calls for graph search, opening the panel or reloading the page.

Endpoints:

- `GET /knowledge/network` — saved complete graph; `refresh=true` explicitly revalidates; `If-None-Match` supports a body-free 304.
- `GET /graph-agent/config` — enabled/model/request-limit metadata, without keys.
- `POST /graph-agent/chat` — bounded JSON conversation + snapshot ID/time + optional selected entity; returns validated NDJSON progress/answer events.
- `GET /stock-performance?symbol=MU` — validated listed-stock daily price history, cached separately for 15 minutes.

## Validation

The current web suite has **106 passing tests**, and typecheck/production build pass. Cache tests cover disk restart reuse without a source read, 24-hour expiry, explicit refresh, stable identity for unchanged contents, corruption, concurrent cold-load deduplication and source failure preserving the previous snapshot. Research tests cover registered citations, company-to-source association, listed identity resolution, untrusted source text as inert data, and honest insufficient-evidence output. Price tests cover ticker/instrument identity, ordering/alignment, missing prices, dated returns, cache expiry/deduplication and provider failure. People research validation is documented in [its implementation report](people_research.md).

The stock-card browser checks replay the previously captured real agent answer (no new model billing), with actual live Yahoo history for TSM and MU. Both charts render, range changes reuse history, arrow-key inspection works, mobile has no horizontal overflow, and a simulated provider failure renders no chart. Results and screenshots are in `.context/stock_performance_ui_validation.json` and `.context/stock_performance_desktop.png` / `stock_performance_mobile.png`.

Live browser checks observed **zero graph API requests after reload**, reuse of saved positions with no layout restart, graph access with API reads blocked, and exactly one explicit refresh request. An unchanged explicit refresh returned HTTP 304 with a zero-byte body. A mismatched research snapshot returned HTTP 409 before a model call.

A live provider run retrieved actual publisher-reported relationship evidence, produced a validated two-company research shortlist with citations and risks, and completed in four model calls. Repeating that request through the browser reused the accepted answer without another model run. Its source links rendered correctly, and selecting a suggested company opened it in the graph. No page errors occurred. Local artifacts are `.context/graph_cache_browser_validation.json`, `.context/graph_agent_live_result.json`, `.context/graph_analyst_ui_validation.json` and the associated screenshots/logs.
