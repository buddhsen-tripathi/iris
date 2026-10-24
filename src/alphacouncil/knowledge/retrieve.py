"""Deterministic bounded graph paths and cited FTS5 passages, with receipt-time gates."""

import json
import re

from .store import utc


def _entity_snapshots(db, as_of):
    rows = db.execute("""SELECT s.*,e.kind FROM entity_snapshots s JOIN entities e ON e.id=s.entity_id
        WHERE s.first_observed_at_utc<=? ORDER BY s.entity_id,s.first_observed_at_utc DESC,s.id DESC""",(as_of,)).fetchall()
    result = {}
    for row in rows:
        if row["entity_id"] in result:
            continue
        result[row["entity_id"]] = {"id":row["entity_id"],"kind":row["kind"],"name":row["name"],
            "aliases":json.loads(row["aliases_json"]),"identifiers":json.loads(row["identifiers_json"]),
            "metadata":json.loads(row["metadata_json"]),"snapshot_first_observed_at_utc":row["first_observed_at_utc"]}
    return result


def _normalized(value):
    return " ".join(str(value).casefold().split())


def resolve_entities(db, query, as_of_utc):
    """Exact IDs/names/aliases/identifiers only. Ambiguity is never fuzzy-resolved."""
    if not isinstance(query,str) or not query.strip() or len(query)>1000:
        raise ValueError("A nonempty entity query up to 1000 characters is required")
    entities = _entity_snapshots(db,utc(as_of_utc))
    term = _normalized(query)
    exact_ids = [entity for entity in entities.values() if _normalized(entity["id"]) == term]
    matches = exact_ids
    if not exact_ids:
        matches = []
        for entity in entities.values():
            identifiers = [value for value in entity["identifiers"].values() if isinstance(value,(str,int))]
            tokens = [entity["name"],*entity["aliases"],*identifiers]
            if any(_normalized(token)==term for token in tokens):
                matches.append(entity)
    matches = sorted(matches,key=lambda row:row["id"])
    return {"query":query,"matches":matches,"ambiguous":len(matches)>1,"resolution_method":"exact_id_name_alias_or_identifier"}


def _limits(max_hops,max_entities,max_edges,max_passages):
    for value,minimum,maximum in ((max_hops,0,4),(max_entities,1,100),(max_edges,1,200),(max_passages,0,30)):
        if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=maximum:
            raise ValueError("Traversal/retrieval limits exceed the bounded research API")


def _edge_evidence(db, row):
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json"))
    result["citation"] = {"document_id":row["document_id"],"source_url":row["source_url"],"title":row["title"],
        "source_name":row["source_name"],"content_sha256":row["content_sha256"],"published_at_utc":row["document_published_at_utc"],
        "first_observed_at_utc":row["document_first_observed_at_utc"]}
    if row["chunk_id"]:
        chunk = db.execute("""SELECT c.*,p.page_number FROM chunks c JOIN pages p ON p.id=c.page_id WHERE c.id=?""",(row["chunk_id"],)).fetchone()
        result["citation"].update(chunk_id=chunk["id"],page_id=chunk["page_id"],page_number=chunk["page_number"],
            start_offset=chunk["start_offset"],end_offset=chunk["end_offset"],text=chunk["text"])
    return result


