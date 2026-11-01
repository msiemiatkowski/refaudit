"""Build the test inputs: tests/fixtures/sample.docx, sample_pl.docx and sample.bib.

Run:  python tests/make_fixtures.py
"""

from __future__ import annotations

import re
from pathlib import Path

import docx
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

FIXTURES = Path(__file__).parent / "fixtures"

# *...* marks italics, as in APA 7 (journal and volume; book titles).
REFERENCES = [
    # 1: correct -> GREEN
    "Douglas, K. M., Sutton, R. M., & Cichocka, A. (2017). The psychology of conspiracy theories. "
    "*Current Directions in Psychological Science, 26*(6), 538–542. https://doi.org/10.1177/0963721417718261",
    # 2: wrong volume and pages -> ORANGE
    "Douglas, K. M., Sutton, R. M., & Cichocka, A. (2017). The psychology of conspiracy theories. "
    "*Current Directions in Psychological Science, 25*(6), 538–545. https://doi.org/10.1177/0963721417718261",
    # 3: no DOI -> YELLOW, DOI suggested
    "Douglas, K. M., Sutton, R. M., & Cichocka, A. (2017). The psychology of conspiracy theories. "
    "*Current Directions in Psychological Science, 26*(6), 538–542.",
    # 4: one DOI digit changed -> RED
    "Douglas, K. M., Sutton, R. M., & Cichocka, A. (2017). The psychology of conspiracy theories. "
    "*Current Directions in Psychological Science, 26*(6), 538–542. https://doi.org/10.1177/0963721417718262",
    # 5: retracted -> RED
    "Stapel, D. A., & Lindenberg, S. (2011). Coping with chaos: How disordered contexts promote stereotyping "
    "and discrimination. *Science, 332*(6026), 251–253. https://doi.org/10.1126/science.1201068",
    # 6: expression of concern -> PURPLE
    "Costello, T. H., Pennycook, G., & Rand, D. G. (2024). Durably reducing conspiracy beliefs through dialogues "
    "with AI. *Science, 385*(6714), Article eadq1814. https://doi.org/10.1126/science.adq1814",
    # 7: online 2025, issue 2026, cited as 2025 -> ORANGE with "issue year is 2026"
    "Siemiątkowski, M., Gkinopoulos, T., & Bilewicz, M. (2025). Free from conspiracies: The negative relationship "
    "between societal freedom and belief in generic and content-specific conspiracy theories. "
    "*British Journal of Social Psychology, 65*(1), Article e70021. https://doi.org/10.1111/bjso.70021",
    # 8: invented article -> RED
    "Moonfield, A. B., & Starling, C. (2019). Lunar cycles and conspiracy beliefs. "
    "*Journal of Imaginary Results, 12*(3), 45–67.",
    # 9: book without DOI -> GREY
    "Allport, G. W. (1954). *The nature of prejudice*. Addison-Wesley.",
]

POLISH_REFERENCES = [
    # 10: Polish book chapter (W:, red., s.)
    "Puchała, D., & Bilewicz, M. (2024). Identyfikacje Polaków i ich konsekwencje. W: D. Bulska, M. Winiewski "
    "i M. Bilewicz (red.), *Uprzedzenia w Polsce. Postawy a ideologia polityczna* (s. 269–292). "
    "Wydawnictwo Liberi Libri.",
]

