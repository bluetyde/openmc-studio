// studio/tools/regen_script.cjs: the regenerated script equals the one Studio saved with an example, is the same twice, and a
// project with error-level problems still writes a script but exits 3. Requires playwright. Run: node test/test_regen_script.cjs
const { spawnSync } = require("child_process");
const fs = require("fs"), path = require("path"), os = require("os"), assert = require("assert");
const root = path.join(__dirname, "..");
const tool = path.join(root, "studio", "tools", "regen_script.cjs");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "regen-"));
const regen = (project, out) => {
  const r = spawnSync(process.execPath, [tool, project, out], { encoding: "utf8" });
  const line = (r.stdout || "").trim().split("\n").pop();
  return { status: r.status, reply: JSON.parse(line) };
};
try {
  const proj = path.join(root, "examples", "triso-particle", "triso-particle.openmc-studio.json");
  const saved = fs.readFileSync(path.join(root, "examples", "triso-particle", "model.py"), "utf8").replace(/\r\n/g, "\n");
  const a = regen(proj, path.join(tmp, "a.py")), b = regen(proj, path.join(tmp, "b.py"));
  assert.strictEqual(a.status, 0, JSON.stringify(a.reply));
  assert.deepStrictEqual(a.reply.problems, []);
  assert.strictEqual(fs.readFileSync(path.join(tmp, "a.py"), "utf8"), saved, "the regenerated script differs from the saved model.py");
  assert.strictEqual(a.reply.sha256, b.reply.sha256, "two regenerations differ");
  console.log("  [PASS] regenerated script equals the saved one, twice");

  const bad = JSON.parse(fs.readFileSync(proj, "utf8"));
  bad.materials = []; // every cell now points at a material that does not exist
  fs.writeFileSync(path.join(tmp, "bad.json"), JSON.stringify(bad));
  const c = regen(path.join(tmp, "bad.json"), path.join(tmp, "c.py"));
  assert.strictEqual(c.status, 3, JSON.stringify(c.reply));
  assert.ok(c.reply.problems.length > 0);
  console.log("  [PASS] a project with errors exits 3 and lists them");

  const n = regen(path.join(tmp, "missing.json"), path.join(tmp, "d.py"));
  assert.strictEqual(n.status, 2);
  console.log("  [PASS] a missing project exits 2");
} finally { fs.rmSync(tmp, { recursive: true, force: true }); }
