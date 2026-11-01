"""Part 2 outputs: <stem>_claims.xlsx, <stem>_claims_comments.docx (Word comments) and <stem>_claims.json."""

from __future__ import annotations

import json
import re
from collections import Counter
from copy import deepcopy

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from .report import BOLD, FILLS, LINK, STATUS_ORDER, WRAP, _fill, _table, _value
from .texts import where

LEVELS = ("FULL", "WEB", "PREPRINT", "ABSTRACT", "NONE")
VERDICT_ROWS = [
    ("SUPPORTED", "The source states this.", "GREEN (full text or web only)"),
    ("SUPPORTED-WITH-CAVEAT", "Substance right; a word, qualifier, number format or page locator needs fixing.", "YELLOW"),
    ("SECONDARY", "The source reports this from another work; cite the original or use “as cited in”.", "YELLOW"),
    ("PARTIALLY-SUPPORTED", "Only part of the claim is in the source, or it holds only for a narrower population, "
                            "measure, design or condition.", "ORANGE"),
    ("OVERSTATED", "Facts right but stated more strongly than the source: causal wording for correlational data, "
                   "overgeneralization, a speculation presented as a finding.", "ORANGE"),
    ("NOT-SUPPORTED", "The source contradicts the claim (reversed direction, wrong number) or doesn't address it "
                      "after a full search.", "RED"),
    ("MISATTRIBUTED", "The claim is right but belongs to another source (named if it is in the reference list).", "RED"),
    ("UNVERIFIABLE", "No readable text, or only an abstract that doesn't settle the claim.", "GREY"),
    ("DISPUTED", "The two judges disagree; both rationales are shown.", "ORANGE"),
]
RULES = [
    "SUPPORTED resting on ABSTRACT or PREPRINT evidence becomes YELLOW (“confirm in full text” / “checked against preprint”).",
    "A retracted source is RED and a source with an expression of concern is PURPLE (part 1 lookup).",
    "An evidence quote not found on the stated page (fuzzy ≥ 95 after normalizing whitespace, hyphenation and "
    "ligatures) turns the row ORANGE: “quote not found, check by hand”.",
    "A direct quotation not found verbatim is ORANGE; one found on another page than cited, or a page locator that "
    "does not match the evidence, is YELLOW.",
    "Row status = the worst of these: RED > PURPLE > ORANGE > YELLOW > GREEN. GREY when nothing could be checked "
    "(unmatched citation, no verdict, or UNVERIFIABLE).",
    "Second opinion: every row that isn't GREEN, every low-confidence row and a random 10% of GREEN rows are judged "
    "again blind; if the two verdicts fall in different groups (supported / partly / wrong / unverifiable) the row "
    "is DISPUTED.",
]
SEVERITY_ROWS = [("CRITICAL", "The meaning changes: reversed direction, a wrong key number, a central claim misattributed."),
                 ("MAJOR", "A substantive problem the authors must fix."),
                 ("MINOR", "A wording, number-format or locator problem."), ("NOTE", "Worth a look; nothing may be wrong.")]
LEVEL_ROWS = [("FULL", "Published version or accepted manuscript, read in full."), ("PREPRINT", "A preprint, read in full."),
              ("WEB", "A web page or report, read in full."), ("ABSTRACT", "Only the abstract was available."),
              ("NONE", "No text: upload the PDF.")]
COLUMNS = [("ID", 6), ("Paragraph", 9), ("Sentence", 9), ("Claim", 60), ("Citation as written", 24), ("Reference", 40),
           ("Evidence level", 11), ("Version", 11), ("Status", 10), ("Verdict", 18), ("Severity", 10),
           ("Type of support", 12), ("Explanation", 55), ("Evidence (quotes with pages)", 55), ("Fix", 45),
           ("Alternative reference", 22), ("Confidence", 10), ("Second opinion", 30), ("Quote check", 32),
           ("Numbers in the claim", 18), ("Candidate passages", 55)]


