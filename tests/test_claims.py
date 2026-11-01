"""Part 2, step 1: sentences, in-text citations, matching to the reference list, occurrence rows."""

import docx
import pytest
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from refaudit import claims
from refaudit.claims import find_citations, match, same_surname, split_sentences

REFS = [
    {"key": "douglas2017", "authors": ["Douglas", "Sutton", "Cichocka"], "year": "2017"},
    {"key": "douglas2017-2", "authors": ["Douglas"], "year": "2017"},
    {"key": "soral2018a", "authors": ["Soral", "Cichocka", "Bilewicz"], "year": "2018a"},
    {"key": "soral2018b", "authors": ["Soral", "Bilewicz", "Winiewski"], "year": "2018b"},
    {"key": "bilewicz2020", "authors": ["Bilewicz", "Soral"], "year": "2020"},
    {"key": "vanprooijen2017", "authors": ["van Prooijen", "Douglas"], "year": "2017"},
    {"key": "golecdezavala", "authors": ["Golec de Zavala", "Cichocka", "Bilewicz"], "year": "in press"},
    {"key": "who2020", "authors": ["World Health Organization"], "year": "2020"},
]


@pytest.mark.parametrize("text, expected", [
    ("Beliefs are common (Douglas et al., 2017). They matter.", 2),
    ("See e.g. the review, i.e. the best one, cf. Smith vs. Jones, p. 5 and pp. 6–7. Then it ends.", 2),
    ("The effect was 3.5 points larger. Next sentence.", 2),
    ("Badanie przeprowadzono w 2020 r. Wyniki pokazały np. wzrost, tzn. silny, m.in. w Polsce (zob. Kowalski, 2020, s. 5). Koniec.", 2),
    ("Według badań (Soral i in., 2018a) jest inaczej. Drugie zdanie.", 2),
    ("K. M. Douglas argued it. Dr. Smith agreed.", 2),
    ("Wynik wyniósł 0,45 i był istotny. Dalej.", 2),
])
def test_sentence_splitting(text, expected):
    assert len(split_sentences(text)) == expected


@pytest.mark.parametrize("sentence, expected", [
    ("Common (Douglas et al., 2017).", [(["Douglas"], True, "2017", None, None, False)]),
    ("Common (e.g., Douglas & Sutton, 2017; see also Uscinski, 2019, p. 5).",
     [(["Douglas", "Sutton"], False, "2017", None, "e.g.,", False), (["Uscinski"], False, "2019", "p. 5", "see also", False)]),
    ("Reviewed (for a review, see Goreis and Voracek, 2019, pp. 205–210).",
     [(["Goreis", "Voracek"], False, "2019", "pp. 205–210", "for a review, see", False)]),
    ("Two papers (Soral i in., 2018a, 2018b; zob. Kofta, Soral i Bilewicz, 2020, s. 12).",
     [(["Soral"], True, "2018a", None, None, False), (["Soral"], True, "2018b", None, None, False),
      (["Kofta", "Soral", "Bilewicz"], False, "2020", "s. 12", "zob.", False)]),
    ("Douglas et al. (2017a, 2017b) argued it.",
     [(["Douglas"], True, "2017a", None, None, True), (["Douglas"], True, "2017b", None, None, True)]),
    ("Douglas and Sutton (2017) showed it.", [(["Douglas", "Sutton"], False, "2017", None, None, True)]),
    ("Douglas, Sutton, and Cichocka (2017) showed it.", [(["Douglas", "Sutton", "Cichocka"], False, "2017", None, None, True)]),
    ("Allport’s (1954) classic book.", [(["Allport"], False, "1954", None, None, True)]),
    ("Douglas et al.’s (2017, p. 540) review.", [(["Douglas"], True, "2017", "p. 540", None, True)]),
    ("However, Douglas et al. (2017) found it.", [(["Douglas"], True, "2017", None, None, True)]),
    ("Według Bilewicza i Sorala (2020) tak jest.", [(["Bilewicza", "Sorala"], False, "2020", None, None, True)]),
    ("Zdaniem Bilewicza i in. (2020) tak jest.", [(["Bilewicza"], True, "2020", None, None, True)]),
    ("Unpublished (Golec de Zavala et al., in press; Smith, n.d.; Nowak, w druku).",
     [(["Golec de Zavala"], True, "in press", None, None, False), (["Smith"], False, "n.d.", None, None, False),
      (["Nowak"], False, "w druku", None, None, False)]),
    ("Contact works (Allport, 1954, as cited in Pettigrew & Tropp, 2006).",
     [(["Pettigrew", "Tropp"], False, "2006", None, None, False)]),
    ("Guidance (World Health Organization, 2020; cf. van Prooijen & Douglas, 2017).",
     [(["World Health Organization"], False, "2020", None, None, False), (["van Prooijen", "Douglas"], False, "2017", None, "cf.", False)]),
    ("Not a citation (N = 2017) and (Study 2, 2019 data).", []),
])
def test_citation_forms(sentence, expected):
    found = [(c.authors, c.et_al, c.year, c.locator, c.prefix, c.narrative) for c in find_citations(sentence)]
    assert found == expected


