# Auditable supply-chain evidence extraction

`src/alphacouncil/knowledge/extract.py` provides deterministic lexical extraction from exact issuer-report or article chunks. It requires no language-model provider, key, or inference call. The result is a lexical retrieval/GraphRAG foundation, **not a complete semantic LLM system or a validated causal market model**.

## Interface and provenance

```python
from alphacouncil.knowledge.extract import extract_document, extract_edges

result = extract_document(document, chunks, company_catalog, issuer_entity_id=issuer_id)
# result: entities, edges, evidence_spans, claims, warnings, extractor_version
edges = extract_edges(document, chunks, company_catalog, issuer_entity_id=issuer_id)
```

Documents require `id`, `source_url`, and `first_observed_at_utc`; optional `published_at_utc` remains distinct from first observation. Source hash is retained when supplied. For extracted assertions the caller supplies the indexing/first-extraction time here, retaining the earlier raw-download observation on the original stored document. Downloading a report does not imply its structured edges were already known. An issuer may be passed explicitly or as `metadata.issuer_entity_id`. Mark news with `metadata.document_type="news"` or another source kind containing `news`/`article`.

Chunks require `id` (or `chunk_id`) and the exact `text`; supply `page_id`, `page_number`, and the chunk's zero-based page `start_offset`. Optional `end_offset` must match the exact length, and optional `page_text` is checked for a precise slice round trip. Offsets are Unicode character offsets and half-open, not PDF byte positions. No normalization changes the text before evidence offsets are calculated.

Every edge contains the store-compatible subject, predicate, object, document/chunk IDs, status, observation/publication timestamps, exact evidence quote, and metadata. `metadata.evidence_span` retains page and chunk offsets, source URL, source hash when present, and exact text. Stable IDs make repeated extraction deterministic and deduplicable. Named entity/taxonomy spans are preserved separately from the enclosing statement.

## Relationship meaning

| Extracted evidence | Predicate/status | Meaning |
|---|---|---|
| An issuer explicitly lists named suppliers or says it purchases from them | named supplier → issuer `SUPPLIES_TO`, `reported` | A narrow source assertion, not independently verified |
| An issuer explicitly lists named customers or says it sells to them | issuer → named customer `SUPPLIES_TO`, `reported` | Direction follows the reported commercial role |
| Ordinary company mention/co-occurrence | `MENTIONS`, `candidate` | A research lead with `needs_review=true`; no supplier proof |
| Commodity/product/industry keyword | `MENTIONS_EXPOSURE`, `candidate` | The document mentions the topic; exposure role remains unspecified |
| News language suggesting an impact | separate claim, `hypothesis` | Sourced claim to investigate; no established causal effect |

High-precision templates include `our suppliers include`, `our customers include`, `we purchase … from`, and `we sell … to`. A named catalog company must be in the matching role's list/clause. Independent subjects and predicates terminate a list; a second company merely appearing later in a sentence is insufficient. Negated, conditional, potential, former, terminated, and forward-looking statements are not upgraded to reported relationships. Conservative suppression can discard an otherwise valid statement if its surrounding sentence contains a negation or conditional.

Reported means **the issuer's text explicitly reports the relation**. `independently_verified=false` remains attached. It does not establish transaction size, contract timing, concentration, present validity, reciprocal confirmation, or who benefits from a security-price move. No temporal validity is invented from the report's publication date. A role attributed to the issuer requires the caller to associate the document with the correct issuer; the extractor does not verify website ownership itself.

## Entity and economic distinctions

Known companies/securities use the supplied catalog, full names, and aliases. Duplicate aliases across entities produce ambiguity warnings and no identified company for that span. Very short company aliases such as `CAT` or `V` require an explicit ticker marker; ordinary words and letters do not become issuers. Ticker-only matches remain candidates rather than being silently treated as named supplier-list entries. Security objects remain separate from company objects.

`configs/knowledge_ontology.json` contains 30 commodity, product, and industry topics, including copper, lithium, natural gas, electricity, steel, semiconductors, memory chips, networking equipment, data centers, batteries, wafer fabrication, automotive, shipping, and telecommunications. Taxonomy entities use the store's lowercase kinds and are emitted only when their aliases occur in the supplied text. A mention of a material does not prove the company produces or consumes it.

Metric-domain tags separately identify `security_price`, `company_operating_metrics`, `commodity_supply`, and `commodity_demand`. These tags describe a statement's vocabulary. Company revenue, a share price, copper production, and copper demand are not interchangeable variables. The extractor never creates automatic `BENEFITS_FROM`, price-growth, or return predictions from their co-occurrence.

News enrichment uses sourced text as untrusted data. It does not execute embedded instructions, visit embedded URLs, grant tool permissions, or accept article text as a replacement extraction policy. News relationships remain candidates, and impact claims remain hypotheses with exact quotations. Statements from a third-party article are never promoted to an issuer's first-person supplier assertion.

## Limits and validation

The extractor favors precision over recall. It does not solve pronouns, nested corporate ownership, arbitrary tables, PDF reading order, names missing from the catalog, long-distance references, geographic role attribution, numeric exposure sizing, or changing relationships over time. Alias matching tolerates PDF whitespace and single line wraps while preserving source offsets. Abbreviations, complex coordination, and indirect wording may leave a relationship as a candidate or miss it. Keyword and alias matches can still be ambiguous; default retrieval should exclude candidates unless the researcher explicitly asks to review them.

A local extraction smoke at **2026-10-24 16:31:44 UTC** processed 22 then-complete retrieved issuer reports (2,640 pages) against the 105-issuer collection catalog. It produced 4,211 candidate edges and **zero reported supplier/customer edges** under these narrow templates; every retained span round-tripped to its source page. Runtime was 9.9 seconds with cached alias patterns. This is a dated extraction snapshot, not a claim that all possible commercial relationships have been found. The snapshot is saved in `.context/knowledge_extraction_smoke.json`, and the parent graph was not changed by this smoke.

Tests cover supplier/customer direction, misleading same-sentence co-occurrence, negation, hypothetical contracts, first-person clause boundaries, short ticker ambiguity, duplicate aliases, security/company separation, exact Unicode span round trips, provenance, deterministic output, news prompt injection as inert text, and distinct economic metric domains. `tests/test_knowledge.py` additionally tests direct extractor-to-store ingestion and exclusion of candidate keyword context from default retrieval.

```sh
uv run --group training --group analysis pytest -q tests/test_knowledge_extract.py tests/test_knowledge.py
```
