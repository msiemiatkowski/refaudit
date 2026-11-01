# refaudit

A small tool that checks the references in a .docx or .bib file against Crossref and OpenAlex and writes a colour-coded .xlsx report. It runs from the command line or, through the [web app](#web-app), in a browser. It is deterministic: no LLM calls and no scraping of publisher pages, only the public APIs of doi.org, Crossref, DataCite and OpenAlex.

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
| `OPENALEX_API_KEY` | optional OpenAlex API key, sent as the `api_key` parameter. If OpenAlex refuses requests, refaudit skips it and says so in the Summary sheet. |

```bash
export REFAUDIT_MAILTO=you@example.org
```

Progress is printed as one line per reference. A reference that fails is never fatal: it becomes a GREY row with the error under Problems.

### Input

- **.docx**: the reference section starts at a paragraph whose whole text is one of these headings (case-insensitive; numbering such as "6." and a final period are ignored): References, Reference List, Bibliography, Bibliografia, Literatura, Literatura cytowana. Use `--heading` for any other heading. Every following non-empty paragraph is one reference, up to the next heading or the end of the document. A heading is a paragraph in a heading style, or a short paragraph that is all bold. The following are read:
  - paragraphs in table cells (a list number alone in a cell is skipped);
  - text in hyperlinks, fields and content controls (Zotero, Mendeley, EndNote);
  - tracked insertions (tracked deletions are skipped).

  Italics help the parser find where the journal or book title starts.
- **.bib**: parsed with bibtexparser (author, year or biblatex date, title, journal/booktitle, volume, number, pages, doi). Entries keep their file order. LaTeX accents are decoded. Files in UTF-8, Windows-1250 or Latin-1 are read. An entry that cannot be parsed becomes a GREY row.

### What is checked

1. **Parse** each reference with a tolerant APA 7 parser. It finds:
   - the DOI;
   - the year (also `2026a`, `in press`, `n.d.`);
   - author surnames and initials, title and source;
   - volume, issue, and pages or article number;
   - editors and publisher.

   The Polish forms `W:`, `(red.)`, `(red. nauk.)` and `s.` are understood. These are left out of the comparison:
   - a translated title in square brackets (`Tytuł [Title]`), as APA 7 asks for non-English works;
   - notes such as `[in Polish]` or `(Original work published 1954)`.
2. **Find the record.**
   - With a DOI: registration is checked at `https://doi.org/api/handles/{doi}`. Metadata comes from Crossref `/works/{doi}`, or from DataCite `/dois/{doi}` if Crossref does not have the DOI.
   - Without a DOI: Crossref is searched (`query.bibliographic`, top 5). If that gives no high-confidence match, OpenAlex is searched too. A candidate is accepted only if its normalized title similarity is at least 90, the first-author surname matches and the year is within ±1. A similarity of 80–89 is a low-confidence match (ORANGE). Anything else is "no record": RED for journal articles, GREY for books, chapters, reports, theses and web pages.
   - A cited DOI that is not registered, or that belongs to a different work, is RED. The reference is then searched as if it had no DOI, so the report can give the correct DOI.
3. **Notices** come from Crossref `updated-by`, Crossref `/works?filter=updates:{doi}` and OpenAlex `is_retracted`. A retraction, partial retraction, withdrawal or removal, or `is_retracted`, is RED. An expression of concern is PURPLE. Other notices, such as corrections, are listed in the Notice column without a status. Each notice is recorded with its type, date and DOI.
4. **Compare fields** after normalizing case, punctuation, diacritics, dashes and "&"/"and" (see the table below).
5. **Row status** is the worst field status: RED > PURPLE > ORANGE > YELLOW > GREEN. It is GREY when nothing could be checked.

## Web app

`web/` holds a browser version with a friendly page. You drop in a .docx or .bib file and watch the references being checked. Then you can filter the results by status, open each reference's comparison with its record, and download the same Excel report.

- **Same results as the command line.** The page runs this repository's Python package in the browser with [Pyodide](https://pyodide.org), so there is a single implementation. The only difference is that rapidfuzz is unavailable in the browser; its similarity ratio is reimplemented exactly (a test checks they agree).
- **Nothing is uploaded.** The file is read in the browser. Only the references' details are sent to Crossref, OpenAlex, DataCite and doi.org, as with the command line. The e-mail and OpenAlex key options are stored only in that browser.
- **First load.** The first visit downloads about 15 MB (Python and its packages, from cdn.jsdelivr.net and PyPI). Later visits come from the browser cache. Checking takes about a second per reference.

### Publishing it on GitHub Pages

1. Merge the branch into `main`.
2. In the repository, open **Settings → Pages → Build and deployment** and set **Source** to **GitHub Actions**.
3. The **Web app** workflow (`.github/workflows/pages.yml`) runs the offline tests and publishes the site. It runs on every push to `main`, or by hand from the Actions tab. The site address is `https://<user>.github.io/refaudit/`.

**Privacy.** A GitHub Pages site is public: anyone with the link can open the page, even when the repository is private. Only organizations on GitHub Enterprise Cloud can restrict a Pages site to people with access to the repository. Publishing Pages from a private repository on a personal account needs GitHub Pro.

The page asks search engines not to index it. It contains no data, because every file stays in the visitor's own browser. If the page itself must not be reachable by others, preview it locally (below) instead of publishing it.

### Local preview

Build the site:

```bash
mkdir -p _site/refaudit && cp -r web/. _site/ && cp refaudit/*.py _site/refaudit/
```

Serve it:

```bash
python -m http.server -d _site 8000
```

Then open http://localhost:8000. The browser needs internet access to cdn.jsdelivr.net, pypi.org, files.pythonhosted.org and the four API hosts.

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

A service that refuses requests is skipped for the rest of the run, and the Summary sheet says so. That means HTTP 401, 402 or 403, a 429 that persists through all the retries, or a request to wait more than a minute. If a reference's own lookup fails, that reference becomes a GREY row with the error. A DOI already known to be unregistered or wrong stays RED.

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
