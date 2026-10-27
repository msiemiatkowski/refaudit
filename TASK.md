# Task: build `refaudit`, a reusable reference checker

## Purpose

I verify reference lists in nearly every manuscript. Build a small, deterministic command-line tool that:
- takes a .docx or .bib file;
- checks each reference against Crossref and OpenAlex;
- writes a colour-coded .xlsx report.

Keep the code small and readable. Build exactly this spec, with no extra features.

## Usage

```
refaudit manuscript.docx            # writes manuscript_refaudit.xlsx
refaudit library.bib -o report.xlsx
```

**Options**
- `-o/--output`
- `--heading TEXT`: override the reference-section heading.
- `--no-openalex`
- `--cache DIR`
- `--limit N`

**Environment variables**
- `REFAUDIT_MAILTO`: for the Crossref and OpenAlex polite pools.
- `OPENALEX_API_KEY`: optional. If OpenAlex refuses requests, skip it and say so in the Summary sheet.

## Input

- **.docx**:
  - Find the reference section by its heading, case-insensitive: References, Reference List, Bibliography, Bibliografia, Literatura, Literatura cytowana.
  - Treat each following non-empty paragraph as one reference, until the next heading or the end of the document.
- **.bib**: parse with bibtexparser (author, year, title, journal/booktitle, volume, number, pages, doi).

## Per reference

**1. Parse** with a tolerant APA 7 parser:
- DOI;
- year, including 2026a, in press, n.d.;
- author surnames, title, source;
- volume, issue, pages or article number.

Handle the Polish forms "W:", "(red.)" and "s.".

**2. Find the record.**
- **DOI given:**
  - Check registration via `https://doi.org/api/handles/{doi}`.
  - Fetch metadata from Crossref `/works/{doi}`, or from DataCite `/dois/{doi}` if it is not in Crossref.
- **No DOI:**
  - Search Crossref (`query.bibliographic`, top 5) and OpenAlex.
  - Accept a candidate only if normalized title similarity is ≥ 90, the first-author surname matches, and the year is within ±1.
  - Similarity 80–89 is a low-confidence match (ORANGE).
  - Anything else is "no record": RED for journal articles; GREY for books, chapters, reports, theses and web pages.

**3. Notices.**
- **Sources:**
  - the Crossref `updated-by` field;
  - Crossref `/works?filter=updates:{doi}`;
  - OpenAlex `is_retracted`.
- **Classification:**
  - Retraction, partial retraction, withdrawal, removal, or OpenAlex `is_retracted` → RED.
  - Expression of concern → PURPLE.
- Record the notice type, date and notice DOI.

**4. Compare fields** after normalizing case, punctuation, diacritics, dashes and "&"/"and":

| Field | YELLOW | ORANGE | RED |
|---|---|---|---|
| Authors | initials or diacritics differ | count, order or surname differs | |
| Year | | cited year is the online-first year while the record has an issue year (note "issue year is X"), or matches neither | |
| Title | similarity 85–94 | below 85 | |
| Journal | abbreviation or "&" difference | different journal | |
| Volume, issue, pages / article no. | missing in reference but present in record | mismatch | |
| DOI | missing but found with high confidence (give it); not in https://doi.org/ form | | not registered, or resolves to a different work (title similarity < 60 and first author differs) |

**5. Row status** is the worst field status, in this order: RED > PURPLE > ORANGE > YELLOW > GREEN. Use GREY when nothing could be checked.

## Output (.xlsx, openpyxl)

**Audit sheet:** one row per reference, in input order. Columns:
- #, Status, Reference as cited;
- Problems, in plain language;
- Matched DOI (hyperlink);
- Match route and confidence;
- Notice;
- cited vs. record columns for authors, year (issue and online), title (with similarity), journal, volume, issue, and pages / article no. Colour each compared cell by its own status.

**Summary sheet:**
- counts per status;
- input file, date, tool version;
- which sources were reached, and any API failures.

