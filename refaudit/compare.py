"""Normalization, field-by-field comparison and status logic."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

from .parse import Person, Reference


def lcs_ratio(a: str, b: str) -> float:
    """rapidfuzz.fuzz.ratio without rapidfuzz (normalized Indel similarity, bit-parallel LCS; same floats)."""
    masks: dict[str, int] = {}
    for i, ch in enumerate(a):
        masks[ch] = masks.get(ch, 0) | 1 << i
    full = v = (1 << len(a)) - 1
    for ch in b:
        u = v & masks.get(ch, 0)
        v = ((v + u) | (v - u)) & full
    total = len(a) + len(b)
    return (1 - (total - 2 * (len(a) - bin(v).count("1"))) / total) * 100 if total else 100.0


try:
    from rapidfuzz.fuzz import ratio as _ratio
except ImportError:  # in the browser (Pyodide) rapidfuzz is not available
    _ratio = lcs_ratio

ORDER = ("RED", "PURPLE", "ORANGE", "YELLOW", "GREEN")  # worst first; GREY = nothing checked
RED_NOTICES = {"retraction", "partial_retraction", "withdrawal", "removal", "is_retracted"}
PURPLE_NOTICES = {"expression_of_concern"}
PARTICLES = {"de", "van", "von", "der", "den", "da", "di", "du", "la", "le", "del", "dos", "ter"}
STOPWORDS = {"the", "of", "and", "for", "in", "on", "a", "an", "to", "de", "der", "und", "i", "w"}
_LETTERS = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss",
                          "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ı": "i", "þ": "th", "Þ": "Th"})
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"  # hyphens, dashes and minus signs


@dataclass
class Record:
    """Metadata of a registered work (from Crossref, DataCite or OpenAlex)."""
    origin: str = ""
    doi: str = ""
    kind: str = ""
    authors: list[Person] = field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    journal: str = ""                # journal, or the book title of a chapter
    alt_journals: list[str] = field(default_factory=list)    # further container titles (book series)
    short_journals: list[str] = field(default_factory=list)  # abbreviated titles
    volume: str = ""
    issue: str = ""
    pages: str = ""
    article_number: str = ""
    issue_year: int | None = None    # print / issue year
    online_year: int | None = None   # online-first year
    updated_by: list[dict] = field(default_factory=list)  # Crossref "updated-by"


@dataclass
class Notice:
    kind: str     # retraction, expression_of_concern, correction, ..., is_retracted
    date: str = ""
    doi: str = ""
    source: str = ""


@dataclass
class Match:
    record: Record | None = None
    route: str = ""
    confidence: str = ""             # "doi", "high", "low"; "" when there is no record
    similarity: int | None = None    # title similarity of a search match
    doi_state: str = ""              # cited DOI: "ok", "unregistered", "different", "no-metadata"
    other: Record | None = None      # the work a wrong DOI belongs to
    searched: str = ""               # sources searched without a DOI


@dataclass
class Check:
    status: str | None = None        # None: not compared
    cited: str = ""
    record: str = ""
    problem: str = ""


@dataclass
class Row:
    status: str
    problems: list[str]
    checks: dict[str, Check] = field(default_factory=dict)
    doi: str = ""
    route: str = ""
    similarity: int | None = None
    issue_year: str = ""
    online_year: str = ""


# --- normalization ---------------------------------------------------------

def clean(text) -> str:
    """Drop markup (JATS/HTML tags and entities) and collapse whitespace."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(text or ""))).split())


def fold(text) -> str:
    """Remove diacritics: ą -> a, ł -> l, ö -> o."""
    text = unicodedata.normalize("NFKD", str(text or "").translate(_LETTERS))
    return "".join(c for c in text if not unicodedata.combining(c))


def norm(text) -> str:
    """Lower-case text without diacritics, punctuation and dashes, with '&' read as 'and'."""
    text = fold(clean(text)).casefold().replace("&", " and ")
    text = re.sub(r"['’ʼ]", "", text)
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def similarity(a, b) -> int:
    """Similarity (0-100) of two normalized strings."""
    a, b = norm(a), norm(b)
    return round(_ratio(a, b)) if a and b else 0


def name_key(name) -> str:
    """A surname without case, diacritics, punctuation or particles: 'van der Linden' -> 'linden'."""
    words = norm(name).split()
    return "".join(w for w in words if w not in PARTICLES) or "".join(words)


