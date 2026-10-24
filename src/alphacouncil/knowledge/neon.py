"""Neon snapshot import and bounded, resumable passage embedding jobs."""

import hashlib
import json
import math
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.types.json import Jsonb

MODEL = 'openai/text-embedding-3-small'
DIMENSIONS = 1536
SCHEMA = 'alphacouncil_graph'


def environment():
    load_dotenv('web/.env.local')
    load_dotenv('.env.local')
    if not os.environ.get('DATABASE_URL'):
        raise ValueError('DATABASE_URL is required in the environment or web/.env.local')
    return os.environ


def connection():
    return psycopg.connect(environment()['DATABASE_URL'], connect_timeout=20, prepare_threshold=None)


def import_snapshot(database=Path('data/knowledge/graph.sqlite3')):
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    source = sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    source.execute('BEGIN')
    counts = {}
    tables = ['entities', 'entity_snapshots', 'documents', 'pages', 'chunks', 'edges']
    with connection() as target:
        target.execute("SET LOCAL statement_timeout='120s'")
        target.execute("SET LOCAL lock_timeout='5s'")
        target.execute(Path('migrations/001_knowledge_graph.sql').read_text())
        target.execute('SELECT pg_advisory_xact_lock(81936241)')
        for table in tables:
            rows = source.execute('SELECT * FROM '+table)
            original = [item[0] for item in rows.description]
            columns = [name.removesuffix('_json') for name in original]
            stage = sql.Identifier('stage_'+table)
            qualified = sql.Identifier(SCHEMA, table)
            fields = sql.SQL(',').join(map(sql.Identifier, columns))
            target.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP').format(stage, qualified))
            with target.cursor().copy(sql.SQL('COPY {} ({}) FROM STDIN').format(stage, fields)) as copy:
                count = 0
                for row in rows:
                    copy.write_row([Jsonb(json.loads(row[name])) if name.endswith('_json') else row[name] for name in original])
                    count += 1
            # A changed existing ID is an error; never silently rewrite source evidence.
            differences = sql.SQL(' OR ').join(sql.SQL('s.{} IS DISTINCT FROM t.{}').format(sql.Identifier(c),sql.Identifier(c)) for c in columns)
            changed = target.execute(sql.SQL('SELECT count(*) FROM {} s JOIN {} t ON t.id=s.id WHERE {}').format(stage,qualified,differences)).fetchone()[0]
            if changed:
                raise ValueError('Existing evidence snapshot differs: '+table)
            target.execute(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT (id) DO NOTHING').format(qualified,fields,fields,stage))
            counts[table] = count
            print(json.dumps({'imported_table':table,'source_rows':count}),flush=True)
        target.execute('INSERT INTO alphacouncil_graph.imports(snapshot_sha256,counts) VALUES (%s,%s) ON CONFLICT DO NOTHING',(digest,Jsonb(counts)))
    source.close()
    return {'snapshot_sha256':digest,'counts':counts}


def configure_reader():
    """Create a schema-scoped SELECT-only login; keep owner credentials out of serving code."""
    env = environment()
    if env.get('KNOWLEDGE_DATABASE_URL'):
        return {'reader':'existing_configuration'}
    password = secrets.token_urlsafe(36)
    role = 'alphacouncil_graph_reader'
    with connection() as conn:
        if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
            raise ValueError('Reader role exists without local credentials; configure KNOWLEDGE_DATABASE_URL explicitly')
        conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA alphacouncil_graph TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA alphacouncil_graph TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='12s'").format(sql.Identifier(role)))
        conn.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only=on').format(sql.Identifier(role)))
    parsed = urlsplit(env['DATABASE_URL'])
    address = parsed.netloc.rsplit('@',1)[-1]
    reader_url = urlunsplit((parsed.scheme,quote(role)+':'+quote(password,safe='')+'@'+address,parsed.path,parsed.query,parsed.fragment))
    path = Path('web/.env.local')
    with path.open('a') as output:
        output.write('\n# Schema-scoped read-only graph service login\nKNOWLEDGE_DATABASE_URL='+reader_url+'\n')
    path.chmod(0o600)
    return {'reader':'created_select_only_login'}


def validate_embeddings(payload, count):
    records = payload.get('data') if isinstance(payload,dict) else None
    if not isinstance(records,list) or len(records)!=count:
        raise ValueError('Embedding response count mismatch')
    vectors = [None]*count
    for row in records:
        index,vector = row.get('index'),row.get('embedding')
        if type(index) is not int or not 0<=index<count or vectors[index] is not None:
            raise ValueError('Embedding response has invalid indices')
        if not isinstance(vector,list) or len(vector)!=DIMENSIONS or any(type(x) not in (int,float) or not math.isfinite(x) for x in vector):
            raise ValueError('Embedding response has invalid vector dimensions/values')
        if not any(vector):
            raise ValueError('Zero vectors cannot be cosine searched')
        vectors[index] = vector
    return vectors


def embed_missing(*, max_chunks=15000, batch_size=64):
    env = environment()
    key = env.get('OPENROUTER_API_KEY')
    if not key:
        raise ValueError('OPENROUTER_API_KEY is required for semantic embeddings')
    if not 1<=batch_size<=128 or not 1<=max_chunks<=20000:
        raise ValueError('Embedding job exceeds bounded batch limits')
    with connection() as conn:
        rows = conn.execute('''SELECT c.id,c.text FROM alphacouncil_graph.chunks c
          LEFT JOIN alphacouncil_graph.embeddings e ON e.chunk_id=c.id WHERE e.chunk_id IS NULL ORDER BY c.id LIMIT %s''',(max_chunks,)).fetchall()
    # Stable chunk size comes from the source index. Refuse unexpectedly enlarged inputs.
    if any(not text.strip() or len(text)>4000 for _,text in rows):
        raise ValueError('Passage exceeds expected bounded embedding input')
    tokens, completed = 0,0
    with httpx.Client(timeout=60) as client, connection() as conn:
        for start in range(0,len(rows),batch_size):
            batch = rows[start:start+batch_size]
            payload = None
            for attempt in range(3):
                try:
                    response = client.post('https://openrouter.ai/api/v1/embeddings',headers={'Authorization':'Bearer '+key},json={'model':MODEL,'dimensions':DIMENSIONS,'encoding_format':'float','input':[text for _,text in batch]})
                except httpx.TransportError:
                    if attempt==2:raise RuntimeError('Embedding transport failed after bounded retries') from None
                    time.sleep(1+attempt)
                    continue
                if response.status_code==200:
                    payload=response.json();break
                if response.status_code not in (429,500,502,503,504):
                    raise RuntimeError('Embedding provider refused request (HTTP '+str(response.status_code)+')')
                if attempt<2:time.sleep(1+attempt)
            if payload is None:
                raise RuntimeError('Embedding provider unavailable after bounded retries')
            vectors = validate_embeddings(payload,len(batch))
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany('''INSERT INTO alphacouncil_graph.embeddings(chunk_id,model,input_sha256,embedding)
                      VALUES (%s,%s,%s,%s::vector) ON CONFLICT (chunk_id) DO NOTHING''',
                      [(identifier,MODEL,hashlib.sha256(text.encode()).hexdigest(),json.dumps(vector)) for (identifier,text),vector in zip(batch,vectors)])
            completed+=len(batch)
            tokens+=payload.get('usage',{}).get('prompt_tokens',0)
            if completed%640==0 or completed==len(rows):print(json.dumps({'embedded':completed,'selected':len(rows),'prompt_tokens':tokens}),flush=True)
        conn.execute('CREATE INDEX IF NOT EXISTS embedding_cosine_idx ON alphacouncil_graph.embeddings USING hnsw (embedding vector_cosine_ops)')
    return {'new_embeddings':completed,'prompt_tokens':tokens,'model':MODEL,'dimensions':DIMENSIONS}
