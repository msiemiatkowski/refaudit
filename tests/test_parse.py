import pytest

from conftest import FIXTURES
from refaudit.parse import clean_doi, parse_apa, parse_authors, read_bib, read_docx, read_references


def italic(marked: str):
    """'Title. *Journal, 1*(2)' -> text and italic mask."""
    text, mask, on = [], [], False
    for ch in marked:
        if ch == "*":
            on = not on
        else:
            text.append(ch)
            mask.append(on)
    return "".join(text), mask


def test_docx_reference_section():
    refs = read_docx(FIXTURES / "sample.docx")
    assert len(refs) == 9  # body text before and the Appendix after are not references
    first = refs[0]
    assert [str(p) for p in first.authors] == ["Douglas, K. M.", "Sutton, R. M.", "Cichocka, A."]
    assert (first.kind, first.year, first.title) == ("article", "2017", "The psychology of conspiracy theories")
    assert first.source == "Current Directions in Psychological Science"
    assert (first.volume, first.issue, first.pages) == ("26", "6", "538–542")
    assert first.doi == "10.1177/0963721417718261"  # read from the hyperlink
    assert first.doi_written == "https://doi.org/10.1177/0963721417718261"
    assert refs[2].doi is None
    assert refs[8].kind == "book" and refs[8].title == "The nature of prejudice"
    assert refs[8].publisher == "Addison-Wesley"


def test_docx_bold_heading_and_override():
    assert len(read_docx(FIXTURES / "sample_pl.docx")) == 1  # 'Bibliografia' in bold, no heading style
    appendix = read_docx(FIXTURES / "sample.docx", heading="appendix")
    assert len(appendix) == 1 and appendix[0].authors[0].surname == "Smith"
    with pytest.raises(ValueError, match="no reference heading"):
        read_docx(FIXTURES / "sample.docx", heading="Works cited")


def test_polish_book_chapter():
    """Case 10: 'W:', '(red.)' and 's.'."""
    ref = read_docx(FIXTURES / "sample_pl.docx")[0]
    assert ref.kind == "chapter"
    assert [str(p) for p in ref.authors] == ["Puchała, D.", "Bilewicz, M."]
    assert ref.year == "2024"
    assert ref.title == "Identyfikacje Polaków i ich konsekwencje"
    assert [(p.surname, p.initials) for p in ref.editors] == [("Bulska", "D."), ("Winiewski", "M."),
                                                                 ("Bilewicz", "M.")]
    assert ref.source == "Uprzedzenia w Polsce. Postawy a ideologia polityczna"
    assert ref.pages == "269–292"
    assert ref.publisher == "Wydawnictwo Liberi Libri"


def test_english_chapter_and_edition():
    ref = parse_apa("Author, A. A. (2020). Chapter title. In E. E. Editor & F. F. Editor (Eds.), Book title "
                    "(2nd ed., pp. 123–145). Publisher. https://doi.org/10.1000/182")
    assert (ref.kind, ref.title, ref.source, ref.pages, ref.publisher) == (
        "chapter", "Chapter title", "Book title", "123–145", "Publisher")
    assert [p.surname for p in ref.editors] == ["Editor", "Editor"]
    book = parse_apa("Wojciszke, B. (2011). Psychologia społeczna (wyd. 2). Wydawnictwo Naukowe Scholar.")
    assert (book.kind, book.title, book.publisher) == ("book", "Psychologia społeczna", "Wydawnictwo Naukowe Scholar")


@pytest.mark.parametrize("cited, year", [("(2026a)", "2026a"), ("(in press)", "in press"), ("(n.d.)", "n.d."),
                                         ("(2020, March 3)", "2020"), ("(w druku)", "w druku")])
def test_year_forms(cited, year):
    assert parse_apa(f"Kowalski, J. {cited}. A title. Some Journal, 1(2), 3–4.").year == year


