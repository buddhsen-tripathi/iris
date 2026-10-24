# Neon asset graph and semantic evidence search

The collected evidence corpus is stored in **Neon Postgres**, in the dedicated `alphacouncil_graph` schema. The trading desk opens the complete relationship explorer through **Asset graph**, or directly at <http://localhost:5180/?view=relationships>. The default map now includes every stored node and assertion, replacing the previous bounded asset view. This does not modify trading models or paper sessions.

## Published corpus

| Record | Count |
|---|---:|
| Typed nodes | 16,911 |
| Historical entity snapshots | 17,022 |
| Source documents, including registry references | 226 |
| Source pages / logical reference pages | 3,529 |
| Searchable and embedded passages | 12,441 |
| Relationship assertions | 15,411 |

Node types are 7,481 securities, 7,482 provisional company records, 1,918 legal entities, 15 commodities, seven industries and eight products. These are not 16,911 unique companies: company, listing and legal identities are intentionally separate, and the listing-associated company master is not deduplicated. See [corpus coverage and caveats](knowledge_foundation.md).

Assertions retain **9,295 references, five reviewed publisher-reported claims and 6,111 review candidates**. The complete map shows all three statuses initially, with distinct colors and explicit status filters. A company may have only a listing reference, or no collected relationship. Such entities remain visible and searchable; unknown links are not invented. The NVIDIA company record currently has **666 source assertions**, all accessible in the ledger. These are separate source assertions, including repeated mentions across passages, not 666 distinct commercial counterparties.

## Storage and retrieval

