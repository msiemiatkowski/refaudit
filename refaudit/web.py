"""Entry point for the web app (web/): refaudit running in the browser with Pyodide.

The page's Web Worker writes the uploaded file into Pyodide's virtual file system, calls check()
and reads the .xlsx report back. The same function runs in ordinary Python, which is how it is tested.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import __version__, cli, lookup, parse, report

CACHE = "/tmp/refaudit-cache"  # in the browser this lives in memory for as long as the page is open


def legend() -> str:
    """Status colours, meanings and rules (JSON), so the page shows the same legend as the report."""
    return json.dumps({"fills": report.FILLS, "order": report.STATUS_ORDER, "meanings": report.MEANINGS,
                       "fields": report.FIELD_RULES, "rules": report.RULES, "version": __version__})


def check(path: str, output: str, options: dict | None = None, progress=None, client=None) -> str:
    """Check the references in a .docx or .bib file and write the .xlsx report to `output`.

    options: name (shown as the input file), heading, limit, mailto, openalex_key, use_openalex.
    progress(n, total, reference, status) is called after each reference.
    Returns JSON: the Audit columns, one row of [value, status] cells per reference, the counts per
    status, and the sources reached and API failures for the Summary sheet."""
    options = options or {}
    refs = parse.read_references(path, options.get("heading") or None)
    if options.get("limit"):
        refs = refs[:int(options["limit"])]
    if not refs:
        raise ValueError("no references found")
    if client is None:
        client = lookup.Client(CACHE, mailto=options.get("mailto") or None,
                               openalex_key=options.get("openalex_key") or None,
                               use_openalex=bool(options.get("use_openalex", True)))
    rows = cli.audit(refs, client, progress and (lambda n, total, ref, row: progress(n, total, ref.raw, row.status)))
    info = {"input": options.get("name") or Path(path).name, "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "version": __version__, "sources": client.summary(), "failures": client.failures,
            "mailto": bool(options.get("mailto"))}
    report.write_report(output, refs, rows, info)
    return json.dumps({
        "columns": [name for name, _ in report.COLUMNS],
        "rows": [report.audit_cells(n, ref, row) for n, (ref, row) in enumerate(zip(refs, rows), 1)],
        "counts": {s: sum(row.status == s for row in rows) for s in report.STATUS_ORDER},
        "sources": info["sources"], "failures": client.failures})
