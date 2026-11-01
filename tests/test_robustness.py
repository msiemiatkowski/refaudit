"""Regression tests for real-world inputs: Polish APA forms, .docx structures, .bib quirks, retries."""

import docx
import pytest
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from conftest import FIXTURES, offline_client
from refaudit import lookup
from refaudit.compare import Match, Notice, Person, Record, assess, compare_authors, compare_journal
from refaudit.parse import parse_apa, parse_authors, read_bib, read_docx

CHAPTER = ("Puchała, D., & Bilewicz, M. (2024). Identyfikacje Polaków i ich konsekwencje [Identifications of Poles "
           "and their consequences]. W: D. Bulska, M. Winiewski i M. Bilewicz (red.), Uprzedzenia w Polsce. Postawy a "
           "ideologia polityczna [Prejudice in Poland: Attitudes and political ideology] (s. 269–292). "
           "Wydawnictwo Liberi Libri.")
BOOK = "Uprzedzenia w Polsce. Postawy a ideologia polityczna"


def test_english_translations_in_brackets():
    chapter = parse_apa(CHAPTER)
    assert (chapter.title, chapter.source, chapter.pages) == ("Identyfikacje Polaków i ich konsekwencje", BOOK, "269–292")
    article = parse_apa("Kowalski, J. (2020). Tytuł artykułu [Title of the article]. Psychologia Społeczna, 15(2), "
                        "100–120.")
    assert (article.title, article.source, article.volume) == ("Tytuł artykułu", "Psychologia Społeczna", "15")
    book = parse_apa("Wojciszke, B. (2011). Psychologia społeczna [Social psychology] (wyd. 2). Scholar.")
    assert (book.title, book.publisher) == ("Psychologia społeczna", "Scholar")


def test_translation_does_not_break_the_match(offline):
    """Case 10 with translations still matches the recorded Crossref record."""
    rec = lookup.search_crossref(offline, read_docx(FIXTURES / "sample_pl.docx")[0])[0]
    assert rec.doi == "10.47943/lib.9788363487645.rozdzial10"
    row = assess(parse_apa(CHAPTER), Match(rec, confidence="high", similarity=100))
    assert row.checks["title"].status == row.checks["journal"].status == "GREEN"


@pytest.mark.parametrize("text, title", [
    ("Nowak, A. (2020). Dostęp do informacji publicznej w Polsce. Państwo i Prawo, 75(3), 1–20.",
     "Dostęp do informacji publicznej w Polsce"),
    ("Smith, J. (2019). Accessed memories and false recall. Memory, 27(4), 1–10.", "Accessed memories and false recall"),
])
def test_retrieval_words_inside_titles(text, title):
    ref = parse_apa(text)
    assert (ref.kind, ref.title, ref.volume) == ("article", title, text.split(", ")[-2].split("(")[0])


@pytest.mark.parametrize("text", [
    "WHO. (n.d.). Fact sheet. Retrieved May 3, 2024, from https://www.who.int/x",
    "GUS. (2023). Fact sheet. Pobrano 3 maja 2024 z https://stat.gov.pl/x",
    "GUS. (2023). Fact sheet. Dostęp: 12.03.2024, https://stat.gov.pl/x",
])
def test_retrieval_statements(text):
    ref = parse_apa(text)
    assert ref.title == "Fact sheet" and ref.url.startswith("https://")


def test_doi_forms_and_notes():
    sici = parse_apa("Smith, J. (1999). Title. European Journal of Social Psychology, 29(1), 57–75. "
                     "https://doi.org/10.1002/(SICI)1099-0992(199901/02)29:1<57::AID-EJSP916>3.0.CO;2-W")
    assert sici.doi == "10.1002/(sici)1099-0992(199901/02)29:1<57::aid-ejsp916>3.0.co;2-w"
    wrapped = parse_apa("Smith, J. (1999). Title. Journal, 1, 2–3. <https://doi.org/10.1037/a0012345>")
    assert (wrapped.kind, wrapped.doi, wrapped.pages) == ("article", "10.1037/a0012345", "2–3")
    assert parse_apa("Smith, J. (2020). T. Journal, 1, 2. https://doi.org/10.1037/a​123").doi == "10.1037/a123"
    polish = parse_apa("Kowalski, J. (2020). Tytuł. Psychologia Społeczna, 15(2), 100–120 [in Polish].")
    assert (polish.kind, polish.source, polish.pages) == ("article", "Psychologia Społeczna", "100–120")
    reprint = parse_apa("Allport, G. W. (1979). The nature of prejudice (25th anniversary ed.). Addison-Wesley. "
                        "(Original work published 1954)")
    assert (reprint.title, reprint.publisher) == ("The nature of prejudice", "Addison-Wesley")


def test_polish_chapter_forms_and_edited_books():
    for text in ("Nowak, A. (2010). Rozdział. W: B. Kowalski (red. nauk.), Książka (s. 12–34). Warszawa: PWN.",
                 "Nowak, A. (2010). Rozdział. W: B. Kowalski (red.), Książka. Warszawa: PWN, s. 12–34."):
        ref = parse_apa(text)
        assert (ref.kind, ref.source, ref.pages, ref.publisher) == ("chapter", "Książka", "12–34", "Warszawa: PWN")
        assert [p.surname for p in ref.editors] == ["Kowalski"]
    edited = parse_apa("Bulska, D., Winiewski, M., & Bilewicz, M. (Eds.). (2024). Uprzedzenia w Polsce. Liberi Libri.")
    assert [str(p) for p in edited.authors] == ["Bulska, D.", "Winiewski, M.", "Bilewicz, M."]
    record = lookup.from_crossref({"DOI": "10.1/x", "title": ["T"], "editor": [{"family": "Bulska", "given": "D."}]})
    assert [p.surname for p in record.authors] == ["Bulska"]  # an edited book is matched by its editors


