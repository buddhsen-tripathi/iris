# Primary issuer sources for broad US equity GraphRAG

The candidate source catalog in `configs/knowledge_reports.json` contains **40 documents: 35 annual reports / 10-K / 20-F candidates from 35 US-listed issuers across all 11 broad equity sectors, plus five issuer announcements**. TSM and ASML are foreign issuers with US-listed securities. This is a deliberately broad seed universe, not comprehensive market or supply-chain coverage.

Sources were discovered through issuer investor-relations pages and search results pointing to issuer-controlled documents. Public issuer CDNs such as Q4, CloudFront and GCS are included when the issuer identifies the report. The catalog retains unavailable candidates to make coverage gaps visible. No SEC endpoint, blocked third-party annual-report archive, authentication or access-control workaround is used.

## Availability checked on October 24, 2026

Actual Python HTTP GET prefix checks found **28 annual-document candidates and all five announcements accessible with HTTP 200**. PDF candidates were checked for the `%PDF` signature; successful HTTP status alone did not count as a report. Microsoft and Prologis supply HTML web editions, and Coca-Cola supplies issuer-hosted 10-K HTML. Prologis's web edition is narrative annual-report content, not a substitute for a complete 10-K.

The prefix check proves reachability and broad content type, not successful full download, text extraction, document identity throughout the file, or chunk quality. The collector's raw receipts, checksums, extracted text and coverage results are authoritative for ingested data. Discovery/preflight detail is recorded in `.context/report_landing_links.json`, `.context/report_more_links.json` and `.context/knowledge_preflight.json`.

