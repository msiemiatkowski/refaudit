"""Read references from .docx and .bib files; tolerant APA 7 parser (with Polish 'W:', '(red.)', 's.')."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

HEADINGS = ("references", "reference list", "bibliography", "bibliografia", "literatura", "literatura cytowana")
HEADING_STYLES = ("heading", "title", "nagłówek", "tytuł")

YEAR_RE = re.compile(r"\(\s*((?:1[5-9]|20)\d\d[a-z]?|n\.\s?d\.|in press|w druku|b\.\s?d\.)(?:\s*,[^()]*)?\s*\)\.?", re.I)
LOOSE_YEAR_RE = re.compile(r"(?<![\d(])((?:1[5-9]|20)\d\d[a-z]?)(?!\d)")
DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*|\bdoi\s+)?10\.\d{4,9}/[^\s\"<>]+", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)
RETRIEVED_RE = re.compile(r"\b(?:Retrieved|Accessed|Pobrano|Dostęp)\b", re.I)
PAGES = r"(?:(?:Article|Art\.|Artykuł|pp?\.|ss?\.)\s*)?[A-Za-z]{0,4}\d+[A-Za-z]?(?:\s*[-–—‐‑]\s*[A-Za-z]{0,4}\d+[A-Za-z]?)?"
ARTICLE_TAIL = re.compile(
    rf",\s*(?P<volume>\d+[A-Za-z]?)\s*(?:\((?P<issue>[^()]+)\))?(?:\s*,\s*(?P<pages>{PAGES}))?\s*\.?\s*$")
ONLINE_FIRST_RE = re.compile(r"[\s.]*(?:Advance online publication|Online first|Epub ahead of print)\.?\s*$", re.I)
CHAPTER_RE = re.compile(r"(?<=[.?!])\s+(?:In|W):?\s+")
EDITORS_RE = re.compile(r"\((?:Eds?|Ed|red|Red|Hrsg|Hg)\.?\)\s*,?\s*")
CHAPTER_PAGES_RE = re.compile(r"\((?:[^()]*,\s*)?(?:pp?|ss?)\.\s*\d")
THESIS_RE = re.compile(r"\[[^\]]*(?:dissertation|thesis|praca doktorska|rozprawa doktorska|praca magisterska)[^\]]*\]", re.I)
REPORT_RE = re.compile(r"\b(?:report|raport|working paper|policy brief)\b", re.I)
EDITION_RE = re.compile(r"\s*\([^()]*\b(?:ed|eds|Vol|wyd|t)\.[^()]*\)\s*\.?$", re.I)
ABBREVIATIONS = {"vs", "ed", "eds", "vol", "no", "nr", "pp", "p", "st", "dr", "red", "wyd", "t", "s", "ss",
                 "np", "tzw", "e.g", "i.e", "cz", "jr", "sr"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
BIB_KINDS = {"article": "article", "inproceedings": "article", "conference": "article", "book": "book",
             "inbook": "chapter", "incollection": "chapter", "techreport": "report", "report": "report",
             "phdthesis": "thesis", "mastersthesis": "thesis", "thesis": "thesis", "online": "web"}


@dataclass
class Person:
    surname: str
    initials: str = ""  # as cited, e.g. "K. M."
    given: str = ""     # full given names, when known

    def __str__(self):
        first = self.given or self.initials
        return f"{self.surname}, {first}" if first else self.surname


@dataclass
class Reference:
    raw: str
    kind: str = "other"  # article, book, chapter, report, thesis, web, other
    authors: list[Person] = field(default_factory=list)
    truncated: bool = False  # author list shortened with an ellipsis (APA 7, 21+ authors)
    year: str | None = None  # "2017", "2026a", "in press", "n.d."
    title: str | None = None
    source: str | None = None  # journal, or the book title of a chapter
    editors: list[Person] = field(default_factory=list)
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None  # page range or article number
    doi: str | None = None
    doi_written: str | None = None  # the DOI as written (None for .bib, where bare DOIs are normal)
    url: str | None = None
    error: str | None = None  # the entry could not be read


def read_references(path, heading=None) -> list[Reference]:
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return read_docx(path, heading)
    if path.suffix.lower() == ".bib":
        return read_bib(path)
    raise ValueError(f"unsupported file type '{path.suffix}': use .docx or .bib")


# --- .docx -----------------------------------------------------------------

def read_docx(path, heading=None) -> list[Reference]:
    """References are the non-empty paragraphs after the reference heading, up to the next heading."""
    import docx

    wanted = {heading.strip().casefold()} if heading else set(HEADINGS)
    paragraphs = list(_docx_paragraphs(docx.Document(path)))
    starts = [i for i, p in enumerate(paragraphs) if p and p[0].strip().rstrip(":").strip().casefold() in wanted]
    if not starts:
        raise ValueError(f"no reference heading found in {Path(path).name} (looked for: {', '.join(sorted(wanted))})")
    refs = []
    for p in paragraphs[starts[-1] + 1:]:
        if p is None or p[2]:  # a table or the next heading
            break
        if p[0]:
            try:
                refs.append(parse_apa(p[0], p[1]))
            except Exception as exc:  # never lose a reference
                refs.append(Reference(raw=p[0], error=f"could not parse: {exc}"))
    return refs


def _docx_paragraphs(doc):
    """Yield (text, italic mask, is_heading) per body paragraph, or None for a table."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.text.run import Run

    w_p, w_tbl, w_r, w_t = qn("w:p"), qn("w:tbl"), qn("w:r"), qn("w:t")
    spaces = {qn("w:tab"), qn("w:br"), qn("w:cr")}
    for el in doc.element.body.iter(w_p, w_tbl):
        if el.tag == w_tbl:
            yield None
            continue
        if any(True for _ in el.iterancestors(w_tbl, qn("w:txbxContent"))):
            continue
        para = Paragraph(el, doc)
        chars, mask, bold = [], [], []
        for r in el.iter(w_r):  # also finds runs inside hyperlinks, fields and content controls
            if next(r.iterancestors(w_p)) is not el:
                continue
            run = Run(r, para)
            italic = _flag(run, "italic")
            text = "".join((c.text or "") if c.tag == w_t else " " for c in r if c.tag == w_t or c.tag in spaces)
            for ch in text:
                if ch.isspace():
                    if not chars or chars[-1] == " ":
                        continue
                    ch = " "
                chars.append(ch)
                mask.append(italic)
            if text.strip():
                bold.append(_flag(run, "bold"))
        while chars and chars[-1] == " ":
            chars.pop()
            mask.pop()
        text = "".join(chars)
        style = (para.style.name if para.style is not None else "").casefold()
        outline = el.find(f"{qn('w:pPr')}/{qn('w:outlineLvl')}")
        is_heading = (style.startswith(HEADING_STYLES) or (outline is not None and outline.get(qn("w:val")) != "9")
                      or (bool(bold) and all(bold) and len(text) <= 100))
        yield text, mask[:len(text)], is_heading


