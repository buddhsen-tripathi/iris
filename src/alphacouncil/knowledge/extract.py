"""Deterministic lexical evidence extraction; text is data, never instructions.

This is a retrieval/GraphRAG foundation, not semantic LLM inference. Every relation
retains exact source offsets. Co-occurrence alone never establishes a supplier.
"""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_ONTOLOGY = Path(__file__).resolve().parents[3] / "configs" / "knowledge_ontology.json"
VERSION = "deterministic-evidence-v1"
COMPANY_KINDS = {"COMPANY", "ISSUER"}
STOP_REPORTED = re.compile(r"\b(?:not|never|no|neither|nor|without|except|formerly|previously|ceased|terminated|may|might|could|would|will|plans?|expects?|intends?|potential|prospective|proposed|if|should|consider(?:ing)?|seeks?|negotiat\w*)\b", re.I)
ROLE = re.compile(
    r"\bour\s+(?:(?:key|major|principal|significant|largest|primary|current)\s+)?(?P<role>suppliers?|customers?)\s+(?:include(?:s)?|are|is|such\s+as|:)\s*"
    r"|\bwe\s+(?P<buy>purchase|buy|source|procure)\s+(?:[^.;:!?]{0,65}?\s+)?from\s+"
    r"|\bwe\s+(?P<sell>sell|supply|provide)\s+(?:[^.;:!?]{0,65}?\s+)?to\s+", re.I)
CLAUSE_END = re.compile(r"[.;!?]|\n\s*\n|\b(?:while|whereas|but|although|however|because|which|that|who)\b|\band\s+(?:we|our|they|their|it)\b", re.I)
LIST_CONNECTOR = re.compile(r"^[\s,:()\[\]&-]*(?:(?:and|or|the|including|such\s+as|primarily|companies|company|vendors|manufacturers)\b[\s,:()\[\]&-]*)*$", re.I)
NEW_PREDICATE = re.compile(r"^\s+(?:is|are|was|were|has|have|sells?|supplies|purchases?|buys?|provides?|announced|reported|discusses|competes?|develops?|acquired|expects?)\b", re.I)
IMPACT = re.compile(r"\b(?:benefit\w*|hurt\w*|harm\w*|impact\w*|boost\w*|increase\w*|decrease\w*|growth|grow\w*|declin\w*|rises?|rising|falls?|falling|higher|lower|bullish|bearish)\b", re.I)