def same_surname(a, b) -> bool:
    """Surnames match, ignoring case and diacritics; 'van der Linden' matches 'Linden'."""
    a, b = norm(a).split(), norm(b).split()
    return bool(a and b) and (a == b or a[-1] == b[-1])


def initials_of(names) -> str:
    """'Karen M.' -> 'KM', 'K. M.' -> 'KM', 'J.-P.' -> 'JP'."""
    parts = re.split(r"[\s.\-‐]+", clean(names))
    return "".join(p[0].upper() for p in parts if p and p[0].isalpha() and p.lower() not in PARTICLES)


def full_title(record: Record) -> str:
    return clean(f"{record.title}: {record.subtitle}" if record.subtitle else record.title)


def title_score(cited, record: Record) -> int:
    """Title similarity, with and without the record's subtitle."""
    return max(similarity(cited, record.title), similarity(cited, full_title(record)))


def year_close(cited, record: Record) -> bool:
    """Cited year within +-1 of the record's issue or online year (true when either is unknown)."""
    m = re.match(r"\d{4}", cited or "")
    years = [y for y in (record.issue_year, record.online_year) if y]
    return not m or not years or any(abs(int(m.group()) - y) <= 1 for y in years)


def worst(statuses) -> str | None:
    return next((s for s in ORDER if s in statuses), None)


# --- field comparisons -----------------------------------------------------

def _set(check: Check, status: str, problem: str = "") -> Check:
    check.status, check.problem = status, problem
    return check


def _letters(name) -> str:
    """A surname without case, punctuation or particles, but with its diacritics."""
    words = re.findall(r"[^\W\d_]+", str(name).casefold())
    return "".join(w for w in words if fold(w) not in PARTICLES) or "".join(words)


def _names(people: list[Person]) -> str:
    """'Douglas, K. M.; Sutton, R. M.', shortened APA-style beyond 20 names."""
    if len(people) <= 20:
        return "; ".join(map(str, people))
    return "; ".join(map(str, people[:19])) + f"; … {people[-1]} ({len(people)} authors)"


def compare_authors(cited: list[Person], record: list[Person], truncated=False) -> Check:
    check = Check(None, _names(cited), _names(record))
    if not cited or not record:
        return check
    rec = record
    if truncated and len(record) > len(cited):  # APA 7: first 19 authors, ..., last author
        rec = record[:len(cited) - 1] + record[-1:]
    cited_keys, rec_keys = [name_key(p.surname) for p in cited], [name_key(p.surname) for p in rec]
    if len(cited_keys) != len(rec_keys):
        return _set(check, "ORANGE", f"Authors: the reference lists {len(cited)}, the record has {len(record)}.")
    if cited_keys != rec_keys:
        if sorted(cited_keys) == sorted(rec_keys):
            return _set(check, "ORANGE", "Authors: the order differs from the record.")
        c, r = next((c, r) for c, r in zip(cited, rec) if name_key(c.surname) != name_key(r.surname))
        return _set(check, "ORANGE", f"Authors: {c.surname} differs from the record ({r.surname}).")
    notes = []
    for c, r in zip(cited, rec):
        if _letters(c.surname) != _letters(r.surname):
            notes.append(f"diacritics in {c.surname} (record: {r.surname})")
        cited_init, rec_init = initials_of(c.initials or c.given), initials_of(r.given)
        if cited_init and rec_init and cited_init != rec_init:
            what = "diacritics" if fold(cited_init) == fold(rec_init) else "initials"
            notes.append(f"{what} of {c.surname} (cited {c.initials or c.given}, record {r.given})")
    if notes:
        return _set(check, "YELLOW", "Authors: " + "; ".join(notes) + ".")
    return _set(check, "GREEN")


def compare_year(cited, record: Record) -> Check:
    issue, online = record.issue_year, record.online_year
    check = Check(None, cited or "", str(issue or ""))
    if not (issue or online):
        return check
    m = re.match(r"\d{4}", cited or "")
    if not m:
        return _set(check, "ORANGE", f"Year: cited as '{cited or 'no year'}', but the record has {issue or online}.")
    year = int(m.group())
    if year == (issue or online):
        return _set(check, "GREEN")
    if year == online:
        return _set(check, "ORANGE", f"Year: {year} is the online-first year; issue year is {issue}.")
    return _set(check, "ORANGE", f"Year: {year} matches neither the issue year ({issue or '–'}) "
                                 f"nor the online year ({online or '–'}).")


