"""Write the colour-coded .xlsx report: Audit, Summary and Legend sheets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .compare import Check, Row
from .parse import Reference

FILLS = {"GREEN": "C6EFCE", "YELLOW": "FFEB9C", "ORANGE": "F4B183", "PURPLE": "D9C3E9", "RED": "FF8B8B",
         "GREY": "D9D9D9"}
STATUS_ORDER = ("RED", "PURPLE", "ORANGE", "YELLOW", "GREEN", "GREY")
MEANINGS = {
    "GREEN": "Checked against the record; everything matches.",
    "YELLOW": "Minor issues: initials or diacritics, a slightly different title, an abbreviated journal or "
              "'&'/'and', volume, issue or pages missing, a missing DOI (given) or a DOI not written as "
              "https://doi.org/….",
    "ORANGE": "Mismatches: author count, order or surname, the year, the title, the journal, volume, issue or "
              "pages; or only a low-confidence match.",
    "PURPLE": "The work has an expression of concern.",
    "RED": "The work is retracted, partially retracted, withdrawn or removed; the DOI is not registered or "
           "belongs to another work; or no record exists for a journal article.",
    "GREY": "Nothing could be checked: no record for a book, chapter, report, thesis or web page, or an error.",
}
FIELD_RULES = [
    ("Field", "YELLOW", "ORANGE", "RED"),
    ("Authors", "initials or diacritics differ", "count, order or surname differs", ""),
    ("Year", "", "the cited year is the online-first year while the record has an issue year "
                 "(note 'issue year is X'), or it matches neither", ""),
    ("Title", "similarity 85–94", "similarity below 85", ""),
    ("Journal", "abbreviation or '&' difference", "different journal", ""),
    ("Volume, issue, pages / article no.", "missing in the reference but present in the record", "mismatch", ""),
    ("DOI", "missing but found with high confidence (given); not in https://doi.org/ form", "",
     "not registered, or resolves to a different work (title similarity < 60 and first author differs)"),
    ("Notice", "", "", "retraction, partial retraction, withdrawal, removal, or OpenAlex is_retracted "
                       "(an expression of concern is PURPLE)"),
    ("Match without DOI", "", "low-confidence match: title similarity 80–89",
     "no record for a journal article (GREY for books, chapters, reports, theses and web pages)"),
]
RULES = [
    "Row status = the worst field status: RED > PURPLE > ORANGE > YELLOW > GREEN. GREY when nothing could be checked.",
    "With a DOI: registration is checked at doi.org; metadata comes from Crossref, or from DataCite.",
    "Without a DOI: Crossref (query.bibliographic, top 5) and OpenAlex are searched. A candidate is accepted only "
    "if the title similarity is at least 90, the first-author surname matches and the year is within ±1.",
    "Notices: Crossref 'updated-by', Crossref /works?filter=updates:{doi} and OpenAlex is_retracted.",
    "Fields are compared after normalizing case, punctuation, diacritics, dashes and '&'/'and'.",
    "Similarities are 0–100 (rapidfuzz ratio of the normalized strings).",
]
COLUMNS = [("#", 5), ("Status", 10), ("Reference as cited", 60), ("Problems", 60), ("Matched DOI", 44),
           ("Match route and confidence", 30), ("Notice", 32), ("Authors (cited)", 32), ("Authors (record)", 32),
           ("Year (cited)", 9), ("Year (record, issue)", 10), ("Year (record, online)", 10), ("Title (cited)", 40),
           ("Title (record)", 40), ("Title similarity", 10), ("Journal (cited)", 28), ("Journal (record)", 28),
           ("Volume (cited)", 9), ("Volume (record)", 9), ("Issue (cited)", 9), ("Issue (record)", 9),
           ("Pages / article no. (cited)", 13), ("Pages / article no. (record)", 13)]
WRAP = Alignment(wrap_text=True, vertical="top", horizontal="left")
BOLD = Font(bold=True)
LINK = Font(color="0563C1", underline="single")


def _fill(status):
    return PatternFill("solid", start_color=FILLS[status], end_color=FILLS[status]) if status in FILLS else None


def _value(value):
    """A cell value Excel accepts: no control characters, at most 32,000 characters, None for ''."""
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)[:32000]
    return None if value == "" else value


def audit_cells(n: int, ref: Reference, row: Row) -> list[tuple[object, str | None]]:
    """(value, status for the cell colour) for each Audit column."""
    def get(key):
        return row.checks.get(key) or Check()

    def pair(key):
        c = get(key)
        return [(c.cited, c.status), (c.record, c.status)]

    year, title = get("year"), get("title")
    return [(n, None), (row.status, row.status), (ref.raw, None), ("\n".join(row.problems), None),
            (f"https://doi.org/{row.doi}" if row.doi else "", get("doi").status), (row.route, get("match").status),
            (get("notice").record, get("notice").status), *pair("authors"),
            (year.cited, year.status), (row.issue_year, year.status), (row.online_year, year.status),
            *pair("title"), (row.similarity, title.status), *pair("journal"), *pair("volume"), *pair("issue"),
            *pair("pages")]


def _table(ws, rows: Sequence[Sequence], widths: Sequence[int]) -> None:
    for values in rows:
        ws.append([_value(v) for v in values])
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = WRAP


def write_report(path, refs: list[Reference], rows: list[Row], info: dict) -> None:
    """info: input, date, version, sources [(service, text)], failures [str], mailto (bool)."""
    wb = Workbook()
    audit = wb.active
    audit.title = "Audit"
    _table(audit, [[name for name, _ in COLUMNS]], [width for _, width in COLUMNS])
    for n, (ref, row) in enumerate(zip(refs, rows), 1):
        cells = audit_cells(n, ref, row)
        audit.append([_value(value) for value, _ in cells])
        for col, (value, status) in enumerate(cells, 1):
            cell = audit.cell(row=n + 1, column=col)
            cell.alignment = WRAP
            if _fill(status):
                cell.fill = _fill(status)
            if COLUMNS[col - 1][0] == "Matched DOI" and value:
                cell.hyperlink, cell.font = value, LINK
    for cell in audit[1]:
        cell.font = BOLD
    audit.freeze_panes = "A2"
    audit.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}"

    summary = wb.create_sheet("Summary")
    counts = Counter(row.status for row in rows)
    failures = Counter(info.get("failures", []))
    lines = [("refaudit report", ""), ("Input file", info["input"]), ("Date", info["date"]),
             ("Tool version", f"refaudit {info['version']}"), ("References", len(rows)), ("", ""),
             ("Status", "Count"), *[(s, counts.get(s, 0)) for s in STATUS_ORDER], ("", ""),
             ("Source", "Result"), *info.get("sources", []),
             ("Polite pool", "REFAUDIT_MAILTO is set" if info.get("mailto") else
              "REFAUDIT_MAILTO is not set (public pools)"), ("", ""),
             ("API failures", "none" if not failures else f"{sum(failures.values())}"),
             *[("", f"{text}" + (f" ({k} times)" if k > 1 else "")) for text, k in failures.items()]]
    _table(summary, lines, [26, 100])
    for row in summary.iter_rows():
        if row[0].value in FILLS:
            row[0].fill = _fill(row[0].value)
        if row[0].value in ("refaudit report", "Status", "Source", "API failures"):
            row[0].font = row[1].font = BOLD

    legend = wb.create_sheet("Legend")
    lines = [("Status", "Meaning"), *[(s, MEANINGS[s]) for s in STATUS_ORDER], ("", ""),
             *FIELD_RULES, ("", ""), ("Rules", ""), *[("", rule) for rule in RULES]]
    _table(legend, lines, [26, 60, 60, 60])
    for row in legend.iter_rows():
        if row[0].value in FILLS:
            row[0].fill = _fill(row[0].value)
        if row[0].value in ("Status", "Field", "Rules"):
            for cell in row:
                cell.font = BOLD
    header = len(STATUS_ORDER) + 3  # the row of the field-rules table's header
    for cell, status in zip(legend[header], ("", "YELLOW", "ORANGE", "RED")):
        if status:
            cell.fill = _fill(status)
    wb.save(path)