def _flag(run, name) -> bool:
    value = getattr(run.font, name)
    if value is None and run.style is not None:
        value = getattr(run.style.font, name)
    return bool(value)


# --- APA 7 -----------------------------------------------------------------

def _trim(text: str) -> str:
    """Strip trailing punctuation and unbalanced closing brackets from a DOI or URL."""
    while text and (text[-1] in ".,;:'\"" or (text[-1] == ")" and text.count(")") > text.count("("))
                    or (text[-1] == "]" and text.count("]") > text.count("["))):
        text = text[:-1]
    return text


def clean_doi(text) -> str | None:
    m = re.search(r"10\.\d{4,9}/\S+", unquote(str(text or "")))
    return _trim(m.group()).lower() if m else None


def _is_initials(token: str) -> bool:
    """'K. M.', 'J.-P.', 'Th.', 'KM'."""
    parts = [p for p in re.split(r"[.\s\-‐]+", token) if p]
    if not parts or len(parts) > 4 or token.strip(". ").casefold() in SUFFIXES:
        return False
    if "." not in token:
        return len(token) <= 3 and token.isalpha() and token.isupper()
    return all(p[0].isupper() and len(p) <= 2 and (len(p) == 1 or p[1:].islower()) for p in parts)


def parse_authors(text: str) -> tuple[list[Person], bool]:
    """'Douglas, K. M., Sutton, R. M., & Cichocka, A.' -> people; True if shortened with '...'."""
    truncated = bool(re.search(r"\.\s?\.\s?\.|…", text))
    text = re.sub(r"\.\s?\.\s?\.|…", ",", text)
    text = re.sub(r"\s*&\s*", ", ", text)
    text = re.sub(r"(?<=\.)\s*,?\s+(?:and|i)\s+", ", ", text)  # 'A. and Smith', Polish 'A. i Kowalski'
    text = re.sub(r",?\s*\bet al\.?", "", text)
    tokens = [t.strip().lstrip(". ") for t in text.split(",")]
    tokens = [t for t in tokens if t.strip(". ")]
    people, i = [], 0
    while i < len(tokens):
        if i + 1 < len(tokens) and _is_initials(tokens[i + 1]):
            people.append(Person(tokens[i], tokens[i + 1]))
            i += 2
            if i < len(tokens) and tokens[i].strip(". ").casefold() in SUFFIXES:
                i += 1
        else:  # group author, or a surname without initials
            people.append(Person(tokens[i].rstrip(". ")))
            i += 1
    return people, truncated


