# Broad US equity relationship data foundation

Corpus snapshot: **October 24, 2026, 16:48 UTC**. Collection, evidence storage, graph traversal and lexical retrieval are implemented. The subsequent [Neon implementation](knowledge_neon.md) adds the asset graph interface and pgvector semantic search over the same corpus. The [graph analyst](graph_cache_and_agent.md) now provides cited questions and conditional research shortlists. Community summaries and automatic news enrichment remain future work.

## Collected coverage

| Dataset | Actual coverage | Interpretation |
|---|---:|---|
| Current Nasdaq Trader listing references | 7,481 securities | US-exchange-listed, non-ETF, non-test issues; includes foreign issuers, preferred shares and other security types. Not 7,481 unique US companies. |
| Curated legal-entity research universe | 105 company queries | Broad research buckets spanning 11 sectors; not exhaustive or a verified sector classification. |
| GLEIF consolidation records | 1,814 records | Accounting consolidation, not supplier/customer relationships. One page of up to 200 children per queried entity. |
| Full annual reports / 10-K / 20-F | 26 documents | Captured primary issuer documents, including issuer-hosted HTML filings. |
| Issuer announcements | 5 documents | A small relationship example corpus; includes a historical 2012 announcement. |
| Annual overview | 1 document | Prologis overview, excluded from full-report counts. |
| Issuer text | 3,335 pages / logical HTML sections | Across 11 research sectors; Real Estate currently has only the overview. |
| Searchable passages | 12,441 | Exact page character offsets and document citations. |

The graph has **16,911 typed entities**: 7,481 securities, 7,482 listing-associated company records, 1,918 legal entities, and 30 commodity/product/industry topics. Listing-associated company records are provisional identities and may include multiple securities associated with one real issuer. They are not a deduplicated company master. Company, security and legal entity IDs remain separate.

The 226 stored documents include listing and registry reference snapshots as well as the 32 usable issuer documents. There are 3,529 total pages including logical reference pages. Exact counts, source errors and hashes are in [knowledge_inventory.json](knowledge_inventory.json).

## What the edges establish

| Status | Count | Meaning |
|---|---:|---|
| `reference` | 9,295 | 7,481 security-to-provisional-issuer references and 1,814 accounting consolidation records. |
| `reported` | 5 | Agent-reviewed exact publisher statements; not independently confirmed active contracts. |
| `candidate` | 6,111 | 104 legal-name match assertions, 884 company mentions and 5,123 commodity/product/industry mention assertions requiring review. |

Bounded reference retrieval excludes candidates unless explicitly requested. The newer complete corpus map exposes all statuses as labeled, user-filterable records. Retrieved passages can still contain mentions; a passage is evidence to read, not automatically a confirmed relationship. The narrow automatic supplier/customer templates accepted **zero reported supplier/customer edges** from this corpus. The five reported edges were separately reviewed against exact source passages. Mention counts must not be presented as supply-chain coverage.

The reviewed NVIDIA example contains these publisher-reported relations:

