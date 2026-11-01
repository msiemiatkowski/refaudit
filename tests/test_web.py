"""The web app's Python entry point (refaudit/web.py), run here in ordinary Python on recorded responses."""

import json
import random
import re
from pathlib import Path

import pytest
from openpyxl import load_workbook
from rapidfuzz.fuzz import ratio

from conftest import FIXTURES, expected_cases, offline_client
from refaudit import web
from refaudit.compare import lcs_ratio

ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("name", ["sample.docx", "sample_pl.docx", "sample.bib"])
def test_check(name, tmp_path):
    calls = []
    out = tmp_path / "report.xlsx"
    result = json.loads(web.check(str(FIXTURES / name), str(out), {"name": name},
                                  lambda *args: calls.append(args), client=offline_client()))
    statuses = [row[1][0] for row in result["rows"]]
    for case in (c for c in expected_cases() if c["file"] == name and c["expected"] != "as returned"):
        assert statuses[int(case["row"]) - 1] == case["expected"]
    assert result["columns"][:4] == ["#", "Status", "Reference as cited", "Problems"]
    assert sum(result["counts"].values()) == len(result["rows"]) == len(calls) == calls[-1][1]
    assert [c[3] for c in calls] == statuses
    audit = load_workbook(out)["Audit"]
    assert [r[1] for r in audit.iter_rows(min_row=2, values_only=True)] == statuses
    summary = {r[0]: r[1] for r in load_workbook(out)["Summary"].iter_rows(values_only=True) if r[0]}
    assert summary["Input file"] == name


def test_check_errors(tmp_path):
    with pytest.raises(ValueError, match="no reference heading"):
        web.check(str(FIXTURES / "sample.docx"), str(tmp_path / "r.xlsx"), {"heading": "Works cited"})
    empty = tmp_path / "empty.bib"
    empty.write_text("% nothing here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no references found"):
        web.check(str(empty), str(tmp_path / "r.xlsx"))


def test_legend():
    legend = json.loads(web.legend())
    assert legend["order"] == ["RED", "PURPLE", "ORANGE", "YELLOW", "GREEN", "GREY"]
    assert legend["fills"]["GREEN"] == "C6EFCE" and set(legend["meanings"]) == set(legend["order"])


def test_worker_loads_every_module_the_web_app_needs():
    worker = (ROOT / "web" / "worker.js").read_text(encoding="utf-8")
    listed = set(json.loads(re.search(r"const MODULES = (\[.*?\]);", worker).group(1)))
    needed, todo = {"__init__.py"}, ["web"]
    while todo:  # modules imported by refaudit/web.py, directly or indirectly
        name = todo.pop()
        if f"{name}.py" in needed or not (ROOT / "refaudit" / f"{name}.py").exists():  # e.g. __version__
            continue
        needed.add(f"{name}.py")
        source = (ROOT / "refaudit" / f"{name}.py").read_text(encoding="utf-8")
        for group in re.findall(r"^from \.(\w*) import ([\w, ()]+)", source, re.M):
            todo += [group[0]] if group[0] else [n.strip(" ()") for n in group[1].split(",") if n.strip(" ()")]
    assert needed <= listed, needed - listed


def test_pure_python_ratio_matches_rapidfuzz():
    """The browser has no rapidfuzz; its replacement must give exactly the same numbers."""
    rng = random.Random(7)
    alphabet = "abcde ąłż-"
    for _ in range(20000):
        a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        assert lcs_ratio(a, b) == ratio(a, b), (a, b)
