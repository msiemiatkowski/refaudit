"""`refaudit claims ...`: the deterministic steps of claim-by-claim citation checking.

    prepare -> (Claude Code: one claim-judge per source) -> verify -> (claim-second-opinion) -> verify -> report

Without Claude Code, `prepare` and `report` still run; the report then shows the evidence available for each
source and the candidate passages for each claim, but no verdicts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, claims, claims_report, cli, lookup, parse, quotes, retrieval, texts
from .compare import worst

PROMPT_VERSION = "1"  # bump when .claude/agents/claim-*.md change: cached verdicts are then judged again
VERDICTS = {"SUPPORTED": "GREEN", "SUPPORTED-WITH-CAVEAT": "YELLOW", "SECONDARY": "YELLOW",
            "PARTIALLY-SUPPORTED": "ORANGE", "OVERSTATED": "ORANGE", "NOT-SUPPORTED": "RED", "MISATTRIBUTED": "RED",
            "UNVERIFIABLE": "GREY", "DISPUTED": "ORANGE"}
AGREEMENT = {"SUPPORTED": "supported", "SUPPORTED-WITH-CAVEAT": "supported", "SECONDARY": "supported",
             "PARTIALLY-SUPPORTED": "partly", "OVERSTATED": "partly", "NOT-SUPPORTED": "wrong",
             "MISATTRIBUTED": "wrong", "UNVERIFIABLE": "unverifiable"}
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR", "NOTE")
SUPPORT_TYPES = ("finding", "theory", "speculation", "secondary", "definition", "none")
CONFIDENCE = ("high", "medium", "low")
SECOND_SAMPLE = 0.10  # share of GREEN rows that get a second opinion
WORK_FILES = ("verdict_cache.json", "second_cache.json", "results.json", "second_requests.json")


# --- the work directory -------------------------------------------------------------

def work_dir(manuscript, out=None) -> Path:
    return Path(out or Path(manuscript).parent).resolve() / f"{Path(manuscript).stem}_claims"


def load(work: Path, name: str, default=None):
    try:
        return json.loads((work / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(work: Path, name: str, data) -> None:
    path = work / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


# --- prepare -----------------------------------------------------------------------

def prepare(manuscript, sources=None, out=None, heading=None, force=False, offline=False, log=print) -> Path:
    """Extract claims and citations, match them, fetch source texts and write one packet per source."""
    manuscript = Path(manuscript).resolve()
    work = work_dir(manuscript, out)
    if work.exists():
        if load(work, "claims.json"):
            ingest(work, load(work, "claims.json"))  # keep the verdicts of earlier runs in the cache
        if force:
            for name in ("texts", "packets"):
                shutil.rmtree(work / name, ignore_errors=True)
            for name in WORK_FILES:
                (work / name).unlink(missing_ok=True)
    for name in ("texts", "packets", "verdicts", "second"):
        (work / name).mkdir(parents=True, exist_ok=True)

    paragraphs, method = claims.manuscript_paragraphs(manuscript, heading)
    refs = claims.reference_table(manuscript, heading)
    rows = claims.occurrences(paragraphs, refs)
    cited = {row["ref"] for row in rows if row["ref"]}
    log(f"{len(paragraphs)} paragraphs ({method}), {len(rows)} citations, {len(cited)} of {len(refs)} entries cited")

    mailto = os.environ.get("REFAUDIT_MAILTO") or None
    client = None if offline else lookup.Client(cli.default_cache(), mailto=mailto,
                                                openalex_key=os.environ.get("OPENALEX_API_KEY") or None)
    entries = {ref.raw: ref for ref in parse.read_docx(manuscript, heading)}
    for ref in refs:  # part 1: DOI, retractions and expressions of concern
        if ref["key"] not in cited or client is None:
            continue
        try:
            checked = cli.check_reference(client, entries[ref["raw"]])
        except Exception as exc:  # one failing reference never stops the run
            ref["reference_check"] = f"failed: {exc}"
            continue
        notice = checked.checks.get("notice")
        ref.update(doi=ref["doi"] or checked.doi or None, reference_check=checked.status,
                   notice=notice.record if notice else "", notice_status=notice.status if notice else None)

    files = texts.scan(sources) if sources else []
    candidates = [ref for ref in refs if ref["key"] in cited]
    for entry in files:
        entry["ref"], entry["how"] = (None, entry["error"]) if entry.get("error") else texts.match_file(entry, candidates)

    for ref in candidates:
        log(f"  {ref['key']}: ", end="")
        try:
            text = _text(work, ref, files, client, mailto, force)
        except Exception as exc:
            text = {"key": ref["key"], "level": "NONE", "version": "", "origin": "", "reason": f"error: {exc}",
                    "pages": [], "supplements": [], "abstract": "", "discarded": [], "notes": [], "identity": "",
                    "extraction": "", "sha256": digest("error", ref["key"])}
        ref.update(level=text["level"], version=text["version"], origin=text["origin"], reason=text["reason"],
                   identity=text["identity"], pages=len(text["pages"]), discarded=text["discarded"],
                   text_notes=text["notes"], sha256=text["sha256"])
        log(f"{text['level']} {text['origin'] or text['reason']}")
        mine = [row for row in rows if row["ref"] == ref["key"]]
        save(work, f"packets/{ref['key']}.json", retrieval.packet(ref, text, mine, str(work / "texts" / f"{ref['key']}.txt")))
    shas = {ref["key"]: ref.get("sha256", "") for ref in refs}
    for row in rows:
        row["cache_key"] = digest(row["sentence"], row["citation"], row["year"], row["ref"], shas.get(row["ref"], ""),
                                  PROMPT_VERSION)
    state = {"manuscript": str(manuscript), "sources": str(Path(sources).resolve()) if sources else "",
             "heading": heading, "method": method, "tracked_changes": claims.has_tracked_changes(manuscript),
             "prepared": datetime.now().strftime("%Y-%m-%d %H:%M"), "version": __version__,
             "prompt_version": PROMPT_VERSION, "refs": refs, "rows": rows,
             "files": [{k: f.get(k) for k in ("path", "ref", "how", "supp", "error")} for f in files],
             "services": client.summary(texts.SERVICES) if client else [], "failures": client.failures if client else []}
    save(work, "claims.json", state)
    for name in ("verdicts", "second"):  # judged again below only where the cache has no verdict
        for path in (work / name).glob("*.json"):
            path.unlink()
    return work


def _text(work: Path, ref: dict, files: list[dict], client, mailto, force: bool) -> dict:
    """A source text from the cache, unless your files for it changed (or --force)."""
    path = work / "texts" / f"{ref['key']}.json"
    signature = [sorted([f["path"], f["size"], f["mtime"]] for f in files if f.get("ref") == ref["key"]), client is not None]
    if path.exists() and not force:
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("signature") == signature:
            return old
    text = texts.build_text(ref, files, client, mailto)
    text["signature"] = signature
    save(work, f"texts/{ref['key']}.json", text)
    (work / "texts" / f"{ref['key']}.txt").write_text(texts.render(text), encoding="utf-8")
    return text


# --- verdicts ----------------------------------------------------------------------

def validate(entry: dict) -> list[str]:
    """Problems with one occurrence's verdict as written by a judge."""
    problems = []
    if entry.get("verdict") not in VERDICTS or entry.get("verdict") == "DISPUTED":
        problems.append(f"verdict {entry.get('verdict')!r} is not one of {', '.join(v for v in VERDICTS if v != 'DISPUTED')}")
    if entry.get("severity") not in ("", None, *SEVERITIES):
        problems.append(f"severity {entry.get('severity')!r}")
    if entry.get("support_type") not in (None, "", *SUPPORT_TYPES):
        problems.append(f"support_type {entry.get('support_type')!r}")
    if entry.get("confidence") not in CONFIDENCE:
        problems.append(f"confidence {entry.get('confidence')!r}")
    for item in entry.get("evidence") or []:
        if len(str(item.get("quote", "")).split()) > 40:
            problems.append("an evidence quote is longer than 40 words")
    return problems


