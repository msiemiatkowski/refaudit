"""Polite, cached access to doi.org, Crossref, DataCite and OpenAlex, and finding a reference's record."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

from . import __version__
from .compare import Match, Notice, Record, RED_NOTICES, norm, same_surname, similarity, title_score, year_close
from .parse import Person, Reference

HANDLES = "https://doi.org/api/handles"
CROSSREF = "https://api.crossref.org"
DATACITE = "https://api.datacite.org"
OPENALEX = "https://api.openalex.org"
SERVICES = ("doi.org", "Crossref", "DataCite", "OpenAlex", "OpenAlex search")
CROSSREF_FIELDS = ("DOI,type,title,subtitle,author,container-title,short-container-title,volume,issue,page,"
                   "article-number,published-print,published-online,issued,updated-by")
OPENALEX_FIELDS = "id,doi,type,display_name,publication_year,authorships,primary_location,biblio,is_retracted"
TIMEOUT = 20          # seconds
INTERVAL = 0.2        # at most 5 requests per second
RETRIES = 4           # on 429, 5xx and network errors, waiting 2, 4, 8 and 16 s
MAX_AGE = 7 * 86400   # cached responses are fetched again after a week


class ApiError(Exception):
    """A request failed."""


class Refused(ApiError):
    """The service refused requests (or was turned off); it is skipped for the rest of the run."""


class Client:
    """GET JSON with mailto, rate limiting, retries with backoff, timeouts and an on-disk JSON cache."""

    def __init__(self, cache_dir, mailto=None, openalex_key=None, use_openalex=True, offline=False):
        self.cache_dir, self.mailto, self.openalex_key, self.offline = Path(cache_dir), mailto, openalex_key, offline
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"refaudit/{__version__}"
        self.fetched, self.cached = Counter(), Counter()
        self.failures: list[str] = []
        self.skipped: dict[str, str] = {}
        if not use_openalex:
            self.skipped["OpenAlex"] = self.skipped["OpenAlex search"] = "turned off (--no-openalex)"
        self._next = 0.0

    def get(self, service: str, url: str, params: dict | None = None):
        """The JSON body, or None for 404 Not Found."""
        if service in self.skipped:
            raise Refused(f"{service} skipped: {self.skipped[service]}")
        key = url + ("?" + urlencode(sorted(params.items())) if params else "")
        path = self.cache_dir / f"{service.split()[0].lower()}-{hashlib.sha1(key.encode()).hexdigest()[:20]}.json"
        try:
            if self.offline or time.time() - path.stat().st_mtime < MAX_AGE:
                body = json.loads(path.read_text(encoding="utf-8"))["body"]
                self.cached[service] += 1
                return body
        except (OSError, ValueError, KeyError):
            pass
        if self.offline:
            self.skipped[service] = "no recorded response (offline)"
            raise Refused(f"{service}: no recorded response for {key}")
        status, body = self._fetch(service, url, params)
        self.fetched[service] += 1
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"url": key, "status": status, "body": body}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)
        return body

    def _fetch(self, service, url, params):
        params, headers = dict(params or {}), {}
        if self.mailto and service.startswith(("Crossref", "OpenAlex")):  # their polite pools
            params["mailto"] = self.mailto
            headers["User-Agent"] = f"refaudit/{__version__} (mailto:{self.mailto})"
        if self.openalex_key and service.startswith("OpenAlex"):
            headers["Authorization"] = f"Bearer {self.openalex_key}"
        problem, wait = "", 0
        for attempt in range(RETRIES + 1):
            if attempt:
                time.sleep(wait)
            pause = self._next - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            self._next = time.monotonic() + INTERVAL
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=TIMEOUT)
            except requests.RequestException as exc:
                problem, wait = type(exc).__name__, 2 ** (attempt + 1)
                continue
            if r.status_code == 404:
                return 404, None
            if r.status_code == 200:
                try:
                    return 200, r.json()
                except ValueError:
                    problem = "invalid JSON"
                    break
            delay = _retry_after(r)
            if r.status_code in (401, 402, 403) or (r.status_code == 429 and delay > 60):
                reason = f"refused requests (HTTP {r.status_code}{_reason(r)})"
                self.skipped[service] = reason
                self.failures.append(f"{service} {reason}; skipped for the rest of the run.")
                raise Refused(f"{service} {reason}")
            problem, wait = f"HTTP {r.status_code}", delay or 2 ** (attempt + 1)
            if r.status_code != 429 and r.status_code < 500:
                break
        message = f"{service}: {problem} for {url}" + (f" (after {RETRIES + 1} attempts)" if attempt == RETRIES else "")
        self.failures.append(message)
        raise ApiError(message)

    def summary(self) -> list[tuple[str, str]]:
        """(service, plain-language result) for the Summary sheet."""
        def n(count, word):
            return f"{count} {word}{'' if count == 1 else 's'}"

        rows = []
        for service in SERVICES:
            fetched, cached = self.fetched[service], self.cached[service]
            text = (f"reached ({n(fetched, 'request')}" if fetched
                    else f"answered from the cache only ({n(cached, 'response')}" if cached else "not needed")
            if fetched and cached:
                text += f"; {cached} more answered from the cache"
            text += ")" if fetched or cached else ""
            if service in self.skipped:
                text = f"skipped: {self.skipped[service]}" + (f" (after {n(fetched + cached, 'response')})"
                                                             if fetched or cached else "")
            rows.append((service, text))
        return rows


def _retry_after(r) -> int:
    try:
        return int(r.headers.get("Retry-After", 0))
    except ValueError:
        return 60


def _reason(r) -> str:
    try:
        data = r.json()
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    message = re.split(r"(?<=[.!?])\s", str(data.get("message", "")), maxsplit=1)[0]
    text = ": ".join(str(x) for x in (data.get("error"), message) if x)
    return f": {text[:150]}" if text else ""


# --- records ---------------------------------------------------------------

def _year(date) -> int | None:
    try:
        return int((date or {})["date-parts"][0][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _date(date) -> str:
    try:
        return "-".join(f"{int(x):02d}" for x in date["date-parts"][0] if x)
    except (KeyError, IndexError, TypeError, ValueError):
        return ""


def _first(values) -> str:
    return values[0] if values else ""


def from_crossref(m: dict) -> Record:
    printed = _year(m.get("published-print")) or _year((m.get("journal-issue") or {}).get("published-print"))
    online = _year(m.get("published-online"))
    return Record(
        origin="Crossref", doi=(m.get("DOI") or "").lower(), kind=m.get("type", ""),
        authors=[Person(a.get("family") or a.get("name", ""), given=a.get("given", "")) for a in m.get("author", [])],
        title=_first(m.get("title")), subtitle=_first(m.get("subtitle")),
        journal=_first(m.get("container-title")), short_journals=m.get("short-container-title") or [],
        volume=m.get("volume", ""), issue=m.get("issue", ""), pages=m.get("page", ""),
        article_number=m.get("article-number", ""),
        issue_year=printed or (None if online else _year(m.get("issued"))), online_year=online,
        updated_by=m.get("updated-by") or [])


def from_datacite(data: dict) -> Record:
    a = data.get("attributes", {})
    authors = []
    for c in a.get("creators", []):
        name = c.get("name", "")
        if c.get("familyName"):
            authors.append(Person(c["familyName"], given=c.get("givenName", "")))
        elif "," in name and c.get("nameType") != "Organizational":
            surname, given = name.split(",", 1)
            authors.append(Person(surname.strip(), given=given.strip()))
        else:
            authors.append(Person(name))
    box = a.get("container") or {}
    year = a.get("publicationYear")
    return Record(
        origin="DataCite", doi=(a.get("doi") or "").lower(), kind=(a.get("types") or {}).get("resourceTypeGeneral", ""),
        authors=authors, title=(a.get("titles") or [{}])[0].get("title", ""), journal=box.get("title", ""),
        volume=box.get("volume", ""), issue=box.get("issue", ""),
        pages="-".join(dict.fromkeys(p for p in (box.get("firstPage"), box.get("lastPage")) if p)),
        issue_year=int(year) if str(year or "").isdigit() else None)


def from_openalex(w: dict) -> Record:
    authors = []
    for au in w.get("authorships", []):
        words = (au.get("raw_author_name") or (au.get("author") or {}).get("display_name") or "").split()
        if words:
            authors.append(Person(words[-1], given=" ".join(words[:-1])))
    biblio = w.get("biblio") or {}
    source = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
    year = w.get("publication_year")
    return Record(
        origin="OpenAlex", doi=(w.get("doi") or "").replace("https://doi.org/", "").lower(), kind=w.get("type", ""),
        authors=authors, title=w.get("display_name") or "", journal=source or "",
        volume=biblio.get("volume") or "", issue=biblio.get("issue") or "",
        pages="-".join(dict.fromkeys(p for p in (biblio.get("first_page"), biblio.get("last_page")) if p)),
        issue_year=int(year) if year else None)


# --- lookups ---------------------------------------------------------------

def _path(doi: str) -> str:
    return quote(doi, safe="/")


def doi_registered(client: Client, doi: str) -> bool:
    body = client.get("doi.org", f"{HANDLES}/{_path(doi)}")
    return bool(body) and body.get("responseCode") == 1


def fetch_record(client: Client, doi: str) -> Record | None:
    """Crossref /works/{doi}, or DataCite /dois/{doi} if Crossref does not have it."""
    body = client.get("Crossref", f"{CROSSREF}/works/{_path(doi)}")
    if body:
        return from_crossref(body["message"])
    body = client.get("DataCite", f"{DATACITE}/dois/{_path(doi)}")
    return from_datacite(body["data"]) if body else None


def query_text(ref: Reference) -> str:
    """The reference without DOIs and URLs, for Crossref's query.bibliographic."""
    return " ".join(re.sub(r"\S*10\.\d{4,9}/\S+|https?://\S+", " ", ref.raw).split())[:1000]


