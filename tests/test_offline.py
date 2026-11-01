"""The whole pipeline on the three samples, answered from the recorded API responses."""

import pytest
from openpyxl import load_workbook

from conftest import FIXTURES, expected_cases, offline_client
from refaudit import cli, report
from refaudit.parse import read_references

SAMPLES = ("sample.docx", "sample_pl.docx", "sample.bib")


@pytest.fixture(scope="module")
def results():
    """file -> (references, rows), one client per file as in a CLI run."""
    out = {}
    for name in SAMPLES:
        refs = read_references(FIXTURES / name)
        out[name] = refs, cli.audit(refs, offline_client())
    return out


@pytest.mark.parametrize("case", expected_cases(), ids=lambda c: f"{c['file']}-{c['row']}")
def test_expected_status(results, case):
    refs, rows = results[case["file"]]
    row = rows[int(case["row"]) - 1]
    if case["expected"] != "as returned":
        assert row.status == case["expected"], row.problems
    assert case["problem_contains"] in "\n".join(row.problems)


def test_polish_chapter_as_returned(results):
    """Case 10: found by search in Crossref; only the DOI is missing."""
    for name in ("sample_pl.docx", "sample.bib"):
        row = results[name][1][-1]
        assert row.status == "YELLOW"
        assert row.doi == "10.47943/lib.9788363487645.rozdzial10"
        assert row.checks["authors"].status == row.checks["title"].status == row.checks["pages"].status == "GREEN"


def test_failing_reference_becomes_a_row(results):
    refs = read_references(FIXTURES / "sample.docx")[:1]
    refs[0].authors = [None]  # breaks the lookup
    rows = cli.audit(refs, offline_client())
    assert rows[0].status == "GREY" and rows[0].problems[0].startswith("Error:")


def test_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.lookup, "Client", lambda *args, **kwargs: offline_client())
    out = tmp_path / "out.xlsx"
    assert cli.main([str(FIXTURES / "sample.docx"), "-o", str(out), "--limit", "2", "--heading", "References"]) == 0
    assert [r[1] for r in load_workbook(out)["Audit"].iter_rows(min_row=2, values_only=True)] == ["GREEN", "ORANGE"]
    bib = tmp_path / "library.bib"
    bib.write_bytes((FIXTURES / "sample.bib").read_bytes())
    assert cli.main([str(bib)]) == 0 and (tmp_path / "library_refaudit.xlsx").exists()  # default output name
    assert "Wrote" in capsys.readouterr().err
    assert cli.main([str(tmp_path / "missing.docx")]) == 2


def test_report(results, tmp_path):
    refs, rows = results["sample.docx"]
    path = tmp_path / "report.xlsx"
    report.write_report(path, refs, rows, {"input": "sample.docx", "date": "2026-11-01 12:00", "version": "1.0.0",
                                           "sources": [("Crossref", "reached (3 requests)")], "failures": []})
    wb = load_workbook(path)
    assert wb.sheetnames == ["Audit", "Summary", "Legend"]
    audit = wb["Audit"]
    header = [c.value for c in audit[1]]
    assert header[:7] == ["#", "Status", "Reference as cited", "Problems", "Matched DOI",
                          "Match route and confidence", "Notice"]
    assert audit.freeze_panes == "A2" and audit.auto_filter.ref == f"A1:W{len(rows) + 1}"
    assert audit.max_row == len(rows) + 1
    for i, row in enumerate(rows, 2):
        status = audit.cell(i, 2)
        assert status.value == row.status
        assert status.fill.start_color.rgb.endswith(report.FILLS[row.status])
        assert status.alignment.wrap_text
    doi = audit.cell(2, header.index("Matched DOI") + 1)
    assert doi.hyperlink.target == "https://doi.org/10.1177/0963721417718261"
    volume = audit.cell(3, header.index("Volume (cited)") + 1)  # case 2: volume 25 instead of 26
    assert volume.value == "25" and volume.fill.start_color.rgb.endswith(report.FILLS["ORANGE"])
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    assert summary["RED"] == 3 and summary["GREY"] == 1 and summary["Crossref"] == "reached (3 requests)"
    legend = [r[0] for r in wb["Legend"].iter_rows(values_only=True)]
    assert all(s in legend for s in report.FILLS)
