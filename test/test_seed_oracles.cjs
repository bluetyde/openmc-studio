// The SEED oracle files equal what the generator makes, every tolerance pin matches its entry, and every input hash matches its file.
// Needs an Electron binary (SEED_ELECTRON, else the sibling SEED clone's). Run: node test/test_seed_oracles.cjs
const { spawnSync } = require("child_process");
const fs = require("fs"), path = require("path"), crypto = require("crypto"), assert = require("assert");
const root = path.join(__dirname, "..");
const base = path.join(root, "oracles", "seed");
const sha256 = (b) => crypto.createHash("sha256").update(b).digest("hex");
const sorted = (v) => (Array.isArray(v) ? v.map(sorted) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);

const gen = spawnSync(process.execPath, [path.join(root, "studio", "tools", "gen_seed_oracles.cjs"), "--check"], { encoding: "utf8" });
if (gen.status === 2) { console.error("NOT RUN: " + gen.stderr); process.exit(3); }
assert.strictEqual(gen.status, 0, "the files differ from the generator's output:\n" + gen.stdout + gen.stderr);
console.log("  [PASS] generated files equal the files on disk");

const entries = fs.readdirSync(path.join(base, "entries")).map((f) => JSON.parse(fs.readFileSync(path.join(base, "entries", f), "utf8")));
assert.strictEqual(entries.length, 8);
for (const e of entries) {
  assert.strictEqual(e.toleranceHash, sha256(JSON.stringify(sorted({ expected: e.expected ?? null, tolerance: e.tolerance ?? null }))), e.oracleId + ": toleranceHash");
  for (const i of e.inputs) assert.strictEqual(sha256(fs.readFileSync(path.join(base, i.path))), i.sha256, e.oracleId + ": " + i.path + " does not match its pinned hash");
}
console.log("  [PASS] every tolerance pin and input hash matches (" + entries.length + " entries)");

// The analytic cases come from the library cross sections, and the library identity is recorded with them.
const xs = JSON.parse(fs.readFileSync(path.join(base, "xs", "b10-294K-0.0253eV.json"), "utf8"));
assert.ok(/^[0-9a-f]{64}$/.test(xs.library.file_sha256) && /^[0-9a-f]{64}$/.test(xs.library.cross_sections_xml_sha256));
assert.ok(Math.abs(xs.sigma_total_b - xs.sigma_elastic_b - xs.sigma_absorption_b) <= 1e-6 * xs.sigma_total_b);
console.log("  [PASS] the cross-section file records its library and is consistent");