def test_numbering_and_year_suffixes():
    for text in ("1) Douglas, K. M. (2017). Title. Journal, 1(2), 3–4.", "(12) Douglas, K. M. (2017). Title. J, 1, 2."):
        assert parse_apa(text).authors[0].surname == "Douglas"
    assert parse_apa("Kowalski, J. (in press-a). Tytuł. Strona.").year == "in press-a"
    assert parse_apa("Kowalski, J. (n.d.-b). Tytuł. Strona.").year == "n.d.-b"


def test_names():
    record = [Person("Linden", given="Sander van der"), Person("Roozenbeek", given="Jon")]
    assert compare_authors(parse_authors("van der Linden, S., & Roozenbeek, J.")[0], record).status == "GREEN"
    assert lookup.split_name("Martin Luther King Jr.").surname == "King"
    assert lookup.split_name("Golec de Zavala, Agnieszka").surname == "Golec de Zavala"
    assert lookup.split_name("Sander van der Linden").surname == "van der Linden"


def test_book_series_and_low_confidence_notices():
    chapter_record = Record(journal="Trends in Mathematics", alt_journals=["Advances in Algebra and Analysis"])
    assert compare_journal("Advances in Algebra and Analysis", chapter_record).status == "GREEN"
    ref = parse_apa("Smith, J. (2017). Title of the work. Journal, 1(2), 3–4.")
    rec = Record(doi="10.1/x", title="Title of a work", authors=[Person("Smith", given="J.")])
    row = assess(ref, Match(rec, confidence="low", similarity=85), [Notice("retraction", "2020-01-01", "10.1/n")])
    assert row.status == "RED" and any(p.startswith("Notice on the low-confidence match") for p in row.problems)


def test_bad_doi_stays_red_when_the_search_fails():
    """The cited DOI is known to be unregistered; the search for the right record is not recorded (fails)."""
    ref = parse_apa("Nobody, A. (2017). Some unrecorded title. Journal, 1(2), 3–4. "
                    "https://doi.org/10.1177/0963721417718262")
    notes = []
    match = lookup.find_match(offline_client(), ref, notes)
    row = assess(ref, match, [], notes)
    assert row.status == "RED" and "not registered" in row.problems[0]


def _docx(tmp_path, build) -> str:
    document = docx.Document()
    build(document)
    path = tmp_path / "test.docx"
    document.save(path)
    return path


def test_docx_tables_headings_and_special_characters(tmp_path):
    ref = "Douglas, K. M. (2017). The psychology of conspiracy theories. Journal, 26(6), 538–542."

    def build(document):
        document.add_paragraph("6. References.")  # numbered, with a period
        document.add_paragraph("", style="Heading 2")  # empty heading-styled paragraph
        table = document.add_table(rows=2, cols=2)  # a list laid out in a table
        table.cell(0, 0).text, table.cell(0, 1).text = "[1]", ref
        table.cell(1, 0).text, table.cell(1, 1).text = "[2]", ref.replace("2017", "2018")
        p = document.add_paragraph("Nowak")
        p._p.append(parse_xml(f'<w:r {nsdecls("w")}><w:noBreakHyphen/><w:t xml:space="preserve">Kowalska, A. (2019). '
                              'Title. Journal, 1(2), 3</w:t><w:sym w:font="Symbol" w:char="F02D"/><w:t>4.</w:t></w:r>'))
        styles = document.styles
        section = styles.add_style("Section Title", 1)  # bold through its style only
        section.font.bold = True
        document.add_paragraph("Appendix", style="Section Title")
        document.add_paragraph("Smith, J. (2020). Not a reference. Journal, 1, 2.")

    refs = read_docx(_docx(tmp_path, build))
    assert [r.year for r in refs] == ["2017", "2018", "2019"]
    assert refs[2].authors[0].surname == "Nowak-Kowalska" and refs[2].pages == "3-4"


def test_bib_order_duplicates_dates_and_encoding(tmp_path):
    bib = ("@article{a, author={Douglas, Karen M.}, title={First}, journal={J}, date={2017-12}}\n"
           "@article{broken, title={Broken\n"
           "@article{a, author={Pucha{\\l}a, Dominik}, title={Second}, year={2024}}\n"
           "@inproceedings{c, author={Nowak, Anna}, title={Third}, booktitle={Proceedings}, year={2020}}\n"
           "@article{d, author={Wójcik, Ewa}, title={Fourth}, year={2021}}\n")
    path = tmp_path / "library.bib"
    path.write_bytes(bib.encode("cp1250"))
    refs = read_bib(path)
    assert [r.title for r in refs] == ["First", None, "Second", "Third", "Fourth"]  # in file order
    assert refs[0].year == "2017" and refs[1].error and refs[2].authors[0].surname == "Puchała"
    assert refs[3].kind == "chapter" and refs[4].authors[0].surname == "Wójcik"