def parse_editors(text: str) -> list[Person]:
    """'D. Bulska, M. Winiewski i M. Bilewicz' -> people (also accepts 'Bulska, D., ...')."""
    text = text.strip(" ,")
    if re.match(r"[^\W\d_]{2,}[^,.]*,\s*[^\W\d_]{1,2}\.", text):
        return parse_authors(text)[0]
    people = []
    for item in re.split(r"\s*(?:,|&|\band\b|\bi\b)\s*", text):
        if item.strip():
            m = re.match(r"((?:[^\W\d_]{1,2}\.\s*-?\s*)+)(.+)", item.strip())
            people.append(Person(m.group(2).strip(), m.group(1).strip()) if m else Person(item.strip()))
    return people


def _sentence_ends(text: str):
    """Positions just after '.', '?' or '!' that end a sentence (outside brackets, not after an initial)."""
    depth = 0
    for i, c in enumerate(text):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(depth - 1, 0)
        elif c in ".?!" and depth == 0 and (i + 1 == len(text) or text[i + 1].isspace()):
            words = text[:i].split()
            word = words[-1] if words else ""
            if c == "." and (word.casefold().strip("(") in ABBREVIATIONS or re.fullmatch(r"(?:\w\.)*[A-ZÀ-Ž]", word)):
                continue
            yield i + 1


def _italic_start(mask: list[bool], pos: int) -> int | None:
    """Start of the italic run that ends at pos (APA italicizes 'Journal, Volume')."""
    i = min(pos, len(mask)) - 1
    while i >= 0 and not mask[i] and pos - i <= 2:
        i -= 1
    if i < 0 or not mask[i]:
        return None
    while i > 0 and mask[i - 1]:
        i -= 1
    return i


def _source_start(head: str) -> int:
    """Where the journal starts in 'Title. Journal' (without italics)."""
    if head.endswith("."):  # abbreviated journal: 'Title. J. Pers. Soc. Psychol.'
        words = list(re.finditer(r"\S+", head))
        k = len(words)
        while k and words[k - 1].group().endswith("."):
            k -= 1
        if not (k and words[k - 1].group().endswith(("?", "!"))):
            k += 1  # the first of the dotted words ends the title
        if k < len(words):
            return words[k].start()
    ends = [e for e in _sentence_ends(head) if e < len(head)]
    ends = ends or [m.end() for m in re.finditer(r"[.?!](?=\s)", head)]  # e.g. a title ending in 'U.S.'
    return ends[-1] if ends else 0


