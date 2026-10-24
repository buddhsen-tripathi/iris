"""Read-only graph data for a future asset relationship view."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from alphacouncil.knowledge.retrieve import resolve_entities, retrieve_context


def knowledge_router(root: Path):
    root = root.resolve()
    router = APIRouter(prefix="/api/v1/knowledge", tags=["Evidence graph"])

    @contextmanager
    def database():
        path = root / "data/knowledge/graph.sqlite3"
        if not path.is_file():
            raise HTTPException(503, "Knowledge data has not been collected/indexed")
        if not path.resolve().is_relative_to(root):
            raise HTTPException(503, "Knowledge database must be inside the workspace")
        db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            yield db
        except sqlite3.Error:
            raise HTTPException(503, "Knowledge index is temporarily unavailable")
        finally:
            db.close()

    @router.get("/stats")
    def stats():
        path = root / "data/manifests/knowledge_latest.json"
        if not path.is_file():
            return {"status": "unavailable", "mode": "EVIDENCE_GRAPH_AND_LEXICAL_RETRIEVAL"}
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            raise HTTPException(503, "Knowledge inventory is temporarily unavailable")

    @router.get("/entities")
    def entities(q: str = Query(min_length=1, max_length=1000), as_of: str | None = None):
        try:
            with database() as db:
                return resolve_entities(db, q, as_of or datetime.now(timezone.utc))
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.get("/query")
    def query(q: str = Query(min_length=1, max_length=1000), entity: str | None = Query(None, max_length=300),
              as_of: str | None = None, max_hops: int = Query(2, ge=0, le=4), max_passages: int = Query(5, ge=0, le=15), include_candidates: bool = False):
        try:
            with database() as db:
                return retrieve_context(db, q, as_of or datetime.now(timezone.utc), entity_id=entity, max_hops=max_hops,
                                        max_passages=max_passages, include_candidates=include_candidates)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.get("/graph/{ticker}")
    def graph(ticker: str, max_hops: int = Query(3, ge=0, le=4), include_candidates: bool = False):
        if len(ticker) > 20:
            raise HTTPException(422, "Ticker is too long")
        with database() as db:
            result = retrieve_context(db, ticker, datetime.now(timezone.utc), max_hops=max_hops, max_passages=0, include_candidates=include_candidates)
        if not result["resolution"]["matches"]:
            raise HTTPException(404, "No exact entity/ticker match")
        return result

    return router
