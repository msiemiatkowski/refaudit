"""The claim check in a browser page: the deterministic steps for the claude.ai version of the app.

The page runs this module with Pyodide (no network: claude.ai pages cannot reach other hosts) and plays the
part of the /check-claims skill. It asks Claude, on the viewer's own plan, one question per source, and its
answers are saved exactly where Claude Code's judges save theirs (`verdicts/` and `second/`), so verification
and the reports are the same code as the command line's.

Each question carries the judging rules from `.claude/agents/claim-judge.md`, the source's text, the claims
that cite it and, for spotting misattributions, the best passages from the manuscript's other sources. The
second judge's question never contains the first verdict, so it is blind by construction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import __version__, claims_cli, retrieval, texts
from .claims_cli import PROMPT_VERSION, load, save

OUT = Path("/tmp/claims")  # the work folder and reports live in the page's memory while it is open
_work: Path | None = None  # the work folder of the manuscript last prepared
RULES_FILE = "claim-judge.md"
MARGIN = 2_000  # bytes kept free under the question size limit


def _rules() -> dict[str, str]:
    """The Rules, Verdicts and Output sections of the claim-judge agent (bundled beside this module)."""
    here = Path(__file__).with_name(RULES_FILE)
    path = here if here.exists() else Path(__file__).parent.parent / ".claude" / "agents" / RULES_FILE
    body = path.read_text(encoding="utf-8").split("\n---\n", 1)[-1]
    sections = {}
    for part in re.split(r"^## ", body, flags=re.M)[1:]:
        title, _, text = part.partition("\n")
        sections[title.split(":")[0].strip()] = text.strip()
    return sections


def info() -> str:
    """Version and the status legend, for the page."""
    from .report import FILLS, STATUS_ORDER
    return json.dumps({"version": __version__, "prompt_version": PROMPT_VERSION, "fills": FILLS, "order": STATUS_ORDER})


def prepare(manuscript: str, sources: str | None = None) -> str:
    """Claims, citations, matching and your files' texts (offline). Returns what the page shows before judging."""
    global _work
    _work = claims_cli.prepare(manuscript, sources, out=OUT, offline=True, log=lambda *a, **k: None)
    return json.dumps(overview())


def _folder(work) -> Path:
    if work is None and _work is None:
        raise RuntimeError("no manuscript prepared yet")
    return Path(work) if work is not None else _work


def overview(work: Path | None = None) -> dict:
    work = _folder(work)
    state = load(work, "claims.json")
    status = claims_cli.status(work)
    pending = {s["refkey"]: s for s in status["sources"]}
    refs = {ref["key"]: ref for ref in state["refs"]}
    cited = {row["ref"] for row in state["rows"] if row["ref"]}
    sources = []
    for key in sorted(cited):
        ref = refs[key]
        sources.append({"refkey": key, "reference": ref["raw"], "doi": ref.get("doi"), "level": ref.get("level"),
                        "origin": ref.get("origin", ""), "pages": ref.get("pages", 0), "reason": ref.get("reason", ""),
                        "claims": pending[key]["occurrences"], "pending": pending[key]["pending"],
                        "second_pending": pending[key]["second_pending"]})
    return {"rows": len(state["rows"]), "unmatched": [
                {"id": r["id"], "citation": r["citation"], "note": r["match_note"]} for r in state["rows"]
                if r["match"] != "matched"],
            "uncited": [ref["raw"] for ref in state["refs"] if ref["key"] not in cited],
            "files": [{"name": Path(f["path"]).name, "ref": f["ref"], "how": f["how"]} for f in state["files"]],
            "sources": sources, "to_judge": status["to_judge"], "to_second": status["to_second"],
            "method": state["method"], "tracked_changes": state["tracked_changes"]}


