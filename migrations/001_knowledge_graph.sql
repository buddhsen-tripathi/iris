-- Dedicated schema: does not alter the application's public tables.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS alphacouncil_graph;
REVOKE ALL ON SCHEMA alphacouncil_graph FROM PUBLIC;
CREATE TABLE IF NOT EXISTS alphacouncil_graph.entities (
 id text PRIMARY KEY, kind text NOT NULL, first_observed_at_utc timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS alphacouncil_graph.entity_snapshots (
 id text PRIMARY KEY, entity_id text NOT NULL REFERENCES alphacouncil_graph.entities(id),
 name text NOT NULL, aliases jsonb NOT NULL, identifiers jsonb NOT NULL, metadata jsonb NOT NULL,
 first_observed_at_utc timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS entity_snapshot_observed_idx ON alphacouncil_graph.entity_snapshots(entity_id,first_observed_at_utc DESC,id DESC);
CREATE INDEX IF NOT EXISTS entity_name_idx ON alphacouncil_graph.entity_snapshots(lower(name));
CREATE INDEX IF NOT EXISTS entity_alias_idx ON alphacouncil_graph.entity_snapshots USING gin(aliases);
CREATE TABLE IF NOT EXISTS alphacouncil_graph.documents (
 id text PRIMARY KEY, source_url text NOT NULL, title text NOT NULL, content_sha256 text NOT NULL,
 source_name text NOT NULL, first_observed_at_utc timestamptz NOT NULL, published_at_utc timestamptz, metadata jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS alphacouncil_graph.pages (
 id text PRIMARY KEY, document_id text NOT NULL REFERENCES alphacouncil_graph.documents(id),
 page_number integer NOT NULL CHECK(page_number>0), text text NOT NULL, text_sha256 text NOT NULL,
 UNIQUE(document_id,page_number)
);
CREATE TABLE IF NOT EXISTS alphacouncil_graph.chunks (
 id text PRIMARY KEY, page_id text NOT NULL REFERENCES alphacouncil_graph.pages(id),
 start_offset integer NOT NULL CHECK(start_offset>=0), end_offset integer NOT NULL CHECK(end_offset>start_offset), text text NOT NULL,
 search tsvector GENERATED ALWAYS AS (to_tsvector('english',text)) STORED,
 UNIQUE(page_id,start_offset,end_offset)
);
CREATE INDEX IF NOT EXISTS chunk_search_idx ON alphacouncil_graph.chunks USING gin(search);
CREATE TABLE IF NOT EXISTS alphacouncil_graph.edges (
 id text PRIMARY KEY, subject_id text NOT NULL REFERENCES alphacouncil_graph.entities(id),
 predicate text NOT NULL, object_id text NOT NULL REFERENCES alphacouncil_graph.entities(id),
 document_id text NOT NULL REFERENCES alphacouncil_graph.documents(id), chunk_id text REFERENCES alphacouncil_graph.chunks(id),
 status text NOT NULL CHECK(status IN ('reference','reported','candidate')),
 first_observed_at_utc timestamptz NOT NULL, published_at_utc timestamptz, valid_from_utc timestamptz, valid_to_utc timestamptz,
 evidence_quote text, metadata jsonb NOT NULL,
 CHECK(valid_to_utc IS NULL OR valid_from_utc IS NULL OR valid_to_utc>valid_from_utc)
);
CREATE INDEX IF NOT EXISTS edge_subject_idx ON alphacouncil_graph.edges(subject_id,status,first_observed_at_utc);
CREATE INDEX IF NOT EXISTS edge_object_idx ON alphacouncil_graph.edges(object_id,status,first_observed_at_utc);
CREATE INDEX IF NOT EXISTS edge_document_idx ON alphacouncil_graph.edges(document_id);
CREATE INDEX IF NOT EXISTS edge_chunk_idx ON alphacouncil_graph.edges(chunk_id);
CREATE TABLE IF NOT EXISTS alphacouncil_graph.embeddings (
 chunk_id text PRIMARY KEY REFERENCES alphacouncil_graph.chunks(id),
 model text NOT NULL CHECK(model='openai/text-embedding-3-small'),
 input_sha256 text NOT NULL, embedding vector(1536) NOT NULL,
 first_observed_at_utc timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS alphacouncil_graph.imports (
 snapshot_sha256 text PRIMARY KEY, imported_at_utc timestamptz NOT NULL DEFAULT now(), counts jsonb NOT NULL
);
