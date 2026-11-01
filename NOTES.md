# Notes on part 2 (claim checking)

## Decisions

**Command line.** `refaudit claims prepare|status|verify|report|candidates` is a subcommand group. `cli.main`
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
- **Blindness.** It is enforced, not only requested: a PreToolUse hook stops the second judge from reading
  `verdicts/`, the caches or the reports, and from searching outside `texts/` and `packets/`.

**Judges' Bash.** A subagent's `tools` field can't restrict Bash to particular commands. A PreToolUse hook
(`.claude/hooks/refaudit_only.py`) therefore allows only single `refaudit claims candidates|status` commands. The
judges have no web tools.

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

## Known limits

- **`.claude/settings.json` was not written.** Claude Code's auto-mode classifier refused it because it changes
  Claude's own permissions. The intended rules are in `.claude/settings.example.json`; copy it to activate them.
- **Agents need a restart.** The agents load only in sessions started after `.claude/agents/` exists; the first
  agents directory created mid-session isn't hot-reloaded. Restart Claude Code once after pulling.
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

## Acceptance

The end-to-end acceptance needs **Full network access**. That covers the fixture manuscript citing real CC-BY
open-access articles, `tests/claims_expected.csv`, the `/check-claims` run, and the outputs in `examples/`.

In this cloud session, Unpaywall, Europe PMC, Semantic Scholar and the publisher hosts were blocked by the
environment's network policy, so the acceptance run is pending. Everything else is covered by offline tests, which
include a small paged two-column PDF and a scanned PDF for OCR.

## Open questions

- Should disagreement be judged on exact verdicts rather than groups, or should a DISPUTED row show the more
  severe of the two verdicts?
- Should cached source texts be deleted after a run? They can contain copyrighted text, and are kept for re-runs
  only.
- Should a source with a retraction still be judged? It is now, and the row is RED either way.
