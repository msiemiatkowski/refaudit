"""Part 2, step 2: the text of each cited source.

Tried in order: your own files (--sources), an open-access copy found through Unpaywall, OpenAlex, Europe PMC
or Semantic Scholar, and finally the abstract. Only identifiers (DOIs) go to these services, never manuscript
text. Each source's text is cached as JSON (pages, page labels, version, origin, sha256) in texts/.
"""

from __future__ import annotations

import glob
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

from .fuzzy import partial_ratio

from .claims import surname_key
from .compare import clean, norm
from .lookup import CROSSREF, OPENALEX, ApiError, Client, Refused

UNPAYWALL = "https://api.unpaywall.org/v2"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
S2 = "https://api.semanticscholar.org/graph/v1/paper"
SERVICES = ("Crossref", "OpenAlex", "Unpaywall", "Europe PMC", "Semantic Scholar", "Download")
FILE_TYPES = {".pdf", ".epub", ".docx", ".html", ".htm", ".txt"}
VERSIONS = {"publishedVersion": "published", "acceptedVersion": "accepted", "submittedVersion": "preprint"}
VERSION_RANK = {"published": 0, "accepted": 1, "unknown": 2, "preprint": 3}
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)
# Not "submitted to": Frontiers prints "This article was submitted to <section>" on published articles.
PREPRINT_MARKS = re.compile(r"\b(preprint|psyarxiv|arxiv|biorxiv|medrxiv|socarxiv|not (?:yet )?(?:been )?peer[- ]reviewed|"
                            r"manuscript submitted|submitted for publication|under review)\b", re.I)
# Not a bare "Accepted:" date, which published articles print too.
ACCEPTED_MARKS = re.compile(r"\b(accepted (?:author )?manuscript|author accepted|(?:has been|was) accepted for "
                            r"publication|accepted for publication in|post-?print|peer[- ]reviewed version)\b", re.I)


# --- reading files -------------------------------------------------------------

def page(text: str, pdf: int | None = None, label: str | None = None, ocr: bool = False) -> dict:
    return {"pdf": pdf, "label": label, "text": text, "ocr": ocr}


