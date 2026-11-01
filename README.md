# refaudit

A small tool in two parts.

1. **Reference check**, `refaudit FILE`. It checks every entry of a reference list (.docx or .bib) against Crossref, OpenAlex, DataCite and doi.org: metadata, DOI, retractions and expressions of concern. It writes a colour-coded .xlsx and runs from the command line or, through the [web app](#web-app), in a browser. It is deterministic: no model calls and no scraping, only public APIs.
2. **Claim check**, `/check-claims` in Claude Code. It checks every claim in a manuscript that carries a citation against the cited source's own text, from your PDFs or an open-access copy. It writes an .xlsx, a commented copy of the manuscript and JSON. See [Claim check](#claim-check).

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
| `REFAUDIT_MAILTO` | your e-mail address, sent to Crossref and OpenAlex for their polite pools, and (claim check only) to Unpaywall, which requires one. Any address you read works; it is never written to the cache or the reports. |
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

## Claim check

Part 2 asks, for each sentence that cites a source: does that source, read in full, actually support the sentence?

The work is split in two:
- **Deterministic steps in Python** (`refaudit claims …`). These extract claims and citations, match them to the reference list, get the source texts, pull candidate passages, check quotes and build the reports.
- **Judging by Claude Code subagents** (`.claude/`). This runs on your Claude plan with no API key.

Part 1 (`refaudit FILE`) is unchanged and makes no model calls.

### Workflow

1. Put the PDFs you have into a folder. Any file names work; EPUB, DOCX, HTML and TXT are fine too. A file whose name contains `supp` is attached to its reference as supplementary material.
2. In Claude Code, in this repository, run:

   ```
   /check-claims manuscript.docx --sources path/to/pdfs
   ```

3. Read `manuscript_claims.xlsx` and `manuscript_claims_comments.docx`, a copy of the manuscript with a Word comment on every citation that isn't GREEN.
4. Upload the PDFs listed on the **PDFs to upload** sheet into the folder and run `/check-claims` again. Only sources whose text changed are judged again; `--force` redoes everything.

Options are `--sources DIR`, `--model M` (default `fable`), `--effort E` (default `max`), `--out DIR` and `--force`.

### Running it locally or in a cloud session

- **Locally** (best for paywalled PDFs on your disk): clone the repository, `pip install -e .`, and install pandoc and poppler-utils. Optionally install tesseract-ocr for scanned PDFs. Start `claude` in the repository and run `/check-claims` with paths anywhere on your disk.
- **In a cloud session:** commit the manuscript and PDFs under `inputs/`, and give the environment **Full** network access, because open-access copies come from many publisher hosts. Then run `/check-claims inputs/manuscript.docx --sources inputs/pdfs`.

So that unattended runs don't stop at permission prompts, copy `.claude/settings.example.json` to `.claude/settings.json`. It allows `refaudit claims`, pandoc, pdftotext, pdftoppm and tesseract, the two judge agents, and writes to the verdict folders. It also registers the judges' two hooks at settings level, limited to the judges' own tool calls, so they apply even where agent hooks are skipped. Claude Code would not write that file itself, because it changes Claude's own permissions.

The two agents also load only in sessions started after `.claude/agents/` exists; restart once after pulling this branch. Trust the folder when Claude Code asks: until then it skips the hooks in the agents' files.

### What happens

1. **`refaudit claims prepare manuscript.docx [--sources DIR] [--out DIR]`**
   - Reads the manuscript with `pandoc --track-changes=accept`, or python-docx without pandoc, leaving out the reference section.
   - Splits it into sentences (English and Polish abbreviations).
   - Finds every APA in-text citation and makes one row per occurrence.
   - Matches each citation to the reference list by first-author surname (with Polish case endings), author count, year and letter. Unmatched and ambiguous citations are GREY.
   - Uses part 1 for each cited reference's DOI and notices.
   - Gets each source's text, in this order:
     - **your file**, matched by a DOI in the file, the title on its first page, or an AuthorYear file name;
     - **an open-access copy**, from URLs given by Unpaywall, OpenAlex, Europe PMC full-text XML or Semantic Scholar (only PDFs and Europe PMC XML are read; landing pages are not scraped and no shadow libraries are used);
       a host that refuses a download (usually a bot check, as at SAGE, Wiley and PMC's PDF links) is skipped for the rest of the run and named in the Summary sheet;
     - **the abstract**, from OpenAlex, Crossref or Semantic Scholar.
   - Keeps a text only if its title (fuzzy ≥ 85) and first author appear on its first pages.
   - Reads PDFs with `pdftotext -layout` page by page, splitting two-column pages and finding printed page numbers, so evidence reads "p. 540 (PDF p. 3)". It falls back to pypdf, and uses tesseract OCR for pages without text.
   - Writes `packets/<refkey>.json` for each source: metadata, evidence level, abstract, every citing claim, and its best BM25 passages plus any passage containing one of the claim's numbers.
   - Only identifiers (DOIs) go to these services, never manuscript text.
2. **Judging** (`/check-claims`): one `claim-judge` subagent per source, in parallel batches of up to five.
   - Each reads the source once and judges each of its citations separately.
   - Each writes `verdicts/<refkey>.json` with the verdict, type of support, severity, explanation, one or two verbatim quotes with pages, a minimal fix, a better reference from the list if there is one, and its confidence.
   - The judges may run only `refaudit claims candidates` and `status`, and have no web tools. A hook enforces this where Claude Code runs the agents' hooks (see below).
3. **`refaudit claims verify WORK`**
   - Checks every evidence quote against the source text on the stated page (fuzzy ≥ 95 after normalizing whitespace, hyphenation and ligatures).
   - Compares page locators, matches the manuscript's direct quotations verbatim, and lists the claim's numbers as found or not found.
   - Picks rows for a blind second opinion: every row that isn't GREEN, every low-confidence row and a random 10% of GREEN rows.
   - Before the second opinions, `refaudit claims seal WORK` moves the first verdicts out of the work folder. The `claim-second-opinion` subagent therefore cannot see them, even where hooks don't run, and its hook blocks the rest. The next `verify` brings them back and compares the two opinions.
4. **`refaudit claims report WORK`**: writes `<stem>_claims.xlsx`, `<stem>_claims_comments.docx` and `<stem>_claims.json`.

`refaudit claims status WORK` prints, as JSON, what still needs judging. `refaudit claims candidates WORK C012` lists the passages in the other cited sources that best fit claim C012.

**Without Claude Code**, `prepare` and `report` still run. The report then shows each source's evidence level and each claim's candidate passages, with every claim GREY ("not judged yet").

### Verdicts and statuses

| Verdict | Meaning | Status |
|---|---|---|
| SUPPORTED | The source states this | GREEN (full text or web only) |
| SUPPORTED-WITH-CAVEAT | Substance right; a word, qualifier, number format or page locator needs fixing | YELLOW |
| SECONDARY | The source reports this from another work; cite the original or use "as cited in" | YELLOW |
| PARTIALLY-SUPPORTED | Only part of the claim is in the source, or it holds only for a narrower population, measure, design or condition | ORANGE |
| OVERSTATED | Facts right but stated more strongly than the source: causal wording for correlational data, overgeneralization, speculation as a finding | ORANGE |
| NOT-SUPPORTED | The source contradicts the claim (reversed direction, wrong number) or doesn't address it after a full search | RED |
| MISATTRIBUTED | The claim is right but belongs to another source (named if it is in the list) | RED |
| UNVERIFIABLE | No readable text, or only an abstract that doesn't settle the claim | GREY |
| DISPUTED | The two judges disagree; both rationales are shown | ORANGE |

These rules then adjust the status:
- SUPPORTED resting on ABSTRACT or PREPRINT evidence is YELLOW ("confirm in full text" or "checked against preprint").
- A retracted source is RED, and one with an expression of concern is PURPLE (from part 1).
- An evidence quote not found on its stated page is ORANGE ("quote not found, check by hand").
- A direct quotation that isn't verbatim is ORANGE. One on another page than cited, or a wrong page locator, is YELLOW.
- The row status is the worst of these, in part 1's order.

Rows that aren't GREEN get a **severity**: CRITICAL (the meaning changes: a reversed direction, a wrong key number, a central claim misattributed), MAJOR, MINOR or NOTE.

**Evidence levels:**
- FULL: the published version or accepted manuscript;
- PREPRINT;
- WEB: a web page or report read in full;
- ABSTRACT;
- NONE.

The workbook's sheets are:
- **Claims**: one row per citation;
- **Sources**: one row per reference, with its text origin, pages, identity check and notice;
- **PDFs to upload**: sources at ABSTRACT, PREPRINT or NONE, ranked by how many of their claims aren't GREEN;
- **Summary**: counts, unmatched citations, uncited entries, run info and second-opinion agreement;
- **Legend**.

### Cost

Each source gets one judge at max effort (Fable by default), plus a second opinion for every non-GREEN row, every low-confidence row and 10% of the GREEN rows. A manuscript citing 50 sources therefore runs 50+ judges, each reading a full paper.

To spend less:
- choose a lighter model or effort, for example `/check-claims ms.docx --model sonnet --effort high`;
- check part of a manuscript first;
- rely on the cache: re-runs judge only claims whose text, citation or source text changed.

If your plan's limit for a model is reached mid-run, run `/check-claims` again with another `--model`: verdicts already written are kept, and the Summary sheet records the model you name.

The design decisions, known limits and open questions are in [NOTES.md](NOTES.md). The acceptance run, with its outputs, is described in [examples/README.md](examples/README.md).

### External tools

- pandoc: optional; without it, python-docx is used.
- poppler-utils (`pdftotext`, `pdftoppm`): pypdf is the fallback.
- tesseract-ocr with `eng` and `pol` data: optional, for scanned PDFs.

On Ubuntu:

```bash
sudo apt install pandoc poppler-utils tesseract-ocr tesseract-ocr-pol
```

## Statuses and colours (part 1)

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

refaudit uses the APIs politely. It sends `REFAUDIT_MAILTO` to Crossref and OpenAlex only, as `mailto` and in the User-Agent (the claim check also sends it to Unpaywall as `email`). It makes at most 5 requests per second and uses 20-second timeouts. It retries with backoff (2, 4, 8 and 16 s) on 429, 5xx and network errors. Answers, including "not found", are kept in an on-disk JSON cache (`--cache DIR`) and fetched again after 7 days. Delete the cache directory to force fresh answers.

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

This is the live smoke test. It runs the CLI on the three samples against the real APIs and asserts the statuses in `tests/expected.csv`. With `REFAUDIT_MAILTO` set, it also fetches the claim-check fixture's source texts and checks their evidence levels.

The claim check's offline tests cover sentence splitting, citation forms and matching, your files, PDF pages and labels, BM25, quote checks, the reports and the hooks. `tests/test_claims_acceptance.py` checks the acceptance criteria against the committed run in `examples/`. `python tests/make_claims_fixture.py` rebuilds `tests/fixtures/claims_sample.docx` and `tests/claims_expected.csv`; `--download` fetches the two CC-BY PDFs again.

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