def _evidence(row: dict) -> str:
    items = []
    for e in (row["judge"].get("evidence") or []):
        place = ", ".join(x for x in (f"p. {e['page']}" if e.get("page") not in (None, "") else "",
                                      f"PDF p. {e['pdf_page']}" if e.get("pdf_page") not in (None, "") else "",
                                      f"section {e['section']}" if e.get("section") else "") if x)
        items.append(f"“{e.get('quote', '')}” ({place})" if place else f"“{e.get('quote', '')}”")
    return "\n".join(items)


def _second(row: dict) -> tuple[str, str | None]:
    if row["second"]:
        same = row["verdict"] != "DISPUTED"
        text = f"{'agrees' if same else 'disagrees'}: {row['second']['verdict']}"
        return (text if same else f"{text}: {row['second'].get('explanation', '')}"), (None if same else "ORANGE")
    if row["second_requested"]:
        return "pending", None
    return ("not requested" if row["judge"] else ""), None


def _quote_check(row: dict) -> tuple[str, str | None]:
    result = row.get("checks")
    if not result:
        return "", None
    lines, status = [], None
    for e in result["evidence"]:
        if not e["ok"]:
            lines.append(f"quote not found on {e['where']} ({e.get('detail', '')}), check by hand")
            status = "ORANGE"
    for q in result["quotations"]:
        if not q["ok"]:
            lines.append(f"quotation: {q.get('detail', '')}")
            status = status or ("YELLOW" if q.get("page_mismatch") else "ORANGE")
    if result["locator"]:
        lines.append(f"page locator: {result['locator']}")
        status = status or "YELLOW"
    if not lines and result["evidence"]:
        lines.append(f"all {len(result['evidence'])} quotes found on the stated pages")
    return "\n".join(lines), status


def _reference(row: dict) -> tuple[str, str | None]:
    if row["match"] != "matched":
        return f"{row['match']}: {row['match_note']}", "GREY"
    return f"{row['ref']}: {row['ref_info'].get('raw', '')[:160]}", None


def claim_cells(row: dict) -> list[tuple[object, str | None]]:
    """(value, colour) for each Claims column."""
    level = row["ref_info"].get("level", "")
    explanation = "\n".join(x for x in [row["judge"].get("explanation", ""), *row["notes"]] if x)
    if row["judge"].get("group_share"):
        explanation += f"\nShare of the group: {row['judge']['group_share']}"
    numbers = ", ".join(f"{n} {'✓' if ok else '✗'}" for n, ok in ((row.get("checks") or {}).get("numbers") or {}).items())
    passages = "\n\n".join(f"[{p['where']}] {p['text'][:300]}" for p in row["passages"])
    second, second_colour = _second(row)
    check, check_colour = _quote_check(row)
    reference, reference_colour = _reference(row)
    verdict_colour = {"DISPUTED": "ORANGE"}.get(row["verdict"]) or (row["status"] if row["verdict"] else None)
    return [(row["id"], None), (row["paragraph"], None), (row["sentence_id"], None), (row["sentence"], None),
            (row["citation"], None), (reference, reference_colour), (level, {"ABSTRACT": "YELLOW", "PREPRINT": "YELLOW",
                                                                            "NONE": "GREY"}.get(level)),
            (row["ref_info"].get("version", ""), None), (row["status"], row["status"]), (row["verdict"], verdict_colour),
            (row["severity"], None), (row["judge"].get("support_type", ""), None), (explanation, None),
            (_evidence(row), None), (row["judge"].get("fix", ""), None), (row["judge"].get("alternative", ""), None),
            (row["judge"].get("confidence", ""), None), (second, second_colour), (check, check_colour),
            (numbers, None), (passages, None)]


def _sheet(wb, title, columns, rows, links=()):
    ws = wb.create_sheet(title) if wb.worksheets[0].title != "Sheet" else wb.worksheets[0]
    ws.title = title
    _table(ws, [[name for name, _ in columns]], [width for _, width in columns])
    for r, cells in enumerate(rows, 2):
        ws.append([_value(value) for value, _ in cells])
        for c, (value, colour) in enumerate(cells, 1):
            cell = ws.cell(row=r, column=c)
            cell.alignment = WRAP
            if _fill(colour):
                cell.fill = _fill(colour)
            if columns[c - 1][0] in links and isinstance(value, str) and value.startswith("https://"):
                cell.hyperlink, cell.font = value, LINK
    for cell in ws[1]:
        cell.font = BOLD
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(len(rows), 1) + 1}"
    return ws


