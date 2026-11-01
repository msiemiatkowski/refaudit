# refaudit

A small command-line tool that checks the references in a .docx or .bib file against Crossref and OpenAlex and writes a colour-coded .xlsx report. It is deterministic: no LLM calls and no scraping of publisher pages, only the public APIs of doi.org, Crossref, DataCite and OpenAlex.

## Installation

Python 3.10 or newer.

```bash
pip install -e .
```

This installs the `refaudit` command and its dependencies: requests, python-docx, bibtexparser, openpyxl and rapidfuzz. For the tests, add pytest (`pip install -e ".[test]"`).

## Usage

```bash
refaudit manuscript.docx
```

writes `manuscript_refaudit.xlsx` next to the manuscript.

```bash
refaudit library.bib -o report.xlsx
```

| Option | Meaning |
|---|---|
| `-o`, `--output FILE` | report path (default: `INPUT_refaudit.xlsx`) |
| `--heading TEXT` | heading of the reference section in a .docx, if it is not one of the defaults |
| `--no-openalex` | do not use OpenAlex |
| `--cache DIR` | cache directory (default: `~/.cache/refaudit`) |
| `--limit N` | check only the first N references |

| Environment variable | Meaning |
|---|---|
| `REFAUDIT_MAILTO` | your e-mail address, sent to Crossref and OpenAlex for their polite pools |
| `OPENALEX_API_KEY` | optional OpenAlex API key. If OpenAlex refuses requests, refaudit skips it and says so in the Summary sheet. |

```bash
export REFAUDIT_MAILTO=you@example.org
```

Progress is printed as one line per reference. A reference that fails is never fatal: it becomes a GREY row with the error under Problems.

### Input

- **.docx**: the reference section starts at a paragraph whose whole text is one of these headings (case-insensitive): References, Reference List, Bibliography, Bibliografia, Literatura, Literatura cytowana. Use `--heading` for any other heading. Every following non-empty paragraph is one reference, up to the next heading (a heading style, or a short all-bold paragraph) or a table, or to the end of the document. Text in hyperlinks, fields and content controls (Zotero, Mendeley, EndNote) is read. Italics help the parser find where the journal or book title starts.
- **.bib**: parsed with bibtexparser (author, year, title, journal/booktitle, volume, number, pages, doi). LaTeX accents are decoded.

### What is checked

1. **Parse** each reference with a tolerant APA 7 parser: the DOI; the year (also `2026a`, `in press`, `n.d.`); author surnames and initials, title and source; volume, issue, and pages or article number; editors and publisher. The Polish forms `W:`, `(red.)` and `s.` are understood.
2. **Find the record.**
   - With a DOI: registration is checked at `https://doi.org/api/handles/{doi}`. Metadata comes from Crossref `/works/{doi}`, or from DataCite `/dois/{doi}` if Crossref does not have the DOI.
   - Without a DOI: Crossref is searched (`query.bibliographic`, top 5). If that gives no high-confidence match, OpenAlex is searched too. A candidate is accepted only if its normalized title similarity is at least 90, the first-author surname matches and the year is within ±1. A similarity of 80–89 is a low-confidence match (ORANGE). Anything else is "no record": RED for journal articles, GREY for books, chapters, reports, theses and web pages.
   - A cited DOI that is not registered, or that belongs to a different work, is RED. The reference is then searched as if it had no DOI, so the report can give the correct DOI.
3. **Notices** come from Crossref `updated-by`, Crossref `/works?filter=updates:{doi}` and OpenAlex `is_retracted`. A retraction, partial retraction, withdrawal or removal, or `is_retracted`, is RED. An expression of concern is PURPLE. Other notices, such as corrections, are listed in the Notice column without a status. Each notice is recorded with its type, date and DOI.
4. **Compare fields** after normalizing case, punctuation, diacritics, dashes and "&"/"and" (see the table below).
5. **Row status** is the worst field status: RED > PURPLE > ORANGE > YELLOW > GREEN. It is GREY when nothing could be checked.

## Statuses and colours

| Status | Fill | Meaning |
|---|---|---|
| GREEN | `C6EFCE` | checked against the record; everything matches |
| YELLOW | `FFEB9C` | minor issues |
| ORANGE | `F4B183` | mismatches, or only a low-confidence match |
| PURPLE | `D9C3E9` | expression of concern |
| RED | `FF8B8B` | retracted, withdrawn or removed; the DOI is not registered or belongs to another work; or no record exists for a journal article |
| GREY | `D9D9D9` | nothing could be checked (no record for a book, chapter, report, thesis or web page, or an error) |