| Sector | Accessible annual-document candidates | Explicit gaps |
|---|---|---|
| Information Technology | [NVIDIA 2026](https://s201.q4cdn.com/141608511/files/doc_financials/2026/ar/2026-Annual-Report-Web.pdf), [Microsoft 2025 HTML](https://www.microsoft.com/investor/reports/ar25/index.html), [TSMC 2025 Form 20-F](https://investor.tsmc.com/sites/ir/sec-filings/2025_20F%20Report.pdf), [Micron 2025 10-K](https://s25.q4cdn.com/621799436/files/doc_financials/2025/ar/2025-Form-10-K.pdf) | ASML report CDN returns 403 |
| Communication Services | [Disney 2025](https://investors.thewaltdisneycompany.com/files/doc_financials/2025/ar/2025-Annual-Report.pdf) | Indexed Alphabet PDF now returns an HTML site map |
| Consumer Discretionary | [Home Depot 2025](https://ir.homedepot.com/~/media/Files/H/HomeDepot-IR/2026/thd-annualreport-2025.pdf), [Nike 2025 10-K](https://s1.q4cdn.com/806093406/files/doc_financials/2025/ar/Nike-Inc-2025_10K.pdf) | — |
| Consumer Staples | [Costco 2025](https://s201.q4cdn.com/287523651/files/doc_financials/2025/ar/COST-Annual-Report-2025.pdf), [P&G 2026](https://s204.q4cdn.com/332108499/files/doc_financials/2026/ar/2026_annual_report.pdf), [Coca-Cola 2025 10-K HTML](https://investors.coca-colacompany.com/filings-reports/all-sec-filings/content/0001628280-26-010047/ko-20251231.htm), [Target 2025](https://corporate.target.com/getmedia/79214b4b-6331-4b1c-b76f-acff121b40f9/2025-Annual-Report-Target-Corporation.pdf) | Walmart and PepsiCo PDFs return 403 |
| Energy | [ConocoPhillips 2025](https://static.conocophillips.com/files/resources/2025-conocophillips-annual-report.pdf) (10,192,799 bytes), [ExxonMobil 2025](https://investor.exxonmobil.com/company-information/annual-reports-proxy) | ExxonMobil PDF exceeds the collector’s 64 MiB limit and is excluded from ingested coverage |
| Financials | [JPMorgan Chase 2025](https://www.jpmorganchase.com/content/dam/jpmc/jpmorgan-chase-and-co/investor-relations/documents/annualreport-2025.pdf), [Visa 2025](https://s29.q4cdn.com/385744025/files/doc_downloads/2025/Visa-Fiscal-2025-Annual-Report.pdf), [Berkshire Hathaway 2025](https://berkshirehathaway.com/2025ar/2025ar.pdf) | — |
| Health Care | [UnitedHealth 2025 10-K](https://www.unitedhealthgroup.com/content/dam/UHG/PDF/investors/2025/UNH-Q4-2025-Form-10-K.pdf), [Pfizer 2025 10-K](https://s206.q4cdn.com/795948973/files/doc_financials/2025/q4/2025-Form-10-K.pdf), [Cigna 2025](https://s202.q4cdn.com/757723766/files/doc_financials/2025/ar/2025-Annual-Report.pdf) | Later J&J check returned maintenance HTML; preserve the collector’s earlier valid PDF snapshot |
| Industrials | [Deere 2025](https://s22.q4cdn.com/253594569/files/doc_financials/2025/ar/2025-Deere-Company-Annual-Report.pdf), [GE Aerospace 2025](https://www.geaerospace.com/sites/default/files/geaerospace_2025annualreport.pdf), [3M 2025](https://investors.3m.com/financials/sec-filings/content/0000066740-26-000155/0000066740-26-000155.pdf) | Eaton request timed out |
| Materials | [Nucor 2025](https://s202.q4cdn.com/531038915/files/doc_financials/2026/ar/2025-Nucor-Annual-Report.pdf), [Freeport-McMoRan 2025](https://s22.q4cdn.com/529358580/files/doc_financials/annual/AR_2025.pdf), [Linde 2025](https://assets.linde.com/-/media/global/corporate/corporate/documents/investors/full-year-financial-reports/2025-annual-report-to-shareholders.pdf) | — |
| Real Estate | [Prologis 2025 annual web edition](https://www.prologis.com/annual-report-2025) | American Tower report CDN returns 403; Prologis web edition is not a full filing |
| Utilities | [NextEra 2025](https://www.investor.nexteraenergy.com/~/media/Files/N/NEE-IR/2025%20Annual%20Report.pdf), [AEP 2025 annual report in proxy appendix](https://docs.aep.com/docs/investors/AnnualReportsProxies/docs/25annrep/2026ProxyAppendixA.pdf) | — |

The unavailable and content-invalid candidates remain in the config as discovered candidates. Availability can vary between observations: the collector captured a genuine J&J PDF before the later maintenance page, so its successful raw receipt remains usable. ExxonMobil passes a PDF prefix check but exceeds the collector’s size limit; ConocoPhillips supplies the verified smaller Energy document. No permanent 403 was retried or bypassed during verification. A transient timeout is distinguished from an access restriction. The collector should preserve these failures and exclude maintenance/site-map pages from document or sector coverage counts.

## Supplier and customer evidence for the NVIDIA example

Five issuer announcements supplement annual filings. These are evidence to extract and date, not hand-written graph edges or trading signals.

| Primary document | Relationship context it can support | Limit |
|---|---|---|
| [NVIDIA: American-made AI supercomputer manufacturing](https://blogs.nvidia.com/blog/nvidia-manufacture-american-made-ai-supercomputers-us/) | NVIDIA manufacturing ecosystem and named partners | Plans and forward-looking statements must retain their modality |
| [NVIDIA and TSMC: AI in fabs, May 31, 2026](https://nvidianews.nvidia.com/news/nvidia-and-tsmc-bring-ai-into-fabs-to-advance-semiconductor-design-and-manufacturing) | Explicit collaboration; TSMC uses NVIDIA products in fab operations | Collaboration direction differs from foundry-supply direction; preserve exact predicate |
| [Micron: NVIDIA collaboration, March 18, 2025](https://investors.micron.com/news/press-release/2025/Micron-Innovates-From-the-Data-Center-to-the-Edge-With-NVIDIA-03-18-2025/default.aspx) | Named product compatibility, memory and system ecosystem | Compatibility does not prove revenue, exclusivity or contract size |
| [Microsoft: Azure GB300 deployment](https://azure.microsoft.com/en-us/blog/microsoft-azure-delivers-the-first-large-scale-cluster-with-nvidia-gb300-nvl72-for-openai-workloads/) | Customer/platform deployment of NVIDIA systems | Public deployment is not a purchase-price or profit-sensitivity estimate |
| [TSMC and ASML: lithography agreement, August 5, 2012](https://pr.tsmc.com/english/news/1734) | Historical direct agreement and investment for lithography development | **Historical evidence only.** Do not infer that a 2012 contract or ownership percentage remains current |

An eventual NVIDIA → foundry → equipment path must cite each independently supported hop. Common mentions in one document are not a supplier edge. A supplier relationship alone does not establish that a demand shock increases another issuer's profit or stock return. Unknown direction, strength, transaction amount and validity end dates should remain unknown.

## Time and provenance rules

Every catalog record includes ticker, issuer name, broad sector, disambiguation aliases, exact document URL, issuer landing URL, document kind, report year, hosting classification and `published_at_utc`. All publication timestamps are null: a year in a filename or a date-only page label does not establish a UTC publication instant. `report_year` is a report/announcement year, not an ingestion or availability timestamp.

The collector must record first observation separately. These documents collected in October 2026 cannot automatically be treated as available to a historical model in 2025. Any date-only publication evidence should retain its precision instead of inventing midnight UTC. The dated 2012 ASML announcement requires historical temporal scope.

Aliases support search and entity disambiguation; they are not evidence of corporate ownership or supply-chain relationships. Brand aliases such as Azure, Optum and Frito-Lay need context, and ordinary words such as Target or Deere require company-aware matching. Exchange-specific ticker spelling, ADR structure, subsidiaries, corporate renaming and business-segment boundaries need explicit registry rules before production entity resolution.

The seed omits many smaller firms, private suppliers, international operating companies, historical report versions and quarterly changes. Annual disclosures may anonymize customers, discuss dependencies without naming counterparties, or describe planned rather than operating capacity. The next data work should measure extracted coverage and evidence quality before expanding entity or edge counts, and should add missing primary documents without constructing relationships from assumptions.
