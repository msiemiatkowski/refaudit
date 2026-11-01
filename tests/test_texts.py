"""Part 2, step 2: reading sources, printed page labels, OCR, matching your files to references, evidence levels."""

import shutil
import zipfile

import docx
import pytest

from conftest import FIXTURES
from refaudit import texts

PDF = FIXTURES / "claims" / "paged.pdf"
REF = {"key": "kowalska2017", "authors": ["Kowalska", "Nowak"], "year": "2017", "kind": "article",
       "title": "Uncertainty and conspiracy belief: A test article", "doi": "10.9999/test.2017.001"}
OTHER = {"key": "douglas2017", "authors": ["Douglas", "Sutton", "Cichocka"], "year": "2017", "kind": "article",
         "title": "The psychology of conspiracy theories", "doi": "10.1177/0963721417718261"}


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler-utils not installed")
def test_pdf_pages_labels_and_columns():
    doc = texts.read_pdf(PDF)
    assert [(p["pdf"], p["label"]) for p in doc["pages"]] == [(1, "538"), (2, "539"), (3, "540")]
    first = doc["pages"][0]["text"]
    assert first.index("Abstract.") < first.index("Introduction filler sentence number 5")  # left column first
    assert doc["meta"]["extraction"] == "pdftotext -layout"
    assert texts.where(doc["pages"][2]) == "PDF page 3, printed page 540"


