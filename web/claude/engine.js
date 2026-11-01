/* The claim-check engine for the claude.ai page: refaudit's Python code, run with Pyodide in a Web Worker.

   The page cannot reach other hosts, so Pyodide and every package come from the page's own published files.
   claude.ai serves no .zip or .whl files, so each archive is published base64-encoded as "<name>.txt"; the fetch
   shim below answers Pyodide's request for the archive with the decoded bytes, and Pyodide checks each wheel
   against its lock file as usual.

   Messages in: {id, op, ...args}. Messages out: {type: "status", text} while starting, then {id, ok, result} or
   {id, ok: false, error} for each request. */
"use strict";

const realFetch = self.fetch.bind(self);
self.fetch = async (input, init) => {
  const url = new URL(input instanceof Request ? input.url : String(input), self.location.href);
  if (!/\.(zip|whl)$/.test(url.pathname)) return realFetch(input, init);
  const response = await realFetch(url.href + ".txt");
  if (!response.ok) return response;
  const text = (await response.text()).trim();
  const bytes = Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
  return new Response(bytes, { status: 200, headers: { "Content-Type": "application/zip" } });
};

const status = (text) => postMessage({ type: "status", text });
const lastLine = (error) => {
  const lines = String((error && error.message) || error).trim().split("\n");
  return lines[lines.length - 1].replace(/^[\w.]*(Error|Exception): /, "");
};

const ready = (async () => {
  status("Starting Python in your browser…");
  importScripts("pyodide/pyodide.js");
  const pyodide = await loadPyodide({ indexURL: new URL("pyodide/", self.location.href).href });
  status("Loading the document readers…");
  await pyodide.loadPackage(["lxml"]);
  const site = await fetch("py/site.zip");
  if (!site.ok) throw new Error(`py/site.zip: HTTP ${site.status}`);
  pyodide.unpackArchive(await site.arrayBuffer(), "zip", { extractDir: "/home/pyodide/site" });
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide/site')");
  status("Loading refaudit…");
  const web = pyodide.pyimport("refaudit.claims_web");
  return { pyodide, web, info: JSON.parse(web.info()) };
})();

function writeFiles(pyodide, folder, files) {
  const FS = pyodide.FS;
  if (FS.analyzePath(folder).exists) pyodide.runPython(`import shutil; shutil.rmtree(${JSON.stringify(folder)})`);
  FS.mkdirTree(folder);
  const paths = [];
  for (const file of files) {
    const name = file.name.replace(/[\\/]/g, "_");
    FS.writeFile(`${folder}/${name}`, new Uint8Array(file.bytes));
    paths.push(`${folder}/${name}`);
  }
  return paths;
}

const OPS = {
  boot: async ({ info }) => info,
  prepare: async ({ pyodide, web }, { manuscript, sources }) => {
    const [path] = writeFiles(pyodide, "/tmp/in/manuscript", [manuscript]);
    writeFiles(pyodide, "/tmp/in/sources", sources);
    return JSON.parse(web.prepare(path, sources.length ? "/tmp/in/sources" : null));
  },
  question: async ({ pyodide, web }, { refkey, ids, second, maxBytes }) => {
    const pyIds = pyodide.toPy(ids);
    try { return web.question(refkey, pyIds, Boolean(second), maxBytes); } finally { pyIds.destroy(); }
  },
  answer: async ({ web }, { refkey, reply, second, model }) => JSON.parse(web.answer(refkey, reply, Boolean(second), model || "")),
  noText: async ({ pyodide, web }, { refkey, ids }) => {
    const pyIds = pyodide.toPy(ids);
    try { return JSON.parse(web.no_text(refkey, pyIds)); } finally { pyIds.destroy(); }
  },
  verify: async ({ web }) => JSON.parse(web.verify()),
  report: async ({ pyodide, web }, { model, effort }) => {
    const result = JSON.parse(web.report(model || "", effort || ""));
    result.files = result.files.map((path) => ({ name: path.split("/").pop(), bytes: pyodide.FS.readFile(path).buffer }));
    return result;
  },
};

ready.then(() => postMessage({ type: "ready" }), (error) => postMessage({ type: "fatal", error: lastLine(error) }));

onmessage = async ({ data }) => {
  const { id, op, ...args } = data;
  let runtime;
  try {
    runtime = await ready;
  } catch (error) {
    postMessage({ id, ok: false, error: lastLine(error) });
    return;
  }
  try {
    const result = await OPS[op](runtime, args);
    const transfer = op === "report" ? result.files.map((f) => f.bytes) : [];
    postMessage({ id, ok: true, result }, transfer);
  } catch (error) {
    postMessage({ id, ok: false, error: lastLine(error) });
  }
};