| Subject | Relation | Object | Primary evidence |
|---|---|---|---|
| TSMC | Manufactures for | NVIDIA | [NVIDIA manufacturing announcement](https://blogs.nvidia.com/blog/nvidia-manufacture-american-made-ai-supercomputers-us/) |
| NVIDIA | Partners with for packaging/testing | Amkor | [NVIDIA manufacturing announcement](https://blogs.nvidia.com/blog/nvidia-manufacture-american-made-ai-supercomputers-us/) |
| NVIDIA | Partners with for packaging/testing | SPIL | Same NVIDIA announcement; source-scoped identity, no inferred ticker |
| Micron | Collaborates with | NVIDIA | [Micron product announcement](https://investors.micron.com/news/press-release/2025/Micron-Innovates-From-the-Data-Center-to-the-Edge-With-NVIDIA-03-18-2025/default.aspx) |
| Microsoft | Deploys technology from | NVIDIA | [Azure deployment announcement](https://azure.microsoft.com/en-us/blog/microsoft-azure-delivers-the-first-large-scale-cluster-with-nvidia-gb300-nvl72-for-openai-workloads/) |

These statements do not quantify incremental orders, revenue sensitivity, margins, capacity constraints, contract validity today or expected stock returns. A path establishes which evidence connects entities; it does not establish that every connected stock benefits from a news event. No financial impact weights were fabricated.

## Source integrity and time

Raw HTTP bodies retain source/final URLs, status, retrieval time, byte counts, SHA-256 and failures. Hashes are verified before reuse. Requests, retries and response bytes are bounded; permanent failures are retained without bypassing access controls. A nominal PDF returning a site map or maintenance page is rejected. Truncated downloads are never indexed.

Exact page text and character offsets are retained. Assertions record their actual first-extraction time separately from the earlier document receipt. Publication timestamps remain unknown where an exact UTC instant was not established. Report years and date-only labels are not substituted for publication timestamps. Today's collected documents cannot be used as if this system knew them in a historical backtest.

Direct SEC ticker/submissions requests returned **403** here. Issuer-hosted reports supplied partial coverage. Eight of the 40 configured candidates were unavailable or rejected: WMT, XOM, AMT, GOOG, ETN, ASML, AEP and PEP. Reasons include access restrictions, certificate errors, timeouts, invalid content and a 64 MiB limit. The earlier valid J&J PDF snapshot is preserved despite a later maintenance response.

[Nasdaq's directory definitions](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs) describe listing fields. [GLEIF's Level 2 specification](https://www.gleif.org/en/lei-data/access-and-use-lei-data/level-2-data-relationship-record-rr-cdf-2-1-format) defines consolidation relationships. Neither is a complete commercial supply-chain dataset. See [source discovery and gaps](knowledge_sources.md) and [extraction rules](knowledge_extraction.md).

## Reproduce and inspect

```sh
uv sync --locked --group training --group analysis --group web --group knowledge
uv run --group knowledge python scripts/collect_knowledge.py --phase all --limit-issuers 105
uv run --group knowledge python scripts/index_knowledge.py
uv run python scripts/export_knowledge.py
uv run python scripts/query_knowledge.py 'NVIDIA TSMC Micron packaging' \
  --entity equity:NASDAQ:NVDA --max-hops 3 --max-passages 3
```

Collection reuses pinned raw snapshots; rerunning does not refresh upstream data silently. The listing universe is a current snapshot, not a historical constituent archive. Indexing is idempotent and does not backdate newly extracted claims.

`data/knowledge/` holds the local graph database, raw cache, report text and typed JSONL exports. It is gitignored; preserve it to retain this corpus. Exports retain assertion status, timestamps and provenance. Check redistribution rights before publishing raw source documents.

The running read-only local API exposes:

- `GET http://127.0.0.1:8000/api/v1/knowledge/stats`
- `GET http://127.0.0.1:8000/api/v1/knowledge/entities?q=NVDA`
- `GET http://127.0.0.1:8000/api/v1/knowledge/graph/NVDA`
- `GET http://127.0.0.1:8000/api/v1/knowledge/query?q=NVIDIA%20TSMC&entity=equity:NASDAQ:NVDA&max_hops=3`

The Python reference API requires exact names/aliases or stable IDs and preserves ambiguity. It supports observation-time filtering, bounded traversal and literal lexical search with citations. The web explorer now draws the Neon copy through separate same-origin `/knowledge/*` endpoints, described in [knowledge_neon.md](knowledge_neon.md).

## Validation and remaining work

**177 tests passed**. Live local API checks returned HTTP 200 for statistics, lookup, the NVIDIA graph and retrieval, with candidates excluded by default. The full corpus audit verified 242 raw attempt receipts, 32 usable document page hashes, every stored page hash, all 12,441 passage offsets, every edge quote and foreign key, observation ordering, database integrity, code/configuration hashes and all export hashes/counts. Reindexing preserved counts. Audit detail is local in `.context/knowledge_validation.json`.

Next: fill missing full reports, resolve issuer/security/LEI identities using authoritative identifiers, and review named suppliers/customers beyond NVIDIA. Measure accepted relationship coverage and extraction precision before expanding counts. Then connect deduplicated news with first-seen timestamps, cited event-to-entity links and explicit impact hypotheses. Generated reasoning should consume those evidence paths while preserving uncertainty.