def test_as_cited_in_keeps_the_original():
    cite = find_citations("Contact works (Allport, 1954, as cited in Pettigrew & Tropp, 2006).")[0]
    assert cite.original == "Allport, 1954"
    group = find_citations("A (Douglas et al., 2017; Uscinski, 2019).")
    assert group[0].group == ["Uscinski, 2019"] and group[1].group == ["Douglas et al., 2017"]


@pytest.mark.parametrize("sentence, key, state", [
    ("x (Douglas et al., 2017).", "douglas2017", "matched"),
    ("x (Douglas, 2017).", "douglas2017-2", "matched"),          # author count picks the single-author entry
    ("x (Soral et al., 2018a).", "soral2018a", "matched"),
    ("x (Soral et al., 2018).", None, "ambiguous"),              # 2018a or 2018b
    ("x (Soral et al., 2018c).", None, "ambiguous"),
    ("Według Bilewicza i Sorala (2020) tak.", "bilewicz2020", "matched"),  # Polish case endings
    ("x (Siemiątkowski, 2025).", None, "unmatched"),
    ("x (van Prooijen & Douglas, 2017).", "vanprooijen2017", "matched"),
    ("x (Prooijen & Douglas, 2017).", "vanprooijen2017", "matched"),
    ("x (Golec de Zavala et al., in press).", "golecdezavala", "matched"),
    ("x (World Health Organization, 2020).", "who2020", "matched"),
])
def test_matching(sentence, key, state):
    found = match(find_citations(sentence)[0], REFS)
    assert found[:2] == (key, state)


def test_matching_notes():
    assert "author count" in match(find_citations("x (Bilewicz, 2020).")[0], REFS)[2]
    assert same_surname("Kowalskiego", "Kowalski") and same_surname("Kowalskiej", "Kowalska")
    assert not same_surname("Kowalski", "Kowal") and not same_surname("Douglas", "Sutton")


def test_occurrences_from_a_manuscript(tmp_path):
    d = docx.Document()
    d.add_heading("Introduction", level=1)
    p = d.add_paragraph("Beliefs are common (Douglas et al., 2017; Smith, 2001). Douglas et al. (2017) found that 45.5% "
                        "of 1,200 people agree, “believing is easier than knowing” (Douglas et al., 2017, p. 540).")
    p._p.append(parse_xml(f'<w:del {nsdecls("w")} w:id="1" w:author="a"><w:r><w:delText> Deleted (Gone, 1999).'
                          f'</w:delText></w:r></w:del>'))
    d.add_heading("References", level=1)
    d.add_paragraph("Douglas, K. M., Sutton, R. M., & Cichocka, A. (2017). The psychology of conspiracy theories. "
                    "Current Directions in Psychological Science, 26(6), 538–542.")
    d.add_paragraph("Unused, A. (2015). Never cited. Journal, 1, 1–2.")
    d.add_heading("Appendix", level=1)
    d.add_paragraph("Also cited here (Douglas et al., 2017).")
    path = tmp_path / "ms.docx"
    d.save(path)
    paragraphs, method = claims.manuscript_paragraphs(path)
    assert "Unused, A. (2015). Never cited. Journal, 1, 1–2." not in paragraphs and "Appendix" in paragraphs
    assert claims.has_tracked_changes(path)
    rows = claims.occurrences(paragraphs, claims.reference_table(path))
    assert [(r["id"], r["sentence_id"], r["ref"], r["match"]) for r in rows] == [
        ("C001", "P002.S1", "douglas2017", "matched"), ("C002", "P002.S1", None, "unmatched"),
        ("C003", "P002.S2", "douglas2017", "matched"), ("C004", "P002.S2", "douglas2017", "matched"),
        ("C005", "P004.S1", "douglas2017", "matched")]
    narrative, parenthetical = rows[2], rows[3]
    assert narrative["scope"].startswith("found that 45.5%") and narrative["numbers"] == ["45.5%", "1,200"]
    assert parenthetical["locator"] == "p. 540" and parenthetical["quotes"] == ["believing is easier than knowing"]
    assert rows[0]["group"] == ["Smith, 2001"] and rows[1]["prev"] == "Introduction" and rows[0]["next"].startswith("Douglas")
