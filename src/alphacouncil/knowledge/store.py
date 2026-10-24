"""Evidence-centric append-only SQLite graph and exact-source passage storage.

All mutations are local. The caller owns commit boundaries. This is a retrieval
foundation, not an LLM or a stock-return predictor.
"""

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {"reference", "reported", "candidate"}


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timezone-aware UTC observation timestamps are required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def serialized(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def stable_id(prefix, value):
    return prefix+":"+hashlib.sha256(serialized(value).encode()).hexdigest()


def connect(path):
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
      PRAGMA foreign_keys=ON;
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,kind TEXT NOT NULL,first_observed_at_utc TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS entity_snapshots(id TEXT PRIMARY KEY,entity_id TEXT NOT NULL REFERENCES entities(id),
        name TEXT NOT NULL,aliases_json TEXT NOT NULL,identifiers_json TEXT NOT NULL,metadata_json TEXT NOT NULL,first_observed_at_utc TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS entity_observed ON entity_snapshots(entity_id,first_observed_at_utc);
      CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,source_url TEXT NOT NULL,title TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,source_name TEXT NOT NULL,first_observed_at_utc TEXT NOT NULL,published_at_utc TEXT,metadata_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS pages(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),page_number INTEGER NOT NULL,
        text TEXT NOT NULL,text_sha256 TEXT NOT NULL,UNIQUE(document_id,page_number));
      CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,page_id TEXT NOT NULL REFERENCES pages(id),start_offset INTEGER NOT NULL,
        end_offset INTEGER NOT NULL,text TEXT NOT NULL,UNIQUE(page_id,start_offset,end_offset));
      CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED,text,tokenize='unicode61');
      CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY,subject_id TEXT NOT NULL REFERENCES entities(id),predicate TEXT NOT NULL,
        object_id TEXT NOT NULL REFERENCES entities(id),document_id TEXT NOT NULL REFERENCES documents(id),chunk_id TEXT REFERENCES chunks(id),
        status TEXT NOT NULL CHECK(status IN ('reference','reported','candidate')),first_observed_at_utc TEXT NOT NULL,
        published_at_utc TEXT,valid_from_utc TEXT,valid_to_utc TEXT,evidence_quote TEXT,metadata_json TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS edge_subject ON edges(subject_id,first_observed_at_utc);
      CREATE INDEX IF NOT EXISTS edge_object ON edges(object_id,first_observed_at_utc);
    """)
    return db


def _insert_immutable(db, table, record):
    existing = db.execute(f"SELECT * FROM {table} WHERE id=?", (record["id"],)).fetchone()
    if existing:
        # Repeated source receipts never rewrite the first observation timestamp.
        if any(existing[key] != value for key, value in record.items() if key != "first_observed_at_utc"):
            raise ValueError(f"Immutable {table} snapshot was revised: {record['id']}")
        return False
    fields = tuple(record)
    db.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", tuple(record.values()))
    return True


def ingest_entity(db, record):
    entity_id = str(record.get("id", record.get("entity_id", ""))).strip()
    kind = str(record.get("kind", record.get("type", ""))).strip()
    name = str(record["name"]).strip()
    if not entity_id or not re.fullmatch(r"[a-z][a-z_]*", kind) or not name:
        raise ValueError("Stable entity ID, explicit entity kind and name required")
    for prefix, expected in (("equity:", "security"), ("issuer:", "company"), ("lei:", "legal_entity")):
        if entity_id.startswith(prefix) and kind != expected:
            raise ValueError(f"{prefix} IDs must retain kind {expected}")
    observed = utc(record["first_observed_at_utc"])
    previous = db.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
    if previous and previous["kind"] != kind:
        raise ValueError("A company, security and legal entity cannot share an identity")
    db.execute("INSERT OR IGNORE INTO entities VALUES (?,?,?)", (entity_id, kind, observed))
    aliases = sorted(set(str(alias).strip() for alias in record.get("aliases", []) if str(alias).strip()))
    snapshot = {"entity_id":entity_id,"name":name,"aliases_json":serialized(aliases),
        "identifiers_json":serialized(record.get("identifiers", {})),"metadata_json":serialized(record.get("metadata", {}))}
    snapshot = {"id":stable_id("entity_snapshot", snapshot), **snapshot,"first_observed_at_utc":observed}
    _insert_immutable(db, "entity_snapshots", snapshot)
    return entity_id


def ingest_document(db, record):
    digest = record["content_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Exact source snapshot SHA-256 required")
    url = str(record["source_url"])
    if not url.startswith(("https://", "http://")):
        raise ValueError("A source HTTP(S) URL is required")
    identity = {"source_url":url,"content_sha256":digest}
    doc = {"id":record.get("id") or stable_id("document", identity),"source_url":url,
        "title":str(record.get("title", "")),"content_sha256":digest,"source_name":str(record.get("source_name", "")),
        "first_observed_at_utc":utc(record["first_observed_at_utc"]),
        "published_at_utc":utc(record["published_at_utc"]) if record.get("published_at_utc") else None,
        "metadata_json":serialized(record.get("metadata", {}))}
    _insert_immutable(db, "documents", doc)
    return doc["id"]


def ingest_page(db, record):
    document_id, number, text = record["document_id"], record["page_number"], str(record["text"])
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("Page numbers start at one")
    page = {"id":record.get("id") or stable_id("page",[document_id,number]),"document_id":document_id,
        "page_number":number,"text":text,"text_sha256":hashlib.sha256(text.encode()).hexdigest()}
    _insert_immutable(db, "pages", page)
    return page["id"]


def ingest_chunk(db, record):
    page = db.execute("SELECT * FROM pages WHERE id=?", (record["page_id"],)).fetchone()
    if page is None:
        raise ValueError("Chunk page does not exist")
    start, end = record["start_offset"], record["end_offset"]
    if any(isinstance(value,bool) or not isinstance(value,int) for value in (start,end)) or not 0 <= start < end <= len(page["text"]):
        raise ValueError("Exact half-open character offsets within the page are required")
    text = page["text"][start:end]
    if "text" in record and record["text"] != text:
        raise ValueError("Chunk text does not match the exact page slice")
    chunk = {"id":record.get("id") or stable_id("chunk",[page["id"],start,end]),"page_id":page["id"],
             "start_offset":start,"end_offset":end,"text":text}
    if _insert_immutable(db, "chunks", chunk):
        db.execute("INSERT INTO chunks_fts(chunk_id,text) VALUES (?,?)", (chunk["id"],text))
    return chunk["id"]


def ingest_chunks(db, records):
    return [ingest_chunk(db, record) for record in records]


def ingest_edge(db, record):
    status = record.get("status", "candidate")
    if status not in STATUSES:
        raise ValueError("Explicit reference/reported/candidate assertion status required")
    document = db.execute("SELECT * FROM documents WHERE id=?", (record["document_id"],)).fetchone()
    if document is None:
        raise ValueError("Every assertion needs an existing source document")
    observed = utc(record["first_observed_at_utc"])
    if observed < document["first_observed_at_utc"]:
        raise ValueError("Assertion observation cannot predate the source receipt")
    chunk_id, quote = record.get("chunk_id"), record.get("evidence_quote")
    if chunk_id:
        chunk = db.execute("SELECT c.*,p.document_id FROM chunks c JOIN pages p ON p.id=c.page_id WHERE c.id=?",(chunk_id,)).fetchone()
        if chunk is None or chunk["document_id"] != document["id"]:
            raise ValueError("Evidence chunk must belong to the cited document")
        if quote and quote not in chunk["text"]:
            raise ValueError("Evidence quote must occur exactly in the cited passage")
    elif quote:
        if not db.execute("SELECT 1 FROM pages WHERE document_id=? AND instr(text,?)>0 LIMIT 1",(document["id"],quote)).fetchone():
            raise ValueError("Evidence quote must occur exactly in the source document")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(record["predicate"])):
        raise ValueError("An explicit uppercase relation predicate is required")
    edge = {"subject_id":record["subject_id"],"predicate":record["predicate"],"object_id":record["object_id"],
        "document_id":document["id"],"chunk_id":chunk_id,"status":status,
        "published_at_utc":utc(record["published_at_utc"]) if record.get("published_at_utc") else document["published_at_utc"],
        "valid_from_utc":utc(record["valid_from_utc"]) if record.get("valid_from_utc") else None,
        "valid_to_utc":utc(record["valid_to_utc"]) if record.get("valid_to_utc") else None,
        "evidence_quote":quote,"metadata_json":serialized(record.get("metadata", {}))}
    if edge["valid_from_utc"] and edge["valid_to_utc"] and edge["valid_to_utc"] <= edge["valid_from_utc"]:
        raise ValueError("Validity end must follow validity start")
    payload = {"id":record.get("id") or stable_id("edge",edge),**edge,"first_observed_at_utc":observed}
    _insert_immutable(db,"edges",payload)
    return payload["id"]
