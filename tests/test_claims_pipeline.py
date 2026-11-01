"""Part 2 end to end without network or models: prepare, verdicts written as a judge would, verify, report."""

import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import docx
import pytest
from openpyxl import load_workbook

from conftest import FIXTURES
from refaudit import claims_cli
from refaudit.cli import main

ROOT = Path(__file__).parent.parent
SENTENCES = [
    "Uncertainty is positively related to conspiracy belief (Kowalska & Nowak, 2017).",
    "Uncertainty causes conspiracy belief (Kowalska & Nowak, 2017).",
    "Kowalska and Nowak (2017) surveyed 500 adults.",
    "Uncertainty was linked to conspiracy belief before (Douglas et al., 2017; Missing, 2020).",
]


def verdict(id_, name, quote="", page="", pdf=None, severity="", confidence="high"):
    return {"id": id_, "verdict": name, "support_type": "finding", "severity": severity, "explanation": f"{name} because.",
            "group_share": "", "evidence": [{"quote": quote, "page": page, "pdf_page": pdf, "section": ""}] if quote else [],
            "search_terms": ["x"], "fix": "a fix" if severity else "", "alternative": "", "confidence": confidence}


@pytest.fixture
def run(tmp_path):
    d = docx.Document()
    d.add_heading("Introduction", level=1)
    d.add_paragraph(" ".join(SENTENCES))
    d.add_heading("References", level=1)
    d.add_paragraph("Douglas, K. M., Sutton, R. M., & Cichocka, A. (2017). The psychology of conspiracy theories. "
                    "Current Directions in Psychological Science, 26(6), 538–542.")
    d.add_paragraph("Kowalska, A., & Nowak, J. (2017). Uncertainty and conspiracy belief: A test article. "
                    "Journal of Test Results, 26(6), 538–540. https://doi.org/10.9999/test.2017.001")
    d.add_paragraph("Uncited, B. (2010). Never cited. Journal, 1, 1–2.")
    d.save(tmp_path / "ms.docx")
    (tmp_path / "pdfs").mkdir()
    shutil.copy(FIXTURES / "claims" / "paged.pdf", tmp_path / "pdfs" / "download (3).pdf")
    work = claims_cli.prepare(tmp_path / "ms.docx", tmp_path / "pdfs", offline=True, log=lambda *a, **k: None)
    return tmp_path, work


def write(work, folder, key, entries):
    (work / folder / f"{key}.json").write_text(json.dumps({"refkey": key, "prompt_version": claims_cli.PROMPT_VERSION,
                                                           "occurrences": entries}), encoding="utf-8")


def test_prepare_writes_packets_and_texts(run):
    _, work = run
    state = claims_cli.load(work, "claims.json")
    assert [r["ref"] for r in state["rows"]] == ["kowalska2017"] * 3 + ["douglas2017", None]
    refs = {r["key"]: r for r in state["refs"]}
    assert refs["kowalska2017"]["level"] == "FULL" and refs["douglas2017"]["level"] == "NONE"
    assert state["files"][0]["ref"] == "kowalska2017" and state["files"][0]["how"] == "DOI in the file"
    packet = claims_cli.load(work, "packets/kowalska2017.json")
    assert len(packet["occurrences"]) == 3 and Path(packet["full_text"]).exists()
    status = claims_cli.status(work)
    assert status["to_judge"] == ["douglas2017", "kowalska2017"] and status["unmatched"] == ["C005"]