def compare_title(cited, record: Record) -> tuple[Check, int | None]:
    check = Check(None, cited or "", full_title(record))
    if not cited or not record.title:
        return check, None
    sim = title_score(cited, record)
    if sim >= 95:
        return _set(check, "GREEN"), sim
    level = "YELLOW" if sim >= 85 else "ORANGE"
    return _set(check, level, f"Title: similarity {sim}; the record has “{full_title(record)}”."), sim


def _is_abbreviation(short, full) -> bool:
    """'J Pers Soc Psychol' abbreviates 'Journal of Personality and Social Psychology'."""
    s = [w for w in norm(short).split() if w not in STOPWORDS]
    f = [w for w in norm(full).split() if w not in STOPWORDS]

    def subsequence(a, b):
        letters = iter(b)
        return a[0] == b[0] and all(ch in letters for ch in a)

    return bool(s) and len(s) == len(f) and all(subsequence(a, b) for a, b in zip(s, f))


def compare_journal(cited, record: Record) -> Check:
    titles = [clean(t) for t in [record.journal, *record.alt_journals] if t]  # a chapter may list series and book
    journal = max(titles, key=lambda t: similarity(cited, t)) if cited and titles else (titles[0] if titles else "")
    check = Check(None, cited or "", journal)
    if not cited or not journal:
        return check
    if norm(cited) == norm(journal):
        if ("&" in cited) != ("&" in journal):
            return _set(check, "YELLOW", f"Journal: '&' and 'and' differ; the record has {journal}.")
        return _set(check, "GREEN")
    if any(norm(cited) == norm(s) for s in record.short_journals) or _is_abbreviation(cited, journal):
        return _set(check, "YELLOW", f"Journal: abbreviated; the full title is {journal}.")
    return _set(check, "ORANGE", f"Journal: {cited} differs from the record ({journal}).")


def _number(value) -> str:
    text = re.sub(f"[{DASHES}]", "-", clean(value).casefold())
    text = re.sub(r"^(?:article|art\.|artykuł|pp?\.|ss?\.|no\.|nr)\s*", "", text)
    return re.sub(r"(?<!\d)0+(?=\d)", "", text.replace(" ", ""))


def compare_value(label, cited, recorded) -> Check:
    """Volume or issue."""
    recorded = clean(recorded)
    check = Check(None, cited or "", recorded)
    if not recorded:
        return check
    if not cited:
        return _set(check, "YELLOW", f"{label}: missing in the reference; the record has {recorded}.")
    if _number(cited) == _number(recorded):
        return _set(check, "GREEN")
    return _set(check, "ORANGE", f"{label}: cited {cited}, the record has {recorded}.")


def _pages(value) -> str:
    """'538–42' -> '538-542'."""
    text = _number(value)
    m = re.fullmatch(r"([a-z]*)(\d+)-([a-z]*)(\d+)", text)
    if m and len(m[4]) < len(m[2]) and not m[3]:
        text = f"{m[1]}{m[2]}-{m[1]}{m[2][:len(m[2]) - len(m[4])]}{m[4]}"
    return text


def compare_pages(cited, record: Record) -> Check:
    pages, number = clean(record.pages), clean(record.article_number)
    shown = f"{number} (pp. {pages})" if pages and number else pages or number
    check = Check(None, cited or "", shown)
    if not shown:
        return check
    if not cited:
        return _set(check, "YELLOW", f"Pages / article no.: missing in the reference; the record has {shown}.")
    got = _pages(cited)
    first_page_only = pages and "-" not in _pages(pages)
    if got in {_pages(x) for x in (pages, number) if x} or (first_page_only and got.split("-")[0] == _pages(pages)):
        return _set(check, "GREEN")
    return _set(check, "ORANGE", f"Pages / article no.: cited {cited}, the record has {shown}.")


# --- DOI, notices, match, row status --------------------------------------

def _work(record: Record) -> str:
    first = record.authors[0].surname if record.authors else "no author"
    return f"“{full_title(record)}” ({first}, {record.issue_year or record.online_year or 'no year'})"