def ingest(work: Path, state: dict) -> list[str]:
    """Move the judges' verdict files into the caches, keyed by claim text, citation, source text and prompt."""
    rows = {row["id"]: row for row in state["rows"]}
    errors = []
    for folder, cache_name in (("verdicts", "verdict_cache.json"), ("second", "second_cache.json")):
        cache = load(work, cache_name, {})
        for path in sorted((work / folder).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                errors.append(f"{folder}/{path.name}: not valid JSON ({exc})")
                continue
            if str(data.get("prompt_version")) != PROMPT_VERSION:
                errors.append(f"{folder}/{path.name}: prompt_version {data.get('prompt_version')!r}, expected {PROMPT_VERSION}")
                continue
            for entry in data.get("occurrences") or []:
                row = rows.get(entry.get("id"))
                if not row or row["ref"] != data.get("refkey"):
                    errors.append(f"{folder}/{path.name}: {entry.get('id')!r} is not an occurrence of {data.get('refkey')}")
                    continue
                problems = validate(entry)
                if problems:
                    errors.append(f"{folder}/{path.name} {entry['id']}: " + "; ".join(problems))
                    continue
                cache[row["cache_key"]] = dict(entry, refkey=data["refkey"], source_summary=data.get("source_summary"))
        save(work, cache_name, cache)
    return errors


def checks(row: dict, verdict: dict, text: dict) -> dict:
    """The deterministic checks of one judged row (step 6)."""
    evidence = quotes.check_evidence(verdict.get("evidence") or [], text)
    return {"evidence": evidence, "locator": quotes.check_locator(row["locator"], evidence, text),
            "quotations": quotes.check_quotations(row["quotes"], row["locator"], text),
            "numbers": quotes.check_numbers(row["numbers"], text)}


def assess(row: dict, ref: dict | None, verdict: dict | None, second: dict | None, result: dict | None) -> dict:
    """Status, verdict, severity and notes of one row (step 5)."""
    statuses, notes = [], []
    name = (verdict or {}).get("verdict", "")
    severity = (verdict or {}).get("severity") or ""
    if row["match"] != "matched":
        statuses.append("GREY")
        notes.append(f"Citation {row['match']}: {row['match_note']}.")
        severity = severity or "MAJOR"
    if verdict:
        status = VERDICTS[name]
        level = (ref or {}).get("level", "")
        if name == "SUPPORTED" and level not in ("FULL", "WEB"):
            status = "YELLOW"
            notes.append("Checked against a preprint." if level == "PREPRINT" else "Confirm in full text.")
        if second and AGREEMENT[second["verdict"]] != AGREEMENT[name]:
            notes.append(f"First judge: {name}. Second opinion: {second['verdict']}: {second.get('explanation', '')}")
            name, status, severity = "DISPUTED", VERDICTS["DISPUTED"], severity or "MAJOR"
        statuses.append(status)
    if result:
        if any(not e["ok"] for e in result["evidence"]):
            statuses.append("ORANGE")
            notes.append("Quote not found, check by hand.")
        for q in result["quotations"]:
            statuses.append("YELLOW" if q.get("page_mismatch") else "ORANGE" if not q["ok"] else None)
            if not q["ok"]:
                notes.append(f"Quotation “{q['quote'][:60]}”: {q.get('detail', '')}.")
        if result["locator"]:
            statuses.append("YELLOW")
            notes.append(f"Page locator: {result['locator']}.")
    notice_status = (ref or {}).get("notice_status")
    if notice_status in ("RED", "PURPLE"):
        statuses.append(notice_status)
        notes.append(f"Notice on the source: {ref['notice'].splitlines()[0]}.")
        severity = severity or ("CRITICAL" if notice_status == "RED" else "MAJOR")
    status = worst([s for s in statuses if s and s != "GREY"]) or "GREY"
    if status == "GREY" and not verdict and row["match"] == "matched":
        notes.append("Not judged yet (run /check-claims in Claude Code).")
    if status != "GREEN" and not severity:
        severity = "NOTE" if status in ("GREY", "YELLOW") else "MAJOR"
    return {"status": status, "verdict": name, "severity": severity if status != "GREEN" else "", "notes": notes}


def second_sample(state: dict, green: list[dict]) -> set[str]:
    """A stable random 10% of the GREEN rows (at least one), for the second-opinion agreement check."""
    ranked = sorted(green, key=lambda row: digest(state["manuscript"], row["cache_key"]))
    return {row["id"] for row in ranked[:math.ceil(SECOND_SAMPLE * len(green))]}


def verify(work: Path, log=print) -> dict:
    """Ingest verdicts, run the deterministic checks and decide which rows need a second opinion."""
    state = load(work, "claims.json")
    errors = ingest(work, state)
    cache, seconds = load(work, "verdict_cache.json", {}), load(work, "second_cache.json", {})
    refs = {ref["key"]: ref for ref in state["refs"]}
    text_cache, results, first = {}, {}, {}
    for row in state["rows"]:
        verdict = cache.get(row["cache_key"])
        if not verdict:
            continue
        if row["ref"] not in text_cache:
            text_cache[row["ref"]] = load(work, f"texts/{row['ref']}.json", {"pages": [], "supplements": [], "abstract": ""})
        results[row["id"]] = checks(row, verdict, text_cache[row["ref"]])
        first[row["id"]] = assess(row, refs.get(row["ref"]), verdict, None, results[row["id"]])
    judged = [row for row in state["rows"] if row["id"] in first]
    green = [row for row in judged if first[row["id"]]["status"] == "GREEN"
             and cache[row["cache_key"]].get("confidence") != "low"]
    sample = second_sample(state, green)
    requests = {}
    for row in judged:
        if (first[row["id"]]["status"] != "GREEN" or cache[row["cache_key"]].get("confidence") == "low"
                or row["id"] in sample):
            requests.setdefault(row["ref"], []).append(row["id"])
    save(work, "results.json", {"results": results, "errors": errors, "sample": sorted(sample)})
    save(work, "second_requests.json", requests)
    pending = sum(1 for ids in requests.values() for i in ids
                  if next(r for r in state["rows"] if r["id"] == i)["cache_key"] not in seconds)
    failed = sum(1 for r in results.values() for e in r["evidence"] if not e["ok"])
    log(f"{len(judged)} of {len(state['rows'])} citations judged; {failed} evidence quotes not found; "
        f"{pending} second opinions to run" + (f"; {len(errors)} problems in verdict files" if errors else ""))
    for error in errors:
        log(f"  {error}")
    return {"judged": len(judged), "pending_second": pending, "errors": errors}


def status(work: Path) -> dict:
    """What remains: sources whose occurrences have no cached verdict, and second opinions not yet run."""
    state = load(work, "claims.json")
    ingest(work, state)
    cache, seconds = load(work, "verdict_cache.json", {}), load(work, "second_cache.json", {})
    requests = load(work, "second_requests.json", {})
    by_id = {row["id"]: row for row in state["rows"]}
    sources = []
    for ref in state["refs"]:
        mine = [row for row in state["rows"] if row["ref"] == ref["key"]]
        if not mine:
            continue
        sources.append({
            "refkey": ref["key"], "reference": ref["raw"][:140], "evidence_level": ref.get("level"),
            "occurrences": [row["id"] for row in mine], "pending": [r["id"] for r in mine if r["cache_key"] not in cache],
            "second_pending": [i for i in requests.get(ref["key"], []) if by_id[i]["cache_key"] not in seconds],
            "packet": str(work / "packets" / f"{ref['key']}.json"), "verdicts": str(work / "verdicts" / f"{ref['key']}.json"),
            "second": str(work / "second" / f"{ref['key']}.json")})
    return {"work": str(work), "manuscript": state["manuscript"], "prompt_version": PROMPT_VERSION,
            "to_judge": [s["refkey"] for s in sources if s["pending"]],
            "to_second": [s["refkey"] for s in sources if s["second_pending"]], "sources": sources,
            "unmatched": [r["id"] for r in state["rows"] if r["match"] != "matched"]}


# --- report ------------------------------------------------------------------------

def rows_for_report(work: Path) -> tuple[dict, list[dict]]:
    state = load(work, "claims.json")
    cache, seconds = load(work, "verdict_cache.json", {}), load(work, "second_cache.json", {})
    results = (load(work, "results.json", {}) or {}).get("results", {})
    requests = load(work, "second_requests.json", {})
    requested = {i for ids in requests.values() for i in ids}
    refs = {ref["key"]: ref for ref in state["refs"]}
    out = []
    for row in state["rows"]:
        verdict, second = cache.get(row["cache_key"]), seconds.get(row["cache_key"])
        result = results.get(row["id"]) if verdict else None
        assessed = assess(row, refs.get(row["ref"]), verdict, second, result)
        packet = load(work, f"packets/{row['ref']}.json", {}) if row["ref"] else {}
        passages = next((o["passages"] for o in packet.get("occurrences", []) if o["id"] == row["id"]), [])
        out.append(dict(row, **assessed, ref_info=refs.get(row["ref"]) or {}, judge=verdict or {}, second=second,
                        second_requested=row["id"] in requested, checks=result, passages=passages[:2]))
    return state, out


def report(work: Path, out=None, model=None, effort=None, log=print) -> list[Path]:
    """Write <stem>_claims.xlsx, <stem>_claims_comments.docx and <stem>_claims.json."""
    state, rows = rows_for_report(work)
    manuscript = Path(state["manuscript"])
    folder = Path(out) if out else work.parent
    stem = folder / f"{manuscript.stem}_claims"
    run = {"manuscript": str(manuscript), "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "version": __version__,
           "model": model or "", "effort": effort or "", "prompt_version": PROMPT_VERSION, "method": state["method"],
           "tracked_changes": state["tracked_changes"], "sources_folder": state["sources"],
           "sample": (load(work, "results.json", {}) or {}).get("sample", []),
           "errors": (load(work, "results.json", {}) or {}).get("errors", [])}
    paths = [Path(f"{stem}.xlsx"), Path(f"{stem}_comments.docx"), Path(f"{stem}.json")]
    claims_report.write_xlsx(paths[0], state, rows, run)
    commented = claims_report.write_comments(manuscript, paths[1], rows)
    claims_report.write_json(paths[2], state, rows, run)
    log(f"Wrote {paths[0]}, {paths[1]} ({commented} comments) and {paths[2]}")
    return paths


# --- command line --------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="refaudit claims", description="Claim-by-claim citation checking "
                                     "(the deterministic steps; the /check-claims skill adds the judging).")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="extract claims and citations, fetch source texts, write packets")
    p.add_argument("manuscript")
    p.add_argument("--sources", metavar="DIR", help="your files: PDF, EPUB, DOCX, HTML or TXT, any names")
    p.add_argument("--out", metavar="DIR", help="where the work folder and reports go (default: next to the manuscript)")
    p.add_argument("--heading", metavar="TEXT", help="heading of the reference section")
    p.add_argument("--force", action="store_true", help="fetch every text and judge every claim again")
    p.add_argument("--offline", action="store_true", help="no network: your files only, no reference lookups")
    for name, text in (("status", "what still needs judging (JSON)"), ("verify", "check the verdicts"),
                       ("report", "write the xlsx, the commented docx and the JSON")):
        q = sub.add_parser(name, help=text)
        q.add_argument("work", help="the work folder printed by prepare (<manuscript>_claims)")
        if name == "report":
            q.add_argument("--out", metavar="DIR")
            q.add_argument("--model", default="")
            q.add_argument("--effort", default="")
    c = sub.add_parser("candidates", help="passages in the other sources that fit a claim")
    c.add_argument("work")
    c.add_argument("claim", help="a claim ID such as C012")
    c.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)
    err = lambda *a, **k: print(*a, file=sys.stderr, **k)  # noqa: E731 (progress goes to stderr)
    try:
        if args.command == "prepare":
            work = prepare(args.manuscript, args.sources, args.out, args.heading, args.force, args.offline, log=err)
            print(work)
            return 0
        work = Path(args.work).resolve()
        if not (work / "claims.json").exists():
            err(f"refaudit claims: {work} is not a work folder (run 'refaudit claims prepare' first)")
            return 2
        if args.command == "status":
            print(json.dumps(status(work), ensure_ascii=False, indent=1))
        elif args.command == "verify":
            verify(work, log=err)
        elif args.command == "report":
            report(work, args.out, args.model, args.effort, log=err)
        elif args.command == "candidates":
            state = load(work, "claims.json")
            row = next((r for r in state["rows"] if r["id"] == args.claim), None)
            if row is None:
                err(f"refaudit claims: no claim {args.claim}")
                return 2
            sources = {ref["key"]: load(work, f"texts/{ref['key']}.json") for ref in state["refs"]
                       if (work / "texts" / f"{ref['key']}.json").exists()}
            found = retrieval.candidates({k: v for k, v in sources.items() if v}, row, row["ref"], args.top)
            print(json.dumps({"claim": row["id"], "sentence": row["sentence"], "cited": row["ref"],
                              "candidates": found}, ensure_ascii=False, indent=1))
    except (OSError, ValueError) as exc:
        err(f"refaudit claims: {exc}")
        return 2
    return 0
