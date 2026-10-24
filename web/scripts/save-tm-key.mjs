// Saves a True Markets API key file from the macOS clipboard to TM_KEY_FILE (default ~/.truemarkets/api-key.json).
// Copy the downloaded JSON, then run: npm run tm:key   (add -- --force to replace an existing key)
// The key never touches the repo or the terminal output; only a key_id prefix is printed.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

const target = process.env.TM_KEY_FILE || join(homedir(), ".truemarkets", "api-key.json");
const force = process.argv.includes("--force");
const fail = (message) => {
  console.error(`✗ ${message}`);
  process.exit(1);
};

let raw;
try {
  raw = execFileSync("pbpaste", { encoding: "utf8" }).trim();
} catch {
  fail("Could not read the clipboard (pbpaste). Copy the key JSON first.");
}
let key;
try {
  key = JSON.parse(raw);
} catch {
  fail("Clipboard isn't JSON. Copy the whole downloaded key file, braces included.");
}
const jwk = key?.private_key;
if (typeof key?.key_id !== "string" || !key.key_id) fail("Missing key_id.");
if (key.algorithm && key.algorithm !== "ES256") fail(`Unexpected algorithm ${key.algorithm}; expected ES256.`);
if (jwk?.kty !== "EC" || jwk?.crv !== "P-256" || !jwk?.d || !jwk?.x || !jwk?.y) fail("private_key must be a P-256 EC JWK with d, x and y.");
if (existsSync(target) && !force) fail(`${target} already exists. Re-run with --force to replace it.`);

mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
const temp = `${target}.tmp-${process.pid}`;
writeFileSync(temp, `${JSON.stringify(key, null, 2)}\n`, { mode: 0o600 });
renameSync(temp, target);
// Clear the clipboard so the key isn't left there.
try {
  execFileSync("pbcopy", { input: "" });
} catch {}
console.log(`✓ Saved key ${key.key_id.slice(0, 8)}… (${key.algorithm ?? "ES256"}, P-256) to ${target} with owner-only permissions. Clipboard cleared.`);