def check_doi(ref: Reference, match: Match) -> Check:
    rec = match.record
    found = (f" The reference matches https://doi.org/{rec.doi} instead."
             if rec and rec.doi and match.confidence == "high" else "")
    check = Check(None, ref.doi or "", rec.doi if rec else "")
    if ref.doi:
        if match.doi_state == "unregistered":
            return _set(check, "RED", f"DOI {ref.doi} is not registered at doi.org.{found}")
        if match.doi_state == "different":
            return _set(check, "RED", f"DOI {ref.doi} belongs to a different work: {_work(match.other)}.{found}")
        if ref.doi_written is not None and not ref.doi_written.lower().startswith("https://doi.org/"):
            return _set(check, "YELLOW", f"DOI: not in https://doi.org/ form; write https://doi.org/{ref.doi}")
        return _set(check, "GREEN")
    if rec and rec.doi and match.confidence == "high":
        return _set(check, "YELLOW", f"DOI missing; found https://doi.org/{rec.doi}")
    return check


NOTICE_LABELS = {"is_retracted": "Retracted (OpenAlex is_retracted)", "expression_of_concern": "Expression of concern"}


def _notice_text(n: Notice) -> str:
    label = NOTICE_LABELS.get(n.kind, n.kind.replace("_", " ").capitalize())
    return ", ".join(x for x in (label, n.date, f"https://doi.org/{n.doi}" if n.doi else "") if x)


def check_notices(notices: list[Notice]) -> Check:
    red = [n for n in notices if n.kind in RED_NOTICES]
    purple = [n for n in notices if n.kind in PURPLE_NOTICES]
    rest = [n for n in notices if n not in red and n not in purple]
    check = Check(None, "", "\n".join(_notice_text(n) for n in red + purple + rest))
    if red or purple:
        return _set(check, "RED" if red else "PURPLE", "Notice: " + "; ".join(map(_notice_text, red or purple)))
    return check


def check_match(ref: Reference, match: Match) -> Check:
    if match.doi_state == "no-metadata":
        return Check("GREY", problem="The DOI is registered, but neither Crossref nor DataCite has "
                                     "metadata for it, so the other fields could not be checked.")
    if match.record is None:
        if not match.searched:  # the search failed after a bad DOI; the DOI check says what is known
            return Check(None)
        if ref.kind == "article":
            return Check("RED", problem=f"No matching record found ({match.searched} searched).")
        return Check("GREY", problem=f"No matching record found ({match.searched} searched); books, chapters, "
                                     "reports, theses and web pages often have none.")
    if match.confidence == "low":
        return Check("ORANGE", problem=f"Low-confidence match (title similarity {match.similarity}): check "
                                       f"that https://doi.org/{match.record.doi} is the cited work.")
    return Check(None)


def assess(ref: Reference, match: Match, notices=(), notes=()) -> Row:
    """Compare a reference with its record and work out the row status."""
    rec = match.record or Record()
    title, sim = compare_title(ref.title, rec)
    notice = check_notices(list(notices))
    if notice.problem and match.confidence == "low":
        notice.problem = notice.problem.replace("Notice:", "Notice on the low-confidence match:", 1)
    checks = {
        "match": check_match(ref, match),
        "doi": check_doi(ref, match),
        "notice": notice,
        "authors": compare_authors(ref.authors, rec.authors, ref.truncated),
        "year": compare_year(ref.year, rec),
        "title": title,
        "journal": compare_journal(ref.source, rec),
        "volume": compare_value("Volume", ref.volume, rec.volume),
        "issue": compare_value("Issue", ref.issue, rec.issue),
        "pages": compare_pages(ref.pages, rec),
    }
    statuses = [c.status for c in checks.values()]
    if match.record is None:  # nothing was verified against a record
        statuses = [s for s in statuses if s != "GREEN"]
    return Row(status=worst(statuses) or "GREY",
               problems=[c.problem for c in checks.values() if c.problem] + list(notes),
               checks=checks, doi=rec.doi, route=match.route, similarity=sim,
               issue_year=str(rec.issue_year or ""), online_year=str(rec.online_year or ""))


def failed(message: str) -> Row:
    """Row for a reference that could not be checked at all."""
    return Row(status="GREY", problems=[f"Error: {message}"])
