"""Part 2, step 3: candidate passages for each claim (BM25 over paragraph chunks, no dependencies) and packets."""

from __future__ import annotations

import math
import re
from collections import Counter

from .compare import fold
from .texts import where

STOPWORDS = {fold(w) for w in """
a about after all also an and any are as at be been being between both but by can could did do does during each
for from had has have how if in into is it its may more most no not of on or other our such than that the their
them then there these they this those through to under was we were what when which while who will with would
i w z ze na do nie się że to jest są oraz lub ale jak co od po przez dla przy czy tym te tej ten ta tego jego
ich być było była były może można który która które których także również jako już tylko więc gdy też
""".split()}
CHUNK_WORDS, STEP = 120, 90


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(text).lower()) if len(w) > 1 and w not in STOPWORDS]


def number_key(text: str) -> str:
    """'1,200' and '1 200' -> '1200'; '0,45' and '.45' -> '0.45'; '45.5%' -> '45.5'."""
    t = text.strip().rstrip("%").replace(" ", " ")
    t = re.sub(r"(?<=\d)[ ,](?=\d{3}\b)", "", t)
    t = t.replace(",", ".")
    return "0" + t if t.startswith(".") else t


def numbers_in(text: str) -> set[str]:
    return {number_key(m) for m in re.findall(r"(?<![\w.])(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:[.,]\d+)?|(?<![\w.,])[.,]\d+",
                                              text)}


def chunks(text: dict) -> list[dict]:
    """Paragraph chunks of a source text (and its supplements), each about 120 words, with their location."""
    out = []
    sources = [("", text.get("pages", []))] + [(f"Supplement, ", s["pages"]) for s in text.get("supplements", [])]
    for prefix, pages in sources:
        for p in pages:
            words = " ".join(p["text"].split()).split()
            for start in range(0, max(len(words), 1), STEP):
                piece = " ".join(words[start:start + CHUNK_WORDS])
                if piece:
                    out.append({"where": prefix + where(p), "pdf": p.get("pdf"), "label": p.get("label"),
                                "text": piece})
                if start + CHUNK_WORDS >= len(words):
                    break
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b, self.lengths = k1, b, [len(d) for d in docs]
        self.average = sum(self.lengths) / len(docs) if docs else 0
        self.tf = [Counter(d) for d in docs]
        self.df = Counter(t for d in docs for t in set(d))
        self.n = len(docs)

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, length in zip(self.tf, self.lengths):
            score = 0.0
            for term in set(query):
                if term in tf:
                    idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                    norm_tf = tf[term] * (self.k1 + 1) / (tf[term] + self.k1 * (1 - self.b + self.b * length / self.average))
                    score += idf * norm_tf
            out.append(score)
        return out


def claim_query(row: dict) -> str:
    """The words of the claim: the scope hint and the sentence, without the citation text."""
    sentence = row["sentence"].replace(row.get("citation") or "", " ")
    return f"{row.get('scope', '')} {sentence}"


def passages(row: dict, pieces: list[dict], index: BM25 | None = None, top: int = 5) -> list[dict]:
    """The top BM25 passages for a claim, plus every passage that contains one of the claim's numbers."""
    if not pieces:
        return []
    index = index or BM25([tokenize(p["text"]) for p in pieces])
    scores = index.scores(tokenize(claim_query(row)))
    ranked = sorted(range(len(pieces)), key=lambda i: -scores[i])
    chosen = [i for i in ranked[:top] if scores[i] > 0]
    wanted = {number_key(n) for n in row.get("numbers", [])}
    if wanted:
        chosen += [i for i, p in enumerate(pieces) if i not in chosen and wanted & numbers_in(p["text"])][:top]
    return [{"where": pieces[i]["where"], "score": round(scores[i], 2), "text": pieces[i]["text"],
             "numbers": sorted(wanted & numbers_in(pieces[i]["text"]))} for i in chosen]


def packet(ref: dict, text: dict, rows: list[dict], text_path: str) -> dict:
    """Everything a judge needs about one source: metadata, evidence level, abstract and each citing claim."""
    pieces = chunks(text)
    index = BM25([tokenize(p["text"]) for p in pieces]) if pieces else None
    return {
        "refkey": ref["key"], "reference": ref["raw"], "doi": ref.get("doi"), "title": ref.get("title"),
        "authors": ref["authors"], "year": ref.get("year"), "notice": ref.get("notice", ""),
        "evidence_level": text["level"], "version": text["version"], "origin": text["origin"],
        "full_text": text_path if text["pages"] else None, "abstract": text["abstract"],
        "occurrences": [{
            "id": r["id"], "sentence": r["sentence"], "scope": r["scope"], "previous": r["prev"], "next": r["next"],
            "citation": r["citation"], "group": r["group"], "locator": r["locator"], "prefix": r["prefix"],
            "as_cited_in": r["original"], "quotes": r["quotes"], "numbers": r["numbers"],
            "passages": passages(r, pieces, index)} for r in rows]}


def candidates(texts: dict[str, dict], row: dict, exclude: str | None, top: int = 5) -> list[dict]:
    """The passages in the other sources that best match a claim, for proposing a better-fitting reference."""
    pieces = [dict(p, ref=key) for key, text in texts.items() if key != exclude for p in chunks(text)]
    if not pieces:
        return []
    scores = BM25([tokenize(p["text"]) for p in pieces]).scores(tokenize(claim_query(row)))
    ranked = sorted(range(len(pieces)), key=lambda i: -scores[i])[:top]
    return [{"ref": pieces[i]["ref"], "where": pieces[i]["where"], "score": round(scores[i], 2),
             "text": pieces[i]["text"]} for i in ranked if scores[i] > 0]
