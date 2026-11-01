"""Part 2, step 6: deterministic checks of the judges' evidence quotes and of the manuscript's own quotations."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz.fuzz import partial_ratio

from .retrieval import number_key, numbers_in
from .texts import where

THRESHOLD = 95


def normalize(text: str) -> str:
    """Whitespace, hyphenation, ligatures, quote marks and case do not matter when matching quotes."""
    t = unicodedata.normalize("NFKC", text or "").replace("­", "")
    t = re.sub(r"(\w)[‐‑‒–—―−-]\s+(?=\w)", r"\1", t)  # a word hyphenated across lines ('con-\nspiracy')
    t = re.sub(r"[‘’‚‛′`]", "'", t)
    t = re.sub(r"[“”„‟″«»]", '"', t)
    t = re.sub(r"[‐‑‒–—―−-]", "", t)  # 'self-esteem' and a broken 'self- esteem' compare equal
    return " ".join(t.split()).lower()


def score(quote: str, text: str) -> int:
    q, t = normalize(quote), normalize(text)
    if not q or not t:
        return 0
    return 100 if q in t else round(partial_ratio(q, t))


def all_pages(text: dict) -> list[dict]:
    pages = list(text.get("pages", []))
    for supp in text.get("supplements", []):
        pages += [dict(p, supplement=supp["origin"]) for p in supp["pages"]]
    if text.get("abstract"):
        pages.append({"pdf": None, "label": "Abstract", "text": text["abstract"]})
    return pages


def locate(quote: str, text: dict) -> tuple[int, dict | None]:
    """The best score of a quote over all pages and the page it is on."""
    best = (0, None)
    for p in all_pages(text):
        s = score(quote, p["text"])
        if s > best[0]:
            best = (s, p)
        if s == 100:
            break
    return best


def stated_pages(item: dict, text: dict) -> list[dict]:
    """The pages an evidence item says it comes from (PDF page, printed page or section)."""
    pages = all_pages(text)
    if item.get("pdf_page") not in (None, ""):
        found = [p for p in pages if str(p.get("pdf")) == str(item["pdf_page"]) and not p.get("supplement")]
        if found or not item.get("supplement"):
            return found
    if item.get("page") not in (None, ""):
        return [p for p in pages if str(p.get("label")) == str(item["page"]).strip()]
    if item.get("section"):
        wanted = item["section"].lower()
        return [p for p in pages if p.get("pdf") is None and wanted in str(p.get("label", "")).lower()]
    return []


def check_evidence(evidence: list[dict], text: dict) -> list[dict]:
    """Each quote must be on the stated page (fuzzy >= 95 after normalization)."""
    results = []
    for item in evidence:
        quote = item.get("quote", "")
        pages = stated_pages(item, text)
        on_page = max((score(quote, p["text"]) for p in pages), default=0)
        if on_page >= THRESHOLD:
            results.append({"quote": quote, "ok": True, "score": on_page, "where": where(pages[0])})
            continue
        best, found = locate(quote, text)
        detail = (f"found on {where(found)} instead" if found and best >= THRESHOLD
                  else f"best match {best} anywhere in the text")
        results.append({"quote": quote, "ok": False, "score": on_page,
                        "where": where(pages[0]) if pages else "no such page", "detail": detail})
    return results


def locator_pages(locator: str | None) -> set[str]:
    """'p. 540' -> {'540'}; 'pp. 540–542' -> {'540', '541', '542'}; 's. 15' -> {'15'}."""
    if not locator:
        return set()
    m = re.search(r"(\d+)(?:\s*[-–—]\s*(\d+))?", locator)
    if not m:
        return set()
    first, last = int(m.group(1)), int(m.group(2) or m.group(1))
    if last < first:
        last = int(str(first)[:len(str(first)) - len(str(last))] + str(last))
    return {str(n) for n in range(first, min(last, first + 50) + 1)}


def check_quotations(quotes: list[str], locator: str | None, text: dict) -> list[dict]:
    """The manuscript's direct quotations must be in the source verbatim (after normalization), on the cited page."""
    results, cited = [], locator_pages(locator)
    for quote in quotes:
        best, found = locate(quote, text)
        ok = best == 100
        result = {"quote": quote, "ok": ok, "score": best, "where": where(found) if found else ""}
        if ok and cited and found and found.get("label") and found["label"] not in cited:
            result.update(ok=False, page_mismatch=True,
                          detail=f"on printed page {found['label']}, cited as {locator}")
        elif not ok:
            result["detail"] = "not found verbatim" + (f" (closest: {where(found)}, {best})" if found else "")
        results.append(result)
    return results


def check_locator(locator: str | None, evidence_checks: list[dict], text: dict) -> str:
    """Compare the manuscript's page locator with the pages where the evidence was found."""
    cited = locator_pages(locator)
    if not cited:
        return ""
    labels = set()
    for check in evidence_checks:
        if check["ok"]:
            labels |= {p.get("label") for p in all_pages(text) if where(p) == check["where"]}
    labels.discard(None)
    if not labels or labels & cited:
        return ""
    return f"cited {locator}; the evidence is on printed page {', '.join(sorted(labels))}"


def check_numbers(numbers: list[str], text: dict) -> dict[str, bool]:
    """Each number in the claim: found anywhere in the source text, or not."""
    present = set()
    for p in all_pages(text):
        present |= numbers_in(p["text"])
    return {n: number_key(n) in present for n in numbers}