def question(refkey: str, ids: list[str], second: bool = False, max_bytes: int = 262_144,
             work: Path | None = None) -> str:
    """The whole question for one source: rules, the claims, other sources' passages, then the source's text."""
    work = _folder(work)
    state = load(work, "claims.json")
    packet = load(work, f"packets/{refkey}.json")
    text = load(work, f"texts/{refkey}.json")
    rows = {row["id"]: row for row in state["rows"]}
    occurrences = [dict(o) for o in packet["occurrences"] if o["id"] in ids]
    others = {}
    for ref in state["refs"]:
        if ref["key"] != refkey and ref["key"] in {r["ref"] for r in state["rows"]}:
            other = load(work, f"texts/{ref['key']}.json")
            if other and (other.get("pages") or other.get("abstract")):
                others[ref["key"]] = other
    labels = {ref["key"]: ref["raw"][:140] for ref in state["refs"]}
    for o in occurrences:
        o.pop("passages", None)  # the whole text follows, so the keyword hints are not needed
        o["other_sources"] = [{"refkey": c["ref"], "reference": labels.get(c["ref"], ""), "where": c["where"],
                               "passage": c["text"][:700]} for c in retrieval.candidates(others, rows[o["id"]], refkey, 3)]
    rules = _rules()
    lead = (
        "You give an independent SECOND OPINION on citations in a scientific manuscript. Another judge has already "
        "judged these claims; you have not seen that judgment and must not guess it. Judge from the source text "
        "below only, exactly as a first judge would."
        if second else
        "You are a careful research assistant who checks citations in a scientific manuscript. You judge one "
        "source: for each claim below that cites it, decide whether the source's own text supports the claim.")
    head = "\n\n".join([
        lead,
        "## How to work\n\n"
        "1. Read the abstract and enough of SOURCE TEXT (below, with `=== PDF page N, printed page P ===` or "
        "`=== section … ===` headers) to know the paper's design, sample, measures and main results before judging.\n"
        "2. For each claim, search the WHOLE source text for it (synonyms, numbers, key terms, the other language) "
        "before concluding that something is not there, and record your search terms.\n"
        "3. If the claim seems right but belongs to another source, each claim lists `other_sources`: the passages "
        "from the manuscript's other references that fit it best. Name one in `alternative` (its refkey) only if its "
        "passage supports the claim.\n"
        "4. Reply with only the JSON object described under Output: no other text.",
        "## Rules\n\n" + rules.get("Rules", ""),
        "## Verdicts\n\n" + rules.get("Verdicts", ""),
        "## Output\n\n" + rules.get("Output", "").replace('"refkey": "douglas2017"', f'"refkey": "{refkey}"'),
        f"## The source\n\nRefkey: {refkey}\nReference: {packet['reference']}\nEvidence level: {packet['evidence_level']}"
        f" ({packet['version'] or 'no full text'}), text from: {packet['origin'] or 'nowhere'}"
        + (f"\nNotice on this source: {packet['notice']}" if packet.get("notice") else ""),
        f"## Claims to judge ({', '.join(o['id'] for o in occurrences)})\n\n" + json.dumps(occurrences, ensure_ascii=False, indent=1),
        "## SOURCE TEXT",
    ])
    body = texts.render(text) if text else "(no text of this source is available)"
    room = max_bytes - len(head.encode("utf-8")) - MARGIN
    if len(body.encode("utf-8")) > room:
        body = _shorten(text, occurrences, room)
    return head + "\n\n" + body


