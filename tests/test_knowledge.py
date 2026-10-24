import hashlib
import json
import sqlite3

import pytest

from alphacouncil.knowledge.store import connect,ingest_entity,ingest_document,ingest_page,ingest_chunk,ingest_edge
from alphacouncil.knowledge.retrieve import resolve_entities,retrieve_context,graph_paths,lexical_passages

T="2026-10-24T12:00:00Z"
PAST="2026-10-23T12:00:00Z"
FUTURE="2026-10-25T12:00:00Z"


def entity(db,identity,name=None,kind="company",observed=PAST,aliases=None):
    return ingest_entity(db,{"id":identity,"kind":kind,"name":name or identity,"aliases":aliases or [],"first_observed_at_utc":observed})


def document(db,text="Acme supplies Orion. Semiconductor chips.",observed=PAST,url="https://example.org/filing",published=PAST):
    document_id=ingest_document(db,{"source_url":url,"title":"Source filing","content_sha256":hashlib.sha256(text.encode()).hexdigest(),"first_observed_at_utc":observed,"published_at_utc":published})
    page_id=ingest_page(db,{"document_id":document_id,"page_number":1,"text":text})
    chunk_id=ingest_chunk(db,{"page_id":page_id,"start_offset":0,"end_offset":len(text)})
    return document_id,page_id,chunk_id


def edge(db,subject,target,doc,chunk,status="reported",observed=PAST,**extras):
    return ingest_edge(db,{"subject_id":subject,"predicate":"SUPPLIES_TO","object_id":target,"document_id":doc,"chunk_id":chunk,"status":status,"first_observed_at_utc":observed,**extras})


def basic():
    db=connect(":memory:")
    entity(db,"issuer:ACME","Acme")
    entity(db,"issuer:ORION","Orion")
    doc,page,chunk=document(db)
    edge(db,"issuer:ACME","issuer:ORION",doc,chunk,evidence_quote="Acme supplies Orion.")
    return db,doc,page,chunk


def test_company_security_and_legal_entity_never_fuzzy_merged():
    db=connect(":memory:")
    entity(db,"issuer:ACME","Acme Incorporated")
    entity(db,"equity:NASDAQ:ACME","Acme Common Stock","security",aliases=["ACME"])
    entity(db,"equity:NYSE:ACME","Other Common Stock","security",aliases=["ACME"])
    entity(db,"lei:1234","Acme Incorporated","legal_entity")
    assert resolve_entities(db,"ACME",T)["ambiguous"]
    assert len(resolve_entities(db,"Acme Incorporated",T)["matches"])==2
    assert resolve_entities(db,"Acme Inc",T)["matches"]==[]
    assert resolve_entities(db,"equity:NASDAQ:ACME",T)["matches"][0]["kind"]=="security"
    assert retrieve_context(db,"ACME",T)["paths"]==[]
    with pytest.raises(ValueError,match="retain kind"):
        entity(db,"equity:NASDAQ:ACME","Acme Incorporated","company")


def test_future_observations_and_entity_renames_are_invisible():
    db,doc,page,chunk=basic()
    before=retrieve_context(db,"Acme",T)
    entity(db,"issuer:FUTURE","FutureCo",observed=FUTURE)
    future_doc,_,future_chunk=document(db,"Future secrets chips Orion.",FUTURE,"https://example.org/future",FUTURE)
    edge(db,"issuer:ACME","issuer:FUTURE",future_doc,future_chunk,observed=FUTURE)
    ingest_entity(db,{"id":"issuer:ACME","kind":"company","name":"Acme Tomorrow","aliases":["SECRET"],"first_observed_at_utc":FUTURE})
    assert retrieve_context(db,"Acme",T)==before
    assert resolve_entities(db,"SECRET",T)["matches"]==[]
    assert lexical_passages(db,"secrets",T)==[]
    assert len(graph_paths(db,"issuer:ACME",FUTURE)["edges"])==2


def test_candidates_are_excluded_by_default_and_dates_are_enforced():
    db,doc,page,chunk=basic()
    entity(db,"issuer:CANDIDATE")
    edge(db,"issuer:ACME","issuer:CANDIDATE",doc,chunk,"candidate")
    entity(db,"issuer:EXPIRED")
    edge(db,"issuer:ACME","issuer:EXPIRED",doc,chunk,valid_to_utc=T)
    entity(db,"issuer:NOTYET")
    edge(db,"issuer:ACME","issuer:NOTYET",doc,chunk,valid_from_utc=FUTURE)
    normal=graph_paths(db,"issuer:ACME",T)
    assert len(normal["edges"])==1
    research=graph_paths(db,"issuer:ACME",T,include_candidates=True)
    assert {row["status"] for row in research["edges"]}=={"reported","candidate"}