def test_pypdf_fallback(monkeypatch):
    monkeypatch.setattr(texts, "_pdftotext", lambda path: None)
    doc = texts.read_pdf(PDF)
    assert doc["meta"]["extraction"].startswith("pypdf") and [p["label"] for p in doc["pages"]] == ["538", "539", "540"]
    assert "412" in doc["pages"][1]["text"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_ocr_for_pages_without_text():
    doc = texts.read_pdf(FIXTURES / "claims" / "scanned.pdf")
    assert doc["pages"][0]["ocr"] and "correlational" in doc["pages"][0]["text"]


def test_no_text_layer_without_ocr(monkeypatch):
    which = shutil.which
    monkeypatch.setattr(texts.shutil, "which", lambda name: None if name == "tesseract" else which(name))
    doc = texts.read_pdf(FIXTURES / "claims" / "scanned.pdf")
    assert "no text layer" in doc["meta"]["problem"] and "not installed" in doc["meta"]["problem"]


def test_running_heads_beat_default_page_labels(monkeypatch):
    """A journal PDF with a default 1..N /PageLabels and two-column pages whose running head holds the number."""
    def layout(left, right):
        body = [f"{f'left column words, line {c}':<55}     right column words, line {c}" for c in "abcdefghijkl"]
        return "\n".join([f"{left:<60}{right:>40}", ""] + body)
    raw = [layout("Psychological Medicine", ""), layout("5710", "Jan-Willem van Prooijen et al."),
           layout("Psychological Medicine", "5711"), layout("5712", "Jan-Willem van Prooijen et al.")]
    monkeypatch.setattr(texts, "_pdftotext", lambda path: raw)
    monkeypatch.setattr(texts, "_pdf_page_labels", lambda path, count: [str(i) for i in range(1, count + 1)])
    assert [p["label"] for p in texts.read_pdf(PDF)["pages"]] == ["5709", "5710", "5711", "5712"]
    monkeypatch.setattr(texts, "_pdf_page_labels", lambda path, count: ["i", "ii", "1", "2"])  # real labels win
    assert [p["label"] for p in texts.read_pdf(PDF)["pages"]] == ["i", "ii", "1", "2"]


def test_detect_labels():
    pages = [f"Header\nbody\n{n}" for n in (12, 13, 14, 15)]
    assert texts.detect_labels(pages) == ["12", "13", "14", "15"]
    assert texts.detect_labels(["no numbers", "at all"]) == [None, None]
    assert texts.detect_labels(["PLOS ONE 1 / 9\nx", "PLOS ONE 2 / 9\nx", "PLOS ONE 3 / 9\nx"]) == ["1", "2", "3"]


def test_other_formats(tmp_path):
    epub = tmp_path / "book.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/'
                   'elements/1.1/"><metadata><dc:title>A Book</dc:title></metadata><manifest><item id="a" href="a.xhtml"/>'
                   '<item id="b" href="b.xhtml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
        z.writestr("OEBPS/a.xhtml", "<html><body><h1>Chapter 1</h1><p>First chapter text.</p></body></html>")
        z.writestr("OEBPS/b.xhtml", "<html><body><h2>Chapter 2</h2><p>Second chapter text.</p><script>x()</script></body></html>")
    book = texts.read_file(epub)
    assert [(p["label"], p["text"]) for p in book["pages"]] == [("Chapter 1", "First chapter text."),
                                                                 ("Chapter 2", "Second chapter text.")]
    html = tmp_path / "page.html"
    html.write_text("<nav>menu</nav><h1>Report</h1><p>Intro.</p><h2>Results</h2><p>Found 45%.</p>", encoding="utf-8")
    assert [(p["label"], p["text"]) for p in texts.read_file(html)["pages"]] == [("Report", "Intro."), ("Results", "Found 45%.")]
    d = docx.Document()
    d.add_heading("Methods", level=1)
    d.add_paragraph("We asked 100 people.")
    d.save(tmp_path / "source.docx")
    assert texts.read_file(tmp_path / "source.docx")["pages"][0]["label"] == "Methods"
    jats = texts.read_jats('<article><front><article-meta><title-group><article-title>T</article-title></title-group>'
                           '<abstract><p>Short abstract.</p></abstract></article-meta></front><body><sec><title>Results'
                           '</title><p>We found it.</p><sec><title>Study 2</title><p>Again.</p></sec></sec></body></article>')
    assert [(p["label"], p["text"]) for p in jats["pages"]] == [("Results", "We found it."), ("Results > Study 2", "Again.")]
    assert jats["meta"]["abstract"] == "Short abstract."


def test_identity_and_version():
    doc = texts.read_pdf(PDF)
    assert texts.identity(doc, REF)[0] and not texts.identity(doc, OTHER)[0]
    assert texts.version_of(doc) == "published"
    assert texts.version_of({"pages": [{"text": "PsyArXiv preprint. Not peer reviewed."}]}) == "preprint"
    assert texts.version_of({"pages": [{"text": "This is the author accepted manuscript."}]}) == "accepted"
    assert texts.level_of("article", "preprint", True, True) == "PREPRINT"
    assert texts.level_of("web", "published", True, False) == "WEB"
    assert texts.level_of("article", "", False, True) == "ABSTRACT" and texts.level_of("book", "", False, False) == "NONE"


def test_matching_your_files(tmp_path):
    shutil.copy(PDF, tmp_path / "scan0001.pdf")  # matched by the DOI printed on its first page
    (tmp_path / "notes.txt").write_text("The Psychology of Conspiracy Theories\nKaren Douglas", encoding="utf-8")
    (tmp_path / "Kowalska_2017_supp.txt").write_text("Supplementary table S1: 412 participants.", encoding="utf-8")
    (tmp_path / "unrelated.txt").write_text("Nothing to see.", encoding="utf-8")
    files = {f["path"].rsplit("/", 1)[-1]: f for f in texts.scan(tmp_path)}
    assert texts.match_file(files["scan0001.pdf"], [REF, OTHER]) == ("kowalska2017", "DOI in the file")
    assert texts.match_file(files["notes.txt"], [REF, OTHER])[0] == "douglas2017"
    assert texts.match_file(files["Kowalska_2017_supp.txt"], [REF, OTHER]) == ("kowalska2017", "AuthorYear file name")
    assert files["Kowalska_2017_supp.txt"]["supp"] and texts.match_file(files["unrelated.txt"], [REF, OTHER])[0] is None
    for entry in files.values():
        entry["ref"] = texts.match_file(entry, [REF, OTHER])[0]
    text = texts.build_text(REF, list(files.values()), None, None)
    assert (text["level"], text["version"]) == ("FULL", "published") and text["origin"].endswith("scan0001.pdf")
    assert text["supplements"] and "Supplement Kowalska_2017_supp.txt" in texts.render(text)
    none = texts.build_text(dict(OTHER, key="other", doi=None), [], None, None)
    assert none["level"] == "NONE" and "no DOI" in none["reason"]
    wrong = texts.build_text(dict(OTHER, key="kowalska2017"), list(files.values()), None, None)  # identity fails
    assert wrong["level"] == "NONE" and "identity check failed" in wrong["discarded"][0]["reason"]
