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
