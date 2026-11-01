"""Build the claim-check acceptance fixture: tests/fixtures/claims_sample.docx and tests/claims_expected.csv.

The manuscript cites nine CC-BY open-access articles and one closed article (Goertzel, 1994), with ten planted
cases. Two of the CC-BY PDFs are delivered as "your" files in tests/fixtures/claims_sources/ (run with
--download to fetch them again from the publishers).

Run:  python tests/make_claims_fixture.py [--download]
Then: /check-claims tests/fixtures/claims_sample.docx --sources tests/fixtures/claims_sources
"""

from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

import docx

from make_fixtures import add_reference

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"

# The PDFs delivered through --sources (both CC BY 4.0), with where they came from.
SOURCES = {
    "vanProoijen_2023_PsycholMed.pdf": (
        "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/A82149DB513C00AA9575E8C062AD97BF/"
        "S0033291722002938a.pdf/div-class-title-a-longitudinal-analysis-of-conspiracy-beliefs-and-covid-19-health-"
        "responses-div.pdf",
        "9c5b8345b3d8fc2dd7eac4b5af22a3a8fc95d9b9fa6cd37b4cc76542a2ace08f"),
    "Pilch_2023_FrontPsychol.pdf": (
        "https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2023.1075779/pdf",
        "8be566f9f76c2214912be70051e098abb26bb0da5d6343f911d05e95991cf6b2"),
}

# Each sentence: (text, case, expected status, expected verdict, what was planted, what the source says).
# case "" = an uncited sentence; "extra" = an unplanted correct claim (it must not be RED).
PARAGRAPHS = [
    [
        ("Conspiracy theories are often described as a growing problem of our time.", "", "", "", "", ""),
        ("Contrary to this impression, Uscinski et al. (2022) found no systematic evidence that belief in conspiracy "
         "theories has increased over time, either in the United States or in six European countries.",
         "1", "GREEN", "SUPPORTED", "correct claim",
         "Abstract: 'In no instance do we observe systematic evidence for an increase in conspiracism' (US, Study 1; "
         "six European countries, Study 2)."),
        ("Goertzel (1994) argued that conspiracy theories offer people simple explanations for events that are "
         "otherwise hard to understand.",
         "9", "GREY", "UNVERIFIABLE", "closed article, no PDF: only the OpenAlex abstract, which does not settle it",
         "Political Psychology 1994 is not open access anywhere; the abstract reports survey correlates only."),
        ("At the beginning of March 2020, 13% of Americans were convinced that the coronavirus is a hoax "
         "(Imhoff & Lamberty, 2020).",
         "7", "YELLOW", "SECONDARY", "secondary citation",
         "Introduction: the 13% comes from a YouGov survey, cited as (Frankovic, 2020)."),
    ],
    [
        ("Between 2018 and 2021, the Generic Conspiracist Beliefs Scale was the most frequently used measure of "
         "general conspiracy belief (Pilch et al., 2023).",
         "10", "GREEN", "SUPPORTED", "correct claim supported only by the uploaded PDF (not in the abstract)",
         "Section 3.1 (printed page 3): 'The GCBS was the most frequently used measure of general belief on "
         "conspiracy theories.'"),
        ("Most of this research comes from Europe: 71.2% of the studies were conducted in European countries "
         "(Pilch et al., 2023).",
         "4", "RED", "NOT-SUPPORTED", "wrong percentage (71.2% is the share of cross-sectional studies)",
         "Abstract and Results: 'Almost half of the studies (49.6%) were conducted in European countries.'"),
    ],
    [
        ("In a pre-registered online study of 1,000 participants, more paranoid individuals were more likely to "
         "endorse conspiracy items describing intentional and self-referential harm (Greenburgh et al., 2022).",
         "extra", "GREEN", "SUPPORTED", "correct claim", "Abstract."),
        ("Loneliness drives people towards conspiracy theories (Alsuhibani et al., 2022).",
         "3", "ORANGE", "OVERSTATED", "causal wording for a correlational finding",
         "Cross-sectional surveys; 'we make no strong claims about the causal role of the psychological processes "
         "identified'."),
        ("Across 36 countries, greater societal freedom, as measured by the Human Freedom Index, was associated with "
         "weaker generic conspiracy beliefs (Siemiątkowski et al., 2026).",
         "extra", "GREEN", "SUPPORTED", "correct claim", "Abstract and Study 1 (N = 6353, 36 countries)."),
    ],
    [
        ("People who believed that COVID-19 is a hoax reported more containment-related behaviour, such as hygiene "
         "and physical distancing (Imhoff & Lamberty, 2020).",
         "2", "RED", "NOT-SUPPORTED", "reversed direction",
         "Results: 'containment-related behavior was negatively predicted by believing that COVID-19 was a hoax'."),
        ("In a three-wave Dutch panel study, conspiracy theories were found to “predict deteriorated health responses "
         "to Covid-19 throughout the course of the pandemic” (van Prooijen et al., 2023, p. 5713).",
         "8", "YELLOW", "SUPPORTED-WITH-CAVEAT", "direct quotation with a wrong page (it is on p. 5715)",
         "Discussion, printed page 5715 (PDF page 7) of the uploaded PDF."),
        ("Belief in COVID-19 conspiracy theories at baseline also predicted increases in generic conspiracist "
         "ideation over several months (Granados Samayoa et al., 2022).",
         "extra", "GREEN", "SUPPORTED", "correct claim", "Abstract (Studies 1 and 2)."),
        ("Granados Samayoa et al. (2022) showed that this happens because believers lose trust in authorities, which "
         "makes them receptive to other conspiracy theories.",
         "6", "ORANGE", "OVERSTATED", "a discussion speculation stated as a finding",
         "Discussion: 'Future research should address the mechanisms ... A loss of trust in authorities is one "
         "possible mechanism'."),
    ],
    [
        ("A systematic review of 25 studies found that most interventions designed to counter conspiracy beliefs "
         "were ineffective (O'Mahony et al., 2023).",
         "extra", "GREEN", "SUPPORTED", "correct claim", "Abstract."),
        ("The most effective interventions were those that fostered an analytical mindset or taught critical thinking "
         "skills (Greenburgh et al., 2022).",
         "5", "RED", "MISATTRIBUTED", "the claim belongs to O'Mahony et al. (2023); the fix should name it",
         "Greenburgh et al. study paranoia and conspiracy items, not interventions; O'Mahony et al.'s abstract "
         "states this finding."),
    ],
]