def source_rows(state: dict, rows: list[dict]) -> list[dict]:
    out = []
    for ref in state["refs"]:
        mine = [r for r in rows if r["ref"] == ref["key"]]
        if not mine:
            continue
        statuses = [r["status"] for r in mine]
        worst_status = next((s for s in STATUS_ORDER if s in statuses), "GREY")
        notes = [f"discarded {d['origin']}: {d['reason']}" for d in ref.get("discarded", [])] + ref.get("text_notes", [])
        if ref.get("reason"):
            notes.insert(0, ref["reason"])
        out.append({"ref": ref, "rows": mine, "worst": worst_status, "notes": notes,
                    "bad": sum(r["status"] != "GREEN" for r in mine)})
    return out


def write_xlsx(path, state: dict, rows: list[dict], run: dict) -> None:
    wb = Workbook()
    _sheet(wb, "Claims", COLUMNS, [claim_cells(r) for r in rows])
    sources = source_rows(state, rows)
    doi = lambda ref: f"https://doi.org/{ref['doi']}" if ref.get("doi") else ""  # noqa: E731
    origin = lambda ref: ref.get("origin", "").split(": ", 1)[-1] if "http" in ref.get("origin", "") else ref.get("origin", "")  # noqa: E731
    _sheet(wb, "Sources", [("Ref key", 16), ("Reference", 60), ("DOI", 32), ("Evidence level", 11), ("Version", 11),
                           ("Text from", 50), ("Pages", 7), ("Identity check", 32), ("Notice", 32),
                           ("Reference check (part 1)", 12), ("Occurrences", 11), ("Worst status", 11), ("Notes", 60)],
           [[(s["ref"]["key"], None), (s["ref"]["raw"], None), (doi(s["ref"]), None),
             (s["ref"].get("level", ""), {"ABSTRACT": "YELLOW", "PREPRINT": "YELLOW", "NONE": "GREY"}.get(s["ref"].get("level"))),
             (s["ref"].get("version", ""), None), (origin(s["ref"]), None), (s["ref"].get("pages", 0), None),
             (s["ref"].get("identity", ""), None), (s["ref"].get("notice", ""), s["ref"].get("notice_status")),
             (s["ref"].get("reference_check", ""), s["ref"].get("reference_check") if s["ref"].get("reference_check") in FILLS else None),
             (len(s["rows"]), None), (s["worst"], s["worst"]), ("\n".join(s["notes"]), None)] for s in sources],
           links=("DOI", "Text from"))
    wanted = sorted((s for s in sources if s["ref"].get("level") in ("ABSTRACT", "PREPRINT", "NONE")),
                    key=lambda s: (-s["bad"], -len(s["rows"]), s["ref"]["key"]))
    _sheet(wb, "PDFs to upload", [("Rank", 6), ("Reference", 60), ("DOI", 32), ("Evidence level", 11),
                                  ("Occurrences", 11), ("Not GREEN or unverifiable", 14), ("Why", 50)],
           [[(i, None), (s["ref"]["raw"], None), (doi(s["ref"]), None), (s["ref"]["level"], None), (len(s["rows"]), None),
             (s["bad"], None), (s["ref"].get("reason") or f"only a {s['ref']['level'].lower()} was available", None)]
            for i, s in enumerate(wanted, 1)], links=("DOI",))
    write_summary(wb.create_sheet("Summary"), state, rows, run)
    write_legend(wb.create_sheet("Legend"))
    wb.save(path)


