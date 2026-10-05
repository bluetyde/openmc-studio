// Regenerate model.py from a Studio project with the real page, headless. Used by SEED to check that a model.py is exactly what
// Studio's generator produces for its project.json (no project-supplied Python is executed: only the page's own code runs).
//
//   node studio/tools/regen_script.cjs PROJECT.json OUT.py [--html path/to/index.html]
//
// Prints one JSON line {ok, bytes, sha256, problems, pageErrors}; exit 0 when the script was written, 2 for bad input, 3 when
// the project has error-level problems (the page's own Run button refuses those too; the script is still written for diffing).
// Needs playwright (NODE_PATH or SEED_PLAYWRIGHT) and Edge/Chromium (BROWSER_CHANNEL, default msedge), like the browser tests.
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

function loadPlaywright() {
  const tries = [process.env.SEED_PLAYWRIGHT, "playwright"].filter(Boolean);
  for (const t of tries) {
    try { return require(t); } catch { /* try the next */ }
  }
  throw new Error("playwright not found: set NODE_PATH or SEED_PLAYWRIGHT");
}

(async () => {
  const args = process.argv.slice(2);
  const hi = args.indexOf("--html");
  const html = hi >= 0 ? args.splice(hi, 2)[1] : path.join(__dirname, "..", "openmc_studio", "static", "index.html");
  const [projectPath, outPath] = args;
  const fail = (code, message) => { console.log(JSON.stringify({ ok: false, error: message })); process.exit(code); };
  if (!projectPath || !outPath) fail(2, "usage: regen_script.cjs PROJECT.json OUT.py [--html index.html]");
  let project;
  try { project = JSON.parse(fs.readFileSync(projectPath, "utf8")); } catch (e) { fail(2, "cannot read the project: " + e.message); }
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || "msedge" });
  try {
    const page = await browser.newPage();
    const pageErrors = [];
    page.on("pageerror", e => pageErrors.push(e.message));
    await page.route("**/*", r => r.fulfill({ status: 404, body: "" })); // nothing leaves the page
    await page.setContent(fs.readFileSync(html, "utf8"));
    await page.evaluate(() => { clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {}; });
    const out = await page.evaluate(p => {
      loadProject(p);
      const P = problems();
      return { script: generate(P), problems: P.filter(x => x.sev === "error").map(x => String(x.msg || x.text || x.message || JSON.stringify(x))) };
    }, project).catch(e => ({ failed: e.message }));
    if (out.failed || pageErrors.length) fail(2, out.failed || "the page raised: " + pageErrors[0]);
    fs.writeFileSync(outPath, out.script, "utf8");
    console.log(JSON.stringify({ ok: true, bytes: Buffer.byteLength(out.script), sha256: crypto.createHash("sha256").update(out.script, "utf8").digest("hex"), problems: out.problems, pageErrors }));
    process.exitCode = out.problems.length ? 3 : 0;
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(2); });