**Legend sheet:** the colours and the rules behind them.

**Formatting:**
- frozen header row, autofilter, wrapped text, readable widths;
- fills: GREEN `C6EFCE`, YELLOW `FFEB9C`, ORANGE `F4B183`, PURPLE `D9C3E9`, RED `FF8B8B`, GREY `D9D9D9`.

## Engineering

- **Language:** Python ≥ 3.10.
- **Dependencies:** limited to requests, python-docx, bibtexparser, openpyxl and rapidfuzz.
- **Packaging:** `pyproject.toml` with a `refaudit` console script; a few small modules (parse, lookup, compare, report, cli).
- **Polite API use:**
  - mailto;
  - ≤ 5 requests per second;
  - retries with backoff on 429 and 5xx responses;
  - 20 s timeouts;
  - an on-disk JSON cache.
- **Robustness:** one failing reference never stops the run. It becomes a row with the error under Problems.
- **Determinism:** no LLM calls, and no scraping of publisher pages.

## Tests

**1. Offline unit tests** (pytest) for parsing, normalization, comparison and status logic. Use API responses recorded once into `tests/fixtures/`.

**2. Fixtures.** `tests/make_fixtures.py` builds three files:
- `sample.docx`: a "References" heading with APA 7 hanging indents;
- `sample_pl.docx`: a "Bibliografia" heading;
- `sample.bib`.

Put the expected statuses in `tests/expected.csv`:

| # | Reference | Expected |
|---|---|---|
| 1 | Douglas, Sutton, & Cichocka (2017), *Current Directions in Psychological Science*, 26(6), 538–542, https://doi.org/10.1177/0963721417718261 | GREEN |
| 2 | Case 1 with volume 25 and pages 538–545 | ORANGE |
| 3 | Case 1 without its DOI | YELLOW, DOI suggested |
| 4 | Case 1 with one DOI digit changed | RED |
| 5 | Stapel & Lindenberg (2011), "Coping with chaos", *Science* | RED (retracted) |
| 6 | Costello, Pennycook, & Rand (2024), "Durably reducing conspiracy beliefs through dialogues with AI", *Science* | PURPLE (expression of concern) |
| 7 | Siemiątkowski, Gkinopoulos, & Bilewicz, *British Journal of Social Psychology* (societal freedom; online 2025, issue 2026), cited as 2025 | ORANGE, with the issue-year note |
| 8 | An invented article: "Lunar cycles and conspiracy beliefs", *Journal of Imaginary Results* | RED |
| 9 | Allport (1954), *The nature of prejudice*, Addison-Wesley | GREY |
| 10 | A Polish book chapter in `sample_pl.docx` | parsed correctly (authors, year, title, editors, pages); status as returned |

- **Case 6:** if neither API exposes the expression of concern, record that as a coverage limit in the README. Don't hardcode it.
- **Case 7:** look the record up via Crossref to write the fixture.

**3. Live smoke test**, marked `network`: run the CLI on the samples and assert the expected statuses.

## README

- installation (`pip install -e .`) and usage;
- statuses and colours;
- the hosts that must be reachable: api.crossref.org, api.openalex.org, api.datacite.org, doi.org;
- known limits: books and Polish publications often lack DOIs, and notice coverage depends on Crossref and OpenAlex;
- how to use the tool in another cloud session: add this repo to that session.

## Checks before you finish

- The offline tests pass. The network smoke test passes, or each failure is explained.
- Run the CLI on the three samples. Open the reports with openpyxl and confirm sheets, colours and hyperlinks.
- Commit the sample reports to `examples/`.
- If `inputs/` contains a real manuscript, run on it too and add that report to `examples/`.

## Environment

- **Python:** preinstalled; install packages from PyPI.
- **Network:** API calls need api.crossref.org, api.openalex.org, api.datacite.org and doi.org. If they are blocked, stop and tell me which host to allow.

When done, deliver on branch `refaudit-v1`, push, and end with a short summary: what works, known limits, and how to run it.
