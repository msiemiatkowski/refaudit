"""The HTTP client without network: retries, refusals, polite parameters, rate limit and cache."""

import json

import pytest
import requests

from refaudit import lookup
from refaudit.lookup import ApiError, Client, Refused


class Response:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def json(self):
        if self.body is None:
            raise ValueError("no JSON")
        return self.body


class Session:
    """Replays canned responses and records the requests."""

    def __init__(self, *responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {}),
                           "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(lookup.time, "sleep", waited.append)
    return waited


def client(tmp_path, *responses, **kwargs):
    c = Client(tmp_path / "cache", **kwargs)
    c.session = Session(*responses)
    return c


def test_retries_with_backoff_on_429_and_5xx(tmp_path, sleeps):
    c = client(tmp_path, Response(429), Response(503), requests.ConnectionError(), Response(200, {"ok": 1}))
    assert c.get("Crossref", "https://api.crossref.org/works/x") == {"ok": 1}
    assert len(c.session.calls) == 4
    assert [s for s in sleeps if s >= 1] == [2, 4, 8]  # backoff (the rest are rate-limit pauses)


def test_gives_up_after_retries(tmp_path, sleeps):
    c = client(tmp_path, *[Response(500)] * 5)
    with pytest.raises(ApiError, match="HTTP 500"):
        c.get("Crossref", "https://api.crossref.org/works/x")
    assert len(c.session.calls) == 5 and "after 5 attempts" in c.failures[0]


def test_persistent_429_and_long_waits_are_refusals(tmp_path, sleeps):
    c = client(tmp_path, *[Response(429)] * 5)
    with pytest.raises(Refused):
        c.get("OpenAlex", "https://api.openalex.org/works/doi:x")
    assert "OpenAlex" in c.skipped and max(sleeps) <= lookup.MAX_WAIT
    maintenance = client(tmp_path, Response(503, headers={"Retry-After": "3600"}))
    with pytest.raises(Refused):
        maintenance.get("Crossref", "https://api.crossref.org/works/x")
    assert len(maintenance.session.calls) == 1 and not [s for s in sleeps[5:] if s > lookup.MAX_WAIT]
    failing = client(tmp_path, *[Response(502)] * 5)
    with pytest.raises(ApiError):
        failing.get("DataCite", "https://api.datacite.org/dois/x")
    assert dict(failing.summary())["DataCite"] == "not reached (1 failed request)"


def test_refusal_skips_the_service(tmp_path, sleeps):
    budget = Response(429, {"error": "Rate limit exceeded", "message": "Insufficient budget. Use a key."},
                      {"Retry-After": "75000"})
    c = client(tmp_path, budget)
    with pytest.raises(Refused):
        c.get("OpenAlex search", "https://api.openalex.org/works", {"search": "x"})
    with pytest.raises(Refused):  # no second request
        c.get("OpenAlex search", "https://api.openalex.org/works", {"search": "y"})
    assert len(c.session.calls) == 1
    assert "HTTP 429: Rate limit exceeded: Insufficient budget." in c.skipped["OpenAlex search"]
    assert dict(c.summary())["OpenAlex search"].startswith("skipped: refused requests")
    forbidden = client(tmp_path, Response(403))
    with pytest.raises(Refused):
        forbidden.get("OpenAlex", "https://api.openalex.org/works/doi:x")


def test_polite_parameters(tmp_path, sleeps):
    c = client(tmp_path, Response(200, {}), Response(200, {}), Response(404),
               mailto="me@example.org", openalex_key="KEY")
    c.get("Crossref", "https://api.crossref.org/works", {"rows": 5})
    c.get("OpenAlex", "https://api.openalex.org/works/doi:x")
    assert c.get("doi.org", "https://doi.org/api/handles/x") is None  # 404
    crossref, openalex, handles = c.session.calls
    assert crossref["params"] == {"rows": 5, "mailto": "me@example.org"} and crossref["timeout"] == 20
    assert crossref["headers"]["User-Agent"].endswith("(mailto:me@example.org)")
    assert openalex["params"] == {"mailto": "me@example.org", "api_key": "KEY"}
    assert handles["params"] == {} and handles["headers"] == {}  # the e-mail goes to the polite pools only
    assert Client(tmp_path).session.headers["User-Agent"].startswith("refaudit/")


def test_rate_limit(tmp_path, sleeps):
    c = client(tmp_path, Response(200, {}), Response(200, {}))
    c.get("Crossref", "https://api.crossref.org/works/a")
    c.get("Crossref", "https://api.crossref.org/works/b")
    assert sleeps and 0.15 < sleeps[-1] <= lookup.INTERVAL  # the second request waits ~0.2 s


def test_json_cache(tmp_path, sleeps):
    c = client(tmp_path, Response(200, {"message": 1}), Response(404), mailto="me@example.org")
    url = "https://api.crossref.org/works"
    assert c.get("Crossref", url, {"rows": 5}) == {"message": 1}
    assert c.get("Crossref", url, {"rows": 5}) == {"message": 1}  # from the cache
    assert c.get("DataCite", "https://api.datacite.org/dois/x") is None
    assert c.get("DataCite", "https://api.datacite.org/dois/x") is None  # cached 404
    assert len(c.session.calls) == 2 and c.cached["Crossref"] == 1
    files = sorted((tmp_path / "cache").glob("*.json"))
    saved = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    assert {s["url"] for s in saved} == {f"{url}?rows=5", "https://api.datacite.org/dois/x"}  # no mailto in keys
    offline = Client(tmp_path / "cache", offline=True)
    assert offline.get("Crossref", url, {"rows": 5}) == {"message": 1}
    with pytest.raises(Refused):
        offline.get("Crossref", url, {"rows": 6})
