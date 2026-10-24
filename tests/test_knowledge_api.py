import hashlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from alphacouncil.api.app import create_app
from alphacouncil.knowledge.store import connect, ingest_chunk, ingest_document, ingest_edge, ingest_entity, ingest_page


def test_uncollected_knowledge_is_explicit_and_does_not_create_a_database(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/v1/knowledge/stats").json()["status"] == "unavailable"
    assert client.get("/api/v1/knowledge/query?q=test").status_code == 503
    assert not (tmp_path / "data").exists()
    assert client.post("/api/v1/knowledge/query", json={"q":"test"}).status_code == 405


@pytest.fixture
def indexed(tmp_path):
    path = tmp_path / "data/knowledge/graph.sqlite3";path.parent.mkdir(parents=True)
    db = connect(path)
    now = "2026-01-01T00:00:00Z"
    for identifier, kind, name, aliases in [("equity:NASDAQ:TST", "security", "Toy share", ["TST"]), ("issuer:NASDAQ:TST", "company", "Toy Company", [])]:
        ingest_entity(db, {"id":identifier,"kind":kind,"name":name,"aliases":aliases,"first_observed_at_utc":now})
    doc = ingest_document(db,{"source_url":"https://example.test/report","title":"Synthetic test fixture","content_sha256":hashlib.sha256(b"Toy source").hexdigest(),"first_observed_at_utc":now})
    page = ingest_page(db,{"document_id":doc,"page_number":1,"text":"Toy Company issued this test share."})
    chunk = ingest_chunk(db,{"page_id":page,"start_offset":0,"end_offset":34})
    ingest_edge(db,{"subject_id":"equity:NASDAQ:TST","predicate":"ISSUED_BY","object_id":"issuer:NASDAQ:TST","document_id":doc,"chunk_id":chunk,"status":"reference","first_observed_at_utc":now})
    db.commit();db.close()
    return TestClient(create_app(tmp_path))


def test_graph_api_keeps_asset_and_company_distinct_with_exact_sources(indexed):
    response = indexed.get("/api/v1/knowledge/graph/TST")
    assert response.status_code == 200
    data = response.json()
    assert {entity["kind"] for entity in data["entities"]} == {"company", "security"}
    assert data["edges"][0]["citation"]["source_url"] == "https://example.test/report"
    assert data["candidate_edges_included"] is False
    assert indexed.get("/api/v1/knowledge/entities?q=TST").json()["ambiguous"] is False
    assert indexed.get("/api/v1/knowledge/graph/UNKNOWN").status_code == 404


def test_graph_api_honors_asof_bounds_and_literal_fts(indexed):
    data = indexed.get("/api/v1/knowledge/query",params={"q":"Toy", "entity":"equity:NASDAQ:TST", "as_of":"2025-01-01T00:00:00Z"}).json()
    assert data["entities"] == [] and data["passages"] == []
    assert indexed.get("/api/v1/knowledge/query?q=Toy&max_hops=99").status_code == 422
    assert indexed.get("/api/v1/knowledge/query?q=Toy&as_of=2025-01-01").status_code == 422
    assert indexed.get("/api/v1/knowledge/query",params={"q":"Toy OR (DROP TABLE documents)"}).status_code == 200