def write_summary(ws, state: dict, rows: list[dict], run: dict) -> None:
    def counts(title, values, order):
        counter = Counter(values)
        return [(title, "Count"), *[(k, counter.get(k, 0)) for k in order if counter.get(k) or k in FILLS], ("", "")]

    sample = [r for r in rows if r["id"] in set(run.get("sample", [])) and r["second"]]
    agree = sum(r["verdict"] != "DISPUTED" for r in sample)
    seconds = [r for r in rows if r["second"]]
    cited = {r["ref"] for r in rows if r["ref"]}
    lines = [("refaudit claim check", ""), ("Manuscript", run["manuscript"]), ("Date", run["date"]),
             ("Tool version", f"refaudit {run['version']}"), ("Judge model", run["model"] or "(not given)"),
             ("Judge effort", run["effort"] or "(not given)"), ("Judge prompt version", run["prompt_version"]),
             ("Text extraction", run["method"]),
             ("Tracked changes", "the manuscript has tracked changes: they were accepted for the analysis and the "
                                 "comments are on an accepted-changes copy" if run["tracked_changes"] else "none"),
             ("Citations", len(rows)), ("", ""),
             *counts("Status", [r["status"] for r in rows], STATUS_ORDER),
             *counts("Verdict", [r["verdict"] or "(not judged)" for r in rows],
                     [v for v, _, _ in VERDICT_ROWS] + ["(not judged)"]),
             *counts("Severity", [r["severity"] for r in rows if r["severity"]], [s for s, _ in SEVERITY_ROWS]),
             *counts("Evidence level (sources)", [s["ref"].get("level", "") for s in source_rows(state, rows)], LEVELS),
             ("Second opinion", f"{len(seconds)} rows judged twice; {sum(r['verdict'] == 'DISPUTED' for r in rows)} disputed"),
             ("Agreement on the GREEN sample", f"{agree} of {len(sample)}" + (f" ({round(100 * agree / len(sample))}%)" if sample else "")),
             ("", ""), ("Unmatched citations", str(sum(r["match"] != "matched" for r in rows))),
             *[("", f"{r['id']} {r['citation']}: {r['match']}: {r['match_note']}") for r in rows if r["match"] != "matched"],
             ("Uncited entries", str(sum(ref["key"] not in cited for ref in state["refs"]))),
             *[("", ref["raw"]) for ref in state["refs"] if ref["key"] not in cited],
             ("Your files not matched", str(sum(not f.get("ref") for f in state["files"]))),
             *[("", f"{f['path']}: {f.get('how') or f.get('error') or ''}") for f in state["files"] if not f.get("ref")],
             ("", ""), ("Source", "Result"), *state.get("services", []),
             ("API failures", str(len(state.get("failures", [])))), *[("", x) for x in dict.fromkeys(state.get("failures", []))],
             ("Verdict file problems", str(len(run.get("errors", [])))), *[("", x) for x in run.get("errors", [])]]
    _table(ws, lines, [30, 110])
    for row in ws.iter_rows():
        if row[0].value in FILLS:
            row[0].fill = _fill(row[0].value)
        if row[1].value == "Count" or row[0].value in ("refaudit claim check", "Source", "Second opinion"):
            row[0].font = row[1].font = BOLD


def write_legend(ws) -> None:
    lines = [("Verdict", "Meaning", "Status"), *VERDICT_ROWS, ("", "", ""), ("Status rules", "", ""),
             *[("", rule, "") for rule in RULES], ("", "", ""), ("Severity", "Meaning", ""), *[(s, m, "") for s, m in SEVERITY_ROWS],
             ("", "", ""), ("Evidence level", "Meaning", ""), *[(s, m, "") for s, m in LEVEL_ROWS], ("", "", ""),
             ("Colour", "Status", ""), *[(s, s, "") for s in STATUS_ORDER]]
    _table(ws, lines, [24, 90, 26])
    for row in ws.iter_rows():
        status = str(row[2].value or "").split(" ")[0]
        if status in FILLS:
            row[2].fill = _fill(status)
        if row[0].value in FILLS and row[1].value == row[0].value:
            row[0].fill = _fill(row[0].value)
        if row[0].value in ("Verdict", "Status rules", "Severity", "Evidence level", "Colour"):
            for cell in row:
                cell.font = BOLD