def parse_apa(text: str, italic: list[bool] | None = None) -> Reference:
    """Parse one APA 7 reference. `italic` marks italic characters (from .docx), if known."""
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    mask = list(italic[lead:lead + len(text)]) if italic else []
    mask += [False] * (len(text) - len(mask))
    ref = Reference(raw=text)

    numbered = re.match(r"(?:\[\d+\]|\d+\.)\s+", text)
    start = numbered.end() if numbered else 0
    doi = DOI_RE.search(text)
    if doi:
        ref.doi_written = _trim(doi.group())
        ref.doi = clean_doi(ref.doi_written)
    urls = [u for u in URL_RE.finditer(text) if not (doi and doi.start() <= u.start() < doi.end())]
    if urls:
        ref.url = _trim(urls[0].group())
    cuts = [m.start() for m in (doi, urls[0] if urls else None, RETRIEVED_RE.search(text, start)) if m]
    end = min(cuts) if cuts else len(text)

    year = YEAR_RE.search(text, start, end) or LOOSE_YEAR_RE.search(text, start, end)
    if year:
        ref.year = " ".join(year.group(1).split())
        ref.authors, ref.truncated = parse_authors(text[start:year.start()].strip(" ,("))
        start = year.end()
    rest, mask = text[start:end], mask[start:end]
    skip = len(rest) - len(rest.lstrip(" .,:)"))
    rest, mask = rest[skip:].rstrip(), mask[skip:]
    mask = mask[:len(rest)]
    _parse_rest(ref, rest, mask)
    return ref


def _parse_rest(ref: Reference, rest: str, mask: list[bool]) -> None:
    """Title, source, editors, publisher, volume, issue and pages from the part after the year."""
    thesis = THESIS_RE.search(rest)
    if thesis:
        ref.kind, ref.title = "thesis", rest[:thesis.start()].strip(" .") or None
        ref.publisher = (thesis.group()[1:-1].split(",", 1)[1:] or [""])[0].strip() or None
        return
    chapter = next((m for m in CHAPTER_RE.finditer(rest)
                    if EDITORS_RE.search(rest, m.end()) or CHAPTER_PAGES_RE.search(rest, m.end())), None)
    if chapter:
        ref.kind, ref.title = "chapter", rest[:chapter.start()].strip().rstrip(".") or None
        tail = rest[chapter.end():]
        editors = EDITORS_RE.search(tail)
        if editors:
            ref.editors, tail = parse_editors(tail[:editors.start()]), tail[editors.end():]
        info = re.search(r"\(([^()]*)\)", tail)
        if info and re.search(r"\b(?:pp?|ss?|Vol|t|tom)\.", info.group(1)):
            book, after = tail[:info.start()], tail[info.end():]
            pages = re.search(r"\b(?:pp?|ss?)\.\s*([^,;]+)", info.group(1))
            volume = re.search(r"\b(?:Vol|t|tom)\.\s*([^,;]+)", info.group(1))
            ref.pages = pages.group(1).strip() if pages else None
            ref.volume = volume.group(1).strip() if volume else None
        else:
            cut = next(_sentence_ends(tail), len(tail))
            book, after = tail[:cut], tail[cut:]
        ref.source = EDITION_RE.sub("", book.strip(" .,")).strip(" .,") or None
        ref.publisher = after.strip(" .,") or None
        return
    article = ARTICLE_TAIL.search(rest)
    online_first = None if article else ONLINE_FIRST_RE.search(rest)
    if article or online_first:
        head_end = (article or online_first).start()
        head = rest[:head_end]
        cut = _italic_start(mask, head_end) or _source_start(head)
        ref.kind, ref.title = "article", head[:cut].strip().rstrip(".").strip() or None
        ref.source = head[cut:].strip(" ,") or None
        if article:
            ref.volume, ref.issue, ref.pages = article["volume"], article["issue"], article["pages"]
        return
    # book, report or web page: "Title (2nd ed.). Publisher."
    if mask and mask[0] and not all(mask):
        cut = mask.index(False)
    else:
        cut = next(_sentence_ends(rest), len(rest))
    title, after = rest[:cut], rest[cut:]
    if any(mask[cut:]) and not any(mask[:cut]):  # italic source after a plain title: an article
        ref.kind, ref.title, ref.source = "article", title.strip().rstrip(".") or None, after.strip(" .,") or None
        return
    ref.title = EDITION_RE.sub("", title.strip()).strip().rstrip(".") or None
    ref.publisher = re.sub(r"^\s*\([^()]*\)", "", after).strip(" .,") or None
    ref.kind = "report" if REPORT_RE.search(rest) else "web" if ref.url and not ref.doi else "book"


