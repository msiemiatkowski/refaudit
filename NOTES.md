# Notes on part 2 (claim checking)

## Decisions

**Command line.** `refaudit claims prepare|status|verify|seal|report|candidates` is a subcommand group. `cli.main`
hands any argument list that starts with `claims` to `claims_cli.main`, so `refaudit FILE` keeps working exactly as
before, and part 1 still makes no model calls. Version 2.0.0.

**Work folder.** Everything for one manuscript lives in `<stem>_claims/`, next to the manuscript (or in `--out`):
- `claims.json`: the claims, references and files;
- `texts/` (gitignored): the source texts as JSON, plus a `.txt` with page headers for the judges;
- `packets/`, `verdicts/`, `second/`;
- the verdict caches.

The outputs `<stem>_claims.xlsx`, `<stem>_claims_comments.docx` and `<stem>_claims.json` sit next to that folder.

**Manuscript text.**
- **pandoc first.** `pandoc --track-changes=accept -t plain --wrap=none` is used when pandoc is installed, then
  python-docx (part 1's paragraph reader, which also skips tracked deletions).
- **Reference section.** The reference heading is found with part 1's logic. The paragraphs after it are dropped
  only while they are entries from part 1's parse, so appendices after the reference list are still checked.

**Scope hint.** For a parenthetical citation it is the clause before the citation, back to the previous citation or
the sentence start, as specified. For a narrative citation ("Douglas et al. (2017) showed that …") the claim
follows the citation, so the hint is the text after it, up to the next citation or the sentence end.

**Matching citations to references.**
- **Order of tests.** First-author surname (diacritics folded), numeric year and letter come first. Author count
  ("et al." means 3 or more; two names must both match) then picks between several candidates.
- **Inexact single match.** One candidate whose letter or author count differs is still matched, with a note.
- **Compound surnames.** A narrative "Granados Samayoa et al. (2022)" keeps both words when the list has that
  surname; "In Douglas et al. (2017)" stays "Douglas".
- **Polish inflection.** Narrative citations decline surnames ("Bilewicza", "Kowalskiej"), so a known Polish case
  ending is allowed after the surname. "Kowal" still doesn't match "Kowalski".
- **As cited in.** In "X, 1954, as cited in Y, 2006" only Y is an occurrence, because APA lists only the
  secondary source. X is kept as `original`.

**Your files.**
- **Matching.** A file matches a reference by a DOI in its first pages or metadata, else by the title on its first
  page (partial ratio ≥ 90), else by an AuthorYear file name.
- **Identity check.** Every text, yours or downloaded, must then pass the identity check: title ≥ 85 and the first
  author on the first pages.
- **Version.** Your files are taken as published unless the first pages say preprint (PsyArXiv, "not peer
  reviewed", "manuscript submitted for publication", "under review") or accepted manuscript. Frontiers' "This
  article was submitted to <section>" and a bare "Accepted: <date>" don't count.

**Open-access copies.**
- **Sources of URLs.** Only URLs from Unpaywall (`oa_locations[].url_for_pdf`), OpenAlex (`best_oa_location`,
  `locations[]`, `open_access.oa_url` if it is a PDF), Europe PMC (full-text XML for open-access PMC records) and
  Semantic Scholar (`openAccessPdf`) are tried.
- **Order.** Published versions come before accepted ones, and preprints come last. Within a version, paged PDFs
  come before Europe PMC XML, so evidence can cite pages. When two services list the same URL, the first listing
  (Unpaywall's) keeps its version: a Semantic Scholar copy without one had pushed a published PDF below an
  accepted manuscript.
- **What is read.** A response is used only if it is a PDF (`%PDF`) or Europe PMC XML. HTML landing pages are
  never read. Europe PMC XML gets a title page (title, authors, abstract), so it can pass the identity check.
- **Politeness.** Downloads go through part 1's polite client: mailto, at most 5 requests per second, backoff and
  20 s timeouts.
- **Refused downloads.** A host that refuses a download (HTTP 401–403, usually a bot check) is skipped for the
  rest of the run, but other hosts are still tried, and the Summary names the refusing hosts. Before this, one
  refusal stopped every download.

**PDF text.**
- **Columns.** `pdftotext -layout` keeps two columns side by side, which would interleave sentences. A gutter
  detector splits such pages and puts the left column first; full-width lines (titles) are left alone.
- **Printed page numbers.** They come from the PDF's own `/PageLabels`, unless those are just 1…N, as in
  Cambridge's PDFs. Otherwise each page's first and last three lines are scanned, before the columns are split
  (which would cut a running head in two), for the offset (printed − PDF page) that most pages agree on.
  Psychological Medicine's 5709–5716 on PDF pages 1–8 is found this way.
- **OCR.** Pages with almost no text are OCRed with tesseract (`eng+pol`) when installed. A source with no text
  and no OCR is NONE, with the reason.

**Retrieval.** BM25 (k1 = 1.5, b = 0.75) runs over windows of about 120 words, 90 words apart, per page. Passages
containing one of the claim's numbers are added; numbers are normalized, so `1,200` = `1200` and `0,45` = `.45`.

**Second opinions.**
- **Which rows.** Every row whose first status isn't GREEN, every low-confidence row, and a stable random 10%
  (at least one) of the GREEN rows. Stability comes from hashing the claim's cache key.
- **Agreement.** Two verdicts agree when they fall in the same group: supported (SUPPORTED, WITH-CAVEAT,
  SECONDARY), partly (PARTIALLY-SUPPORTED, OVERSTATED), wrong (NOT-SUPPORTED, MISATTRIBUTED) or unverifiable.
  Otherwise the row is DISPUTED (ORANGE) and both rationales are shown. Strict verdict equality would turn many
  SUPPORTED vs WITH-CAVEAT pairs into disputes.
- **Blindness.** It does not depend on the judges' good behaviour. Before the second opinions, `refaudit claims
  seal` moves the first verdicts (`verdicts/`, the verdict cache, the check results) out of the work folder into a
  hidden sibling folder; `verify` brings them back. While they are away, `status` still knows what was judged.
  On top of that, a PreToolUse hook stops the second judge from reading `verdicts/`, the sealed folder, the
  caches or the reports, and from searching outside `texts/` and `packets/`. The hook alone was not enough: in
  the acceptance run the agents' hooks did not run at all (see Known limits).

**Judges' Bash.** A subagent's `tools` field can't restrict Bash to particular commands. A PreToolUse hook
(`.claude/hooks/refaudit_only.py`) therefore allows only single `refaudit claims candidates|status` commands. The
judges have no web tools.
- **Where the hooks are declared.** They are in each agent's frontmatter. `.claude/settings.example.json`
  declares them again at settings level, with `--only <agent>` so they touch only the judges' tool calls
  (`agent_type`), because settings hooks also run inside subagents.
- **Fail closed.** A hook that crashes or gets bad input blocks the call; by default a crashing hook lets it
  through.

**Cache.**
- **Key.** Verdicts are cached by sentence, citation, year, reference, the source text's sha256 and
  `PROMPT_VERSION`. Adding a PDF changes that source's hash, so only its claims are judged again.
- **Edits.** Editing a sentence re-judges only that sentence.
- **Re-runs.** `prepare` first files any verdicts from an earlier run into the cache, then clears `verdicts/` and
  `second/`, so a re-numbered claim can't pick up a stale verdict.

**Statuses not covered by the spec.**
- A matched claim that hasn't been judged is GREY ("not judged yet").
- SUPPORTED with no text at all (NONE) is treated like ABSTRACT (YELLOW, "confirm in full text").
- When a judge gives no severity, these defaults apply:
  - a retraction is CRITICAL;
  - an expression of concern, an unmatched citation or a dispute is MAJOR;
  - other GREY and YELLOW rows are NOTE.

**Word comments.** They are anchored on the citation text as written, in a copy of the manuscript with tracked
changes accepted. The runs are split so the comment covers only the citation.

**The claude.ai page** (`web/claude/`, built by `tools/build_claude_page.py`).
- **Why a claude.ai page.** It lets a page judge claims on the user's Claude plan with no API key: it asks Claude
  through the page's `sample` capability, and gives files back through `downloads`.
- **No network.** A claude.ai page cannot reach any other host. So the page prepares offline: your files only,
  no lookups.
- **Pyodide from the page's own files.** Pyodide 0.29.5, lxml and the pure-Python wheels are published with the
  page. claude.ai serves no .zip or .whl files, so those archives are published base64-encoded as `.txt`. A fetch
  shim in the worker decodes them, and Pyodide still checks each wheel against its lock file.
- **The same engine.** `refaudit/claims_web.py` wraps `claims_cli`:
  - the page plays the skill;
  - each judge's answer is filed as `verdicts/<refkey>.json`;
  - `verify` and `report` are the command line's.
- **One question per source.** It holds:
  - the Rules, Verdicts and Output sections read from `.claude/agents/claim-judge.md`;
  - the claims;
  - the best passages from the other cited sources, for spotting misattributions;
  - the source's whole text.
- **Long sources.** A text over the 256 KB question limit keeps its first pages and the pages most relevant to the
  claims, and says how many pages were left out.
- **Blind second opinions.** These are blind by construction: the second question never contains the first
  verdict, and it is never served from claude.ai's answer cache (`cache: false`). First questions are cached for
  24 hours, so a re-run replays unchanged answers.
- **Sources without text.** These get UNVERIFIABLE without asking Claude. The same rule now skips their second
  opinions everywhere, since a second judge would have nothing to read either.
- **Pacing.** Questions go two at a time, from one click. A usage limit (`rate_limited`) stops the run with no
  retry; what was judged is kept, and "Continue the check" resumes, for example with another model.
- **rapidfuzz.** It is not available in Pyodide. `refaudit/fuzzy.py` gives a pure-Python `partial_ratio`:
  shared k-grams pick the alignments, scored with the existing exact `lcs_ratio`. It never scores above rapidfuzz,
  and agrees with it at every threshold the claim check uses: 400 real quotes and every title against every first
  page were tested, plus a unit test.
- **requests.** Its import is optional, since the page has no network to use it on.

## Known limits

- **`.claude/settings.json` was not written.** Claude Code's auto-mode classifier refused it because it changes
  Claude's own permissions. The intended rules are in `.claude/settings.example.json`; copy it to activate them.
- **Agents need a restart.** The agents load only in sessions started after `.claude/agents/` exists; the first
  agents directory created mid-session isn't hot-reloaded. Restart Claude Code once after pulling.
- **The agents' hooks did not run in the acceptance session.** The judges' transcripts show no hook events, and
  they ran read-only shell commands (`ls`, `cat`, `grep`, `python3 -c` with `refaudit.quotes`) that the hook
  would have blocked. Claude Code's documentation says frontmatter hooks of project agents are skipped until the
  folder is trusted, and how cloud sessions answer that is not documented; the agents had also been created
  mid-session. Nothing harmful happened, and blindness held because the first verdicts were moved away (now
  `refaudit claims seal`). To enforce the hooks, trust the folder, restart Claude Code, and copy
  `.claude/settings.example.json` to `.claude/settings.json`.
- **Some publishers refuse automated downloads.** SAGE, Wiley and PMC's PDF links answered with bot checks
  (HTTP 403). refaudit doesn't get around them; it uses Europe PMC's XML or another listed copy, or asks for
  your PDF.
- **Usage limits.** A long run can hit the account's limit for a model. The acceptance run hit the Fable limit
  after 5 of 10 sources; the rest was judged with `--model opus`. Verdicts already written are kept, so a run can
  continue later or with another model, and the Summary records what was used.
- **Cross-language retrieval.** BM25 is lexical, so a Polish claim retrieves little from an English source. The
  candidate passages are hints only; the judges read the full text.
- **PDF layouts.** Column splitting and page-label detection are heuristics. Complex layouts (three columns,
  sideways tables, running heads with other numbers) can defeat them. Quotes are then flagged ORANGE "check by
  hand", never silently accepted.
- **Narrative group authors.** A narrative citation with a multi-word group author ("World Health Organization
  (2020) says …") is not recognized; parenthetical group authors are. Non-APA citation styles (numbered,
  footnotes) are not supported.
- **Comments inside fields.** A citation inside a hyperlink or content control (some reference managers) gets no
  Word comment, though its row is still in the workbook.
- **Paywalled sources.** These stay at ABSTRACT or NONE until you upload the PDF. Semantic Scholar's unauthenticated
  limit (about 1 request per second, shared) is easily hit; it is retried and then skipped, and the Summary says so.
- **Cost.** Max-effort judges read whole papers. See the README for ways to lower it.
- **The claude.ai page:**
  - It cannot look anything up (no network). It judges at effort "high" at most.
  - It loses its work if the page is reloaded. claude.ai's 24-hour answer cache makes a re-run cheap.
  - It was tested in Chromium with a stand-in for Claude (`tools/test_claude_page.js`). Its first real run happens
    when you open it in claude.ai.

## Acceptance

The acceptance run passed. Its outputs are in `examples/`, described in `examples/README.md`.

**The fixture.** `tests/make_claims_fixture.py` builds `tests/fixtures/claims_sample.docx`. It has five short
sections, 14 citations and ten references:
- nine CC-BY open-access articles on conspiracy beliefs;
- Goertzel (1994), which is closed, for case 9.

**The planted cases.** Ten cases, plus four correct claims, are listed in `tests/claims_expected.csv`.

**Your PDFs.** Two CC-BY PDFs are delivered through `--sources`:
- van Prooijen et al. (2023), Psychological Medicine, which prints pages 5709–5716 on PDF pages 1–8;
- Pilch et al. (2023), Frontiers in Psychology.

**The run.**
- **Command:** the `/check-claims` procedure with `--sources tests/fixtures/claims_sources --out examples`.
- **Network:** Full network access; the e-mail for Unpaywall was set in the environment, not committed.
- **Texts:**
  - full text for all nine open-access sources:
    - two from your PDFs;
    - four from PLOS PDFs via Unpaywall;
    - three from Europe PMC XML (SAGE, Wiley and PMC's PDF links refused downloads);
  - the abstract only for Goertzel (1994).
- **Judges:**
  - Fable at max effort for 5 sources;
  - Opus at max effort for the other 5 and for all 9 second opinions (Fable limit reached).
- **Blindness:** the first verdicts were sealed away while the second opinions ran.

| Case | Planted | Expected | Got (first judge / second opinion) |
|---|---|---|---|
| 1 | correct claim (Uscinski et al., 2022) | GREEN | GREEN, SUPPORTED |
| 2 | reversed direction (Imhoff & Lamberty, 2020) | RED | RED, NOT-SUPPORTED / agrees |
| 3 | causal wording, correlational data (Alsuhibani et al., 2022) | ORANGE | ORANGE, OVERSTATED / agrees |
| 4 | wrong percentage, 71.2% for 49.6% (Pilch et al., 2023) | RED | RED, NOT-SUPPORTED / agrees |
| 5 | belongs to O'Mahony et al. (2023), cited to Greenburgh et al. (2022) | RED | RED, MISATTRIBUTED, alternative omahony2023 / agrees |
| 6 | discussion speculation as a finding (Granados Samayoa et al., 2022) | ORANGE | ORANGE, OVERSTATED / agrees |
| 7 | secondary: a poll the source cites (Imhoff & Lamberty, 2020) | YELLOW | YELLOW, SECONDARY / agrees |
| 8 | quotation cited as p. 5713, printed on p. 5715 (van Prooijen et al., 2023) | YELLOW | YELLOW, SUPPORTED-WITH-CAVEAT / agrees; quotation check: "on printed page 5715" |
| 9 | closed article, no PDF (Goertzel, 1994) | GREY | GREY, UNVERIFIABLE / agrees |
| 10 | correct claim found only in the uploaded PDF's body (Pilch et al., 2023) | GREEN | GREEN, SUPPORTED |

**Results.**
- **Correct claims.** The four extra correct claims are GREEN; one of them (O'Mahony et al., 2023) was the 10%
  GREEN sample and its second opinion agreed.
- **Quotes.** All 46 evidence quotes (28 first, 18 second) were found on their stated pages.
- **Disputes.** No row is DISPUTED.
- **Test.** `tests/test_claims_acceptance.py` checks these criteria against the committed outputs.
- **Visual check.** The xlsx was opened with openpyxl: five sheets, status fills, frozen headers, filters, DOI
  links. The commented docx was rendered with LibreOffice; its comments sit on the right citations, which
  exposed and fixed a bug: a repeated citation got its comment on the first occurrence.

**Fixes found on real articles.**
- **One refusing host stopped all downloads.**
- **Duplicate listings lost their version.** They demoted a published PDF.
- **Europe PMC XML failed the identity check.**
- **A Frontiers PDF was taken for a preprint.**
- **Printed page numbers were missed.** This happened under a default `/PageLabels` and with two-column
  running heads.
- **Compound surnames were cut.** "Granados Samayoa" in narrative citations lost its first word.
- **"COVID-19" gave a number.** Its 19 was read as a number in the claim.
- **Re-runs lost the fetch report.** A re-run that reused texts dropped the record of the run that fetched them.

**No real manuscript.** `inputs/` holds none, so none was run.

## Open questions

- Should disagreement be judged on exact verdicts rather than groups, or should a DISPUTED row show the more
  severe of the two verdicts?
- Should cached source texts be deleted after a run? They can contain copyrighted text, and are kept for re-runs
  only.
- Should a source with a retraction still be judged? It is now, and the row is RED either way.
- Should the candidates helper also search references that are listed but never cited? A misattributed claim
  may belong to one of them, but their texts are not fetched now, to save requests.
- When a model's usage limit is reached mid-run, should the skill switch to another model by itself, or stop and
  ask? In the acceptance run the switch was made by hand and recorded in the Summary.
- Should the "PDFs to upload" sheet also list sources whose PDF was refused by the publisher's bot check, when
  only XML or an accepted manuscript was found? They are FULL now, so they are not listed.
