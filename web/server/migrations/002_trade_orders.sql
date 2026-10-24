-- Every previewed and executed True Markets order placed from the app (audit log + daily limit).

create table if not exists trade_orders (
  id bigint generated always as identity primary key,
  order_id text not null unique,
  asset_id text not null,
  symbol text not null,
  chain text,
  side text not null check (side in ('buy', 'sell')),
  qty text not null,
  notional_usd numeric(14, 6) not null check (notional_usd >= 0),
  quote jsonb,
  status text not null,
  final_status text,
  error text,
  executed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists trade_orders_executed_idx on trade_orders (executed_at desc) where executed_at is not null;
