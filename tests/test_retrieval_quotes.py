"""Part 2, steps 3 and 6: BM25 passages, packets, candidates, and the deterministic quote checks."""

from conftest import FIXTURES
from refaudit import quotes, retrieval, texts

PAGES = [{"pdf": 1, "label": "538", "text": "Abstract. Uncertainty was positively associated with conspiracy belief "
          "(r = .32) in 412 adults.\n\nWe used a correlational design."},
         {"pdf": 2, "label": "539", "text": "Discussion. Perhaps conspiracy theories reduce anxiety, but we did not test "
          "this specula-\ntion. The ﬁndings replicate earlier work on self-\nesteem."},
         {"pdf": 3, "label": "540", "text": "“Conspiracy beliefs offer a sense of control when people feel powerless.”"}]
TEXT = {"pages": PAGES, "supplements": [], "abstract": ""}


def test_tokens_and_numbers():
    assert retrieval.tokenize("Przekonania spiskowe są częste, the beliefs") == ["przekonania", "spiskowe", "czeste", "beliefs"]
    assert [retrieval.number_key(n) for n in ("1,200", "1 200", "0,45", ".45", "45.5%", "412")] == \
        ["1200", "1200", "0.45", "0.45", "45.5", "412"]
    assert retrieval.numbers_in("N = 1,200; r = .45; 58%") == {"1200", "0.45", "58"}


def test_bm25_ranks_the_relevant_passage_first():
    docs = [retrieval.tokenize(t) for t in ("cats and dogs", "uncertainty predicts conspiracy belief strongly",
                                            "conspiracy theories about the moon landing")]
    scores = retrieval.BM25(docs).scores(retrieval.tokenize("Does uncertainty predict conspiracy belief?"))
    assert scores.index(max(scores)) == 1 and scores[0] == 0


def test_passages_packets_and_candidates():
    row = {"id": "C001", "sentence": "Uncertainty causes conspiracy belief (Kowalska, 2017).", "citation": "Kowalska, 2017",
           "scope": "Uncertainty causes conspiracy belief", "numbers": ["412"], "prev": "", "next": "", "group": [],
           "locator": None, "prefix": None, "original": None, "quotes": []}
    pieces = retrieval.chunks(TEXT)
    found = retrieval.passages(row, pieces, top=2)
    assert found[0]["where"] == "PDF page 1, printed page 538" and found[0]["numbers"] == ["412"]
    ref = {"key": "k", "raw": "Kowalska (2017)", "authors": ["Kowalska"], "title": "T", "doi": None, "year": "2017"}
    packet = retrieval.packet(ref, dict(TEXT, level="FULL", version="published", origin="file: x.pdf"), [row], "/w/texts/k.txt")
    assert packet["full_text"] == "/w/texts/k.txt" and packet["occurrences"][0]["passages"]
    other = {"pages": [{"pdf": 1, "label": "10", "text": "Uncertainty about the future causes conspiracy belief in experiments."}],
             "supplements": []}
    best = retrieval.candidates({"k": TEXT, "o": other}, row, exclude="k")
    assert best and all(c["ref"] == "o" for c in best)
    long_page = {"pages": [{"pdf": 1, "label": None, "text": " ".join(f"w{i}" for i in range(300))}], "supplements": []}
    assert len(retrieval.chunks(long_page)) == 3  # 120-word windows, 90 words apart


def test_normalization():
    assert quotes.normalize("con-\nspiracy") == quotes.normalize("conspiracy")
    assert quotes.normalize("ﬁndings") == "findings"
    assert quotes.normalize("self-\nesteem") == quotes.normalize("self-esteem") == quotes.normalize("self- esteem")
    assert quotes.normalize("“A  quote”\n here") == '"a quote" here'
    assert quotes.score("this speculation", PAGES[1]["text"]) == 100


def test_evidence_quotes():
    results = quotes.check_evidence([
        {"quote": "Uncertainty was positively associated with conspiracy belief", "page": "538", "pdf_page": 1},
        {"quote": "The findings replicate earlier work on self-esteem", "page": "539"},
        {"quote": "we did not test this speculation", "page": "538", "pdf_page": 1},
        {"quote": "an invented sentence that appears nowhere at all", "pdf_page": 2},
        {"quote": "We found it", "section": "Results"}], TEXT)
    assert [r["ok"] for r in results] == [True, True, False, False, False]
    assert results[2]["detail"] == "found on PDF page 2, printed page 539 instead"
    assert results[3]["detail"].startswith("best match")
    sections = {"pages": [{"pdf": None, "label": "Results", "text": "We found it."}], "supplements": []}
    assert quotes.check_evidence([{"quote": "We found it", "section": "results"}], sections)[0]["ok"]


def test_quotations_locators_and_numbers():
    found = quotes.check_quotations(["Conspiracy beliefs offer a sense of control when people feel powerless"], "p. 540", TEXT)
    assert found[0]["ok"] and found[0]["where"] == "PDF page 3, printed page 540"
    wrong_page = quotes.check_quotations(["Conspiracy beliefs offer a sense of control"], "p. 539", TEXT)[0]
    assert not wrong_page["ok"] and wrong_page["page_mismatch"] and "540" in wrong_page["detail"]
    missing = quotes.check_quotations(["Conspiracy beliefs give people total control"], "p. 540", TEXT)[0]
    assert not missing["ok"] and missing["detail"].startswith("not found verbatim")
    assert quotes.locator_pages("pp. 540–42") == {"540", "541", "542"} and quotes.locator_pages("s. 15") == {"15"}
    evidence = quotes.check_evidence([{"quote": "a sense of control", "pdf_page": 3}], TEXT)
    assert quotes.check_locator("p. 539", evidence, TEXT) == "cited p. 539; the evidence is on printed page 540"
    assert quotes.check_locator("p. 540", evidence, TEXT) == ""
    assert quotes.check_numbers(["412", ".32", "500", "58%"], TEXT) == {"412": True, ".32": True, "500": False, "58%": False}


def test_real_pdf_quote_after_column_split():
    doc = texts.read_pdf(FIXTURES / "claims" / "paged.pdf")
    text = {"pages": doc["pages"], "supplements": [], "abstract": ""}
    check = quotes.check_evidence([{"quote": "This study was correlational; no causal conclusions can be drawn from "
                                             "these data.", "page": "539", "pdf_page": 2}], text)
    assert check[0]["ok"]
