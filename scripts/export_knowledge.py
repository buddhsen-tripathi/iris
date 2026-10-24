#!/usr/bin/env python3
"""Export typed nodes, source-backed assertions and documents for graph clients."""

import json
import sqlite3
from pathlib import Path

from alphacouncil.data.archive import file_sha256, utc_now, write_json


def main():
    root = Path("data/knowledge")
    destination = root / "exports"
    destination.mkdir(exist_ok=True)
    db = sqlite3.connect((root/"graph.sqlite3").resolve().as_uri()+"?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    queries = {
        "nodes": """SELECT e.id,e.kind,s.name,s.aliases_json,s.identifiers_json,s.metadata_json,e.first_observed_at_utc
          FROM entities e JOIN entity_snapshots s ON s.id=(SELECT id FROM entity_snapshots WHERE entity_id=e.id ORDER BY first_observed_at_utc DESC,id DESC LIMIT 1) ORDER BY e.id""",
        "edges": """SELECT e.*,d.source_url,d.title,d.source_name,d.content_sha256 FROM edges e JOIN documents d ON d.id=e.document_id ORDER BY e.id""",
        "documents": "SELECT * FROM documents ORDER BY id",
    }
    counts, files = {}, {}
    for name, query in queries.items():
        path = destination / f"{name}.jsonl"
        counts[name] = 0
        with path.open("w") as output:
            for row in db.execute(query):
                item = dict(row)
                for key in tuple(item):
                    if key.endswith("_json"):
                        item[key[:-5]] = json.loads(item.pop(key))
                output.write(json.dumps(item, ensure_ascii=False, allow_nan=False)+"\n")
                counts[name] += 1
        files[str(path)] = file_sha256(path)
    db.close()
    manifest = {"created_at_utc": utc_now().isoformat(), "mode": "TYPED_EVIDENCE_GRAPH_EXPORT", "counts": counts, "files": files,
                "note": "Assertion status is mandatory: references, issuer-reported claims, and review-needed candidates must remain distinct. No edge weight is an expected stock return."}
    write_json(destination / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