def search_crossref(client: Client, ref: Reference) -> list[Record]:
    body = client.get("Crossref", f"{CROSSREF}/works",
                      {"query.bibliographic": query_text(ref), "rows": 5, "select": CROSSREF_FIELDS})
    return [from_crossref(item) for item in body["message"]["items"]] if body else []


def search_openalex(client: Client, ref: Reference) -> list[Record]:
    body = client.get("OpenAlex search", f"{OPENALEX}/works",
                      {"search": norm(ref.title), "per_page": 5, "select": OPENALEX_FIELDS})
    return [from_openalex(w) for w in body["results"]] if body else []


def best_candidate(ref: Reference, records: list[Record]) -> tuple[int, Record] | None:
    """The most similar record with a DOI, the same first author and a year within +-1 (similarity >= 80).

    Ties go to the record whose journal is closest to the cited one (a journal article over its preprint),
    then to the earlier result."""
    best, best_key = None, None
    for rec in records:
        if not (rec.doi and ref.authors and rec.authors):
            continue
        sim = title_score(ref.title, rec)
        if sim < 80 or not same_surname(ref.authors[0].surname, rec.authors[0].surname) or not year_close(ref.year, rec):
            continue
        key = (sim, similarity(ref.source, rec.journal))
        if best_key is None or key > best_key:
            best, best_key = (sim, rec), key
    return best