HEADINGS = ["Introduction", "Research on conspiracy beliefs", "Correlates", "Consequences for health",
            "Interventions"]

# APA 7; *...* marks italics.
REFERENCES = [
    "Alsuhibani, A., Shevlin, M., Freeman, D., Sheaves, B., & Bentall, R. P. (2022). Why conspiracy theorists are "
    "not always paranoid: Conspiracy theories and paranoia form separate factors with distinct psychological "
    "predictors. *PLOS ONE, 17*(4), e0259053. https://doi.org/10.1371/journal.pone.0259053",
    "Goertzel, T. (1994). Belief in conspiracy theories. *Political Psychology, 15*(4), 731–742. "
    "https://doi.org/10.2307/3791630",
    "Granados Samayoa, J. A., Moore, C. A., Ruisch, B. C., Boggs, S. T., Ladanyi, J. T., & Fazio, R. H. (2022). "
    "A gateway conspiracy? Belief in COVID-19 conspiracy theories prospectively predicts greater conspiracist "
    "ideation. *PLOS ONE, 17*(10), e0275502. https://doi.org/10.1371/journal.pone.0275502",
    "Greenburgh, A. G., Liefgreen, A., Bell, V., & Raihani, N. (2022). Factors affecting conspiracy theory "
    "endorsement in paranoia. *Royal Society Open Science, 9*(1), 211555. https://doi.org/10.1098/rsos.211555",
    "Imhoff, R., & Lamberty, P. (2020). A bioweapon or a hoax? The link between distinct conspiracy beliefs about "
    "the coronavirus disease (COVID-19) outbreak and pandemic behavior. *Social Psychological and Personality "
    "Science, 11*(8), 1110–1118. https://doi.org/10.1177/1948550620934692",
    "O'Mahony, C., Brassil, M., Murphy, G., & Linehan, C. (2023). The efficacy of interventions in reducing belief "
    "in conspiracy theories: A systematic review. *PLOS ONE, 18*(4), e0280902. "
    "https://doi.org/10.1371/journal.pone.0280902",
    "Pilch, I., Turska-Kawa, A., Wardawy, P., Olszanecka-Marmola, A., & Smołkowska-Jędo, W. (2023). Contemporary "
    "trends in psychological research on conspiracy beliefs. A systematic review. *Frontiers in Psychology, 14*, "
    "1075779. https://doi.org/10.3389/fpsyg.2023.1075779",
    "Siemiątkowski, M., Gkinopoulos, T., & Bilewicz, M. (2026). Free from conspiracies: The negative relationship "
    "between societal freedom and belief in generic and content-specific conspiracy theories. *British Journal of "
    "Social Psychology, 65*(1), e70021. https://doi.org/10.1111/bjso.70021",
    "Uscinski, J., Enders, A., Klofstad, C., Seelig, M., Drochon, H., Premaratne, K., & Murthi, M. (2022). Have "
    "beliefs in conspiracy theories increased over time? *PLOS ONE, 17*(7), e0270429. "
    "https://doi.org/10.1371/journal.pone.0270429",
    "van Prooijen, J.-W., Amodio, D. M., Boot, A., Eerland, A., Etienne, T., Krouwel, A. P. M., Onderco, M., "
    "Verkoeijen, P., & Zwaan, R. A. (2023). A longitudinal analysis of conspiracy beliefs and Covid-19 health "
    "responses. *Psychological Medicine, 53*(12), 5709–5716. https://doi.org/10.1017/S0033291722002938",
]


