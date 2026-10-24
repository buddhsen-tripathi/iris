// Applies server/migrations/*.sql in name order, once each. Usage: npm run db:migrate
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { neon } from "@neondatabase/serverless";

if (!process.env.DATABASE_URL) {
  console.error("DATABASE_URL is not set (expected in web/.env.local).");
  process.exit(1);
}
const sql = neon(process.env.DATABASE_URL);
const dir = join(dirname(fileURLToPath(import.meta.url)), "migrations");

await sql`create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())`;
const applied = new Set((await sql`select name from schema_migrations`).map((r) => r.name));
for (const name of readdirSync(dir).filter((f) => f.endsWith(".sql")).sort()) {
  if (applied.has(name)) {
    console.log(`skip   ${name}`);
    continue;
  }
  // Split on statement-ending semicolons; the files hold plain DDL without functions or $$ bodies.
  const statements = readFileSync(join(dir, name), "utf8")
    .replace(/--.*$/gm, "")
    .split(/;\s*$/m)
    .map((s) => s.trim())
    .filter(Boolean);
  await sql.transaction([...statements.map((s) => sql.query(s)), sql`insert into schema_migrations (name) values (${name})`]);
  console.log(`apply  ${name} (${statements.length} statements)`);
}