# --- .bib ------------------------------------------------------------------

def read_bib(path) -> list[Reference]:
    import bibtexparser
    from bibtexparser.middlewares import LatexDecodingMiddleware, SeparateCoAuthors, SplitNameParts

    library = bibtexparser.parse_string(
        Path(path).read_text(encoding="utf-8"),
        append_middleware=[LatexDecodingMiddleware(keep_braced_groups=True), SeparateCoAuthors(), SplitNameParts()])
    refs = []
    for entry in library.entries:
        try:
            refs.append(_bib_reference(entry))
        except Exception as exc:  # never lose a reference
            refs.append(Reference(raw=f"@{entry.entry_type}{{{entry.key}, ...}}", error=f"could not read: {exc}"))
    for block in library.failed_blocks:
        refs.append(Reference(raw=" ".join(block.raw.split())[:300], error="could not parse this BibTeX entry"))
    return refs


def _bib_text(value) -> str | None:
    text = " ".join(str(value).replace("{", "").replace("}", "").split()) if value else ""
    return text or None


def _bib_people(value) -> list[Person]:
    people = []
    for name in value or []:
        if isinstance(name, str):
            people.append(Person(_bib_text(name) or ""))
            continue
        surname = _bib_text(" ".join(name.von + name.last)) or ""
        given = _bib_text(" ".join(name.first)) or ""
        initials = " ".join(f"{p[0]}." for p in re.split(r"[\s\-]+", given) if p)
        people.append(Person(surname, initials, given))
    return people


def _bib_reference(entry) -> Reference:
    f = {k.lower(): v.value for k, v in entry.fields_dict.items()}
    kind = BIB_KINDS.get(entry.entry_type.lower(), "other")
    if kind == "other" and f.get("url") and not f.get("doi"):
        kind = "web"
    ref = Reference(
        raw="", kind=kind, authors=_bib_people(f.get("author")), year=_bib_text(f.get("year")),
        title=_bib_text(f.get("title")), source=_bib_text(f.get("journal") or f.get("journaltitle") or f.get("booktitle")),
        editors=_bib_people(f.get("editor")), publisher=_bib_text(f.get("publisher") or f.get("institution") or f.get("school")),
        volume=_bib_text(f.get("volume")), issue=_bib_text(f.get("number") or f.get("issue")),
        pages=_bib_text(f.get("pages")), doi=clean_doi(f.get("doi")), url=_bib_text(f.get("url")))
    ref.raw = format_apa(ref)
    return ref


def format_apa(ref: Reference) -> str:
    """An APA-like rendering of a .bib entry, for the report and the Crossref query."""
    names = [str(Person(p.surname, p.initials)) for p in ref.authors]
    authors = names[0] if len(names) == 1 else ", ".join(names[:-1]) + ", & " + names[-1] if names else ""
    parts = [f"{authors} ({ref.year or 'n.d.'}).".strip(), f"{ref.title}." if ref.title else ""]
    if ref.kind == "chapter":
        editors = ", ".join(f"{p.initials} {p.surname}".strip() for p in ref.editors)
        pages = f" (pp. {ref.pages})" if ref.pages else ""
        parts.append(f"In {editors + ' (Eds.), ' if editors else ''}{ref.source or ''}{pages}.")
    elif ref.source:
        volume = f", {ref.volume}" if ref.volume else ""
        issue = f"({ref.issue})" if ref.issue else ""
        pages = f", {ref.pages}" if ref.pages else ""
        parts.append(f"{ref.source}{volume}{issue}{pages}.")
    if ref.publisher and ref.kind != "article":
        parts.append(f"{ref.publisher}.")
    if ref.doi or ref.url:
        parts.append(f"https://doi.org/{ref.doi}" if ref.doi else ref.url)
    return " ".join(p for p in parts if p)
