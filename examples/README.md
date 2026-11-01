# Example outputs

## Reference check (part 1)

`sample_refaudit.xlsx`, `sample_pl_refaudit.xlsx` and `sample_bib_refaudit.xlsx` are `refaudit FILE` run on the
three samples in `tests/fixtures/`. The ten cases they contain are listed in `tests/expected.csv`.

## Claim check (part 2): the acceptance run

| File | What it is |
|---|---|
| `claims_sample_claims.xlsx` | The report, with the sheets Claims, Sources, PDFs to upload, Summary and Legend. |
| `claims_sample_claims_comments.docx` | The manuscript with a Word comment, by "refaudit", on each citation that isn't GREEN. |
| `claims_sample_claims.json` | Every row, verdict, second opinion and check result, as data. |
| `claims_sample_claims/` | The work folder. It holds `claims.json`, the judges' `verdicts/` and `second/` files, the verdict caches and the check results. `texts/` and `packets/` are not committed. |

### The run

The manuscript is `tests/fixtures/claims_sample.docx`, built by `tests/make_claims_fixture.py`. It has 14
citations of ten references:
- **Nine CC-BY open-access articles** on conspiracy beliefs.
- **Goertzel (1994).** A closed article, for case 9.
- **Two of them delivered as your files.** The PDFs of van Prooijen et al. (2023) and Pilch et al. (2023) are in
  `tests/fixtures/claims_sources/`.

It was run with the `/check-claims` procedure:

```
/check-claims tests/fixtures/claims_sample.docx --sources tests/fixtures/claims_sources --out examples
```

**Network and e-mail.** The cloud environment had Full network access. `REFAUDIT_MAILTO` was set for Unpaywall;
the address is in no committed file.

**Where the texts came from.**

| Source | Evidence | Text from |
|---|---|---|
| Alsuhibani et al., 2022 | FULL | PLOS PDF (Unpaywall) |
| Goertzel, 1994 | ABSTRACT | OpenAlex abstract: closed article, no PDF given |
| Granados Samayoa et al., 2022 | FULL | PLOS PDF (Unpaywall) |
| Greenburgh et al., 2022 | FULL | Europe PMC XML |
| Imhoff & Lamberty, 2020 | FULL | Europe PMC XML (SAGE's PDF link refused the download) |
| O'Mahony et al., 2023 | FULL | PLOS PDF (Unpaywall) |
| Pilch et al., 2023 | FULL | your PDF |
| Siemiątkowski et al., 2026 | FULL | Europe PMC XML (Wiley's PDF link refused the download) |
| Uscinski et al., 2022 | FULL | PLOS PDF (Unpaywall) |
| van Prooijen et al., 2023 | FULL | your PDF (printed pages 5709–5716 on PDF pages 1–8) |

**Refused downloads.** journals.sagepub.com, onlinelibrary.wiley.com and pmc.ncbi.nlm.nih.gov answered automated
downloads with a bot check (HTTP 403). refaudit skipped those hosts and used the next listed copy. The Summary
sheet names them.

**Judges.**
- **First judgments.** Fable at max effort judged five sources: Alsuhibani, Goertzel, Granados Samayoa,
  Greenburgh and Imhoff. Then the account's Fable usage limit was reached, so Opus at max effort judged the
  other five. The Summary sheet says so.
- **Second opinions.** Opus at max effort gave all nine.
- **Blindness.** While the second opinions ran, the first verdicts were moved out of the work folder. That step
  is now `refaudit claims seal`.

### Results

| ID | Case | Citation | Status | Verdict (second opinion) | Fix proposed |
|---|---|---|---|---|---|
| C001 | 1 correct | Uscinski et al. (2022) | GREEN | SUPPORTED | — |
| C002 | 9 no text | Goertzel (1994) | GREY | UNVERIFIABLE (agrees) | check the full text, or replace the citation |
| C003 | 7 secondary | Imhoff & Lamberty, 2020 | YELLOW | SECONDARY (agrees) | "(Frankovic, 2020, as cited in Imhoff & Lamberty, 2020)" |
| C004 | 10 your PDF | Pilch et al., 2023 | GREEN | SUPPORTED | — |
| C005 | 4 wrong % | Pilch et al., 2023 | RED | NOT-SUPPORTED, CRITICAL (agrees) | "Nearly half … 49.6% of the studies …" |
| C006 | correct | Greenburgh et al., 2022 | GREEN | SUPPORTED | — |
| C007 | 3 causal | Alsuhibani et al., 2022 | ORANGE | OVERSTATED (agrees) | "Loneliness is associated with belief in …" |
| C008 | correct | Siemiątkowski et al., 2026 | GREEN | SUPPORTED | — |
| C009 | 2 reversed | Imhoff & Lamberty, 2020 | RED | NOT-SUPPORTED, CRITICAL (agrees) | "… reported less containment-related behaviour …" |
| C010 | 8 wrong page | van Prooijen et al., 2023, p. 5713 | YELLOW | SUPPORTED-WITH-CAVEAT (agrees) | "p. 5715" (the quotation check also found it there) |
| C011 | correct | Granados Samayoa et al., 2022 | GREEN | SUPPORTED | — |
| C012 | 6 speculation | Granados Samayoa et al. (2022) | ORANGE | OVERSTATED (agrees) | "… suggested that this may happen because …" |
| C013 | correct | O'Mahony et al., 2023 | GREEN | SUPPORTED (agrees; the 10% GREEN sample) | — |
| C014 | 5 misattributed | Greenburgh et al., 2022 | RED | MISATTRIBUTED, CRITICAL (agrees) | cite O'Mahony et al. (2023), named as the better-fitting reference |

**The acceptance criteria hold.**
- Every planted case has its expected status.
- No correct claim is RED.
- All 46 evidence quotes (28 from the first judges, 18 from the second) were found on their stated pages.
- The manuscript's direct quotation was found verbatim, on printed page 5715 rather than the cited 5713.

`tests/test_claims_acceptance.py` checks this against these files. No row is DISPUTED.

**Visual check.**
- **Workbook.** Opened with openpyxl: five sheets, status fills, frozen header rows, filters, and DOI links on the
  Sources and PDFs to upload sheets.
- **Commented docx.** Rendered with LibreOffice, with the comments in the margin. Each comment sits on its own
  citation and gives the status, verdict, explanation, fix, better-fitting reference and an evidence quote with
  its page.
