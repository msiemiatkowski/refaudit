/* Runs refaudit (the Python package) in the browser with Pyodide, off the page's main thread.
   Messages in: {bytes, name, options}. Messages out: status, ready, fatal, progress, done, error. */
"use strict";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";
const MODULES = ["__init__.py", "cli.py", "compare.py", "lookup.py", "parse.py", "report.py", "web.py"];
const PACKAGES = ["python-docx==1.2.0", "openpyxl==3.1.5", "bibtexparser==2.1.0"]; // pure Python, from PyPI

importScripts(PYODIDE + "pyodide.js");

const status = (text) => postMessage({ type: "status", text });

const ready = (async () => {
  status("Downloading Python (about 15 MB on the first visit)…");
  const pyodide = await loadPyodide({ indexURL: PYODIDE });
  status("Loading the document readers…");
  await pyodide.loadPackage(["micropip", "lxml", "requests"]);
  await pyodide.pyimport("micropip").install(PACKAGES);
  status("Loading refaudit…");
  pyodide.FS.mkdirTree("/home/pyodide/refaudit");
  for (const name of MODULES) {
    const response = await fetch(`refaudit/${name}`);
    if (!response.ok) throw new Error(`refaudit/${name}: HTTP ${response.status}`);
    pyodide.FS.writeFile(`/home/pyodide/refaudit/${name}`, await response.text());
  }
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
  const web = pyodide.pyimport("refaudit.web");
  postMessage({ type: "ready", legend: JSON.parse(web.legend()) });
  return { pyodide, web };
})();
ready.catch((error) => postMessage({ type: "fatal", message: lastLine(error) }));

function lastLine(error) {
  // A Python error's message is its traceback; the last line says what went wrong.
  const lines = String(error && error.message ? error.message : error).trim().split("\n");
  return lines[lines.length - 1].replace(/^[\w.]*(Error|Exception|Refused): /, "");
}

onmessage = async ({ data }) => {
  let runtime;
  try {
    runtime = await ready;
  } catch {
    return; // "fatal" was already reported
  }
  const { pyodide, web } = runtime;
  try {
    const extension = (data.name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
    const input = `/tmp/input${extension}`;
    pyodide.FS.writeFile(input, new Uint8Array(data.bytes));
    const progress = (n, total, text, rowStatus) => postMessage({ type: "progress", n, total, text, status: rowStatus });
    const options = pyodide.toPy({ ...data.options, name: data.name });
    const result = JSON.parse(web.check(input, "/tmp/report.xlsx", options, progress));
    options.destroy();
    const xlsx = pyodide.FS.readFile("/tmp/report.xlsx");
    postMessage({ type: "done", result, xlsx }, [xlsx.buffer]);
  } catch (error) {
    postMessage({ type: "error", message: lastLine(error) });
  }
};
