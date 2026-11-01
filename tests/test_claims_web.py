"""The claim check as the claude.ai page runs it (refaudit.claims_web), offline, with recorded answers as the judges."""

import json
from pathlib import Path

import pytest

from conftest import FIXTURES
from refaudit import claims_web

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples" / "claims_sample_claims"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_web, "OUT", tmp_path)
    monkeypatch.setattr(claims_web, "_work", None)
    return json.loads(claims_web.prepare(str(FIXTURES / "claims_sample.docx"), str(FIXTURES / "claims_sources")))


def test_prepare_offline_uses_your_files_only(prepared):
    levels = {s["refkey"]: s["level"] for s in prepared["sources"]}
    assert levels.pop("pilch2023") == levels.pop("vanprooijen2023") == "FULL"
    assert set(levels.values()) == {"NONE"}  # no network on a claude.ai page
    assert prepared["rows"] == 14 and not prepared["unmatched"] and len(prepared["to_judge"]) == 10
    assert {f["ref"] for f in prepared["files"]} == {"pilch2023", "vanprooijen2023"}


def test_question_holds_rules_claims_other_sources_and_the_text(prepared):
    question = claims_web.question("pilch2023", ["C004", "C005"])
    assert "## Rules" in question and "## Verdicts" in question and '"refkey": "pilch2023"' in question
    assert '"id": "C005"' in question and "71.2%" in question and "=== PDF page 3, printed page 3 ===" in question
    assert "SECOND OPINION" not in question
    second = claims_web.question("pilch2023", ["C005"], second=True)
    assert "SECOND OPINION" in second and '"id": "C004"' not in second  # blind: no first verdict, only its claims
    short = claims_web.question("pilch2023", ["C005"], max_bytes=60_000)
    assert len(short.encode("utf-8")) <= 60_000 and "PARTIAL TEXT" in short and "printed page 3 ===" in short


def test_answers_are_read_tolerantly_and_validated(prepared):
    reply = (EXAMPLES / "verdicts" / "vanprooijen2023.json").read_text(encoding="utf-8")
    assert json.loads(claims_web.answer("vanprooijen2023", "Here you are:\n```json\n" + reply + "\n```",
                                        model="claude-opus-5-5")) == {"problems": [], "saved": True}
    assert json.loads(claims_web.answer("pilch2023", "I could not decide."))["problems"] == ["the answer holds no JSON object"]
    bad = json.loads(claims_web.answer("pilch2023", '{"occurrences": [{"id": "C004", "verdict": "MAYBE"}]}'))
    assert not bad["saved"] and "MAYBE" in bad["problems"][0]


def test_full_run_with_recorded_judges(prepared):
    for source in prepared["sources"]:
        if source["level"] == "NONE":
            claims_web.no_text(source["refkey"], source["pending"])
        else:
            claims_web.answer(source["refkey"], (EXAMPLES / "verdicts" / f"{source['refkey']}.json").read_text("utf-8"))
    checked = json.loads(claims_web.verify())
    assert checked["judged"] == 14 and not checked["errors"]
    assert set(checked["overview"]["to_second"]) == {"pilch2023", "vanprooijen2023"}  # nothing to read for the rest
    asked = {s["refkey"]: s["second_pending"] for s in checked["overview"]["sources"] if s["second_pending"]}
    assert asked == {"pilch2023": ["C004", "C005"], "vanprooijen2023": ["C010"]}  # C004: the 10% GREEN sample
    for key, ids in asked.items():  # recorded second opinions, plus the first verdict as an agreeing stand-in
        entries = {e["id"]: e for e in json.loads((EXAMPLES / "verdicts" / f"{key}.json").read_text("utf-8"))["occurrences"]}
        entries.update({e["id"]: e for e in json.loads((EXAMPLES / "second" / f"{key}.json").read_text("utf-8"))["occurrences"]})
        claims_web.answer(key, json.dumps({"occurrences": [entries[i] for i in ids]}), second=True)
    assert json.loads(claims_web.verify())["pending_second"] == 0
    result = json.loads(claims_web.report("claude-opus-5-5", "high"))
    assert [Path(f).suffix for f in result["files"]] == [".xlsx", ".docx", ".json"]
    status = {row["id"]: (row["status"], row["verdict"]) for row in result["rows"]}
    assert status["C004"] == ("GREEN", "SUPPORTED") and status["C005"] == ("RED", "NOT-SUPPORTED")
    assert status["C010"] == ("YELLOW", "SUPPORTED-WITH-CAVEAT") and status["C001"] == ("GREY", "UNVERIFIABLE")
