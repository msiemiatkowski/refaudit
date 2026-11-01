"""Normalization, field comparison and status logic, using API responses recorded in tests/fixtures/http."""

import pytest

from refaudit import lookup
from refaudit.compare import (Match, Notice, Record, assess, check_doi, check_notices, compare_authors,
                              compare_journal, compare_pages, compare_title, compare_value, compare_year, norm,
                              same_surname, similarity, worst)
from refaudit.parse import Person, Reference, parse_apa, parse_authors

DOUGLAS = "10.1177/0963721417718261"
CITED = ("Douglas, K. M., Sutton, R. M., & Cichocka, A. (2017). The psychology of conspiracy theories. "
         "Current Directions in Psychological Science, 26(6), 538–542. https://doi.org/10.1177/0963721417718261")


@pytest.fixture
def douglas(offline) -> Record:
    return lookup.fetch_record(offline, DOUGLAS)


def people(text):
    return parse_authors(text)[0]


def test_normalization():
    assert norm("Group Processes & Intergroup Relations") == norm("group processes and intergroup relations")
    assert norm("Siemiątkowski, Michał: content‐specific") == "siemiatkowski michal content specific"
    assert norm("<i>Homo sapiens</i> – a “study”") == "homo sapiens a study"
    assert similarity("The psychology of conspiracy theories", "The Psychology of Conspiracy Theories.") == 100
    assert same_surname("Siemiatkowski", "Siemiątkowski") and same_surname("van der Linden", "Linden")
    assert not same_surname("Douglas", "Sutton")


def test_recorded_crossref_record(douglas):
    assert (douglas.origin, douglas.journal, douglas.volume, douglas.issue, douglas.pages) == (
        "Crossref", "Current Directions in Psychological Science", "26", "6", "538-542")
    assert (douglas.issue_year, douglas.online_year) == (2017, 2017)
    assert [p.surname for p in douglas.authors] == ["Douglas", "Sutton", "Cichocka"]


def test_authors(douglas):
    rec = douglas.authors
    assert compare_authors(people("Douglas, K. M., Sutton, R. M., & Cichocka, A."), rec).status == "GREEN"
    initials = compare_authors(people("Douglas, K., Sutton, R. M., & Cichocka, A."), rec)
    assert initials.status == "YELLOW" and "initials of Douglas" in initials.problem
    accents = compare_authors(people("Douglas, K. M., Sutton, R. M., & Cichócka, A."), rec)
    assert accents.status == "YELLOW" and "diacritics in Cichócka" in accents.problem
    assert "lists 2" in compare_authors(people("Douglas, K. M., & Sutton, R. M."), rec).problem
    assert "order" in compare_authors(people("Sutton, R. M., Douglas, K. M., & Cichocka, A."), rec).problem
    surname = compare_authors(people("Douglas, K. M., Sutten, R. M., & Cichocka, A."), rec)
    assert surname.status == "ORANGE" and "Sutten differs" in surname.problem
    many = [Person(f"Author{i}", given="A.") for i in range(25)]
    cited, truncated = parse_authors(", ".join(f"Author{i}, A." for i in range(19)) + ", . . . Author24, A.")
    assert compare_authors(cited, many, truncated).status == "GREEN"


def test_year():
    def record(issue, online):
        return Record(issue_year=issue, online_year=online)

    assert compare_year("2017", record(2017, 2017)).status == "GREEN"
    assert compare_year("2026a", record(2026, 2025)).status == "GREEN"
    online_first = compare_year("2025", record(2026, 2025))
    assert online_first.status == "ORANGE" and "issue year is 2026" in online_first.problem
    assert "matches neither" in compare_year("2019", record(2026, 2025)).problem
    assert compare_year("2025", record(None, 2025)).status == "GREEN"  # online first, no issue yet
    assert compare_year("in press", record(2024, None)).status == "ORANGE"
    assert compare_year("2017", Record()).status is None


@pytest.mark.parametrize("cited, sim, status", [
    ("The psychology of conspiracy theories", 100, "GREEN"),
    ("The psychology of the conspiracy theories", 95, "GREEN"),
    ("The psychology of conspiracy theory", 94, "YELLOW"),
    ("The psychology of conspiracies", 90, "YELLOW"),
    ("Psychology of conspiracy", 79, "ORANGE"),
    ("Conspiracy theories and their psychology", 49, "ORANGE"),
])
def test_title_thresholds(douglas, cited, sim, status):
    check, score = compare_title(cited, douglas)
    assert (score, check.status) == (sim, status)


