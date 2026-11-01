"""Live smoke test: the CLI on the three samples against the real APIs.  Run with: pytest -m network"""

import pytest
from openpyxl import load_workbook

from conftest import FIXTURES, expected_cases
from refaudit.cli import main

pytestmark = pytest.mark.network


@pytest.mark.parametrize("name", ["sample.docx", "sample_pl.docx", "sample.bib"])
def test_cli_live(name, tmp_path):
    out = tmp_path / "report.xlsx"
    assert main([str(FIXTURES / name), "-o", str(out), "--cache", str(tmp_path / "cache")]) == 0
    rows = list(load_workbook(out)["Audit"].iter_rows(min_row=2, values_only=True))
    for case in (c for c in expected_cases() if c["file"] == name):
        number, status, _, problems = rows[int(case["row"]) - 1][:4]
        if case["expected"] != "as returned":
            assert status == case["expected"], f"case {case['case']}: {problems}"
        assert case["problem_contains"] in (problems or ""), f"case {case['case']}: {problems}"


def test_claims_prepare_live(tmp_path, monkeypatch):
    """Part 2: every open-access source of the acceptance fixture is found in full; Goertzel (1994) is not."""
    import os
    from refaudit import claims_cli
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    if not os.environ.get("REFAUDIT_MAILTO"):
        pytest.skip("set REFAUDIT_MAILTO (your e-mail) for Unpaywall")
    work = claims_cli.prepare(FIXTURES / "claims_sample.docx", sources=FIXTURES / "claims_sources", out=tmp_path,
                              log=lambda *a, **k: None)
    levels = {ref["key"]: (ref["level"], ref["origin"].split(":")[0]) for ref in claims_cli.load(work, "claims.json")["refs"]}
    assert levels.pop("goertzel1994") == ("ABSTRACT", "abstract")
    assert levels.pop("pilch2023") == levels.pop("vanprooijen2023") == ("FULL", "file")
    assert all(level == "FULL" for level, _ in levels.values()), levels
