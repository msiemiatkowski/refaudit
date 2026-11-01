"""Part 2, step 1: the claims in a manuscript that carry citations.

Paragraphs (pandoc or python-docx) -> sentences -> APA in-text citations -> one row per citation
occurrence, matched to the manuscript's own reference list (read with part 1's parser).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field

from . import parse
from .compare import fold, norm

UPPER = "A-ZĄĆĘŁŃÓŚŹŻÀ-ÖØ-Þ"
YEAR = r"(?:\d{4}[a-z]?|in press(?:-[a-z])?|n\.\s?d\.(?:-[a-z])?|w druku(?:-[a-z])?|b\.\s?d\.(?:-[a-z])?)"
LOCATOR = r"(?:pp?|ss?)\.\s*[0-9ivxlc]+(?:\s*[-–—]\s*[0-9ivxlc]+)?"
PARTICLE = r"(?:van|von|de|der|den|du|da|di|la|le|ter|del)"
NAME = rf"(?:{PARTICLE}\s+(?:{PARTICLE}\s+)?)?[{UPPER}][\w'’\-]*(?:\s+{PARTICLE}\s+[{UPPER}][\w'’\-]*)?"
ET_AL = r"(?:et\s+al\.?|i\s+in\.?|i\s+współprac\w*)"
SEP = r"(?:\s*,\s*(?:&\s*|and\s+|i\s+)?|\s+(?:&|and|i)\s+)"
AUTHORS = rf"{NAME}(?:{SEP}{NAME})*(?:,?\s+{ET_AL})?"
NARRATIVE_RE = re.compile(rf"(?P<authors>{AUTHORS})(?:['’]s?)?\s+\((?P<years>{YEAR}(?:\s*,\s*{YEAR})*)"
                          rf"(?:\s*,\s*(?P<loc>{LOCATOR}))?\)")
GROUP_RE = re.compile(rf"\(([^()]*?\b{YEAR}[^()]*)\)")
PART_RE = re.compile(rf"^(?P<authors>.+?),\s*(?P<years>{YEAR}(?:\s*,\s*{YEAR})*)(?:\s*,\s*(?P<loc>{LOCATOR}))?[\s.]*$")
PREFIX_RE = re.compile(r"^(?:for (?:a )?reviews?,? see|see also|see|e\.\s?g\.,?|i\.\s?e\.,?|cf\.|compare|"
                       r"zob\. też|zob\.|por\.|np\.,?|za:?|więcej:?)\s+", re.I)
CITED_IN_RE = re.compile(r",?\s*(?:as cited in|cited in|cyt\. za|za:)\s+", re.I)
SENTENCE_END_RE = re.compile(rf"[()\[\]]|[.?!…]+[\"'”’»)\]]*(?=\s+[\"'“„«(\[]?[{UPPER}0-9])")
ABBREVIATIONS = {"al", "e.g", "i.e", "cf", "vs", "p", "pp", "vol", "no", "np", "tzn", "m.in", "zob", "por", "s", "r",
                 "ss", "fig", "eds", "ed", "red", "tj", "itd", "itp", "tzw", "dr", "prof", "st", "ok", "nr", "ch", "sec"}
QUOTE_RE = re.compile(r"[“\"„«]([^”\"«»“„]{12,}?)[”\"»]")
NUMBER_RE = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:[.,]\d+)?%?|(?<![\w.,])[.,]\d+")
NOT_NAMES = {  # capitalized words that start sentences, not author lists ("However, Douglas et al. (2017)")
    "however", "moreover", "furthermore", "additionally", "similarly", "indeed", "thus", "therefore", "hence", "also",
    "in", "for", "as", "according", "notably", "nevertheless", "yet", "but", "and", "then", "later", "first", "second",
    "finally", "recently", "earlier", "previously", "specifically", "importantly", "interestingly", "likewise",
    "consequently", "accordingly", "conversely", "instead", "still", "here", "there", "the", "a", "an", "this", "these",
    "those", "that", "their", "our", "we", "they", "both", "some", "many", "most", "several", "unlike", "like",
    "following", "jednak", "według", "zdaniem", "natomiast", "ponadto", "również", "także", "podobnie", "dlatego",
    "zatem", "wcześniej", "później", "następnie", "przykładowo", "wreszcie", "co", "jak", "w", "na", "za", "po", "dla",
    "ze", "z", "od", "do", "u", "oraz", "choć", "chociaż", "mimo", "gdy", "kiedy"}
CASE_ENDINGS = ("", "a", "u", "owi", "em", "e", "ie", "y", "ą", "ę", "i", "ego", "emu", "im", "iej", "ej", "ową",
                "owej", "ach", "om", "ami", "owie", "ów", "s")


@dataclass
class Cite:
    text: str                    # as written, e.g. "Douglas et al., 2017, p. 5"
    authors: list[str]           # surnames as written
    et_al: bool
    year: str                    # "2017", "2017a", "in press", "n.d."
    start: int                   # span of the citation (or its group) in the sentence
    end: int
    narrative: bool = False
    locator: str | None = None
    prefix: str | None = None
    original: str | None = None  # "Allport, 1954" in "Allport, 1954, as cited in Douglas et al., 2017"
    group: list[str] = field(default_factory=list)  # the other citations in the same parentheses


# --- manuscript text ---------------------------------------------------------

def has_tracked_changes(path) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    return bool(re.search(r"<w:(?:ins|del|moveFrom|moveTo)\b", xml))


def manuscript_paragraphs(path, heading=None) -> tuple[list[str], str]:
    """Non-empty paragraphs without the reference section, and the method used (pandoc or python-docx)."""
    if shutil.which("pandoc"):
        result = subprocess.run(["pandoc", "--track-changes=accept", "-t", "plain", "--wrap=none", str(path)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            paragraphs = [" ".join(block.split()) for block in re.split(r"\n\s*\n", result.stdout)]
            return _without_references(path, [p for p in paragraphs if p], heading), "pandoc"
    import docx
    paragraphs = [text for text, _, _ in parse._docx_paragraphs(docx.Document(path)) if text]
    return _without_references(path, paragraphs, heading), "python-docx"


def _without_references(path, paragraphs: list[str], heading=None) -> list[str]:
    """Drop the reference heading and the reference entries that follow it (part 1's heading logic)."""
    wanted = {parse._heading_key(heading)} if heading else set(parse.HEADINGS)
    starts = [i for i, p in enumerate(paragraphs) if parse._heading_key(p) in wanted]
    if not starts:
        return paragraphs
    entries = {norm(ref.raw)[:60] for ref in parse.read_docx(path, heading)}
    i = starts[-1] + 1
    while i < len(paragraphs) and norm(paragraphs[i])[:60] in entries:
        i += 1
    return paragraphs[:starts[-1]] + paragraphs[i:]


# --- sentences ---------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """Rule-based sentence splitting that knows English and Polish abbreviations and decimal numbers."""
    sentences, start, depth = [], 0, 0
    for m in SENTENCE_END_RE.finditer(text):
        token = m.group()
        if token in "([":
            depth += 1
            continue
        if token in ")]":
            depth = max(depth - 1, 0)
            continue
        if depth:
            continue
        words = text[start:m.start()].split()
        last = words[-1].lower() if words else ""
        if token.startswith(".") and (last in ABBREVIATIONS or (len(words) > 1 and f"{words[-2]} {last}".lower() == "i in")
                                      or re.fullmatch(rf"[{UPPER}]|(?:\w\.)+\w", words[-1] if words else "")):
            continue
        sentences.append(text[start:m.end()].strip())
        start = m.end()
    tail = text[start:].strip()
    return [s for s in sentences + [tail] if s]


# --- citations ---------------------------------------------------------------

def _authors(text: str) -> tuple[list[str], bool]:
    et_al = bool(re.search(rf"\b{ET_AL}\s*$", text))
    text = re.sub(rf",?\s*\b{ET_AL}\s*$", "", text)
    names = [re.sub(r"['’]s?$", "", n.strip()) for n in re.split(rf"{SEP}", text) if n and n.strip(" ,")]
    while len(names) > 1 and names[0].lower() in NOT_NAMES:
        names.pop(0)
    return names, et_al


def _years(text: str) -> list[str]:
    return [" ".join(y.split()) for y in re.findall(YEAR, text)]


def parse_group(content: str, start: int, end: int) -> list[Cite]:
    """The citations in one parenthetical group such as '(e.g., Douglas et al., 2017; Uscinski, 2019a, 2019b)'."""
    cites = []
    for part in re.split(r";\s*", content):
        part = part.strip()
        prefix = PREFIX_RE.match(part)
        if prefix:
            part = part[prefix.end():]
        original = None
        cited_in = CITED_IN_RE.search(part)
        if cited_in:
            original, part = part[:cited_in.start()].strip(" ,"), part[cited_in.end():]
        m = PART_RE.match(part.strip())
        if not m:
            continue
        authors, et_al = _authors(m["authors"].strip())
        if not authors or not re.match(rf"[{UPPER}]|{PARTICLE}\b", authors[0]):
            continue
        for year in _years(m["years"]):
            cites.append(Cite(text=part.strip(), authors=authors, et_al=et_al, year=year, start=start, end=end,
                              locator=m["loc"], prefix=prefix.group().strip() if prefix else None, original=original))
    for cite in cites:
        cite.group = list(dict.fromkeys(c.text for c in cites if c.text != cite.text))
    return cites


def find_citations(sentence: str) -> list[Cite]:
    """All parenthetical and narrative citations in a sentence, in order."""
    cites, taken = [], []
    for m in GROUP_RE.finditer(sentence):
        found = parse_group(m.group(1), m.start(), m.end())
        if found:
            cites += found
            taken.append((m.start(), m.end()))
    for m in NARRATIVE_RE.finditer(sentence):
        if any(a <= m.start("years") < b for a, b in taken):
            continue
        authors, et_al = _authors(m["authors"])
        text = m.group().strip()
        if len(authors) < len(re.split(rf"{SEP}", re.sub(rf",?\s*\b{ET_AL}\s*$", "", m["authors"]))):
            text = text[text.find(authors[0]):]  # without the sentence-opening word
        for year in _years(m["years"]):
            cites.append(Cite(text=text, authors=authors, et_al=et_al, year=year, start=m.start() + m.group().find(text),
                              end=m.end(), narrative=True, locator=m["loc"]))
    return sorted(cites, key=lambda c: (c.start, c.end))


# --- references and matching -------------------------------------------------

def surname_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", fold(name).lower())


def same_surname(cited: str, surname: str) -> bool:
    """Equal after folding; a Polish case ending is allowed ('Bilewicza' cites 'Bilewicz')."""
    c, s = surname_key(cited), surname_key(surname)
    if not c or not s:
        return False
    if c == s:
        return True
    words_c, words_s = norm(cited).split(), norm(surname).split()  # particles: 'van Prooijen' vs 'Prooijen'
    if words_c and words_s and surname_key(words_c[-1]) == surname_key(words_s[-1]):
        return True
    return any(c == s[:len(s) - k] + ending for k in (0, 1, 2) for ending in CASE_ENDINGS if len(s) - k >= 4)


def refkey(ref: parse.Reference, taken: set[str]) -> str:
    first = surname_key(ref.authors[0].surname)[:20] if ref.authors else "anon"
    year = re.sub(r"[^0-9a-z]", "", (ref.year or "nd").lower()) or "nd"
    key, n = f"{first}{year}", 1
    while key in taken:
        n += 1
        key = f"{first}{year}-{n}"
    taken.add(key)
    return key


def _year_parts(year: str | None) -> tuple[str, str]:
    """('2017', 'a'), ('inpress', ''), ('nd', 'b')."""
    y = re.sub(r"[\s.]", "", (year or "").lower()).replace("wdruku", "inpress").replace("bd", "nd")
    m = re.fullmatch(r"(\d{4}|inpress|nd)-?([a-z]?)", y)
    return (m.group(1), m.group(2)) if m else (y, "")


def match(cite: Cite, refs: list[dict]) -> tuple[str | None, str, str]:
    """(refkey, 'matched' | 'unmatched' | 'ambiguous', note): first-author surname, author count, year and letter."""
    year, letter = _year_parts(cite.year)
    same = [r for r in refs if r["authors"] and same_surname(cite.authors[0], r["authors"][0])
            and _year_parts(r["year"])[0] == year]
    exact = [r for r in same if _year_parts(r["year"])[1] == letter]

    def counted(rs):
        if cite.et_al:
            return [r for r in rs if len(r["authors"]) >= 3]
        if len(cite.authors) >= 2:
            return [r for r in rs if len(r["authors"]) == len(cite.authors)
                    and same_surname(cite.authors[1], r["authors"][1])]
        return [r for r in rs if len(r["authors"]) == 1]

    pool = exact or same
    note = "" if exact else "the year's letter differs from the entry"
    if len(pool) == 1:
        if not counted(pool):
            note = "; ".join(n for n in (note, "the author count differs from the entry") if n)
        return pool[0]["key"], "matched", note
    if len(pool) > 1:
        narrowed = counted(pool)
        if len(narrowed) == 1:
            return narrowed[0]["key"], "matched", note
        return None, "ambiguous", "could be any of: " + ", ".join(r["key"] for r in (narrowed or pool))
    return None, "unmatched", "no entry in the reference list"


def reference_table(path, heading=None) -> list[dict]:
    """The manuscript's reference list, parsed with part 1, as plain dicts with a stable key."""
    taken: set[str] = set()
    refs = []
    for ref in parse.read_docx(path, heading):
        refs.append({"key": refkey(ref, taken), "raw": ref.raw, "authors": [p.surname for p in ref.authors],
                     "year": ref.year, "title": ref.title, "source": ref.source, "kind": ref.kind, "doi": ref.doi})
    return refs


# --- occurrence rows ---------------------------------------------------------

def _numbers(text: str) -> list[str]:
    return list(dict.fromkeys(m.group().strip() for m in NUMBER_RE.finditer(text)
                              if re.search(r"\d", m.group())))


def occurrences(paragraphs: list[str], refs: list[dict]) -> list[dict]:
    """One row per citation occurrence, in manuscript order."""
    rows, sentence_list = [], []
    for p, paragraph in enumerate(paragraphs, 1):
        for s, sentence in enumerate(split_sentences(paragraph), 1):
            sentence_list.append((f"P{p:03d}", f"P{p:03d}.S{s}", sentence))
    for i, (pid, sid, sentence) in enumerate(sentence_list):
        cites = find_citations(sentence)
        bounds = sorted({(c.start, c.end) for c in cites})
        stripped = sentence
        for a, b in reversed(bounds):
            stripped = stripped[:a] + " " + stripped[b:]
        quotes = [q.strip() for q in QUOTE_RE.findall(sentence) if len(q.split()) >= 3]
        for cite in cites:
            before = [b for a, b in bounds if b <= cite.start]
            after = [a for a, b in bounds if a >= cite.end]
            if cite.narrative:  # 'Douglas et al. (2017) showed that ...': the claim follows the citation
                scope = sentence[cite.end:after[0] if after else len(sentence)]
            else:
                scope = sentence[before[-1] if before else 0:cite.start]
            key, state, note = match(cite, refs)
            rows.append({
                "id": f"C{len(rows) + 1:03d}", "paragraph": pid, "sentence_id": sid, "sentence": sentence,
                "scope": " ".join(scope.split()).strip(" ,;:"),
                "prev": sentence_list[i - 1][2] if i else "",
                "next": sentence_list[i + 1][2] if i + 1 < len(sentence_list) else "",
                "citation": cite.text if not cite.narrative else cite.text, "authors": cite.authors,
                "et_al": cite.et_al, "year": cite.year, "narrative": cite.narrative, "locator": cite.locator,
                "prefix": cite.prefix, "original": cite.original, "group": cite.group,
                "quotes": quotes, "numbers": _numbers(stripped), "ref": key, "match": state, "match_note": note})
    return rows