def _shorten(text: dict, occurrences: list[dict], room: int) -> str:
    """A text too long for one question: the abstract, then the pages most relevant to the claims, in order."""
    pages = text.get("pages", [])
    pieces = retrieval.chunks({"pages": pages})
    index = retrieval.BM25([retrieval.tokenize(p["text"]) for p in pieces]) if pieces else None
    score: dict[str, float] = {}
    for o in occurrences:
        row = {"sentence": o["sentence"], "citation": o["citation"], "scope": o["scope"], "numbers": o["numbers"]}
        for p in retrieval.passages(row, pieces, index, top=8):
            score[p["where"]] = score.get(p["where"], 0) + p["score"] + 1
    ranked = sorted(range(len(pages)), key=lambda i: (i > 1, -score.get(texts.where(pages[i]), 0)))  # first pages first
    keep, used = set(), 0
    for i in ranked:
        size = len(pages[i]["text"].encode("utf-8")) + 80
        if used + size <= room - 400:
            keep.add(i)
            used += size
    out = [f"# {text['key']}: {text['level']} — PARTIAL TEXT: {len(pages) - len(keep)} of {len(pages)} pages left out "
           "because the whole text is too long for one question. Treat what is missing as not searched."]
    if text.get("abstract"):
        out += ["", "=== Abstract ===", text["abstract"]]
    for i, p in enumerate(pages):
        out += ["", f"=== {texts.where(p)} ===", p["text"].strip()] if i in keep else []
    return "\n".join(out).encode("utf-8")[:room].decode("utf-8", "ignore")


def parse_reply(reply: str):
    """Claude's answer as JSON: the whole reply, else a fenced block, else the outermost braces."""
    reply = reply.strip()
    candidates = [reply]
    fence = re.search(r"```(?:json)?\s*(.*?)```", reply, re.S)
    if fence:
        candidates.append(fence.group(1))
    start, end = reply.find("{"), reply.rfind("}")
    if start != -1 and end > start:
        candidates.append(reply[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise ValueError("the answer holds no JSON object")


def answer(refkey: str, reply: str, second: bool = False, model: str = "", work: Path | None = None) -> str:
    """File one judge's answer as `verdicts/<refkey>.json` (or `second/`) and report any problems with it."""
    work = _folder(work)
    try:
        data = parse_reply(reply)
    except ValueError as exc:
        return json.dumps({"problems": [str(exc)], "saved": False})
    if not isinstance(data, dict):
        return json.dumps({"problems": ["the answer is not a JSON object"], "saved": False})
    data.update(refkey=refkey, prompt_version=PROMPT_VERSION, judge_model=model)
    folder = "second" if second else "verdicts"
    save(work, f"{folder}/{refkey}.json", data)
    problems = [e for e in claims_cli.ingest(work, load(work, "claims.json")) if f"{folder}/{refkey}.json" in e]
    return json.dumps({"problems": problems, "saved": not problems})


def no_text(refkey: str, ids: list[str], work: Path | None = None) -> str:
    """UNVERIFIABLE for claims whose source has no text at all, without asking Claude (nothing to read)."""
    entries = [{"id": i, "verdict": "UNVERIFIABLE", "support_type": "none", "severity": "NOTE", "confidence": "high",
                "explanation": "No text of this source was available to the check: add its PDF and run it again.",
                "group_share": "", "evidence": [], "search_terms": [], "fix": "", "alternative": ""} for i in ids]
    return answer(refkey, json.dumps({"occurrences": entries}), model="none (no text)", work=work)


def verify(work: Path | None = None) -> str:
    work = _folder(work)
    result = claims_cli.verify(work, log=lambda *a, **k: None)
    return json.dumps(dict(result, overview=overview(work)))


def report(model: str = "", effort: str = "", work: Path | None = None) -> str:
    """The three report files, written beside the work folder; returns their paths and the rows for the page."""
    paths = claims_cli.report(_folder(work), None, model, effort, log=lambda *a, **k: None)
    data = json.loads(Path(paths[2]).read_text(encoding="utf-8"))
    keep = ("id", "sentence", "citation", "ref", "status", "verdict", "severity", "notes")
    rows = [dict({k: r.get(k) for k in keep}, explanation=(r.get("judge") or {}).get("explanation", ""),
                 fix=(r.get("judge") or {}).get("fix", ""), evidence=(r.get("judge") or {}).get("evidence", []),
                 second=(r.get("second") or {}).get("verdict", "")) for r in data["rows"]]
    return json.dumps({"files": [str(p) for p in paths], "rows": rows})