[001_knowledge_graph.sql](../migrations/001_knowledge_graph.sql) installs pgvector and the dedicated schema. Relational entity/edge tables hold the actual relationship graph; vector embeddings index passage meaning. Vector similarity never becomes an assertion of a commercial relationship or a price-impact weight. [Neon's pgvector documentation](https://neon.com/docs/extensions/pgvector) describes the supported vector operators and indexes.

Each passage uses **`openai/text-embedding-3-small`, 1,536 dimensions**, generated through the configured OpenRouter provider. All 12,441 passages have embeddings; the initial job recorded 3,959,239 input tokens. Model IDs, dimensions, original passage hashes and actual embedding-observation timestamps are retained. No synthetic or random fallback vectors are used. The fixed provider endpoint and request format follow [OpenRouter's embedding API](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request).

Evidence search combines Postgres English full-text ranking and pgvector cosine ranking using reciprocal rank fusion, `1 / (60 + rank)`, retaining which methods found each passage. This score orders retrieval results; it is neither confidence in a relationship nor expected financial impact. At the current corpus size, cosine queries retain a stable passage-ID tie break; an HNSW cosine index is also installed for future query optimization. Source and embedding observation times gate historical queries. Corpus publication timestamps remain unknown where exact UTC instants were not established.

## Explorer and API

The explorer loads the complete current network into a [Sigma WebGL map](https://www.sigmajs.org/get-started/quickstart/). A [Graphology ForceAtlas2 worker](https://graphology.github.io/standard-library/layout-forceatlas2.html) refines the initial component layout off the main thread and stops after four seconds; users can pause or resume it. Node size reflects recorded link count, and layout is only a presentation of topology. Labels become visible as users zoom. All nodes and source assertions remain loaded; selecting a company highlights its links and moves the camera without removing the rest of the graph. An explicit focus control can temporarily show its direct neighborhood, and **Show complete graph** restores all nodes, links and status filters.

The searchable directory includes all 16,911 entities and supports company names, aliases, tickers, materials and entity-type filtering. Company ticker search is derived only from reference `ISSUED_BY` links, preserving security/company/legal identity separation. Search results and the relationship ledger have pagination and direct page entry; pagination limits DOM rows, not corpus access. The ledger can show every stored relationship globally or every assertion for a selected entity, without the former 100-edge neighborhood cap. Source details load on demand with quotes, status, source URLs, hashes and observation times. Semantic/keyword corpus search remains available under **Search sources**. The graph bundle loads separately from the trading desk.

The Vite dev/preview server exposes fixed, read-only same-origin endpoints:

- `GET /knowledge/stats`
- `GET /knowledge/network` — compact complete snapshot, including isolated entities and all assertion statuses
- `GET /knowledge/link?id=edge:...` — exact source evidence for one stored assertion
- `GET /knowledge/entities?q=NVDA`
- `GET /knowledge/graph?entity=equity:NASDAQ:NVDA&hops=3&candidates=false`
- `GET /knowledge/search?q=memory%20packaging%20NVIDIA`

The `/knowledge/network` endpoint has **no node, edge or hop cap**. Both source queries run in one read-only repeatable-read transaction; every returned edge must have both endpoints in the snapshot. The default snapshot now uses a 24-hour private server disk cache and browser IndexedDB cache, with saved layout reuse. Large responses support gzip (about 1.04 MB compressed), and unchanged refreshes return HTTP 304 using a content-derived ETag. Explicit historical `as_of` requests bypass the current-snapshot cache. Evidence details are fetched separately, keeping the full-network payload compact. See [cache and graph analyst details](graph_cache_and_agent.md).

The older `/knowledge/graph` endpoint retains its four-hop, 60-node and 100-edge bounds for lightweight consumers; it is no longer the default map's data source. Network, link, graph and source-search endpoints support ISO `as_of` observation gates. Historical availability is not inferred from report years. Source-provider failure visibly falls back to keywords; database failure is explicit. If WebGL is unavailable, the complete searchable directory and relationship ledger remain accessible with an explicit map error.

## Configure and publish

Keep `DATABASE_URL` and `OPENROUTER_API_KEY` in ignored `web/.env.local`. Run from the repository root:

```sh
uv sync --locked --group knowledge
uv run --group knowledge python scripts/publish_knowledge_neon.py --embed
cd web
npm install
npm run dev
```

The publisher imports the pinned SQLite snapshot in one transaction. It verifies existing IDs against the imported contents, inserts only missing records, and refuses changed evidence under an existing ID. It records snapshot SHA-256 and counts. Embedding batches commit separately, are bounded, validate provider response ordering/dimensions/finite nonzero values, and resume from missing chunks. Reruns reuse existing embeddings and do not redownload the source corpus.

On first publish, a dedicated `alphacouncil_graph_reader` login receives schema USAGE and table SELECT privileges. Its connection string is written as **`KNOWLEDGE_DATABASE_URL`** to the ignored local file, which is restricted to owner read/write. The web graph service uses this login and read-only transactions; the owner URL is used only for imports. The reader cannot insert, update, delete or create objects in the graph schema. Database and provider keys are never browser environment variables. This is a local development service; a public deployment needs its own authenticated server and provider-usage controls.

## Validation

**186 Python tests and 53 web tests passed**, and the production frontend build/typecheck passed. The original Neon audit confirmed imported counts against SQLite, all passage offsets, evidence quotes, source input hashes for every embedding, vector dimensions, observation ordering, the pgvector extension/index and SELECT-only service permissions. The complete-network audit additionally compared every node ID and every assertion's ID, endpoints, predicate and status with SQLite; none were missing. A snapshot before source observation returned no entities or links. Exact on-demand evidence and hybrid search were verified.

Browser checks verified all 16,911 nodes and 15,411 edges in the renderer, ticker/name/type search, selection without hiding the full graph, explicit neighborhood focus, restoring all records, status filters retaining isolated nodes, the last page of all 666 NVIDIA assertions, source inspection, the last directory page, semantic search, and a mobile viewport without horizontal page overflow. No browser errors occurred. Unit tests cover separate identities, ticker derivation, disconnected entities, parallel source assertions beyond the former cap and deterministic finite starting positions. Desktop/mobile screenshots and `.context/complete_graph_validation.json` retain that evidence. The subsequent [graph analyst](graph_cache_and_agent.md) adds cited questions and conditional stock research hypotheses. Automatic news enrichment, broader relationship review and validated quantitative financial impact modeling remain future work.
