/* Runs the built claude.ai page (build/claude-page/) in Chromium with a stand-in for claude.ai's window.claude:
   "sample" answers with the verdicts the judges wrote in the committed acceptance run, "downloads" records saves.
   It adds the acceptance fixture, runs the whole check and checks the results and the saved files.

   Run: python tools/build_claude_page.py && node tools/test_claude_page.js [screenshot folder]   (needs Playwright) */
"use strict";
const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.join(ROOT, "build", "claude-page");
const EXAMPLES = path.join(ROOT, "examples", "claims_sample_claims");
const shots = process.argv[2];

function recorded(folder) {
  const out = {};
  for (const name of fs.readdirSync(path.join(EXAMPLES, folder))) {
    const data = JSON.parse(fs.readFileSync(path.join(EXAMPLES, folder, name), "utf8"));
    out[data.refkey] = data;
  }
  return out;
}

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".wasm": "application/wasm", ".json": "application/json", ".txt": "text/plain" };
const server = http.createServer((req, res) => {
  const file = path.join(SITE, decodeURIComponent(new URL(req.url, "http://x").pathname === "/" ? "/index.html" : new URL(req.url, "http://x").pathname));
  if (!file.startsWith(SITE) || !fs.existsSync(file) || /\.(zip|whl)$/.test(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
  if (file.endsWith(".html")) {  // the skeleton claude.ai wraps a published page in
    res.end('<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
      + "<style>:root{color-scheme:light}body{margin:0;font:14px system-ui}img{max-width:100%}[hidden]{display:none!important}</style>"
      + "</head><body>" + fs.readFileSync(file, "utf8") + "</body></html>");
    return;
  }
  fs.createReadStream(file).pipe(res);
});

function fail(message) { console.error("FAIL: " + message); process.exitCode = 1; }

(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  page.on("pageerror", (e) => fail("page error: " + e.message));
  await page.addInitScript(({ first, second }) => {
    window.__questions = [];
    window.__saved = [];
    const sample = async (input, options) => {
      const refkey = /\nRefkey: (\S+)/.exec(input)[1];
      const ids = /## Claims to judge \(([^)]*)\)/.exec(input)[1].split(", ");
      const isSecond = input.includes("SECOND OPINION");
      window.__questions.push({ refkey, ids, second: isSecond, bytes: new TextEncoder().encode(input).length, options });
      const pick = (data) => Object.fromEntries((data?.occurrences || []).map((o) => [o.id, o]));
      const entries = { ...pick(first[refkey]), ...(isSecond ? pick(second[refkey]) : {}) };
      const reply = { refkey, prompt_version: "1", occurrences: ids.map((id) => entries[id]) };
      return { text: "```json\n" + JSON.stringify(reply) + "\n```", truncated: false, modelTierApplied: "complex", modelApplied: options.model };
    };
    sample.limits = async () => ({ maxPromptBytes: 262144 });
    const downloads = { save: async ({ filename, data }) => { window.__saved.push({ filename, bytes: data.byteLength }); return {}; } };
    window.claude = { use: async (name) => ({ sample, downloads })[name] || null };
  }, { first: recorded("verdicts"), second: recorded("second") });

  await page.goto(base);
  const exampleRows = await page.locator("#claims .claim").count();
  if (exampleRows !== 14) fail(`the example shows ${exampleRows} claims, expected 14`);
  if (shots) await page.screenshot({ path: path.join(shots, "1-start.png"), fullPage: true });

  await page.locator("#ms-input").setInputFiles(path.join(ROOT, "tests", "fixtures", "claims_sample.docx"));
  await page.locator("#src-input").setInputFiles(fs.readdirSync(path.join(ROOT, "tests", "fixtures", "claims_sources"))
    .map((f) => path.join(ROOT, "tests", "fixtures", "claims_sources", f)));
  await page.waitForSelector("#sources tr", { timeout: 120000 });
  const sub = await page.textContent("#sources-sub");
  if (!sub.includes("14 citations of 10 works; 2 with text")) fail("sources summary: " + sub);
  if (shots) await page.screenshot({ path: path.join(shots, "2-sources.png"), fullPage: true });

  await page.selectOption("#model", "claude-opus-5-5");
  await page.click("#check");
  await page.waitForSelector("#saves:not([hidden])", { timeout: 180000 });
  const questions = await page.evaluate(() => window.__questions);
  const summary = questions.map((q) => `${q.second ? "second" : "first"} ${q.refkey} ${q.ids.join(",")}`).sort();
  const expected = ["first pilch2023 C004,C005", "first vanprooijen2023 C010", "second pilch2023 C004,C005", "second vanprooijen2023 C010"];
  if (JSON.stringify(summary) !== JSON.stringify(expected)) fail("questions asked: " + summary.join("; "));
  if (questions.some((q) => q.bytes > 262144 || q.options.effort !== "high" || q.options.model !== "claude-opus-5-5")) fail("question size or options");
  if (questions.some((q) => (q.second ? q.options.cache !== false : !q.options.cache))) fail("cache options");

  const statuses = await page.$$eval("#claims .claim", (items) => items.map((li) =>
    li.querySelector(".claim-id").textContent + " " + li.querySelector(".pill").textContent));
  for (const want of ["C004 GREEN", "C005 RED", "C010 YELLOW", "C001 GREY"]) if (!statuses.includes(want)) fail("missing " + want + " in " + statuses.join(", "));
  if (!(await page.locator("#example-banner").isHidden())) fail("the example banner is still shown");
  if (shots) await page.screenshot({ path: path.join(shots, "3-results.png"), fullPage: true });

  for (const button of await page.locator("[data-save]").all()) await button.click();
  const saved = await page.evaluate(() => window.__saved);
  const names = saved.map((s) => s.filename).sort();
  if (JSON.stringify(names) !== JSON.stringify(["claims_sample_claims.json", "claims_sample_claims.xlsx", "claims_sample_claims_comments.docx"])) fail("saved: " + names);
  if (saved.some((s) => s.bytes < 1000)) fail("a saved file is empty");

  if (shots) {
    await page.setViewportSize({ width: 400, height: 900 });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({ path: path.join(shots, "4-phone-dark.png") });
    await page.locator("#results-card").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(shots, "5-phone-results.png") });
    const wide = await page.evaluate(() => {
      const width = document.documentElement.clientWidth;
      return [...document.querySelectorAll("body *")].filter((el) => !el.closest(".table-wrap") && el.getBoundingClientRect().right > width + 1)
        .slice(0, 5).map((el) => `${el.tagName.toLowerCase()}#${el.id}.${el.className} (${Math.round(el.getBoundingClientRect().right)} px)`);
    });
    if (wide.length) fail("the page scrolls sideways at phone width: " + wide.join(", "));
  }
  console.log(process.exitCode ? "claude page test FAILED" : `claude page test passed: ${questions.length} questions, ${saved.length} files saved`);
  await browser.close();
  server.close();
})().catch((e) => { console.error(e); process.exitCode = 1; server.close(); });