@pytest.mark.parametrize("text, doi, written", [
    ("https://doi.org/10.1037/a0012345.", "10.1037/a0012345", "https://doi.org/10.1037/a0012345"),
    ("doi:10.1037/a0012345", "10.1037/a0012345", "doi:10.1037/a0012345"),
    ("http://dx.doi.org/10.1016/S0140-6736(20)30183-5)", "10.1016/s0140-6736(20)30183-5",
     "http://dx.doi.org/10.1016/S0140-6736(20)30183-5"),
    ("10.1002/%28SICI%291097-4679", "10.1002/(sici)1097-4679", "10.1002/%28SICI%291097-4679"),
])
def test_doi_forms(text, doi, written):
    ref = parse_apa(f"Kowalski, J. (2020). A title. Some Journal, 1(2), 3–4. {text}")
    assert (ref.doi, ref.doi_written) == (doi, written)
    assert clean_doi(written) == doi


def test_author_lists():
    people, truncated = parse_authors("Smith, J. A., Jr., Nowak-Kowalska, Ł., & van der Linden, S.")
    assert [(p.surname, p.initials) for p in people] == [("Smith", "J. A."), ("Nowak-Kowalska", "Ł."),
                                                         ("van der Linden", "S.")]
    assert not truncated
    people, _ = parse_authors("Puchała, D. i Bilewicz, M.")  # Polish 'i'
    assert [p.surname for p in people] == ["Puchała", "Bilewicz"]
    people, _ = parse_authors("American Psychological Association.")
    assert [p.surname for p in people] == ["American Psychological Association"]
    people, truncated = parse_authors(", ".join(f"A{i}, B." for i in range(1, 20)) + ", . . . Last, Z.")
    assert truncated and len(people) == 20 and people[-1].surname == "Last"


def test_journal_boundary_with_and_without_italics():
    text, mask = italic("Smith, J. (2020). Who believes? Evidence from the U.S. *J. Pers. Soc. Psychol., 12*, 1–20.")
    for ref in (parse_apa(text, mask), parse_apa(text)):
        assert ref.title == "Who believes? Evidence from the U.S"
        assert ref.source == "J. Pers. Soc. Psychol."
        assert (ref.volume, ref.pages) == ("12", "1–20")
    online = parse_apa("Kowalski, J. (in press). Tytuł. Psychologia Społeczna. Advance online publication.")
    assert (online.kind, online.title, online.source) == ("article", "Tytuł", "Psychologia Społeczna")


def test_thesis_and_web_page():
    thesis = parse_apa("Nowak, A. (2019). Rozprawa [Praca doktorska, Uniwersytet Warszawski]. Repozytorium UW.")
    assert (thesis.kind, thesis.title, thesis.publisher) == ("thesis", "Rozprawa", "Uniwersytet Warszawski")
    web = parse_apa("World Health Organization. (n.d.). Coronavirus disease (COVID-19) pandemic. "
                    "Retrieved May 3, 2024, from https://www.who.int/emergencies")
    assert (web.kind, web.year, web.url) == ("web", "n.d.", "https://www.who.int/emergencies")
    assert web.title == "Coronavirus disease (COVID-19) pandemic"


def test_bib():
    refs = read_bib(FIXTURES / "sample.bib")
    assert len(refs) == 10
    assert refs[0].authors[0].given == "Karen M." and refs[0].authors[0].initials == "K. M."
    assert (refs[0].pages, refs[0].issue, refs[0].doi, refs[0].doi_written) == (
        "538–542", "6", "10.1177/0963721417718261", None)
    assert refs[6].authors[0].surname == "Siemiątkowski"  # LaTeX decoded
    chapter = refs[9]
    assert (chapter.kind, chapter.source) == ("chapter", "Uprzedzenia w Polsce. Postawy a ideologia polityczna")
    assert [p.surname for p in chapter.editors] == ["Bulska", "Winiewski", "Bilewicz"]
    assert chapter.raw.startswith("Puchała, D., & Bilewicz, M. (2024). Identyfikacje Polaków i ich konsekwencje.")


def test_unsupported_file(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        read_references(tmp_path / "refs.txt")