BIB = r"""@article{douglas2017,
  author  = {Douglas, Karen M. and Sutton, Robbie M. and Cichocka, Aleksandra},
  title   = {The psychology of conspiracy theories},
  journal = {Current Directions in Psychological Science},
  year    = {2017}, volume = {26}, number = {6}, pages = {538--542},
  doi     = {10.1177/0963721417718261}
}
@article{douglas2017wrongvolume,
  author  = {Douglas, Karen M. and Sutton, Robbie M. and Cichocka, Aleksandra},
  title   = {The psychology of conspiracy theories},
  journal = {Current Directions in Psychological Science},
  year    = {2017}, volume = {25}, number = {6}, pages = {538--545},
  doi     = {10.1177/0963721417718261}
}
@article{douglas2017nodoi,
  author  = {Douglas, Karen M. and Sutton, Robbie M. and Cichocka, Aleksandra},
  title   = {The psychology of conspiracy theories},
  journal = {Current Directions in Psychological Science},
  year    = {2017}, volume = {26}, number = {6}, pages = {538--542}
}
@article{douglas2017baddoi,
  author  = {Douglas, Karen M. and Sutton, Robbie M. and Cichocka, Aleksandra},
  title   = {The psychology of conspiracy theories},
  journal = {Current Directions in Psychological Science},
  year    = {2017}, volume = {26}, number = {6}, pages = {538--542},
  doi     = {10.1177/0963721417718262}
}
@article{stapel2011,
  author  = {Stapel, Diederik A. and Lindenberg, Siegwart},
  title   = {Coping with chaos: How disordered contexts promote stereotyping and discrimination},
  journal = {Science}, year = {2011}, volume = {332}, number = {6026}, pages = {251--253},
  doi     = {10.1126/science.1201068}
}
@article{costello2024,
  author  = {Costello, Thomas H. and Pennycook, Gordon and Rand, David G.},
  title   = {Durably reducing conspiracy beliefs through dialogues with {AI}},
  journal = {Science}, year = {2024}, volume = {385}, number = {6714}, pages = {eadq1814},
  doi     = {10.1126/science.adq1814}
}
@article{siemiatkowski2025,
  author  = {Siemi{\k{a}}tkowski, Maciej and Gkinopoulos, Theofilos and Bilewicz, Micha{\l}},
  title   = {Free from conspiracies: The negative relationship between societal freedom and belief in generic
             and content-specific conspiracy theories},
  journal = {British Journal of Social Psychology}, year = {2025}, volume = {65}, number = {1}, pages = {e70021},
  doi     = {10.1111/bjso.70021}
}
@article{moonfield2019,
  author  = {Moonfield, Ann B. and Starling, Clara},
  title   = {Lunar cycles and conspiracy beliefs},
  journal = {Journal of Imaginary Results}, year = {2019}, volume = {12}, number = {3}, pages = {45--67}
}
@book{allport1954,
  author    = {Allport, Gordon W.},
  title     = {The nature of prejudice},
  publisher = {Addison-Wesley}, year = {1954}
}
@incollection{puchala2024,
  author    = {Pucha{\l}a, Dominik and Bilewicz, Micha{\l}},
  title     = {Identyfikacje Polak{\'o}w i ich konsekwencje},
  booktitle = {Uprzedzenia w Polsce. Postawy a ideologia polityczna},
  editor    = {Bulska, Dominika and Winiewski, Miko{\l}aj and Bilewicz, Micha{\l}},
  publisher = {Wydawnictwo Liberi Libri}, year = {2024}, pages = {269--292}
}
"""


def add_reference(document, text: str) -> None:
    """A paragraph with an APA hanging indent; *...* in italics, DOIs as hyperlinks."""
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.5)
    paragraph.paragraph_format.first_line_indent = Inches(-0.5)
    for part in re.split(r"(\*[^*]+\*|https://doi\.org/\S+)", text):
        if part.startswith("*"):
            paragraph.add_run(part.strip("*")).italic = True
        elif part.startswith("https://"):
            link = OxmlElement("w:hyperlink")
            link.set(qn("r:id"), paragraph.part.relate_to(part, RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
            run, text_el = OxmlElement("w:r"), OxmlElement("w:t")
            text_el.text = part
            run.append(text_el)
            link.append(run)
            paragraph._p.append(link)
        elif part:
            paragraph.add_run(part)


def sample_docx(path: Path) -> None:
    document = docx.Document()
    document.add_heading("Conspiracy beliefs: a sample manuscript", level=0)
    document.add_paragraph("Belief in conspiracy theories has been studied widely (Douglas et al., 2017). "
                           "This paragraph is body text and must not be read as a reference.")
    document.add_heading("References", level=1)
    for text in REFERENCES:
        add_reference(document, text)
    document.add_heading("Appendix", level=1)
    document.add_paragraph("Smith, J. (2020). Text after the next heading is not part of the reference list.")
    document.save(path)


def sample_pl_docx(path: Path) -> None:
    document = docx.Document()
    document.add_heading("Przykładowy manuskrypt", level=0)
    document.add_paragraph("Uprzedzenia w Polsce badano wielokrotnie (Puchała i Bilewicz, 2024).")
    heading = document.add_paragraph()  # a bold paragraph, not a heading style, as in many manuscripts
    heading.add_run("Bibliografia").bold = True
    for text in POLISH_REFERENCES:
        add_reference(document, text)
    document.save(path)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    sample_docx(FIXTURES / "sample.docx")
    sample_pl_docx(FIXTURES / "sample_pl.docx")
    (FIXTURES / "sample.bib").write_text(BIB, encoding="utf-8")
    print(f"Wrote sample.docx, sample_pl.docx and sample.bib to {FIXTURES}")


if __name__ == "__main__":
    main()