def test_exact_passage_offsets_provenance_and_immutable_dedup():
    db,doc,page,chunk=basic()
    original_counts={name:db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("documents","pages","chunks","edges","chunks_fts")}
    assert document(db)[0]==doc
    original=edge(db,"issuer:ACME","issuer:ORION",doc,chunk,evidence_quote="Acme supplies Orion.")
    again=edge(db,"issuer:ACME","issuer:ORION",doc,chunk,evidence_quote="Acme supplies Orion.",observed=T)
    assert original==again
    assert {name:db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in original_counts}==original_counts
    citation=graph_paths(db,"issuer:ACME",T)["edges"][0]["citation"]
    assert citation["page_number"]==1 and citation["start_offset"]==0
    assert citation["text"]==db.execute("SELECT text FROM pages WHERE id=?",(page,)).fetchone()[0][citation["start_offset"]:citation["end_offset"]]
    assert citation["source_url"]=="https://example.org/filing"
    with pytest.raises(ValueError,match="page slice"):
        ingest_chunk(db,{"page_id":page,"start_offset":0,"end_offset":3,"text":"lie"})
    with pytest.raises(ValueError,match="exactly"):
        edge(db,"issuer:ACME","issuer:ORION",doc,chunk,evidence_quote="Orion supplies Acme.")
    with pytest.raises(ValueError,match="revised"):
        ingest_page(db,{"document_id":doc,"page_number":1,"text":"changed"})


def test_query_injection_and_fts_operators_are_literals():
    db,_,_,_=basic()
    for query in ("' OR 1=1; DROP TABLE entities;--",'chips\" OR NEAR(Orion,100)',"* - : ()", "issuer:ACME') UNION SELECT 1--"):
        result=retrieve_context(db,query,T)
        assert isinstance(result["passages"],list)
    assert db.execute("SELECT count(*) FROM entities").fetchone()[0]==2
    with pytest.raises(ValueError):
        retrieve_context(db,"Acme",T,max_hops=100)


def test_bounded_traversal_is_deterministic_retains_direction_and_separates_hypotheses():
    db,doc,page,chunk=basic()
    for index in range(20):
        target=f"issuer:N{index:02}"
        entity(db,target)
        edge(db,"issuer:ORION",target,doc,chunk,status="reference")
    first=retrieve_context(db,"issuer:ACME",T,max_hops=2,max_entities=4,max_edges=3)
    assert first==retrieve_context(db,"issuer:ACME",T,max_hops=2,max_entities=4,max_edges=3)
    assert len(first["entities"])<=4 and len(first["edges"])<=3 and len(first["paths"])<=3
    assert first["truncated"]
    assert max(path["hops"] for path in first["paths"])<=2
    upstream=graph_paths(db,"issuer:ORION",T,max_hops=1)
    assert any(row["subject_id"]=="issuer:ACME" and row["object_id"]=="issuer:ORION" for row in upstream["edges"])


def test_future_publication_is_not_visible_even_when_received():
    db=connect(":memory:")
    doc,_,chunk=document(db,published=FUTURE)
    assert lexical_passages(db,"chips",T)==[]
    assert len(lexical_passages(db,"chips",FUTURE))==1


def test_passage_local_relevance_avoids_future_corpus_statistics():
    db=connect(":memory:")
    first,_,_=document(db,"Semiconductor chips supplied by Orion.",url="https://example.org/relevant")
    document(db,"Orion sells unrelated products.",url="https://example.org/partial")
    baseline=lexical_passages(db,"Orion semiconductor",T)
    assert baseline[0]["document_id"]==first
    assert baseline[0]["lexical_match_count"]==2
    for index in range(3):
        document(db,"Orion semiconductor future disclosure "+str(index),FUTURE,f"https://example.org/future{index}",FUTURE)
    assert lexical_passages(db,"Orion semiconductor",T)==baseline


def test_extractor_edges_ingest_with_exact_provenance():
    from alphacouncil.knowledge.extract import extract_document
    db=connect(":memory:")
    catalog=[{"id":"issuer:TEST","kind":"company","name":"Issuer Test"},{"id":"issuer:ACME","kind":"company","name":"Acme Components"}]
    for item in catalog:
        ingest_entity(db,{**item,"first_observed_at_utc":PAST})
    text="Our suppliers include Acme Components. Copper demand increased."
    doc,page,chunk=document(db,text)
    document_record={"id":doc,"source_url":"https://example.org/filing","first_observed_at_utc":PAST,"published_at_utc":PAST,
        "metadata":{"document_type":"issuer_report","issuer_entity_id":"issuer:TEST"}}
    result=extract_document(document_record,[{"id":chunk,"page_id":page,"page_number":1,"text":text,"start_offset":0,"end_offset":len(text),"page_text":text}],catalog)
    for item in result["entities"]:
        ingest_entity(db,item)
    for item in result["edges"]:
        ingest_edge(db,item)
    factual=graph_paths(db,"issuer:TEST",T)
    assert len(factual["edges"])==1
    relation=factual["edges"][0]
    assert relation["status"]=="reported" and relation["subject_id"]=="issuer:ACME"
    assert relation["citation"]["text"]==text
    assert relation["evidence_quote"] in text
    assert relation["metadata"]["causal_impact_established"] is False