def test_judging_verification_and_report(run):
    tmp_path, work = run
    write(work, "verdicts", "kowalska2017", [
        verdict("C001", "SUPPORTED", "Uncertainty was positively associated with conspiracy belief", "538", 1),
        verdict("C002", "OVERSTATED", "This study was correlational; no causal conclusions can be drawn", "538", 1, "MAJOR"),
        verdict("C003", "NOT-SUPPORTED", "Participants (N = 412; 58% women)", "539", 2, "CRITICAL")])
    write(work, "verdicts", "douglas2017", [verdict("C004", "UNVERIFIABLE", severity="NOTE")])
    summary = claims_cli.verify(work, log=lambda *a: None)
    assert summary["judged"] == 4 and not summary["errors"]
    results = claims_cli.load(work, "results.json")["results"]
    assert results["C002"]["evidence"][0]["detail"] == "found on PDF page 2, printed page 539 instead"
    assert results["C003"]["numbers"] == {"500": False}
    requests = claims_cli.load(work, "second_requests.json")
    assert set(requests["kowalska2017"]) == {"C001", "C002", "C003"}  # not GREEN, plus the GREEN sample
    write(work, "second", "kowalska2017", [verdict("C001", "SUPPORTED"), verdict("C002", "OVERSTATED", severity="MAJOR"),
                                           verdict("C003", "SUPPORTED", confidence="low")])
    claims_cli.verify(work, log=lambda *a: None)
    paths = claims_cli.report(work, model="fable", effort="max", log=lambda *a: None)
    assert [p.name for p in paths] == ["ms_claims.xlsx", "ms_claims_comments.docx", "ms_claims.json"]

    wb = load_workbook(paths[0])
    assert wb.sheetnames == ["Claims", "Sources", "PDFs to upload", "Summary", "Legend"]
    claims_sheet = wb["Claims"]
    header = [c.value for c in claims_sheet[1]]
    rows = {r[0].value: {h: c for h, c in zip(header, r)} for r in claims_sheet.iter_rows(min_row=2)}
    expected = {"C001": ("GREEN", "SUPPORTED"), "C002": ("ORANGE", "OVERSTATED"), "C003": ("ORANGE", "DISPUTED"),
                "C004": ("GREY", "UNVERIFIABLE"), "C005": ("GREY", None)}
    assert {k: (v["Status"].value, v["Verdict"].value) for k, v in rows.items()} == expected
    assert rows["C001"]["Status"].fill.start_color.rgb.endswith("C6EFCE")
    assert rows["C002"]["Quote check"].fill.start_color.rgb.endswith("F4B183")
    assert "quote not found" in rows["C002"]["Quote check"].value
    assert rows["C003"]["Second opinion"].value.startswith("disagrees: SUPPORTED")
    assert rows["C005"]["Reference"].fill.start_color.rgb.endswith("D9D9D9")
    assert rows["C004"]["Evidence level"].value == "NONE"
    sources = {r[0].value: r for r in wb["Sources"].iter_rows(min_row=2)}
    assert sources["kowalska2017"][2].hyperlink.target == "https://doi.org/10.9999/test.2017.001"
    assert [r[1] for r in wb["PDFs to upload"].iter_rows(min_row=2, values_only=True)][0].startswith("Douglas")
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    assert summary["Judge model"] == "fable" and summary["Agreement on the GREEN sample"].startswith("1 of 1")
    assert summary["Uncited entries"] == "1" and summary["Unmatched citations"] == "1"

    with zipfile.ZipFile(paths[1]) as z:
        comments = z.read("word/comments.xml").decode()
        document = z.read("word/document.xml").decode()
    assert len(re.findall(r"<w:comment ", comments)) == 4 and set(re.findall(r'w:author="([^"]+)"', comments)) == {"refaudit"}
    anchored = ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", m)) for m in
                re.findall(r"<w:commentRangeStart [^>]*/>(.*?)<w:commentRangeEnd", document)]
    assert anchored == ["Kowalska &amp; Nowak, 2017", "Kowalska and Nowak (2017)", "Douglas et al., 2017", "Missing, 2020"]
    data = json.loads(paths[2].read_text(encoding="utf-8"))
    assert len(data["rows"]) == 5 and data["run"]["prompt_version"] == claims_cli.PROMPT_VERSION


def test_reruns_judge_only_changed_sources(run):
    tmp_path, work = run
    write(work, "verdicts", "kowalska2017", [verdict(f"C00{i}", "SUPPORTED") for i in (1, 2, 3)])
    write(work, "verdicts", "douglas2017", [verdict("C004", "UNVERIFIABLE", severity="NOTE")])
    claims_cli.verify(work, log=lambda *a: None)
    assert claims_cli.status(work)["to_judge"] == []
    (tmp_path / "pdfs" / "Douglas2017.txt").write_text("The Psychology of Conspiracy Theories\nKaren M. Douglas\n"
                                                        "Full text of the article.", encoding="utf-8")
    claims_cli.prepare(tmp_path / "ms.docx", tmp_path / "pdfs", offline=True, log=lambda *a, **k: None)
    assert claims_cli.status(work)["to_judge"] == ["douglas2017"]  # a new file for this source only
    claims_cli.prepare(tmp_path / "ms.docx", tmp_path / "pdfs", offline=True, force=True, log=lambda *a, **k: None)
    assert claims_cli.status(work)["to_judge"] == ["douglas2017", "kowalska2017"]


def test_bad_verdict_files_are_reported(run):
    _, work = run
    write(work, "verdicts", "kowalska2017", [verdict("C001", "MAYBE"), verdict("C009", "SUPPORTED"),
                                             verdict("C002", "SUPPORTED", quote=" ".join(["word"] * 41))])
    errors = claims_cli.verify(work, log=lambda *a: None)["errors"]
    assert any("'MAYBE'" in e for e in errors) and any("C009" in e for e in errors) and any("40 words" in e for e in errors)