| Field | YELLOW | ORANGE | RED |
|---|---|---|---|
| Authors | initials or diacritics differ | count, order or surname differs | |
| Year | | the cited year is the online-first year while the record has an issue year (note "issue year is X"), or it matches neither | |
| Title | similarity 85–94 | below 85 | |
| Journal | abbreviation or "&" difference | different journal | |
| Volume, issue, pages / article no. | missing in the reference but present in the record | mismatch | |
| DOI | missing but found with high confidence (given); not in https://doi.org/ form | | not registered, or resolves to a different work (title similarity < 60 and first author differs) |

For a book chapter, the Journal columns compare the book title. In .bib files a bare DOI is normal, so the https://doi.org/ form is checked only in .docx files.

## The report

- **Audit**: one row per reference, in input order. The columns are #, Status, Reference as cited, Problems (in plain language), Matched DOI (a hyperlink), Match route and confidence, and Notice. Then come cited and record columns for authors, year (issue and online), title (with its similarity), journal, volume, issue, and pages / article no. Each compared cell is coloured by its own status. The header row is frozen, the sheet has an autofilter, and text is wrapped.
- **Summary**: the counts per status; the input file, date and tool version; which sources were reached (or skipped, and why); and any API failures.
- **Legend**: the colours and the rules behind them.

`examples/` holds the reports for the three test samples.

## Network

These hosts must be reachable over HTTPS:

- `api.crossref.org`
- `api.openalex.org`
- `api.datacite.org`
- `doi.org`

refaudit uses the APIs politely. It sends `REFAUDIT_MAILTO` to Crossref and OpenAlex only, as `mailto` and in the User-Agent. It makes at most 5 requests per second and uses 20-second timeouts. It retries with backoff (2, 4, 8 and 16 s) on 429, 5xx and network errors. Answers, including "not found", are kept in an on-disk JSON cache (`--cache DIR`) and fetched again after 7 days. Delete the cache directory to force fresh answers.

A service that refuses requests (HTTP 401, 402 or 403, or 429 with a wait of more than a minute) is skipped for the rest of the run, and the Summary sheet says so.

## Known limits

- **Books and Polish publications often lack DOIs.** References without a record are GREY (books, chapters, reports, theses, web pages) or RED (journal articles), and are not otherwise verified. A match also needs a DOI, so OpenAlex entries without one are not used.
- **Notice coverage depends on Crossref and OpenAlex.** refaudit sees only what the publisher or Retraction Watch has deposited in Crossref, plus OpenAlex `is_retracted`. OpenAlex has no expression-of-concern flag. For example, the expression of concern on Costello et al. (2024) appears only in that article's Crossref `updated-by` field (deposited by the publisher, 2026-06-11). The `updates:` filter returns only the later correction.
- **OpenAlex searches may be refused without an API key.** Without a key, OpenAlex now charges searches to a free daily budget shared by everyone on the same IP address. In the cloud environment used to build this tool that budget was used up, so OpenAlex searches were refused (HTTP 429) and skipped. Lookups by DOI, used for `is_retracted`, still worked. Set `OPENALEX_API_KEY` to search OpenAlex reliably. Without it, references without a DOI are searched in Crossref only.
- **Parsing is heuristic.** It is tuned for APA 7. Other styles may parse partly, which shows up as ORANGE fields or "no record". Abbreviated journal names in plain text, without italics, are guessed at.
- **Authors** are compared by surname, then initials. Given names are not checked.

## Tests

```bash
pytest
```

This runs the offline unit tests: parsing, normalization, comparison, status logic and the HTTP client, plus the whole pipeline on the three samples. API responses come from those recorded once in `tests/fixtures/http/`.

```bash
pytest -m network
```

This is the live smoke test. It runs the CLI on the three samples against the real APIs and asserts the statuses in `tests/expected.csv`.

To rebuild the samples (`sample.docx` with a "References" heading and APA 7 hanging indents, `sample_pl.docx` with a "Bibliografia" heading, and `sample.bib`), run:

```bash
python tests/make_fixtures.py
```

To record the API responses again:

```bash
rm -rf tests/fixtures/http
```

```bash
for f in sample.docx sample_pl.docx sample.bib; do refaudit tests/fixtures/$f --cache tests/fixtures/http -o /tmp/$f.xlsx; done
```

`tests/expected.csv` lists the ten cases and where each one sits in the samples. Case 10, the Polish book chapter, is "as returned": the test checks that it is parsed correctly (authors, year, title, editors, pages). Currently Crossref finds it with a DOI, so it is YELLOW (DOI missing).

## Using refaudit in another cloud session

1. Start a Claude Code cloud session and add this repository (`msiemiatkowski/refaudit`) to it, alongside the manuscript's repository or files.
2. Make sure the session's environment allows the four hosts above, plus the package managers (PyPI) for the install.
3. In the session, install the tool and run it:

```bash
pip install -e /path/to/refaudit
```

```bash
refaudit manuscript.docx
```

The tool is on the `refaudit-v1` branch until that branch is merged into `main`. If the session cloned `main`, check that branch out first:

```bash
git -C /path/to/refaudit checkout refaudit-v1
```
