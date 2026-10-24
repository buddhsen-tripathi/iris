#!/usr/bin/env python3
"""Collect broad US listing references, legal relationships, and issuer documents."""

import argparse
import json
from pathlib import Path

from alphacouncil.data.archive import utc_now, write_json
from alphacouncil.knowledge.collect import Sources, collect_catalog, collect_gleif, collect_reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["catalog", "gleif", "reports", "all"], default="all")
    parser.add_argument("--limit-reports", type=int, default=100)
    parser.add_argument("--limit-issuers", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit_reports <= 200 or not 1 <= args.limit_issuers <= 200:
        raise ValueError("This collection limits each enrichment batch to 200")
    sources = Sources()
    sources.root.mkdir(parents=True, exist_ok=True)
    result = {"started_at_utc": utc_now().isoformat(), "mode": "KNOWLEDGE_DATA_COLLECTION", "phase": args.phase}
    reports = json.loads(Path("configs/knowledge_reports.json").read_text())
    if args.phase in {"catalog", "all"}:
        result["listing_count"] = len(collect_catalog(sources))
        # Explicitly capture permanent SEC errors, never bypass or retry a 403.
        result["sec_preflight"] = [sources.get(url)[1] for url in ("https://www.sec.gov/files/company_tickers_exchange.json", "https://data.sec.gov/submissions/CIK0001045810.json")]
    if args.phase in {"gleif", "all"}:
        names = json.loads(Path("configs/knowledge_universe.json").read_text()) if Path("configs/knowledge_universe.json").exists() else reports
        unique = {row["ticker"]: row for row in names}
        gleif = collect_gleif(sources, list(unique.values())[:args.limit_issuers])
        result["gleif_issuers_queried"] = len(gleif)
        result["gleif_relationship_records"] = sum(len(item["records"]) for row in gleif for item in row["relationships"])
    if args.phase in {"reports", "all"}:
        documents = collect_reports(sources, reports[:args.limit_reports])
        result["reports"] = [{"ticker": row["report"]["ticker"], "status": row["status"], "page_count": row.get("page_count", 0), "error": row.get("error")} for row in documents]
    result["finished_at_utc"] = utc_now().isoformat()
    write_json(sources.root / f"collection_{args.phase}.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
