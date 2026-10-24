# Company people and professional background research

Open the relationship graph, select a company, then choose **Research people & backgrounds**. This opens a prepared question in **Ask the graph**; send it to run research. The welcome panel also offers a people-research question. Users can ask follow-ups about a named individual and their professional connection to a company.

`EXA_API_KEY` in `web/.env.local` is loaded only by the server. The existing graph analyst receives a `research_company_people` tool when Exa is configured. No additional SDK or database credentials are required. The capability is disclosed in `/graph-agent/config` without exposing the key.

## Retrieval and evidence

The tool first requires an exact company ID from the existing graph. The server constructs the search from the resolved company name and listing tickers, optionally with a person's name. It calls Exa's [Search API](https://exa.ai/docs/reference/search) with text extraction, up to five documents and 5,000 characters per document. This is a bounded search tool orchestrated by the existing agent, rather than a bulk people-directory or autonomous Exa Agent run. Queries prefer company biographies, filings and institutional sources without assuming every returned page is authoritative or on topic.

The model can return up to six structured profiles, with a recommendation to keep the answer to three useful people. Each profile includes a company identity, person's name, source-reported current/former/unclear affiliation, professional claims, and identity/date caveats. Supported claim topics are company role, previous experience, education, research and other professional background. Each claim must carry a citation ID and exact source excerpt.

The final-answer validator requires:

- A real company in the selected graph and at least one company-role claim for each person.
- Evidence actually retrieved through Exa for that company during this run.
- The person's name in the source text, and the company's name or ticker in company-role evidence.
- A supporting excerpt present verbatim after Unicode and whitespace normalization; fabricated or paraphrased quotes are rejected.
- Registered citation IDs included in the answer's cited sources.

These checks establish provenance and catch common identity/citation substitutions. They do **not** independently prove that a source is correct, that the excerpt semantically entails every word of a claim, or that a described role is still current. Profiles remain explicitly marked **research leads**. Names are not globally merged; lead IDs are scoped to company, normalized name and company-role source identities. The accepted Neon graph is not modified, so neither the node count nor accepted relationship count increases from a search. Later ingestion/review of people and career assertions would be a separate step.

Web research has a separate retrieval timestamp and optional publication date. Unknown publication dates remain unknown; retrieving a page today does not establish when its claims were published or when employment started. Live web evidence is not presented as part of the older saved graph snapshot. The UI exposes each claim's excerpt, source link and retrieval/publication metadata, plus a link back to the company. Source instructions are untrusted data. The agent is instructed to limit research to public professional information and avoid private contact details and sensitive personal information.

## Caching and limits

Source lookups are cached for 24 hours in server memory and private atomic JSON files under the gitignored `data/knowledge/cache/exa-people/` directory. The key includes exact company identity and constructed query; a named-person search has its own cache entry. Cached text is checked against its content hash, and cache files contain sources, not API keys. Concurrent identical cold requests are deduplicated. Source failures do not fabricate profiles or overwrite previously saved files. Up to 64 source queries are retained in memory; saved disk files remain until removed manually. The cache survives server restarts.

Each answer permits at most three Exa searches, including cache hits. Provider requests time out after 20 seconds and are tied to question cancellation. Exa search fees are separate from the existing OpenRouter model cost stop condition; the search cap bounds calls, not a guaranteed dollar amount. There is no background crawl or automatic search when opening the graph. Existing identical-answer reuse lasts 30 minutes and includes the Exa-enabled capability in its versioned cache key.

## Validation

The integrated web suite passed **106 tests** and the production build/typecheck. New tests cover company/person query scoping, exact evidence, invented quotes, same-name mismatches, wrong-company matches, missing roles and sources, three-call limits, publication/retrieval separation, source deduplication, cache expiry/restart/corruption, cancellation and provider failures.

A real Exa + OpenRouter run resolved NVIDIA and returned two validated profiles with role and previous-experience claims from NVIDIA's own biographies: [Jensen Huang](https://www.nvidia.com/en-us/about-nvidia/board-of-directors/jensen-huang/) and [Colette Kress](https://www.nvidia.com/en-us/about-nvidia/governance/management-team/colette-kress/). The search returned five official company pages and Exa reported a $0.007 search cost. The model used four calls. Its SDK-reported cost was zero, which should not be interpreted as proof of zero provider billing.

The shared dev server restarted during the first attempted request while concurrent workspace changes were being applied. The completed live run used an isolated Vite preview on port 4181, avoiding hot reload interruptions. Repeating the same HTTP request reused the accepted answer with no model usage event. Browser checks replay that captured actual answer without additional provider calls, inspect both profiles and source excerpts, exercise the company research action, and check mobile overflow. Artifacts are `.context/exa_people_live_result.json`, `.context/exa_people_answer_cache_validation.json`, `.context/exa_people_browser_validation.json`, and `.context/exa_people_desktop.png` / `exa_people_mobile.png`.
