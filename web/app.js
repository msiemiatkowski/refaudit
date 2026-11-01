/* refaudit web app: choosing a file, options, progress and results. The checking runs in worker.js. */
"use strict";

const $ = (selector) => document.querySelector(selector);
const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const LABELS = {
  RED: "Retracted, wrong DOI or not found", PURPLE: "Expression of concern", ORANGE: "Mismatches",
  YELLOW: "Minor issues", GREEN: "Verified", GREY: "Not checked",
};
const FIELDS = [ // label, cited column, record column (names as in the report's Audit sheet)
  ["Authors", "Authors (cited)", "Authors (record)"],
  ["Year", "Year (cited)", "Year (record, issue)"],
  ["Title", "Title (cited)", "Title (record)"],
  ["Journal / book", "Journal (cited)", "Journal (record)"],
  ["Volume", "Volume (cited)", "Volume (record)"],
  ["Issue", "Issue (cited)", "Issue (record)"],
  ["Pages / article no.", "Pages / article no. (cited)", "Pages / article no. (record)"],
];

const state = { worker: null, ready: false, legend: null, file: null, running: false, result: null, report: null,
                fileName: "", filters: new Set() };

/* --- small helpers --- */

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null && value !== false) el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== "") el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

function paint(el, status) {
  const fill = state.legend && state.legend.fills[status];
  if (fill) {
    el.style.backgroundColor = `#${fill}`;
    el.classList.add("painted");
  }
  return el;
}

const pill = (status) => paint(h("span", { class: "pill", text: status }), status);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const size = (bytes) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB`
                                             : `${(bytes / 1024 / 1024).toFixed(1)} MB`);

const store = { // settings kept in this browser only
  get(key, fallback = "") {
    try { return localStorage.getItem(`refaudit.${key}`) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(`refaudit.${key}`, value); } catch { /* storage unavailable */ }
  },
};

function show(view) {
  $("#start").hidden = view !== "start";
  $("#progress").hidden = view !== "progress";
  $("#results").hidden = view !== "results";
}

function message(text, isError = false) {
  const box = $("#message");
  box.hidden = !text;
  box.textContent = text || "";
  box.classList.toggle("error", isError);
}

function runtime(text, stateName) {
  $("#runtime-text").textContent = text;
  $("#runtime").dataset.state = stateName;
}

/* --- the worker --- */

function startWorker() {
  state.ready = false;
  state.worker = new Worker("worker.js");
  state.worker.onmessage = ({ data }) => handlers[data.type] && handlers[data.type](data);
  state.worker.onerror = (event) => {
    event.preventDefault();
    handlers.fatal({ message: event.message || "it could not start" });
  };
  runtime("Preparing the checker…", "loading");
}

const handlers = {
  status({ text }) {
    runtime(text, "loading");
    if (state.running) $("#progress-text").textContent = `Waiting for the checker: ${text}`;
  },
  ready({ legend }) {
    state.ready = true;
    state.legend = legend;
    runtime("Ready. Checking takes about a second per reference.", "ready");
    $("#version").textContent = `refaudit ${legend.version} runs its Python code in your browser with Pyodide.`;
    renderLegend();
    if (state.running) $("#progress-text").textContent = "Reading the file and finding the references…";
  },
  fatal({ message: text }) {
    runtime(`The checker could not load (${text}). Check the internet connection and reload the page.`, "error");
    if (state.running) {
      state.running = false;
      show("start");
    }
  },
  progress({ n, total, text, status }) {
    const bar = $("#bar");
    bar.max = total;
    bar.value = n;
    $("#progress-title").textContent = `Checking ${plural(total, "reference")}…`;
    $("#progress-text").textContent = `${n} of ${total} checked. Last: ${text}`;
    $("#dots").append(paint(h("li", { title: `#${n}: ${status}` }), status));
  },
  done({ result, xlsx }) {
    state.running = false;
    state.result = result;
    state.report = new Blob([xlsx], { type: XLSX_TYPE });
    state.filters.clear();
    $("#search").value = "";
    renderResults();
    show("results");
    $("#results-title").focus();
  },
  error({ message: text }) {
    state.running = false;
    show("start");
    message(`The file could not be checked: ${text}`, true);
  },
};

/* --- choosing a file and checking it --- */

function choose(file) {
  if (!file) return;
  if (!/\.(docx|bib)$/i.test(file.name)) {
    message("Please choose a Word manuscript (.docx) or a BibTeX file (.bib).", true);
    return;
  }
  state.file = file;
  message("");
  $("#drop-title").textContent = file.name;
  $("#drop-hint").textContent = `${size(file.size)} · click or drop to choose another file`;
  $("#drop").classList.add("chosen");
  $("#check").disabled = false;
}

