-- News headlines seen per instrument, and AI sentiment reads over the latest 10.

create table if not exists news_articles (
  id bigint generated always as identity primary key,
  symbol text not null,
  url text not null,
  title text not null,
  source text not null,
  provider text not null check (provider in ('Yahoo Finance', 'Google News')),
  published_at timestamptz not null,
  first_seen_at timestamptz not null default now(),
  unique (symbol, url)
);

create index if not exists news_articles_symbol_published_idx on news_articles (symbol, published_at desc);

create table if not exists news_sentiment_runs (
  id bigint generated always as identity primary key,
  symbol text not null,
  -- sha256 of the analysed headline URLs, so an identical set can be recognised.
  headline_hash text not null,
  model text not null,
  overall_label text not null check (overall_label in ('positive', 'negative', 'mixed', 'neutral')),
  overall_score real not null check (overall_score between -1 and 1),
  summary text not null,
  -- [{url, title, source, provider, publishedAt, label, score, reason}] in feed order.
  items jsonb not null check (jsonb_typeof(items) = 'array'),
  input_tokens integer,
  output_tokens integer,
  cost_usd numeric(10, 6),
  created_at timestamptz not null default now()
);

create index if not exists news_sentiment_runs_symbol_created_idx on news_sentiment_runs (symbol, created_at desc);
create index if not exists news_sentiment_runs_symbol_hash_idx on news_sentiment_runs (symbol, headline_hash, created_at desc);

create table if not exists schema_migrations (
  name text primary key,
  applied_at timestamptz not null default now()
);