def test_cli_without_claude(run, capsys):
    tmp_path, work = run
    assert main(["claims", "report", str(work)]) == 0
    wb = load_workbook(tmp_path / "ms_claims.xlsx")
    rows = list(wb["Claims"].iter_rows(min_row=2, values_only=True))
    assert {r[8] for r in rows} == {"GREY"} and rows[0][20]  # no verdicts, but candidate passages
    assert main(["claims", "candidates", str(work), "C004"]) == 0
    assert json.loads(capsys.readouterr().out)["candidates"][0]["ref"] == "kowalska2017"
    assert main(["claims", "status", str(tmp_path)]) == 2


@pytest.mark.parametrize("command, allowed", [
    ("refaudit claims candidates /w C012", True), ("python3 -m refaudit claims status /w", True),
    ("refaudit claims report /w", False), ("refaudit claims candidates /w C1; rm -rf ~", False), ("cat x", False)])
def test_judge_bash_guard(command, allowed):
    hook = ROOT / ".claude" / "hooks" / "refaudit_only.py"
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps({"tool_input": {"command": command}}),
                            capture_output=True, text=True)
    assert (result.returncode == 0) == allowed


@pytest.mark.parametrize("tool, args, allowed", [
    ("Read", {"file_path": "/x/ms_claims/texts/a.txt"}, True), ("Read", {"file_path": "/x/ms_claims/verdicts/a.json"}, False),
    ("Grep", {"pattern": "C012", "path": "/x/ms_claims"}, False), ("Grep", {"pattern": "a", "path": "/x/ms_claims/texts/a.txt"}, True),
    ("Glob", {"pattern": "**/*.json"}, False), ("Read", {"file_path": "/x/ms_claims.xlsx"}, False),
    ("Read", {"file_path": "/x/.ms_claims.sealed/verdict_cache.json"}, False)])
def test_second_opinion_is_blind(tool, args, allowed):
    hook = ROOT / ".claude" / "hooks" / "blind_second_opinion.py"
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps({"tool_name": tool, "tool_input": args}),
                            capture_output=True, text=True)
    assert (result.returncode == 0) == allowed


