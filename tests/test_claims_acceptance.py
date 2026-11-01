"""The claim-check acceptance criteria, checked against the committed outputs in examples/.

The outputs come from running /check-claims on tests/fixtures/claims_sample.docx (built by
tests/make_claims_fixture.py) with --sources tests/fixtures/claims_sources. This test reads them; it does not
call any model or API.
"""

import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
REPORT = ROOT / "examples" / "claims_sample_claims.json"
EXPECTED = list(csv.DictReader((ROOT / "tests" / "claims_expected.csv").open(encoding="utf-8")))
CORRECT = {"1", "10", "extra"}

pytestmark = pytest.mark.skipif(not REPORT.exists(), reason="no acceptance run in examples/")


@pytest.fixture(scope="module")
def report():
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    return data, {row["sentence"]: row for row in data["rows"]}, {ref["key"]: ref for ref in data["sources"]}


def test_every_planted_case_gets_its_expected_status(report):
    """The status must match (the spec's criterion); the verdict name and severity may differ."""
    _, rows, _ = report
    got = {(e["case"], rows[e["sentence"]]["status"]) for e in EXPECTED if e["case"] != "extra"}
    assert got == {(e["case"], e["expected_status"]) for e in EXPECTED if e["case"] != "extra"}


def test_no_correct_claim_is_red(report):
    _, rows, _ = report
    assert all(rows[e["sentence"]]["status"] != "RED" for e in EXPECTED if e["case"] in CORRECT)


def test_every_quote_passes_the_quote_check(report):
    data, _, _ = report
    for row in data["rows"]:
        checks = row["checks"] or {}
        assert all(e["ok"] for e in checks.get("evidence", [])), row["id"]
        assert all(e["ok"] for e in checks.get("second_evidence", [])), row["id"]
        assert all(q["ok"] or q.get("page_mismatch") for q in checks.get("quotations", [])), row["id"]


def test_the_planted_details(report):
    _, rows, sources = report
    case = {e["case"]: rows[e["sentence"]] for e in EXPECTED if e["case"] != "extra"}
    misattributed = case["5"]["judge"]
    assert misattributed["alternative"] == "omahony2023" and "O'Mahony" in misattributed["fix"].replace("’", "'")
    quotation = case["8"]["checks"]["quotations"][0]
    assert quotation["page_mismatch"] and "printed page 5715" in quotation["where"]
    assert sources[case["10"]["ref"]]["origin"].startswith("file: ")  # judged from the uploaded PDF
    assert sources[case["9"]["ref"]]["level"] in ("ABSTRACT", "NONE")