def _id(prefix, payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return prefix + hashlib.sha256(body.encode()).hexdigest()


def load_ontology(path=None):
    ontology = json.loads(Path(path or DEFAULT_ONTOLOGY).read_text())
    ids = [item["id"] for item in ontology["taxonomy"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate ontology entity ID")
    return ontology


def _entity(entity):
    entity = dict(entity)
    identifier = entity.get("id", entity.get("entity_id"))
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("Catalog entity requires id")
    entity["id"] = identifier
    entity["kind"] = entity.get("kind", "COMPANY").upper()
    if not isinstance(entity.get("name"), str) or not entity["name"]:
        raise ValueError("Catalog entity requires name")
    return entity


def _alias_key(alias):
    return " ".join(alias.split()).casefold()


@lru_cache(maxsize=8)
def _alias_index(records):
    aliases = {}
    details = {}
    for alias, entity_id in records:
        key = _alias_key(alias)
        aliases.setdefault(key, set()).add(entity_id)
        details.setdefault(key, alias)
    options = [r"\s+".join(re.escape(part) for part in details[key].split())
               for key in sorted(details, key=lambda key:(-len(key),key))]
    pattern = re.compile(r"(?<!\w)(?:"+"|".join(options)+r")(?!\w)", re.I) if options else None
    return aliases, details, pattern


def _matches(text, entities, *, ticker_guard=True):
    records = []
    for entity in entities:
        for alias in [entity["name"], *entity.get("aliases", [])]:
            if isinstance(alias, dict):
                alias = alias.get("text", alias.get("alias", ""))
            if not isinstance(alias, str) or not alias.strip():
                continue
            records.append((alias.strip(),entity["id"]))
    aliases, details, pattern = _alias_index(tuple(records))
    result, ambiguous = [], []
    if pattern is None:
        return result, ambiguous
    for match in pattern.finditer(text):
        key = _alias_key(match.group())
        if key not in aliases:  # Unicode case-insensitive regex can be broader than casefold.
            continue
        entity_ids = aliases[key]
        alias = details[key]
        # Uppercase short company aliases are usually tickers, not ordinary words.
        guarded = ticker_guard and len(alias) <= 3 and alias.isalpha()
        if guarded:
            prefix = text[max(0, match.start()-25):match.start()]
            explicit_ticker = re.search(r"(?:\$|(?:NYSE|NASDAQ|AMEX|ticker)\s*[:=]?\s*)$", prefix, re.I)
            if not explicit_ticker or match.group() != alias.upper():
                continue
        if len(entity_ids) != 1:
            ambiguous.append({"alias":match.group(), "start":match.start(), "end":match.end(), "entity_ids":sorted(entity_ids)})
            continue
        result.append({"entity_id":next(iter(entity_ids)), "start":match.start(), "end":match.end(), "text":match.group()})
    # Prefer longest alias at overlaps; same span for competing identities stays ambiguous.
    selected = []
    for item in sorted(result, key=lambda row:(-(row["end"]-row["start"]), row["start"], row["entity_id"])):
        if any(item["start"] < other["end"] and other["start"] < item["end"] for other in selected):
            continue
        selected.append(item)
    return sorted(selected, key=lambda row:row["start"]), ambiguous


def _sentences(text):
    for match in re.finditer(r"[^.!?;]+(?:[.!?;]|$)", text):
        if match.group().strip():
            yield match.start(), match.end(), match.group()


def _domains(text, ontology):
    domains = []
    for name, terms in ontology["metric_domains"].items():
        if any(re.search(r"(?<!\w)"+re.escape(term)+r"(?!\w)", text, re.I) for term in terms):
            domains.append(name)
    return domains


def extract_document(document, chunks, entity_catalog, issuer_entity_id=None, ontology_path=None):
    """Extract source-backed edge dictionaries compatible with knowledge.store.

    Chunks retain exact input text and page start_offset. Required document fields:
    id, source_url, first_observed_at_utc. An issuer report may name its issuer in
    the argument or metadata. News never upgrades lexical relationships to reported.
    """
    for field in ("id", "source_url", "first_observed_at_utc"):
        if not document.get(field):
            raise ValueError(f"Document {field} required")
    ontology = load_ontology(ontology_path)
    catalog = [_entity(item) for item in entity_catalog]
    if len({item["id"] for item in catalog}) != len(catalog):
        raise ValueError("Duplicate catalog entity ID")
    by_id = {item["id"]:item for item in catalog}
    metadata = document.get("metadata", {})
    issuer = issuer_entity_id or metadata.get("issuer_entity_id") or document.get("issuer_entity_id")
    source_kind = str(metadata.get("document_type", metadata.get("source_kind", document.get("document_type", "issuer_report")))).lower()
    is_news = "news" in source_kind or "article" in source_kind
    issuer_report = not is_news and issuer is not None
    edges, spans, warnings, claims, used_taxonomy = [], {}, [], [], {}

    def evidence(chunk, start, end):
        exact = chunk["text"][start:end]
        base = chunk.get("start_offset", 0)
        payload = {"document_id":document["id"], "chunk_id":chunk.get("id", chunk.get("chunk_id")),
                   "page_id":chunk.get("page_id"), "page_number":chunk.get("page_number"),
                   "start_offset":base+start, "end_offset":base+end, "chunk_start_offset":start,
                   "chunk_end_offset":end, "text":exact, "source_url":document["source_url"],
                   "first_observed_at_utc":document["first_observed_at_utc"],
                   "published_at_utc":document.get("published_at_utc"),
                   "content_sha256":document.get("content_sha256")}
        identifier = _id("span:", payload)
        payload["id"] = identifier
        spans[identifier] = payload
        return payload

    def edge(subject, predicate, target, status, chunk, start, end, *, method, extra=None):
        if subject == target:
            return
        span = evidence(chunk, start, end)
        item = {"subject_id":subject, "predicate":predicate, "object_id":target,
                "document_id":document["id"], "chunk_id":chunk.get("id", chunk.get("chunk_id")),
                "status":status, "first_observed_at_utc":document["first_observed_at_utc"],
                "published_at_utc":document.get("published_at_utc"), "evidence_quote":span["text"],
                "metadata":{"extractor_version":VERSION, "ontology_version":ontology["version"],
                            "supported_extraction":status=="reported", "needs_review":status!="reported",
                            "extraction_method":method, "evidence_span":span,
                            "source_url":document["source_url"], "metric_domains":_domains(span["text"], ontology),
                            "causal_impact_established":False,
                            "claim_scope":"sourced_news_hypothesis" if is_news else "issuer_document_context",
                            **(extra or {})}}
        item["id"] = _id("edge:", item)
        edges.append(item)

    for raw_chunk in chunks:
        chunk = dict(raw_chunk)
        text = chunk.get("text")
        if not isinstance(text, str) or not chunk.get("id", chunk.get("chunk_id")):
            raise ValueError("Chunk requires id/chunk_id and exact text")
        base = chunk.get("start_offset", 0)
        if type(base) is not int or base < 0:
            raise ValueError("Chunk page start_offset must be nonnegative integer")
        if "end_offset" in chunk and chunk["end_offset"] != base+len(text):
            raise ValueError("Chunk end_offset does not match exact text")
        if "page_text" in chunk and chunk["page_text"][base:base+len(text)] != text:
            raise ValueError("Chunk does not round-trip to page text")
        mentions, ambiguity = _matches(text, catalog)
        for problem in ambiguity:
            warnings.append({"kind":"ambiguous_alias", **problem,
                             "evidence_span":evidence(chunk, problem["start"], problem["end"])})
        company_mentions = [item for item in mentions if by_id[item["entity_id"]]["kind"] in COMPANY_KINDS]
        taxonomy_mentions, _ = _matches(text, ontology["taxonomy"], ticker_guard=False)
        for mention in taxonomy_mentions:
            used_taxonomy[mention["entity_id"]] = next(item for item in ontology["taxonomy"] if item["id"]==mention["entity_id"])
        for start, end, sentence in _sentences(text):
            sentence_mentions = [item for item in mentions if start <= item["start"] and item["end"] <= end]
            companies = [item for item in company_mentions if start <= item["start"] and item["end"] <= end]
            taxes = [item for item in taxonomy_mentions if start <= item["start"] and item["end"] <= end]
            subjects = [issuer] if issuer else list(dict.fromkeys(item["entity_id"] for item in companies))
            for subject in subjects:
                for mention in sentence_mentions:
                    edge(subject, "MENTIONS", mention["entity_id"], "candidate", chunk, start, end,
                         method="lexical_mention", extra={"entity_mention_span":evidence(chunk, mention["start"], mention["end"]),
                                                         "relationship_not_established":True})
                for mention in taxes:
                    edge(subject, "MENTIONS_EXPOSURE", mention["entity_id"], "candidate", chunk, start, end,
                         method="taxonomy_keyword_context", extra={"taxonomy_mention_span":evidence(chunk, mention["start"], mention["end"]),
                                                                   "exposure_role":"unspecified"})
            if is_news and IMPACT.search(sentence):
                claims.append({"id":_id("claim:", [document["id"], chunk.get("id", chunk.get("chunk_id")), start, end]),
                               "status":"hypothesis", "needs_review":True, "causal_impact_established":False,
                               "entity_ids":sorted({item["entity_id"] for item in sentence_mentions}),
                               "taxonomy_ids":sorted({item["entity_id"] for item in taxes}),
                               "metric_domains":_domains(sentence, ontology), "evidence_span":evidence(chunk, start, end)})
            if not issuer_report or STOP_REPORTED.search(sentence):
                continue
            for role in ROLE.finditer(sentence):
                tail_start = role.end()
                tail = sentence[tail_start:]
                boundary = CLAUSE_END.search(tail)
                tail_end = tail_start+(boundary.start() if boundary else len(tail))
                targets = [item for item in companies if start+tail_start <= item["start"] and item["end"] <= start+tail_end]
                cursor = start+tail_start
                for mention in targets:
                    if not LIST_CONNECTOR.fullmatch(text[cursor:mention["start"]]):
                        break
                    if NEW_PREDICATE.search(text[mention["end"]:start+tail_end]):
                        break
                    role_name = (role.group("role") or "").lower()
                    supplier = role_name.startswith("supplier") or role.group("buy") is not None
                    subject, target = (mention["entity_id"], issuer) if supplier else (issuer, mention["entity_id"])
                    edge(subject, "SUPPLIES_TO", target, "reported", chunk, start+role.start(), mention["end"],
                         method="explicit_first_person_supplier" if supplier else "explicit_first_person_customer",
                         extra={"reported_by_issuer":issuer, "role_marker":role.group(),
                                "named_entity_span":evidence(chunk, mention["start"], mention["end"]),
                                "independently_verified":False})
                    cursor = mention["end"]
    unique = {item["id"]:item for item in edges}
    entities = [{**used_taxonomy[key], "kind":used_taxonomy[key]["kind"].lower(),
                 "first_observed_at_utc":document["first_observed_at_utc"],
                 "metadata":{"ontology_version":ontology["version"], "lexical_taxonomy_only":True}}
                for key in sorted(used_taxonomy)]
    return {"extractor_version":VERSION, "entities":entities,
            "edges":[unique[key] for key in sorted(unique)], "evidence_spans":[spans[key] for key in sorted(spans)],
            "claims":claims, "warnings":warnings}


def extract_edges(document, chunks, entity_catalog, issuer_entity_id=None, ontology_path=None):
    """Convenience store-ingestion adapter; use extract_document for warnings/claims."""
    return extract_document(document, chunks, entity_catalog, issuer_entity_id, ontology_path)["edges"]