def manuscript(path: Path) -> None:
    document = docx.Document()
    document.add_heading("Conspiracy beliefs: prevalence, correlates and consequences (test manuscript)", level=0)
    for heading, sentences in zip(HEADINGS, PARAGRAPHS):
        document.add_heading(heading, level=1)
        document.add_paragraph(" ".join(s[0] for s in sentences))
    document.add_heading("References", level=1)
    for text in REFERENCES:
        add_reference(document, text)
    document.save(path)


def expected(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        out = csv.writer(f)
        out.writerow(["case", "sentence", "expected_status", "expected_verdict", "planted", "source_says"])
        for sentences in PARAGRAPHS:
            for sentence, case, status, verdict, planted, says in sentences:
                if case:
                    out.writerow([case, sentence, status, verdict, planted, says])


def download(folder: Path) -> None:
    import requests
    folder.mkdir(parents=True, exist_ok=True)
    for name, (url, sha) in SOURCES.items():
        data = requests.get(url, timeout=60, headers={"User-Agent": "refaudit-fixture"}).content
        if hashlib.sha256(data).hexdigest() != sha:
            sys.exit(f"{name}: the download from {url} is not the expected file")
        (folder / name).write_bytes(data)


def main() -> None:
    sources = FIXTURES / "claims_sources"
    if "--download" in sys.argv:
        download(sources)
    for name, (_, sha) in SOURCES.items():
        if not (sources / name).exists() or hashlib.sha256((sources / name).read_bytes()).hexdigest() != sha:
            print(f"warning: {sources / name} is missing or changed (run with --download)")
    manuscript(FIXTURES / "claims_sample.docx")
    expected(TESTS / "claims_expected.csv")
    print(f"Wrote {FIXTURES / 'claims_sample.docx'} and {TESTS / 'claims_expected.csv'}")


if __name__ == "__main__":
    main()