def read_file(path) -> dict:
    """{"kind", "pages": [{"pdf", "label", "text", "ocr"}], "meta"} for a PDF, EPUB, DOCX, HTML or TXT file."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".epub":
        return read_epub(path)
    if suffix == ".docx":
        return read_docx_text(path)
    if suffix in (".html", ".htm"):
        return {"kind": "html", "pages": html_sections(path.read_text(encoding="utf-8", errors="replace")), "meta": {}}
    return {"kind": "txt", "pages": [page(path.read_text(encoding="utf-8", errors="replace"), label="text")],
            "meta": {}}


def read_pdf(path) -> dict:
    """Pages from `pdftotext -layout` (pypdf if poppler is missing), OCR for pages without text, page labels."""
    texts, how = _pdftotext(path), "pdftotext -layout"
    if texts is None:
        texts, how = _pypdf_pages(path), "pypdf"
    can_ocr = bool(shutil.which("tesseract") and shutil.which("pdftoppm"))
    pages, layout = [], []
    for i, text in enumerate(texts, 1):
        ocr = False
        if len(text.strip()) < 25 and can_ocr:
            text, ocr = _ocr(path, i), True
        layout.append(text)
        pages.append(page(_decolumn(text), pdf=i, ocr=ocr))
    # Headers and footers are searched before the columns are split, which would cut a running head in two.
    stored, detected = _pdf_page_labels(path, len(pages)), detect_labels(layout)
    if stored == [str(i) for i in range(1, len(pages) + 1)] and any(detected):
        stored = None  # a default 1..N /PageLabels says nothing about the printed numbers (Cambridge, Wiley)
    labels = stored or detected
    for p, label in zip(pages, labels):
        p["label"] = label
    meta = _pdf_meta(path)
    meta["extraction"] = how + (" + OCR" if any(p["ocr"] for p in pages) else "")
    if not any(p["text"].strip() for p in pages):
        meta["problem"] = "no text layer" + ("" if can_ocr else " and OCR (tesseract) is not installed")
    return {"kind": "pdf", "pages": pages, "meta": meta}


def _pdftotext(path) -> list[str] | None:
    if not shutil.which("pdftotext"):
        return None
    try:
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True,
                             timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    pages = out.stdout.decode("utf-8", "replace").split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def _pypdf_pages(path) -> list[str]:
    from pypdf import PdfReader
    return [(p.extract_text() or "") for p in PdfReader(str(path)).pages]


def _ocr(path, number: int) -> str:
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout.split()
    lang = "+".join(lang for lang in ("eng", "pol") if lang in langs) or "eng"
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "300", "-f", str(number), "-l", str(number), "-png", str(path),
                        f"{tmp}/page"], capture_output=True, timeout=300)
        images = sorted(glob.glob(f"{tmp}/page*.png"))
        if not images:
            return ""
        out = subprocess.run(["tesseract", images[0], "stdout", "-l", lang], capture_output=True, timeout=300)
        return out.stdout.decode("utf-8", "replace")


def _decolumn(text: str) -> str:
    """`pdftotext -layout` prints two columns side by side; put the left column before the right one."""
    lines = text.split("\n")
    content = [line for line in lines if line.strip()]
    if len(content) < 8:
        return text
    width = max(len(line) for line in content)
    share = [sum(x >= len(line) or line[x] == " " for line in content) / len(content) for x in range(width)]
    best, run = None, None
    for x in range(int(width * 0.3), int(width * 0.7) + 1):
        if x < int(width * 0.7) and share[x] >= 0.75:
            run = x if run is None else run
        elif run is not None:
            if best is None or x - run > best[1] - best[0]:
                best = (run, x)
            run = None
    if not best or best[1] - best[0] < 2:
        return text
    cut = (best[0] + best[1]) // 2
    left, right = [], []
    for line in lines:
        if len(line) > cut and line[cut] != " " and line[cut - 1] != " ":  # a full-width line (title, table)
            left.append(line.strip())
        else:
            left.append(line[:cut].strip())
            right.append(line[cut:].strip())
    return "\n".join(left + [""] + right)


def detect_labels(texts: list[str]) -> list[str | None]:
    """Printed page numbers: the offset (printed - PDF page) that most pages' headers or footers agree on."""
    votes = Counter()
    for i, text in enumerate(texts, 1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        numbers = {int(n) for line in lines[:3] + lines[-3:] for n in re.findall(r"(?:^|\s)(\d{1,5})(?=\s|$)", line)}
        for n in numbers:
            votes[n - i] += 1
    if not votes:
        return [None] * len(texts)
    offset, count = votes.most_common(1)[0]
    if count < max(2, 0.4 * len(texts)) or offset < 0:
        return [None] * len(texts)
    return [str(i + offset) for i in range(1, len(texts) + 1)]


def _pdf_page_labels(path, count: int) -> list[str] | None:
    """Page labels stored in the PDF itself (/PageLabels), if any."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if "/PageLabels" not in reader.trailer["/Root"]:
            return None
        labels = list(reader.page_labels)
        return labels if len(labels) == count else None
    except Exception:
        return None


def _pdf_meta(path) -> dict:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        info = reader.metadata or {}
        text = " ".join(str(v) for v in info.values())
        try:
            xmp = reader.trailer["/Root"]["/Metadata"].get_object().get_data().decode("utf-8", "replace")
        except Exception:
            xmp = ""
        dois = DOI_RE.findall(text + " " + xmp)
        return {"title": str(info.get("/Title") or ""), "dois": [_doi(d) for d in dois]}
    except Exception:
        return {}


def _doi(text: str) -> str:
    return text.rstrip(".,;)]}'\"").lower()


class _HTMLText(HTMLParser):
    """Visible text of an HTML page, split into sections at h1-h3 headings."""
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form", "button"}
    BLOCKS = {"p", "div", "li", "br", "tr", "section", "article", "blockquote", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections, self.skip, self.heading = [["", []]], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("h1", "h2", "h3") and not self.skip:
            self.heading = []
        elif tag in self.BLOCKS:
            self.sections[-1][1].append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(self.skip - 1, 0)
        elif tag in ("h1", "h2", "h3") and self.heading is not None:
            self.sections.append([" ".join("".join(self.heading).split()), []])
            self.heading = None
        elif tag in self.BLOCKS:
            self.sections[-1][1].append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        (self.heading if self.heading is not None else self.sections[-1][1]).append(data)


def html_sections(markup: str) -> list[dict]:
    parser = _HTMLText()
    parser.feed(markup)
    pages = []
    for label, parts in parser.sections:
        text = re.sub(r"[ \t]+", " ", "".join(parts))
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        if text:
            pages.append(page(text, label=label or "text"))
    return pages


def read_epub(path) -> dict:
    """Chapters in reading order, labelled with their first heading."""
    with zipfile.ZipFile(path) as z:
        container = ElementTree.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//{*}rootfile").get("full-path")
        opf = ElementTree.fromstring(z.read(opf_path))
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        manifest = {item.get("id"): item.get("href") for item in opf.iterfind(".//{*}item")}
        pages = []
        for ref in opf.iterfind(".//{*}itemref"):
            href = manifest.get(ref.get("idref"))
            if not href:
                continue
            sections = html_sections(z.read(base + href).decode("utf-8", "replace"))
            text = "\n\n".join(s["text"] for s in sections)
            label = next((s["label"] for s in sections if s["label"] != "text"), Path(href).stem)
            if text.strip():
                pages.append(page(text, label=label))
        title = next((t.text for t in opf.iter("{http://purl.org/dc/elements/1.1/}title")), "")
    return {"kind": "epub", "pages": pages, "meta": {"title": title or ""}}


def read_docx_text(path) -> dict:
    """A .docx source, split into sections at its headings."""
    import docx
    from .parse import _docx_paragraphs
    pages = [page("", label="text")]
    for text, _, heading in _docx_paragraphs(docx.Document(path)):
        if heading and text:
            pages.append(page("", label=text))
        elif text:
            pages[-1]["text"] += text + "\n\n"
    return {"kind": "docx", "pages": [p for p in pages if p["text"].strip()], "meta": {}}


def read_jats(xml_text: str) -> dict:
    """Europe PMC full-text XML (JATS): a title page (title, authors, abstract), then sections labelled with titles."""
    root = ElementTree.fromstring(xml_text)
    pages = []

    def walk(sec, prefix=""):
        title = " ".join("".join(sec.findtext("title") or "").split())
        label = f"{prefix} > {title}" if prefix and title else title or prefix or "text"
        paragraphs = [_jats_text(p) for p in sec.findall("p")]
        if any(paragraphs):
            pages.append(page("\n\n".join(p for p in paragraphs if p), label=label))
        for child in sec.findall("sec"):
            walk(child, label)

    body = root.find(".//body")
    if body is not None:
        intro = [_jats_text(p) for p in body.findall("p")]
        if any(intro):
            pages.append(page("\n\n".join(intro), label="text"))
        for sec in body.findall("sec"):
            walk(sec)
    abstract = " ".join(_jats_text(p) for a in root.iter("abstract") for p in a.iter("p"))
    meta = root.find(".//article-meta")
    meta = meta if meta is not None else root
    title_el = meta.find(".//article-title")
    title = _jats_text(title_el) if title_el is not None else ""
    authors = []
    for group in meta.iterfind(".//contrib-group"):  # authors, not editors or reviewers
        for contrib in group.iterfind("contrib") if (group.get("content-type") or "author") == "author" else []:
            name = contrib.find("name")
            if name is not None and (contrib.get("contrib-type") or "author") == "author":
                authors.append(" ".join(x for x in (name.findtext("given-names"), name.findtext("surname")) if x))
    front = "\n\n".join(x for x in (title, ", ".join(authors), abstract) if x)
    if front:  # the title page: what the identity check and the judges look for first
        pages.insert(0, page(front, label="Title and abstract"))
    return {"kind": "jats", "pages": pages, "meta": {"title": title, "abstract": abstract}}


def _jats_text(element) -> str:
    return " ".join("".join(element.itertext()).split())


def version_of(doc: dict) -> str:
    first = " ".join(p["text"] for p in doc["pages"][:2])[:6000]
    if PREPRINT_MARKS.search(first):
        return "preprint"
    if ACCEPTED_MARKS.search(first):
        return "accepted"
    return "published"


# --- matching your files to references ---------------------------------------------

def scan(folder) -> list[dict]:
    """Every readable file in the folder: {path, doc, first (text of the first pages), supp, error}."""
    files = []
    for path in sorted(Path(folder).resolve().rglob("*")) if folder else []:
        if not path.is_file() or path.suffix.lower() not in FILE_TYPES:
            continue
        entry = {"path": str(path), "supp": "supp" in path.name.lower(), "size": path.stat().st_size,
                 "mtime": int(path.stat().st_mtime)}
        try:
            entry["doc"] = read_file(path)
            entry["first"] = " ".join(p["text"] for p in entry["doc"]["pages"][:2])
        except Exception as exc:  # one unreadable file never stops the run
            entry["error"] = f"could not read: {type(exc).__name__}: {exc}"
            entry["first"] = ""
        files.append(entry)
    return files


def match_file(entry: dict, refs: list[dict]) -> tuple[str | None, str]:
    """(reference key, how): a DOI in the file, else the title on its first page, else an AuthorYear file name."""
    meta = (entry.get("doc") or {}).get("meta", {})
    found = {_doi(d) for d in DOI_RE.findall(entry.get("first", "")[:20000])} | set(meta.get("dois", []))
    for ref in refs:
        if ref.get("doi") and ref["doi"].lower() in found:
            return ref["key"], "DOI in the file"
    first = norm(entry.get("first", "")[:8000])
    scored = [(partial_ratio(norm(ref["title"]), first), ref) for ref in refs if ref.get("title") and first]
    if scored:
        score, ref = max(scored, key=lambda pair: pair[0])
        if score >= 90:
            return ref["key"], f"title on the first page (similarity {round(score)})"
    stem = surname_key(Path(entry["path"]).stem.replace("_", " ").replace("-", " ")) + " "
    digits = re.findall(r"\d{4}", Path(entry["path"]).stem)
    named = [ref for ref in refs if ref["authors"] and surname_key(ref["authors"][0]) in stem
             and (ref.get("year") or "")[:4] in digits]
    if len(named) == 1:
        return named[0]["key"], "AuthorYear file name"
    return None, "no reference matched"


def identity(doc: dict, ref: dict) -> tuple[bool, str]:
    """The text belongs to the reference: its title (fuzzy >= 85) and first author appear on the first pages."""
    first = " ".join(p["text"] for p in doc["pages"][:2])[:12000]
    title = round(partial_ratio(norm(ref.get("title") or ""), norm(first))) if ref.get("title") else 0
    author = bool(ref["authors"]) and surname_key(ref["authors"][0]) in surname_key(first)
    ok = title >= 85 and author
    return ok, f"title similarity {title}; first author {'found' if author else 'not found'} on the first pages"


# --- open-access copies and abstracts ------------------------------------------------

def _get(client: Client, service: str, url: str, params: dict | None, notes: list[str]):
    try:
        return client.get(service, url, params)
    except Refused:
        return None
    except ApiError as exc:
        notes.append(f"{service}: {exc}")
        return None


def open_access(client: Client, doi: str, mailto: str | None, notes: list[str]) -> tuple[list[dict], dict]:
    """Candidate open-access copies (best version first) and abstracts, from the four services."""
    candidates, abstracts = [], {}
    path = quote(doi, safe="/")
    if mailto:
        data = _get(client, "Unpaywall", f"{UNPAYWALL}/{path}", None, notes) or {}  # the client adds the email
        for loc in data.get("oa_locations") or []:
            if loc.get("url_for_pdf"):
                candidates.append({"url": loc["url_for_pdf"], "version": VERSIONS.get(loc.get("version"), "unknown"),
                                   "via": f"Unpaywall ({loc.get('host_type') or 'location'})",
                                   "license": loc.get("license")})
    else:
        notes.append("Unpaywall skipped: REFAUDIT_MAILTO is not set")
    data = _get(client, "OpenAlex", f"{OPENALEX}/works/doi:{path}",
                {"select": "best_oa_location,open_access,locations,abstract_inverted_index"}, notes) or {}
    for loc in [data.get("best_oa_location") or {}] + list(data.get("locations") or []):
        if loc.get("pdf_url"):
            source = (loc.get("source") or {}).get("display_name") or "location"
            candidates.append({"url": loc["pdf_url"], "version": VERSIONS.get(loc.get("version"), "unknown"),
                               "via": f"OpenAlex ({source})", "license": loc.get("license")})
    oa_url = (data.get("open_access") or {}).get("oa_url")
    if oa_url and oa_url.lower().endswith(".pdf"):
        candidates.append({"url": oa_url, "version": "unknown", "via": "OpenAlex (oa_url)", "license": None})
    if data.get("abstract_inverted_index"):
        abstracts["OpenAlex"] = _inverted(data["abstract_inverted_index"])
    found = _get(client, "Europe PMC", f"{EUROPEPMC}/search",
                 {"query": f'DOI:"{doi}"', "format": "json", "resultType": "core"}, notes) or {}
    for hit in ((found.get("resultList") or {}).get("result") or [])[:1]:
        if hit.get("pmcid") and hit.get("isOpenAccess") == "Y":
            candidates.append({"url": f"{EUROPEPMC}/{hit['pmcid']}/fullTextXML", "version": "published",
                               "via": f"Europe PMC ({hit['pmcid']})", "license": hit.get("license"), "jats": True})
    s2 = _get(client, "Semantic Scholar", f"{S2}/DOI:{path}", {"fields": "title,abstract,openAccessPdf"}, notes) or {}
    if (s2.get("openAccessPdf") or {}).get("url"):
        candidates.append({"url": s2["openAccessPdf"]["url"], "version": "unknown", "via": "Semantic Scholar",
                           "license": None})
    if s2.get("abstract"):
        abstracts["Semantic Scholar"] = s2["abstract"]
    work = _get(client, "Crossref", f"{CROSSREF}/works/{path}", None, notes) or {}
    if (work.get("message") or {}).get("abstract"):
        abstracts["Crossref"] = clean(work["message"]["abstract"])
    unique = list({c["url"]: c for c in reversed(candidates)}.values())[::-1]  # the first listing knows the version
    unique.sort(key=lambda c: (VERSION_RANK.get(c["version"], 2), bool(c.get("jats"))))  # paged PDFs before XML
    return unique, abstracts


def _inverted(index: dict) -> str:
    words = sorted((pos, word) for word, positions in index.items() for pos in positions)
    return " ".join(word for _, word in words)


def fetch(client: Client, candidate: dict) -> dict:
    """Download one candidate; a PDF or Europe PMC XML becomes a document, anything else raises."""
    got = client.download("Download", candidate["url"])
    if not got:
        raise ValueError("not found (404)")
    content, kind = got
    if candidate.get("jats"):
        return read_jats(content.decode("utf-8", "replace"))
    if not content.startswith(b"%PDF"):
        raise ValueError(f"not a PDF ({kind or 'unknown type'}); landing pages are not read")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(content)
        tmp.flush()
        return read_pdf(tmp.name)


# --- one source -------------------------------------------------------------------

def level_of(kind: str, version: str, full: bool, abstract: bool) -> str:
    if full:
        return "PREPRINT" if version == "preprint" else "WEB" if kind in ("web", "report") else "FULL"
    return "ABSTRACT" if abstract else "NONE"


def build_text(ref: dict, files: list[dict], client: Client | None, mailto: str | None) -> dict:
    """The best available text for one reference, with the reasons for anything discarded."""
    notes, discarded, chosen, origin, version = [], [], None, "", "unknown"
    for entry in (f for f in files if f.get("ref") == ref["key"] and not f["supp"] and f.get("doc")):
        ok, why = identity(entry["doc"], ref)
        if ok:
            chosen, origin, version = entry["doc"], f"file: {entry['path']}", version_of(entry["doc"])
            break
        discarded.append({"origin": entry["path"], "reason": f"identity check failed ({why})"})
    candidates, abstracts = [], {}
    if client is not None and ref.get("doi"):
        candidates, abstracts = open_access(client, ref["doi"], mailto, notes)
    for candidate in candidates if chosen is None else []:
        try:
            doc = fetch(client, candidate)
        except (ApiError, ValueError, OSError, ElementTree.ParseError) as exc:
            discarded.append({"origin": candidate["url"], "reason": str(exc)})
            continue
        if not any(p["text"].strip() for p in doc["pages"]):
            discarded.append({"origin": candidate["url"], "reason": doc["meta"].get("problem", "no text")})
            continue
        ok, why = identity(doc, ref)
        if not ok:
            discarded.append({"origin": candidate["url"], "reason": f"identity check failed ({why})"})
            continue
        chosen, origin = doc, f"{candidate['via']}: {candidate['url']}"
        version = candidate["version"] if candidate["version"] != "unknown" else version_of(doc)
        break
    abstract = next((abstracts[k] for k in ("OpenAlex", "Crossref", "Semantic Scholar") if abstracts.get(k)), "")
    abstract = abstract or (chosen or {}).get("meta", {}).get("abstract", "")
    supplements = [{"origin": f["path"], "pages": f["doc"]["pages"]} for f in files
                   if f.get("ref") == ref["key"] and f["supp"] and f.get("doc")]
    full = chosen is not None and any(p["text"].strip() for p in chosen["pages"])
    level = level_of(ref.get("kind", ""), version, full, bool(abstract))
    reason = "" if full else ((chosen or {}).get("meta", {}).get("problem")
                              or ("no DOI, so no open-access lookup" if not ref.get("doi") else
                                  "no open-access copy and no file of yours"))
    pages = chosen["pages"] if full else []
    digest = hashlib.sha256(json.dumps([pages, supplements, abstract], ensure_ascii=False).encode()).hexdigest()
    return {"key": ref["key"], "level": level, "version": version if full else "", "origin": origin if full else
            (f"abstract: {next(k for k in ('OpenAlex', 'Crossref', 'Semantic Scholar') if abstracts.get(k))}"
             if abstracts else ""),
            "reason": reason, "extraction": (chosen or {}).get("meta", {}).get("extraction", ""),
            "identity": identity(chosen, ref)[1] if full else "", "pages": pages, "supplements": supplements,
            "abstract": abstract, "discarded": discarded, "notes": notes, "sha256": digest}


def render(text: dict) -> str:
    """The plain-text version judges read and search: one header per page or section."""
    out = [f"# {text['key']}: {text['level']} ({text['version'] or 'no full text'}) from {text['origin'] or 'nowhere'}"]
    if text["abstract"]:
        out += ["", "=== Abstract ===", text["abstract"]]
    for p in text["pages"]:
        out += ["", f"=== {where(p)} ===", p["text"].strip()]
    for supp in text["supplements"]:
        for p in supp["pages"]:
            out += ["", f"=== Supplement {Path(supp['origin']).name}, {where(p)} ===", p["text"].strip()]
    return "\n".join(out) + "\n"


def where(p: dict) -> str:
    """'PDF page 3, printed page 540' or 'section Results'."""
    if p.get("pdf") is None:
        return f"section {p.get('label') or 'text'}"
    return f"PDF page {p['pdf']}" + (f", printed page {p['label']}" if p.get("label") else "")