def graph_paths(db, seed_id, as_of_utc, *, max_hops=2,max_entities=30,max_edges=60,include_candidates=False):
    """Breadth-first traversal in both directions; semantic edge direction retained."""
    _limits(max_hops,max_entities,max_edges,0)
    as_of = utc(as_of_utc)
    known = _entity_snapshots(db,as_of)
    if seed_id not in known:
        return {"entities":[],"edges":[],"paths":[],"truncated":False}
    selected, edges, paths = {seed_id:known[seed_id]}, {}, []
    visited, frontier, truncated = {seed_id},[(seed_id,[],[seed_id])],False
    statuses = ("reference","reported","candidate") if include_candidates else ("reference","reported")
    marks = ",".join("?" for _ in statuses)
    for _ in range(max_hops):
        next_frontier = []
        for current,path_ids,node_ids in frontier:
            rows = db.execute(f"""SELECT e.*,d.source_url,d.title,d.source_name,d.content_sha256,
                d.first_observed_at_utc AS document_first_observed_at_utc,d.published_at_utc AS document_published_at_utc
                FROM edges e JOIN documents d ON d.id=e.document_id
                WHERE (e.subject_id=? OR e.object_id=?) AND e.status IN ({marks})
                AND e.first_observed_at_utc<=? AND d.first_observed_at_utc<=?
                AND (e.published_at_utc IS NULL OR e.published_at_utc<=?)
                AND (d.published_at_utc IS NULL OR d.published_at_utc<=?)
                AND (e.valid_from_utc IS NULL OR e.valid_from_utc<=?)
                AND (e.valid_to_utc IS NULL OR e.valid_to_utc>?) ORDER BY e.id LIMIT ?""",
                (current,current,*statuses,as_of,as_of,as_of,as_of,as_of,as_of,max_edges+1)).fetchall()
            if len(rows)>max_edges:
                truncated=True
            for row in rows:
                other = row["object_id"] if row["subject_id"]==current else row["subject_id"]
                if other not in known or other in node_ids:
                    continue
                if row["id"] not in edges and len(edges)>=max_edges:
                    truncated=True
                    continue
                if other not in selected and len(selected)>=max_entities:
                    truncated=True
                    continue
                if len(paths)>=max_edges:
                    truncated=True
                    continue
                selected[other]=known[other]
                edges[row["id"]]=_edge_evidence(db,row)
                new_path,new_nodes = path_ids+[row["id"]],node_ids+[other]
                paths.append({"entity_ids":new_nodes,"edge_ids":new_path,"hops":len(new_path)})
                if other not in visited:
                    visited.add(other)
                    next_frontier.append((other,new_path,new_nodes))
        frontier=next_frontier
        if not frontier:
            break
    return {"entities":[selected[key] for key in sorted(selected)],"edges":[edges[key] for key in sorted(edges)],
            "paths":paths,"truncated":truncated}


def lexical_passages(db, query, as_of_utc, *, limit=10):
    _limits(0,1,1,limit)
    if not isinstance(query,str) or len(query)>1000:
        raise ValueError("Lexical query must be text up to 1000 characters")
    tokens = list(dict.fromkeys(re.findall(r"\w+",query,flags=re.UNICODE)))[:24]
    if not tokens or limit==0:
        return []
    # Never pass arbitrary FTS operators from the caller; tokenize and quote literals.
    expression = " OR ".join('"'+token.replace('"','""')+'"' for token in tokens)
    as_of=utc(as_of_utc)
    score_sql=" + ".join("CASE WHEN instr(lower(c.text),?)>0 THEN 1 ELSE 0 END" for _ in tokens)
    rows=db.execute(f"""SELECT c.id AS chunk_id,c.page_id,c.start_offset,c.end_offset,c.text,p.page_number,
        d.id AS document_id,d.source_url,d.title,d.source_name,d.content_sha256,d.first_observed_at_utc,d.published_at_utc,
        ({score_sql}) AS lexical_match_count FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.chunk_id
        JOIN pages p ON p.id=c.page_id JOIN documents d ON d.id=p.document_id
        WHERE chunks_fts MATCH ? AND d.first_observed_at_utc<=? AND (d.published_at_utc IS NULL OR d.published_at_utc<=?)
        ORDER BY lexical_match_count DESC,c.id LIMIT ?""",(*[token.lower() for token in tokens],expression,as_of,as_of,limit)).fetchall()
    # Rank by passage-local query-term coverage, then stable chunk ID. Whole-corpus
    # BM25 IDF includes future snapshots and would change historical as-of ranks.
    return [dict(row) for row in rows]


def retrieve_context(db, query, as_of_utc, *, entity_id=None,max_hops=2,max_entities=30,max_edges=60,max_passages=10,include_candidates=False):
    _limits(max_hops,max_entities,max_edges,max_passages)
    resolution=resolve_entities(db,entity_id or query,as_of_utc)
    graph={"entities":[],"edges":[],"paths":[],"truncated":False}
    if len(resolution["matches"])==1:
        graph=graph_paths(db,resolution["matches"][0]["id"],as_of_utc,max_hops=max_hops,max_entities=max_entities,max_edges=max_edges,include_candidates=include_candidates)
    return {"schema_version":1,"mode":"EVIDENCE_GRAPH_AND_LEXICAL_RETRIEVAL","query":query,"as_of_utc":utc(as_of_utc),
        "resolution":resolution,**graph,"passages":lexical_passages(db,query,as_of_utc,limit=max_passages),
        "candidate_edges_included":bool(include_candidates),
        "note":"Source-backed retrieval context only. Ambiguous identities require explicit entity IDs. Reported statements retain source provenance; candidate relationships are hypotheses. This is not an LLM answer, validated causal-impact model or stock-return prediction."}