def write_json(path, state: dict, rows: list[dict], run: dict) -> None:
    keep = ("id", "paragraph", "sentence_id", "sentence", "scope", "citation", "authors", "year", "locator", "prefix",
            "original", "group", "quotes", "numbers", "ref", "match", "match_note", "status", "verdict", "severity",
            "notes", "judge", "second", "checks", "passages")
    data = {"run": run, "rows": [{k: r.get(k) for k in keep} for r in rows],
            "sources": [{k: v for k, v in ref.items() if k != "discarded"} | {"discarded": ref.get("discarded", [])}
                        for ref in state["refs"]], "files": state["files"]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# --- Word comments ---------------------------------------------------------------------

TRACKED = ("ins", "moveTo")
REMOVED = ("del", "moveFrom", "rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange", "tcPrChange",
           "numberingChange", "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")


def accept_changes(document) -> bool:
    """Accept tracked insertions and deletions in place; True if there were any."""
    from docx.oxml.ns import qn
    body = document.element.body
    changed = False
    for name in REMOVED:
        for el in list(body.iter(qn(f"w:{name}"))):
            el.getparent().remove(el)
            changed = True
    for name in TRACKED:
        for el in list(body.iter(qn(f"w:{name}"))):
            parent, index = el.getparent(), el.getparent().index(el)
            for offset, child in enumerate(list(el)):
                parent.insert(index + offset, child)
            parent.remove(el)
            changed = True
    return changed


def _isolate(paragraph, start: int, end: int) -> list:
    """The runs covering characters [start, end) of the paragraph's own runs, splitting runs at the edges."""
    from docx.text.run import Run

    def split(run, at):
        clone = deepcopy(run._r)
        run._r.addnext(clone)
        text = run.text
        run.text, Run(clone, run._parent).text = text[:at], text[at:]

    for edge in (start, end):
        position = 0
        for run in paragraph.runs:
            if position < edge < position + len(run.text):
                split(run, edge - position)
                break
            position += len(run.text)
    runs, position = [], 0
    for run in paragraph.runs:
        if start <= position < end and run.text:
            runs.append(run)
        position += len(run.text)
    return runs


def _comment_text(row: dict) -> str:
    lines = [f"{row['status']} · {row['verdict'] or 'not judged'}" + (f" · {row['severity']}" if row["severity"] else "")]
    explanation = row["judge"].get("explanation") or ""
    lines += [x for x in [explanation, *row["notes"]] if x]
    if row["judge"].get("fix"):
        lines.append(f"Fix: {row['judge']['fix']}")
    evidence = (row["judge"].get("evidence") or [])[:1]
    for e in evidence:
        place = f"p. {e['page']}" if e.get("page") else f"section {e.get('section')}" if e.get("section") else ""
        lines.append(f"Evidence: “{e.get('quote', '')}”" + (f" ({place})" if place else ""))
    return "\n".join(lines)


def write_comments(manuscript, path, rows: list[dict]) -> int:
    """A copy of the manuscript with a comment (author "refaudit") on each citation that isn't GREEN."""
    import docx
    from docx.text.paragraph import Paragraph
    from docx.oxml.ns import qn
    document = docx.Document(str(manuscript))
    accept_changes(document)
    paragraphs = [Paragraph(p, document) for p in document.element.body.iter(qn("w:p"))]
    count = 0
    for row in rows:
        if row["status"] == "GREEN":
            continue
        span = _find(paragraphs, row)
        if not span:
            continue
        paragraph, start, end = span
        runs = _isolate(paragraph, start, end)
        if runs:
            document.add_comment(runs, text=_comment_text(row), author="refaudit", initials="RA")
            count += 1
    document.save(str(path))
    return count


def _find(paragraphs, row: dict):
    """(paragraph, start, end) of the citation as written, near the start of its sentence."""
    head = " ".join(row["sentence"].split()[:6])
    pattern = r"\s+".join(map(re.escape, row["citation"].split()))
    for paragraph in paragraphs:
        text = "".join(run.text for run in paragraph.runs)
        flat = " ".join(text.split())
        if head[:30] not in flat and row["citation"] not in text:
            continue
        anchor = text.find(head.split()[0]) if head else 0
        found = re.compile(pattern).search(text, max(anchor, 0)) or re.compile(pattern).search(text)
        if found:
            return paragraph, found.start(), found.end()
    return None