async function check() {
  if (!state.file || state.running) return;
  const options = {
    mailto: $("#mailto").value.trim(),
    openalex_key: $("#openalex-key").value.trim(),
    heading: $("#heading").value.trim(),
    limit: parseInt($("#limit").value, 10) || 0,
    use_openalex: $("#use-openalex").checked,
  };
  message("");
  state.running = true;
  state.fileName = state.file.name;
  $("#bar").removeAttribute("value");
  $("#dots").replaceChildren();
  $("#progress-title").textContent = "Checking references…";
  $("#progress-text").textContent = state.ready ? "Reading the file and finding the references…"
                                                : "Waiting for the checker to finish loading…";
  show("progress");
  const bytes = await state.file.arrayBuffer();
  state.worker.postMessage({ bytes, name: state.file.name, options }, [bytes]); // the worker waits until ready
}

function stop() {
  state.worker.terminate();
  state.running = false;
  startWorker();
  show("start");
  message("Stopped. Your file is still selected; press “Check references” to start again.");
}

function again() {
  state.file = null;
  $("#file").value = "";
  $("#drop-title").textContent = "Drop a manuscript (.docx) or a BibTeX file (.bib) here";
  $("#drop-hint").textContent = "or click to choose a file";
  $("#drop").classList.remove("chosen");
  $("#check").disabled = true;
  message("");
  show("start");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function download() {
  const link = h("a", { href: URL.createObjectURL(state.report),
                        download: `${state.fileName.replace(/\.[^.]+$/, "")}_refaudit.xlsx` });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
}

/* --- results --- */

function renderResults() {
  const { result, legend } = state;
  const column = Object.fromEntries(result.columns.map((name, i) => [name, i]));
  const cell = (row, name) => row[column[name]] || ["", null];
  const total = result.rows.length;
  $("#results-sub").textContent = `${state.fileName} · ${plural(total, "reference")} · ${new Date().toLocaleString()}`;
  $("#tiles").replaceChildren(...legend.order.map((status) => {
    const count = result.counts[status] || 0;
    const tile = h("button", { class: "tile", type: "button", "aria-pressed": "false", disabled: count === 0,
                               title: legend.meanings[status], onclick: () => toggle(status) },
                   h("span", { class: "count", text: count }), h("span", { class: "label", text: LABELS[status] }));
    tile.dataset.status = status;
    return paint(tile, status);
  }));
  $("#refs").replaceChildren(...result.rows.map((row) => renderReference(row, cell)));
  $("#sources").replaceChildren(h("tbody", {}, result.sources.map(([service, text]) =>
    h("tr", {}, h("th", { scope: "row", text: service }), h("td", { text })))));
  const failures = [...new Set(result.failures)];
  $("#failures").replaceChildren(...failures.map((text) => h("li", { text })));
  filter();
}

function renderReference(row, cell) {
  const [number] = cell(row, "#");
  const [status] = cell(row, "Status");
  const [text] = cell(row, "Reference as cited");
  const [problems] = cell(row, "Problems");
  const lines = (problems || "").split("\n").filter(Boolean);
  const item = h("li", { class: "ref" },
    h("div", { class: "ref-head" }, pill(status), h("span", { class: "ref-number", text: `#${number}` })),
    h("p", { class: "ref-text", text }),
    lines.length ? h("ul", { class: "problems" }, lines.map((line) => h("li", { text: line })))
                 : h("p", { class: "muted", text: status === "GREEN" ? "Everything matches the record." : "" }),
    renderComparison(row, cell));
  item.style.borderLeftColor = `#${state.legend.fills[status]}`;
  item.dataset.status = status;
  item.dataset.search = `${text}\n${problems || ""}`.toLowerCase();
  return item;
}

function renderComparison(row, cell) {
  const facts = h("dl", { class: "facts" });
  const fact = (term, value, status) => facts.append(h("dt", { text: term }), paintIf(h("dd", {}, value), status));
  const [doi, doiStatus] = cell(row, "Matched DOI");
  const [route, routeStatus] = cell(row, "Match route and confidence");
  const [notice, noticeStatus] = cell(row, "Notice");
  if (doi) {
    fact("Matched DOI", String(doi).startsWith("https://doi.org/")
      ? h("a", { href: doi, target: "_blank", rel: "noopener noreferrer", text: doi }) : doi, doiStatus);
  }
  if (route) fact("Match", route, routeStatus);
  if (notice) fact("Notice", notice, noticeStatus);
  const rows = FIELDS.flatMap(([label, citedColumn, recordColumn]) => {
    const [cited, status] = cell(row, citedColumn);
    let [record] = cell(row, recordColumn);
    if (label === "Year") {
      const [online] = cell(row, "Year (record, online)");
      if (online && String(online) !== String(record)) record = record ? `${record} (online ${online})` : `${online} (online)`;
    }
    if ((cited === null || cited === "") && (record === null || record === "")) return [];
    const recordCell = paintIf(h("td", { "data-label": "Record", text: record ?? "" }), status);
    if (label === "Title") {
      const [similarity] = cell(row, "Title similarity");
      if (similarity !== null && similarity !== "") recordCell.append(" ", h("span", { class: "similarity", text: `(similarity ${similarity})` }));
    }
    return [h("tr", {}, h("th", { scope: "row", text: label }),
                         paintIf(h("td", { "data-label": "Cited", text: cited ?? "" }), status), recordCell)];
  });
  const table = rows.length ? h("table", { class: "compare" },
    h("thead", {}, h("tr", {}, h("th", { text: "Field" }), h("th", { text: "In the reference" }), h("th", { text: "In the record" }))),
    h("tbody", {}, rows)) : null;
  if (!facts.children.length && !table) return null;
  const label = doi ? "Show the comparison with the record" : "Show the details";
  return h("details", {}, h("summary", { text: label }), facts.children.length ? facts : null, table);
}

function paintIf(el, status) {
  return status ? paint(el, status) : el;
}

function toggle(status) {
  if (state.filters.has(status)) state.filters.delete(status);
  else state.filters.add(status);
  filter();
}

function filter() {
  const query = $("#search").value.trim().toLowerCase();
  const items = [...$("#refs").children];
  let shown = 0;
  for (const item of items) {
    const visible = (!state.filters.size || state.filters.has(item.dataset.status)) && (!query || item.dataset.search.includes(query));
    item.hidden = !visible;
    shown += visible ? 1 : 0;
  }
  for (const tile of $("#tiles").children) tile.setAttribute("aria-pressed", String(state.filters.has(tile.dataset.status)));
  $("#tiles").classList.toggle("filtering", state.filters.size > 0);
  $("#shown").textContent = shown === items.length ? plural(items.length, "reference") : `${shown} of ${items.length} shown`;
}

function renderLegend() {
  const { order, meanings, fields, rules } = state.legend;
  const [head, ...body] = fields;
  const table = h("table", { class: "rules" },
    h("thead", {}, h("tr", {}, head.map((text, i) => (i ? paint(h("th", { text }), text) : h("th", { text }))))),
    h("tbody", {}, body.map((cells) => h("tr", {}, cells.map((text) => h("td", { text }))))));
  $("#legend-body").replaceChildren(
    h("div", { class: "legend-list" }, order.flatMap((status) => [pill(status), h("span", { text: meanings[status] })])),
    h("h3", { text: "Rules for each field" }), table,
    h("h3", { text: "How the references are checked" }), h("ul", {}, rules.map((text) => h("li", { text }))));
  $("#legend").hidden = false;
}

/* --- wiring --- */

function init() {
  for (const [id, key] of [["mailto", "mailto"], ["openalex-key", "openalexKey"]]) {
    const input = $(`#${id}`);
    input.value = store.get(key);
    input.addEventListener("change", () => store.set(key, input.value.trim()));
  }
  const useOpenAlex = $("#use-openalex");
  useOpenAlex.checked = store.get("useOpenAlex", "true") === "true";
  useOpenAlex.addEventListener("change", () => store.set("useOpenAlex", String(useOpenAlex.checked)));

  const drop = $("#drop");
  $("#file").addEventListener("change", (event) => choose(event.target.files[0]));
  for (const type of ["dragenter", "dragover"]) {
    drop.addEventListener(type, (event) => { event.preventDefault(); drop.classList.add("dragging"); });
  }
  for (const type of ["dragleave", "drop"]) {
    drop.addEventListener(type, () => drop.classList.remove("dragging"));
  }
  drop.addEventListener("drop", (event) => { event.preventDefault(); choose(event.dataTransfer.files[0]); });
  window.addEventListener("dragover", (event) => event.preventDefault()); // a file dropped elsewhere
  window.addEventListener("drop", (event) => event.preventDefault());     // is not opened by the browser

  $("#check").addEventListener("click", check);
  $("#stop").addEventListener("click", stop);
  $("#again").addEventListener("click", again);
  $("#download").addEventListener("click", download);
  $("#search").addEventListener("input", filter);
  $("#results-title").tabIndex = -1;
  startWorker();
}

init();