def test_journal(douglas):
    assert compare_journal("Current Directions in Psychological Science", douglas).status == "GREEN"
    assert compare_journal("CURRENT DIRECTIONS IN PSYCHOLOGICAL SCIENCE.", douglas).status == "GREEN"
    assert compare_journal("Curr Dir Psychol Sci", douglas).status == "YELLOW"  # recorded short title
    assert compare_journal("Curr. Dir. Psychol. Sci.", douglas).status == "YELLOW"
    assert compare_journal("Psychological Science", douglas).status == "ORANGE"
    ampersand = Record(journal="Group Processes and Intergroup Relations")
    assert compare_journal("Group Processes & Intergroup Relations", ampersand).status == "YELLOW"
    assert compare_journal("J. Pers. Soc. Psychol.", Record(journal="Journal of Personality and Social Psychology")
                           ).status == "YELLOW"


def test_volume_issue_pages(douglas):
    assert compare_value("Volume", "26", douglas.volume).status == "GREEN"
    assert compare_value("Volume", None, douglas.volume).status == "YELLOW"
    assert compare_value("Volume", "25", douglas.volume).status == "ORANGE"
    assert compare_value("Issue", "06", douglas.issue).status == "GREEN"
    assert compare_value("Issue", "6", "").status is None  # nothing to compare with
    assert compare_pages("538–542", douglas).status == "GREEN"
    assert compare_pages("538–42", douglas).status == "GREEN"
    assert compare_pages("538–545", douglas).status == "ORANGE"
    assert compare_pages(None, douglas).status == "YELLOW"
    article = Record(article_number="e70021")
    assert compare_pages("Article e70021", article).status == "GREEN"
    assert compare_pages("538–542", Record(pages="538")).status == "GREEN"  # record gives the first page only


def test_doi_checks(douglas):
    ref = parse_apa(CITED)
    assert check_doi(ref, Match(douglas, confidence="doi", doi_state="ok")).status == "GREEN"
    old_form = parse_apa(CITED.replace("https://doi.org/", "doi:"))
    assert check_doi(old_form, Match(douglas, confidence="doi", doi_state="ok")).status == "YELLOW"
    unregistered = check_doi(ref, Match(doi_state="unregistered"))
    assert unregistered.status == "RED" and "not registered" in unregistered.problem
    other = Record(title="Something else entirely", authors=[Person("Nowak")], issue_year=2001)
    assert check_doi(ref, Match(doi_state="different", other=other)).status == "RED"
    no_doi = parse_apa(CITED.split(" https://")[0])
    suggested = check_doi(no_doi, Match(douglas, confidence="high"))
    assert suggested.status == "YELLOW" and f"found https://doi.org/{DOUGLAS}" in suggested.problem
    assert check_doi(no_doi, Match(douglas, confidence="low")).status is None


def test_same_work(douglas):
    ref = parse_apa(CITED)
    assert lookup.same_work(ref, douglas)
    other = Record(title="Something else entirely", authors=[Person("Nowak")])
    assert not lookup.same_work(ref, other)
    assert lookup.same_work(ref, Record(title="Something else entirely", authors=[Person("Douglas")]))


def test_notice_classification(offline):
    stapel = lookup.fetch_record(offline, "10.1126/science.1201068")
    costello = lookup.fetch_record(offline, "10.1126/science.adq1814")
    retraction = check_notices(lookup.find_notices(offline, stapel, []))
    assert retraction.status == "RED" and "Retraction, 2011-12-02" in retraction.record
    concern = check_notices(lookup.find_notices(offline, costello, []))
    assert concern.status == "PURPLE"
    assert "Expression of concern, 2026-06-11, https://doi.org/10.1126/science.aej2383" in concern.record
    assert "Correction" in concern.record  # recorded, but no status of its own
    for kind in ("retraction", "partial_retraction", "withdrawal", "removal", "is_retracted"):
        assert check_notices([Notice(kind)]).status == "RED"
    assert check_notices([Notice("expression_of_concern")]).status == "PURPLE"
    assert check_notices([Notice("correction")]).status is None


def test_row_status():
    assert worst(["GREEN", "YELLOW", "PURPLE", "ORANGE"]) == "PURPLE"
    assert worst(["GREEN", "RED", "PURPLE"]) == "RED"
    assert worst([None, None]) is None
    book = parse_apa("Allport, G. W. (1954). The nature of prejudice. Addison-Wesley.")
    assert assess(book, Match(searched="Crossref")).status == "GREY"
    article = parse_apa("Moonfield, A. (2019). Lunar cycles. Journal of Imaginary Results, 12(3), 45–67.")
    assert assess(article, Match(searched="Crossref")).status == "RED"
    assert assess(Reference(raw="x"), Match(doi_state="no-metadata")).status == "GREY"


def test_assess_full_row(douglas):
    row = assess(parse_apa(CITED), Match(douglas, route="DOI → Crossref", confidence="doi", doi_state="ok"))
    assert row.status == "GREEN" and row.problems == []
    low = assess(parse_apa(CITED.split(" https://")[0]), Match(douglas, confidence="low", similarity=85))
    assert low.status == "ORANGE" and "Low-confidence match" in low.problems[0]
