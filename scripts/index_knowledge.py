#!/usr/bin/env python3
"""Index collected source snapshots into a local graph and exact-citation passages."""

import json
import re
from pathlib import Path

from alphacouncil.data.archive import file_sha256, utc_now, write_json
from alphacouncil.knowledge.collect import ROOT
from alphacouncil.knowledge.extract import VERSION, extract_document
from alphacouncil.knowledge.store import connect, ingest_chunk, ingest_document, ingest_edge, ingest_entity, ingest_page


def add_source(db, receipt, title, name, metadata=None, published=None):
    if not receipt.get("ok") or file_sha256(Path(receipt["path"])) != receipt["sha256"]:
        raise ValueError("Only complete, hash-verified source responses may be indexed")
    document = {"source_url": receipt["url"], "title": title, "source_name": name, "content_sha256": receipt["sha256"],
                "first_observed_at_utc": receipt["observed_at_utc"], "published_at_utc": published, "metadata": metadata or {}}
    document["id"] = ingest_document(db, document)
    return document


def text_chunks(db, document_id, pages, size=1800, overlap=180):
    chunks = []
    for row in pages:
        page_id = ingest_page(db, {"document_id": document_id, **row})
        text, start = row["text"], 0
        while start < len(text):
            end = min(len(text), start+size)
            if end < len(text):
                boundary = text.rfind("\n", start+size//2, end)
                if boundary > start:
                    end = boundary+1
            if text[start:end].strip():
                chunk = {"page_id": page_id, "page_number": row["page_number"], "start_offset": start, "end_offset": end, "text": text[start:end]}
                chunk["id"] = ingest_chunk(db, chunk)
                chunks.append(chunk)
            if end == len(text):
                break
            start = max(start+1, end-overlap)
    return chunks


def main():
    now = utc_now().isoformat()
    path = ROOT / "graph.sqlite3"
    db = connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS report_ingestions(document_id TEXT PRIMARY KEY, extracted_at_utc TEXT, extractor_version TEXT, edge_count INTEGER, warning_count INTEGER)")
    catalog = json.loads((ROOT / "catalog.json").read_text())
    listings = catalog["listings"]
    listing_by_ticker = {row["ticker"]: row for row in listings}
    source_documents = {}
    for receipt in catalog["receipts"]:
        if not receipt["ok"]:
            continue
        document = add_source(db, receipt, "Nasdaq Trader symbol directory", "Nasdaq Trader", {"kind": "listing_reference", "historical_membership": False})
        ingest_page(db, {"document_id": document["id"], "page_number": 1, "text": Path(receipt["path"]).read_text(encoding="utf-8-sig")})
        source_documents[receipt["url"]] = document
    for row in listings:
        observed = row["first_observed_at_utc"]
        ingest_entity(db, {"id": row["security_id"], "kind": "security", "name": row["name"], "aliases": [row["ticker"]],
                          "identifiers": {"ticker": row["ticker"], "listing_exchange": row["exchange"]}, "first_observed_at_utc": observed,
                          "metadata": {"instrument_classification": row["instrument_classification"], "source_url": row["source_url"]}})
        ingest_entity(db, {"id": row["issuer_id"], "kind": "company", "name": row["issuer_name_from_listing"],
                          "first_observed_at_utc": observed, "metadata": {"identity_resolution": "listing_name_only", "not_legal_registration_proof": True}})
        ingest_edge(db, {"subject_id": row["security_id"], "predicate": "ISSUED_BY", "object_id": row["issuer_id"],
                        "document_id": source_documents[row["source_url"]]["id"], "status": "reference", "first_observed_at_utc": now,
                        "evidence_quote": row["name"], "metadata": {"basis": "Nasdaq security name; legal entity registration not verified"}})
    db.commit()
    report_config = json.loads(Path("configs/knowledge_reports.json").read_text())
    scope_overrides = {row["document_url"]: row["document_scope"] for row in report_config if row.get("document_scope")}
    universe = json.loads(Path("configs/knowledge_universe.json").read_text())
    seeds = {row["ticker"]: row for row in universe}
    for report in report_config:
        seed = seeds.setdefault(report["ticker"], dict(report))
        seed["aliases"] = sorted(set(seed.get("aliases", []) + report.get("aliases", [])))
    company_catalog = []
    for ticker, seed in seeds.items():
        listing = listing_by_ticker.get(ticker, listing_by_ticker.get(ticker.replace("-", ".")))
        issuer_id = listing["issuer_id"] if listing else f"issuer:research:{ticker}"
        # Curated aliases are resolution hints, not legal-identity or sector evidence.
        entity = {"id": issuer_id, "kind": "company", "name": seed["name"], "aliases": list(seed.get("aliases", [])),
                  "first_observed_at_utc": now, "metadata": {"alias_origin": "curated_research_scope", "ticker_hint": ticker,
                  "registered_identity_verified": False, "research_bucket": seed.get("research_bucket", seed.get("sector"))}}
        ingest_entity(db, entity)
        company_catalog.append(entity)
        seed["issuer_id"] = issuer_id
    # Legal entities and accounting-consolidation records remain their own identities.
    for filename in sorted((ROOT / "gleif").glob("*.json")):
        data = json.loads(filename.read_text())
        receipt = data.get("search_receipt")
        if not receipt or not receipt["ok"]:
            continue
        document = add_source(db, receipt, f"GLEIF legal-name search: {data['query_name']}", "GLEIF", {"kind": "legal_reference"})
        ingest_page(db, {"document_id": document["id"], "page_number": 1, "text": Path(receipt["path"]).read_text()})
        for match in data["exact_matches"]:
            lei = match["id"]
            name = match["attributes"]["entity"]["legalName"]["name"]
            ingest_entity(db, {"id": f"lei:{lei}", "kind": "legal_entity", "name": name, "identifiers": {"lei": lei},
                              "first_observed_at_utc": receipt["observed_at_utc"], "metadata": match["attributes"]})
            seed = seeds.get(data["ticker"])
            if seed:
                ingest_edge(db, {"subject_id": seed["issuer_id"], "predicate": "MATCHES_LEGAL_NAME", "object_id": f"lei:{lei}",
                                "document_id": document["id"], "status": "candidate", "first_observed_at_utc": now,
                                "metadata": {"needs_review": True, "identity_not_proven_by_name_alone": True}})
        for item in data["relationships"]:
            receipt = item["receipt"]
            if not receipt["ok"]:
                continue
            document = add_source(db, receipt, f"GLEIF {item['kind']}: {data['query_name']}", "GLEIF", {"kind": "accounting_consolidation_reference", "pagination_truncated": item.get("truncated", False)})
            ingest_page(db, {"document_id": document["id"], "page_number": 1, "text": Path(receipt["path"]).read_text()})
            for record in item["records"]:
                attributes = record["attributes"]
                relation = attributes["relationship"]
                for node in (relation["startNode"], relation["endNode"]):
                    # Parent search may have supplied a real name already; do not replace it with an unknown LEI display name.
                    if db.execute("SELECT 1 FROM entities WHERE id=?", (f"lei:{node['id']}",)).fetchone() is None:
                        ingest_entity(db, {"id": f"lei:{node['id']}", "kind": "legal_entity", "name": node["id"], "identifiers": {"lei": node["id"]},
                                          "first_observed_at_utc": receipt["observed_at_utc"], "metadata": {"legal_name_not_collected": True}})
                if relation["status"] != "ACTIVE":
                    continue
                periods = [period for period in relation.get("periods", []) if period.get("type") == "RELATIONSHIP_PERIOD"]
                ingest_edge(db, {"subject_id": f"lei:{relation['startNode']['id']}", "predicate": relation["type"], "object_id": f"lei:{relation['endNode']['id']}",
                                "document_id": document["id"], "status": "reference", "first_observed_at_utc": now,
                                "valid_from_utc": periods[0].get("startDate") if periods else None, "valid_to_utc": periods[0].get("endDate") if periods else None,
                                "metadata": {"gleif_record_id": record["id"], "registration": attributes.get("registration"),
                                             "meaning": "Accounting consolidation; not a supplier/customer relationship or ownership percentage", "source_record_valid_from": attributes.get("validFrom")}})
    db.commit()
    report_status = []
    for manifest_path in sorted((ROOT / "reports").glob("*/manifest.json")):
        report = json.loads(manifest_path.read_text())
        metadata = report["report"]
        report_status.append({"ticker": metadata["ticker"], "status": report["status"], "sector": metadata.get("sector"), "kind": metadata["document_kind"], "source_url": metadata["document_url"], "error": report.get("error") or report.get("receipt", {}).get("error"), "pages": report.get("page_count", 0), "document_scope": scope_overrides.get(metadata["document_url"], report.get("document_scope", "captured_document_text"))})
        if report["status"] != "complete":
            continue
        if file_sha256(Path(report["pages_path"])) != report["pages_sha256"]:
            raise ValueError("Extracted document hash mismatch")
        seed = seeds[metadata["ticker"]]
        kind = "news" if metadata["document_kind"] == "partnership_announcement" else "issuer_report"
        document = add_source(db, report["receipt"], f"{metadata['name']} {metadata.get('report_year','')} {metadata['document_kind']}", metadata["name"],
                              {"document_type": kind, "issuer_entity_id": seed["issuer_id"], "report_year": metadata.get("report_year"),
                               "source_kind": "issuer_hosted", "landing_url": metadata["landing_url"], "extraction_method": report["extraction_method"]}, metadata.get("published_at_utc"))
        if db.execute("SELECT 1 FROM report_ingestions WHERE document_id=?", (document["id"],)).fetchone():
            continue
        pages = json.loads(Path(report["pages_path"]).read_text())["pages"]
        chunks = text_chunks(db, document["id"], pages)
        extracted = extract_document({**document, "first_observed_at_utc": now}, chunks, company_catalog, issuer_entity_id=seed["issuer_id"])
        for entity in extracted["entities"]:
            ingest_entity(db, entity)
        for edge in extracted["edges"]:
            ingest_edge(db, edge)
        db.execute("INSERT INTO report_ingestions VALUES (?,?,?,?,?)", (document["id"], now, VERSION, len(extracted["edges"]), len(extracted["warnings"])))
        write_json(manifest_path.parent / "extraction.json", {key: value for key, value in extracted.items() if key != "edges"})
        db.commit()
        print(f"INDEX {metadata['ticker']}: {len(chunks)} passages, {len(extracted['edges'])} source assertions", flush=True)
    reviewed = json.loads(Path("configs/knowledge_reviewed_claims.json").read_text())
    for claim in reviewed["claims"]:
        pages = db.execute("SELECT p.*,d.id AS doc_id FROM pages p JOIN documents d ON p.document_id=d.id WHERE d.source_url=? ORDER BY p.page_number", (claim["source_url"],)).fetchall()
        pattern = re.compile(r"\s+".join(re.escape(part) for part in claim["quote"].split()))
        found = next(((page, pattern.search(page["text"])) for page in pages if pattern.search(page["text"])), None)
        if found is None:
            raise ValueError(f"Reviewed statement not present in captured source: {claim['source_url']}")
        page, match = found
        subject = listing_by_ticker[claim["subject_ticker"]]["issuer_id"]
        if claim.get("object_ticker"):
            target = listing_by_ticker[claim["object_ticker"]]["issuer_id"]
        else:
            from alphacouncil.data.archive import sha256
            target = f"issuer:source_scoped:{sha256((claim['source_url']+claim['object_source_name']).encode())[:24]}"
            ingest_entity(db, {"id": target, "kind": "company", "name": claim["object_source_name"], "first_observed_at_utc": reviewed["reviewed_at_utc"],
                              "metadata": {"identity_resolution": "source_scoped_name_only", "ticker_not_inferred": True}})
        chunk_id = ingest_chunk(db, {"page_id": page["id"], "start_offset": match.start(), "end_offset": match.end(), "text": match.group()})
        ingest_edge(db, {"subject_id": subject, "predicate": claim["predicate"], "object_id": target, "document_id": page["doc_id"],
                        "chunk_id": chunk_id, "status": "reported", "first_observed_at_utc": reviewed["reviewed_at_utc"], "evidence_quote": match.group(),
                        "metadata": {"extraction_method": "agent_reviewed_exact_publisher_statement", "reviewed_at_utc": reviewed["reviewed_at_utc"],
                                     "independently_verified": False, "current_status_not_reverified": True, "causal_impact_established": False,
                                     "quote_start_offset": match.start(), "quote_end_offset": match.end(), "no_return_prediction": True}})
    db.commit()
    counts = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("entities", "documents", "pages", "chunks", "edges")}
    statuses = {row[0]: row[1] for row in db.execute("SELECT status,count(*) FROM edges GROUP BY status")}
    predicates = {row[0]: row[1] for row in db.execute("SELECT predicate,count(*) FROM edges GROUP BY predicate")}
    report = {"schema_version": 1, "created_at_utc": utc_now().isoformat(), "mode": "EVIDENCE_GRAPH_AND_LEXICAL_RETRIEVAL", "database": str(path),
              "counts": counts, "assertion_status_counts": statuses, "predicate_counts": predicates, "listing_count": len(listings),
              "issuer_enrichment_scope": len(seeds), "reports": report_status, "complete_reports": sum(row["status"] == "complete" for row in report_status),
              "completed_report_pages": sum(row["pages"] for row in report_status if row["status"] == "complete"),
              "usable_full_annual_or_filing_documents": sum(row["status"] == "complete" and row["kind"] != "partnership_announcement" and row["document_scope"] != "landing_or_summary_not_full_report" for row in report_status),
              "usable_announcement_documents": sum(row["status"] == "complete" and row["kind"] == "partnership_announcement" for row in report_status),
              "scope_not_full_report_documents": sum(row["status"] == "complete" and row["document_scope"] == "landing_or_summary_not_full_report" for row in report_status),
              "code_sha256": {str(p): file_sha256(p) for p in [Path(__file__).resolve().relative_to(Path.cwd()), *sorted(Path("src/alphacouncil/knowledge").glob("*.py"))]},
              "config_sha256": {str(p): file_sha256(p) for p in sorted(Path("configs").glob("knowledge_*.json"))},
              "entity_kind_counts": {row[0]: row[1] for row in db.execute("SELECT kind,count(*) FROM entities GROUP BY kind")},
              "complete_report_research_sectors": sorted({row["sector"] for row in report_status if row["status"] == "complete" and row["sector"]}),
              "limitations": ["Current listing directory is not a point-in-time historical universe", "Only a curated subset of companies has report/LEI enrichment",
                              "Name-only identity matches are candidates, not verified legal joins", "GLEIF parent links describe accounting consolidation, not supply chains",
                              "Publication timestamps unknown unless explicitly supplied; receipt timestamps are actual", "No complete supply-chain coverage or financial impact model",
                              "Candidate mentions/commodity exposure are excluded from default graph traversal", "Lexical and graph retrieval implemented; embeddings, community summaries and LLM generation not configured"]}
    db.close()
    report["database_sha256"] = file_sha256(path)
    write_json(Path("data/manifests/knowledge_latest.json"), report)
    write_json(Path("reports/knowledge_inventory.json"), report)
    print(json.dumps({"counts": counts, "statuses": statuses, "complete_reports": report["complete_reports"]}, indent=2))


if __name__ == "__main__":
    main()
