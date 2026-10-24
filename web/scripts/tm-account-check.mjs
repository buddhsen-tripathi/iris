// Read-only True Markets account check: mints a token with TM_KEY_FILE, then calls GET endpoints only.
// Usage: npm run tm:check   (never prints the key, tokens, or signatures)
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";

const BASE = "https://api.truemarkets.co";
const READS = ["/v1/gateway/portfolio", "/v1/gateway/balances", "/v1/gateway/positions", "/v1/gateway/orders?limit=5", "/v1/gateway/transactions?limit=5"];
const keyFile = process.env.TM_KEY_FILE;
if (!keyFile) throw new Error("TM_KEY_FILE is not set (web/.env.local).");
const { key_id, private_key: jwk } = JSON.parse(readFileSync(keyFile, "utf8"));

// Token challenge: ES256 over "{key_id}.{timestamp}", r||s base64url (WebCrypto ECDSA output is already r||s).
const key = await webcrypto.subtle.importKey("jwk", { ...jwk, key_ops: ["sign"] }, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
const timestamp = Math.floor(Date.now() / 1000);
const signed = await webcrypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, new TextEncoder().encode(`${key_id}.${timestamp}`));
const mint = await fetch(`${BASE}/v1/auth/api-key/token`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ key_id, timestamp, signature: Buffer.from(signed).toString("base64url") }),
});
const minted = await mint.json().catch(() => ({}));
if (!mint.ok) {
  console.error(`✗ Token mint failed: HTTP ${mint.status} ${minted.code ?? minted.type ?? ""} ${minted.message ?? ""} (request_id ${minted.request_id ?? "n/a"})`);
  process.exit(1);
}
console.log(`✓ Authenticated with key ${key_id.slice(0, 8)}… · access token expires ${minted.expires_in} · refresh token ${minted.refresh_token ? "issued" : "not issued"}`);

const redact = (value) =>
  JSON.parse(JSON.stringify(value), (k, v) => (/token|signature|secret|private|payload/i.test(k) ? "<redacted>" : v));
for (const path of READS) {
  const response = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${minted.access_token}`, Accept: "application/json" } });
  const body = await response.json().catch(() => null);
  const text = JSON.stringify(redact(body));
  console.log(`\n${response.ok ? "✓" : "✗"} GET ${path} → ${response.status}`);
  console.log(text.length > 1800 ? `${text.slice(0, 1800)}… (${text.length} chars)` : text);
}