def same_work(ref: Reference, rec: Record) -> bool:
    """False only if the title similarity is below 60 and the first author differs."""
    title_differs = bool(ref.title and rec.title) and title_score(ref.title, rec) < 60
    author_differs = bool(ref.authors and rec.authors) and not same_surname(ref.authors[0].surname,
                                                                            rec.authors[0].surname)
    return not (title_differs and author_differs)


def find_match(client: Client, ref: Reference, notes: list[str]) -> Match:
    """Find the record by DOI, or else by bibliographic search in Crossref and OpenAlex."""
    match = Match()
    if ref.doi:
        if not doi_registered(client, ref.doi):
            match.doi_state = "unregistered"
        else:
            rec = fetch_record(client, ref.doi)
            if rec is None:
                match.doi_state, match.route = "no-metadata", "DOI registered, but no Crossref or DataCite record"
                return match
            if same_work(ref, rec):
                match.record, match.doi_state, match.confidence, match.route = rec, "ok", "doi", f"DOI → {rec.origin}"
                return match
            match.doi_state, match.other = "different", rec
    searched = ["Crossref"]
    candidates = search_crossref(client, ref)
    best = best_candidate(ref, candidates)
    if (best is None or best[0] < 90) and ref.title:
        try:
            candidates += search_openalex(client, ref)
            searched.append("OpenAlex")
            best = best_candidate(ref, candidates)
        except Refused:
            pass
        except ApiError as exc:
            notes.append(f"OpenAlex search failed ({exc}).")
    match.searched = " and ".join(searched)
    prefix = {"unregistered": "Cited DOI not registered; ", "different": "Cited DOI is another work; "}.get(
        match.doi_state, "")
    if best is None:
        match.route = f"{prefix}no record ({match.searched} searched)"
        return match
    sim, rec = best
    route = f"{rec.origin} search"
    if rec.origin == "OpenAlex":
        full = fetch_record(client, rec.doi)
        if full:
            rec, route = full, f"OpenAlex search → {full.origin}"
    match.record, match.similarity = rec, sim
    match.confidence = "high" if sim >= 90 else "low"
    match.route = f"{prefix}{route}, {match.confidence} confidence (title similarity {sim})"
    return match


def find_notices(client: Client, rec: Record, notes: list[str]) -> list[Notice]:
    """Retractions, expressions of concern etc. from Crossref (updated-by, updates filter) and OpenAlex."""
    found: dict[tuple[str, str], Notice] = {}

    def add(kind, date, doi, source):
        kind = re.sub(r"[\s-]+", "_", (kind or "notice").strip().lower())
        found.setdefault((kind, (doi or "").lower()), Notice(kind, date, (doi or "").lower(), source))

    for u in rec.updated_by:
        add(u.get("type") or u.get("label"), _date(u.get("updated")), u.get("DOI"), "Crossref updated-by")
    try:
        body = client.get("Crossref", f"{CROSSREF}/works",
                          {"filter": f"updates:{rec.doi}", "rows": 20, "select": "DOI,update-to,issued"})
        for item in (body or {}).get("message", {}).get("items", []):
            for u in item.get("update-to") or []:
                if (u.get("DOI") or "").lower() == rec.doi:
                    add(u.get("type") or u.get("label"), _date(u.get("updated")) or _date(item.get("issued")),
                        item.get("DOI"), "Crossref updates")
    except ApiError as exc:
        notes.append(f"Crossref notice search failed ({exc}).")
    try:
        work = client.get("OpenAlex", f"{OPENALEX}/works/doi:{_path(rec.doi)}", {"select": "id,doi,is_retracted"})
        if work and work.get("is_retracted") and not any(k in RED_NOTICES for k, _ in found):
            add("is_retracted", "", "", "OpenAlex")
    except Refused:
        pass
    except ApiError as exc:
        notes.append(f"OpenAlex check failed ({exc}); is_retracted not checked.")
    return list(found.values())
