"""Command line: refaudit FILE [-o OUTPUT] [--heading TEXT] [--no-openalex] [--cache DIR] [--limit N]."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, compare, lookup, parse, report


def default_cache() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "refaudit"


def check_reference(client: lookup.Client, ref: parse.Reference) -> compare.Row:
    if ref.error:
        return compare.failed(ref.error)
    notes: list[str] = []
    match = lookup.find_match(client, ref, notes)
    notices = lookup.find_notices(client, match.record, notes) if match.record and match.record.doi else []
    return compare.assess(ref, match, notices, notes)


def audit(refs: list[parse.Reference], client: lookup.Client, progress=None) -> list[compare.Row]:
    """Check every reference; a failing reference becomes a GREY row with the error.

    progress(n, total, ref, row) is called after each reference."""
    rows = []
    for n, ref in enumerate(refs, 1):
        try:
            row = check_reference(client, ref)
        except lookup.ApiError as exc:
            row = compare.failed(f"could not check this reference ({exc})")
        except Exception as exc:
            row = compare.failed(f"{type(exc).__name__}: {exc}")
        rows.append(row)
        if progress:
            progress(n, len(refs), ref, row)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="refaudit",
        description="Check the references in a .docx or .bib file against Crossref and OpenAlex "
                    "and write a colour-coded .xlsx report.",
        epilog="Environment: REFAUDIT_MAILTO (e-mail for the Crossref and OpenAlex polite pools), "
               "OPENALEX_API_KEY (optional).")
    parser.add_argument("input", help="a .docx manuscript or a .bib file")
    parser.add_argument("-o", "--output", help="report path (default: INPUT_refaudit.xlsx)")
    parser.add_argument("--heading", metavar="TEXT", help="heading of the reference section in a .docx")
    parser.add_argument("--no-openalex", action="store_true", help="do not use OpenAlex")
    parser.add_argument("--cache", metavar="DIR", help=f"cache directory (default: {default_cache()})")
    parser.add_argument("--limit", metavar="N", type=int, help="check only the first N references")
    args = parser.parse_args(argv)

    source = Path(args.input)
    output = Path(args.output) if args.output else source.with_name(f"{source.stem}_refaudit.xlsx")
    try:
        refs = parse.read_references(source, args.heading)
    except Exception as exc:
        print(f"refaudit: cannot read {source}: {exc}", file=sys.stderr)
        return 2
    if args.limit is not None:
        refs = refs[:max(args.limit, 0)]
    if not refs:
        print(f"refaudit: no references found in {source}", file=sys.stderr)
        return 2

    mailto = os.environ.get("REFAUDIT_MAILTO") or None
    client = lookup.Client(args.cache or default_cache(), mailto=mailto,
                           openalex_key=os.environ.get("OPENALEX_API_KEY") or None,
                           use_openalex=not args.no_openalex)
    rows = audit(refs, client, lambda n, total, ref, row: print(f"[{n}/{total}] {row.status:<6} {ref.raw[:90]}",
                                                             file=sys.stderr))
    info = {"input": str(source), "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "version": __version__,
            "sources": client.summary(), "failures": client.failures, "mailto": bool(mailto)}
    try:
        report.write_report(output, refs, rows, info)
    except OSError as exc:
        print(f"refaudit: cannot write {output}: {exc}", file=sys.stderr)
        return 1
    counts = ", ".join(f"{s} {sum(r.status == s for r in rows)}" for s in report.STATUS_ORDER
                       if any(r.status == s for r in rows))
    print(f"Wrote {output} ({len(rows)} reference{'' if len(rows) == 1 else 's'}: {counts})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
