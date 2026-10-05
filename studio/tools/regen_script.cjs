// Regenerate model.py from a Studio project with the real page, headless, inside Electron's Chromium (hidden window, every
// network request blocked). Used by SEED to check that a model.py is exactly what Studio's generator produces for its
// project.json: no project-supplied Python is executed, only the page's own code runs.
//
//   <electron> studio/tools/regen_script.cjs PROJECT.json OUT.py [INDEX.html]
//
// Prints one JSON line {ok, bytes, sha256, problems, chrome}. Exit 0: script written. 2: bad input or the page failed.
// 3: the project has error-level problems (the page's own Run button refuses those too; the script is still written for diffing).
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

app.disableHardwareAcceleration();
const [projectPath, outPath, htmlArg] = process.argv.slice(process.argv.findIndex(a => path.resolve(a) === __filename) + 1);
const html = htmlArg || path.join(__dirname, "..", "openmc_studio", "static", "index.html");
const done = (code, reply) => { console.log(JSON.stringify(reply)); app.exit(code); };

app.whenReady().then(async () => {
  if (!projectPath || !outPath) return done(2, { ok: false, error: "usage: regen_script.cjs PROJECT.json OUT.py [INDEX.html]" });
  let project;
  try { project = JSON.parse(fs.readFileSync(projectPath, "utf8")); } catch (e) { return done(2, { ok: false, error: "cannot read the project: " + e.message }); }
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true } });
  const pageErrors = [];
  win.webContents.on("console-message", (_e, level, message) => { if (level >= 3) pageErrors.push(String(message)); });
  win.webContents.session.webRequest.onBeforeRequest((d, cb) => cb({ cancel: !d.url.startsWith("data:") }));
  await win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(fs.readFileSync(html, "utf8")));
  await win.webContents.executeJavaScript("clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {}; 0");
  const out = await win.webContents.executeJavaScript(
    `(function (p) { loadProject(p); const P = problems(); return { script: generate(P), problems: P.filter(x => x.sev === "error").map(x => String(x.msg || x.text || x.message || JSON.stringify(x))) }; })(${JSON.stringify(project)})`);
  fs.writeFileSync(outPath, out.script, "utf8");
  done(out.problems.length ? 3 : 0, { ok: true, bytes: Buffer.byteLength(out.script), sha256: crypto.createHash("sha256").update(out.script, "utf8").digest("hex"), problems: out.problems, chrome: process.versions.chrome });
}).catch(e => done(2, { ok: false, error: String(e && e.message || e) }));