def test_agent_and_skill_files():
    for name in ("claim-judge", "claim-second-opinion"):
        text = (ROOT / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
        front = text.split("---")[1]
        assert f"name: {name}" in front and "model: fable" in front and "effort: max" in front
        assert "WebFetch" not in front and "WebSearch" not in front
        assert f'"prompt_version": "{claims_cli.PROMPT_VERSION}"' in text
    skill = (ROOT / ".claude" / "skills" / "check-claims" / "SKILL.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in skill and "$ARGUMENTS" in skill and "at most five" in skill


def test_comment_names_the_better_reference_and_both_pages():
    from refaudit import claims_report
    row = {"status": "RED", "verdict": "MISATTRIBUTED", "severity": "MAJOR", "notes": [],
           "alternative": claims_report.short_cite({"authors": ["O'Mahony", "Brassil", "Murphy"], "year": "2023"}),
           "judge": {"explanation": "The finding is O'Mahony et al.'s.", "fix": "Cite O'Mahony et al. (2023).",
                     "evidence": [{"quote": "the most effective", "page": "5715", "pdf_page": 7}]}}
    text = claims_report._comment_text(row)
    assert "Better-fitting reference in your list: O'Mahony et al., 2023" in text
    assert "Evidence, p. 5715 (PDF p. 7): “the most effective”" in text
    assert claims_report.short_cite({"authors": ["Imhoff", "Lamberty"], "year": "2020"}) == "Imhoff & Lamberty, 2020"
    assert claims_report._place({"page": "", "pdf_page": 3}) == "PDF p. 3"
    assert claims_report._place({"section": "Results"}) == "section Results"


def test_reused_texts_keep_the_fetch_report_of_their_run():
    from refaudit import claims_cli

    class Quiet:
        failures = []

        def summary(self, services):
            return [(name, "not needed") for name in services]

    earlier = {"services": [("Download", "reached (7 responses); journals.sagepub.com refused (HTTP 403)"),
                            ("Unpaywall", "not needed")],
               "failures": ["journals.sagepub.com refused a download (HTTP 403); its other files were skipped."]}
    report = claims_cli._fetch_report(Quiet(), earlier, reused=3)
    assert dict(report["services"])["Download"].endswith("refused (HTTP 403) (earlier run)")
    assert dict(report["services"])["Unpaywall"] == "not needed" and report["failures"] == earlier["failures"]
    assert claims_cli._fetch_report(Quiet(), earlier, reused=0)["failures"] == []


def test_comments_land_on_the_cited_occurrence(tmp_path):
    """The same citation in two sentences, and twice in one sentence: each comment marks its own occurrence."""
    import docx
    from refaudit import claims_report
    d = docx.Document()
    d.add_paragraph("First claim here (Smith, 2020). Second claim (Smith, 2020).")
    d.add_paragraph("A later claim (Smith, 2020), and again (Smith, 2020).")
    d.save(tmp_path / "ms.docx")
    later = "A later claim (Smith, 2020), and again (Smith, 2020)."
    rows = [{"sentence": sentence, "citation": "Smith, 2020", "status": status, "verdict": "NOT-SUPPORTED",
             "severity": "MAJOR", "notes": [], "judge": {}, "alternative": ""}
            for sentence, status in [("First claim here (Smith, 2020).", "GREEN"), ("Second claim (Smith, 2020).", "RED"),
                                     (later, "GREEN"), (later, "RED")]]
    assert claims_report.write_comments(tmp_path / "ms.docx", tmp_path / "out.docx", rows) == 2
    before = []
    for p in docx.Document(tmp_path / "out.docx").paragraphs:
        xml = p._p.xml
        if "commentRangeStart" in xml:
            before.append("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml.split("commentRangeStart")[0])))
    assert before == ["First claim here (Smith, 2020). Second claim (", "A later claim (Smith, 2020), and again ("]


def test_seal_hides_the_first_verdicts_until_verify(run):
    _, work = run
    write(work, "verdicts", "kowalska2017", [
        verdict("C001", "SUPPORTED", "Uncertainty was positively associated with conspiracy belief", "538", 1),
        verdict("C002", "NOT-SUPPORTED", "This study was correlational; no causal conclusions can be drawn", "538", 1,
                "MAJOR"),
        verdict("C003", "SUPPORTED", "Participants (N = 412; 58% women)", "539", 2)])
    claims_cli.verify(work, log=lambda *a: None)
    hold = claims_cli.seal(work, log=lambda *a: None)
    assert hold.parent == work.parent and not list((work / "verdicts").glob("*.json"))
    assert not (work / "verdict_cache.json").exists() and not (work / "results.json").exists()
    status = claims_cli.status(work)  # a second judge may run this: nothing to judge, the seconds still listed
    assert status["sealed"] and status["to_judge"] == ["douglas2017"] and "kowalska2017" in status["to_second"]
    assert "C002" not in (work / "verdict_cache.json").read_text()  # rebuilt while sealed, without first verdicts
    claims_cli.verify(work, log=lambda *a: None)
    assert not hold.exists() and len(list((work / "verdicts").glob("*.json"))) == 1
    assert claims_cli.status(work)["sealed"] is False and claims_cli.status(work)["to_judge"] == ["douglas2017"]



@pytest.mark.parametrize("hook, agent, call, code", [
    ("refaudit_only.py", None, {"tool_input": {"command": "ls"}}, 0),  # the main conversation (settings.json)
    ("refaudit_only.py", "claim-judge", {"tool_input": {"command": "ls"}}, 2),
    ("refaudit_only.py", "claim-judge", {"tool_input": {"command": "refaudit claims status /w"}}, 0),
    ("blind_second_opinion.py", "claim-judge", {"tool_name": "Read", "tool_input": {"file_path": "/w/verdicts/a.json"}}, 0),
    ("blind_second_opinion.py", "claim-second-opinion",
     {"tool_name": "Read", "tool_input": {"file_path": "/w/verdicts/a.json"}}, 2)])
def test_hooks_in_settings_apply_only_to_the_judges(hook, agent, call, code):
    only = "claim-second-opinion" if hook.startswith("blind") else "claim-judge,claim-second-opinion"
    payload = json.dumps(dict(call, agent_type=agent) if agent else call)
    result = subprocess.run([sys.executable, str(ROOT / ".claude" / "hooks" / hook), "--only", only], input=payload,
                            capture_output=True, text=True)
    assert result.returncode == code


@pytest.mark.parametrize("hook", ["refaudit_only.py", "blind_second_opinion.py"])
def test_hooks_fail_closed(hook):
    result = subprocess.run([sys.executable, str(ROOT / ".claude" / "hooks" / hook)], input="not json",
                            capture_output=True, text=True)
    assert result.returncode == 2 and "blocked to be safe" in result.stderr
