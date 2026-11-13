"""Adapter framework and Crossref adapter, with a fake transport (no network)."""

import json

import pytest
from sqlalchemy import select

from integrity.domain.enums import ApiOutcome, SourceAuthorization
from integrity.infrastructure.db.models import ApiRequest, AuditEvent, ExternalSource
from integrity.infrastructure.db.session import session_scope
from integrity.integrations.base import CircuitBreaker, HttpResponse, TransportError, TransportTimeout
from integrity.integrations.factory import crossref_client

WORK = {"status": "ok", "message": {
    "DOI": "10.1038/NATURE12373", "title": ["Nanometre-scale thermometry in a living cell"],
    "author": [{"given": "G.", "family": "Kucsko"}, {"name": "Consortium X"}],
    "issued": {"date-parts": [[2013, 7, 31]]}, "container-title": ["Nature"], "type": "journal-article",
    "publisher": "Springer Science and Business Media LLC", "abstract": "<p>not kept</p>"}}


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers, timeout_s, max_bytes):
        self.calls.append((url, headers))
        r = self.responses.pop(0) if self.responses else HttpResponse(500, {}, b"")
        if isinstance(r, Exception):
            raise r
        return r


def ok(body):
    return HttpResponse(200, {"content-type": "application/json"}, json.dumps(body).encode())


@pytest.fixture()
def registered(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["integrity", "sources-sync"]).exit_code == 0
    return runner


def authorize(runner, *extra):
    r = runner.invoke(args=["integrity", "source-review", "--code", "crossref", "--reviewed-by", "Legal (test)",
                            "--terms-url", "https://example.invalid/terms", "--authorization", "authorized",
                            "--allow", "commercial_use", "--enable", *extra])
    assert r.exit_code == 0, r.output


def client_with(app, *responses, breaker=None):
    t = FakeTransport(*responses)
    c = crossref_client(app, transport=t)
    c.sleep = lambda s: None
    if breaker:
        c.breaker = breaker
    return c, t


def api_rows(app):
    with session_scope(app) as s:
        return [(r.operation, r.outcome, r.http_status, r.result_count) for r in s.scalars(select(ApiRequest))]


# ------------------------------------------------------------------ policy

def test_seeded_sources_are_disabled_and_unverified(app, registered):
    with session_scope(app) as s:
        rows = s.scalars(select(ExternalSource)).all()
        assert {r.code for r in rows} >= {"crossref", "epo_ops", "uspto_odp"}
        assert all(not r.enabled and r.authorization == SourceAuthorization.UNVERIFIED for r in rows)
        assert all(r.allows_commercial_use is None for r in rows)
    # re-sync never touches existing rows
    assert "added: none" in registered.invoke(args=["integrity", "sources-sync"]).output


def test_unreviewed_source_makes_no_network_call(app, registered):
    c, t = client_with(app, ok(WORK))
    with session_scope(app) as s:
        res = c.lookup_doi(s, "10.1038/nature12373")
    assert res.result.outcome == ApiOutcome.BLOCKED_BY_POLICY and t.calls == []
    assert "unverified" in res.result.reason or "disabled" in res.result.reason
    assert api_rows(app) == [("doi_lookup", ApiOutcome.BLOCKED_BY_POLICY, None, None)]


def test_unregistered_source_is_blocked_without_record(app):
    c, t = client_with(app, ok(WORK))
    with session_scope(app) as s:
        res = c.lookup_doi(s, "10.1038/nature12373")
    assert res.result.outcome == ApiOutcome.BLOCKED_BY_POLICY and t.calls == [] and api_rows(app) == []


@pytest.mark.parametrize("args,msg", [
    (["--authorization", "unverified", "--allow", "commercial_use", "--enable"], "only be enabled"),
    (["--authorization", "authorized", "--enable"], "commercial_use"),
])
def test_review_cannot_enable_without_authorization_and_commercial_use(registered, args, msg):
    r = registered.invoke(args=["integrity", "source-review", "--code", "crossref", "--reviewed-by", "x",
                                "--terms-url", "https://example.invalid", *args])
    assert r.exit_code != 0 and msg in r.output


def test_extra_permissions_must_be_explicit(app, registered):
    authorize(registered)
    c, t = client_with(app, ok(WORK))
    with session_scope(app) as s:
        res = c.call(s, operation="x", path="/works", query=None, fingerprint_params={},
                     extra_permissions=("allows_storage",))
    assert res.outcome == ApiOutcome.BLOCKED_BY_POLICY and "allows_storage" in res.reason and t.calls == []


def test_review_is_audited(app, registered):
    authorize(registered, "--license", "CC0-1.0")
    with session_scope(app) as s:
        ev = s.scalars(select(AuditEvent).where(AuditEvent.action == "external_source.reviewed")).one()
        assert ev.details["reviewed_by"] == "Legal (test)" and ev.details["enabled"] is True
        src = s.scalars(select(ExternalSource).where(ExternalSource.code == "crossref")).one()
        assert src.allows_commercial_use is True and src.allows_storage is False and src.terms_reviewed_at


# ------------------------------------------------------------------ crossref behaviour

def test_doi_lookup_normalises_minimal_metadata(app, registered):
    authorize(registered)
    c, t = client_with(app, ok(WORK))
    with session_scope(app) as s:
        res = c.lookup_doi(s, "https://doi.org/10.1038/NATURE12373", organization_id=None)
    rec = res.record
    assert res.result.outcome == ApiOutcome.OK
    assert (rec.doi, rec.year, rec.container, rec.type) == ("10.1038/nature12373", 2013, "Nature", "journal-article")
    assert rec.authors == ("G. Kucsko", "Consortium X") and not hasattr(rec, "abstract")
    url, headers = t.calls[0]
    assert url == "https://api.crossref.org/works/10.1038%2Fnature12373"
    assert headers["User-Agent"].startswith("xplagiax-integrity/")
    [row] = api_rows(app)
    assert row == ("doi_lookup", ApiOutcome.OK, 200, 1)


def test_not_found_is_distinguished_from_errors(app, registered):
    authorize(registered)
    c, _ = client_with(app, HttpResponse(404, {}, b"Resource not found."))
    with session_scope(app) as s:
        res = c.lookup_doi(s, "10.5555/does-not-exist")
    assert res.result.outcome == ApiOutcome.NOT_FOUND and res.record is None and res.result.attempts == 1


def test_retries_transient_failures_then_succeeds(app, registered):
    authorize(registered)
    c, t = client_with(app, TransportTimeout("t"), HttpResponse(503, {}, b""), ok(WORK))
    delays = []
    c.sleep = delays.append
    with session_scope(app) as s:
        res = c.lookup_doi(s, "10.1038/nature12373")
    assert res.result.outcome == ApiOutcome.OK and res.result.attempts == 3 and len(t.calls) == 3
    assert delays == [0.5, 1.0]
    assert len(api_rows(app)) == 1  # one logical call, one record


def test_retry_after_is_honoured_but_bounded(app, registered):
    authorize(registered)
    c, _ = client_with(app, HttpResponse(429, {"retry-after": "120"}, b""), ok(WORK))
    delays = []
    c.sleep = delays.append
    with session_scope(app) as s:
        assert c.lookup_doi(s, "10.1038/nature12373").result.outcome == ApiOutcome.OK
    assert delays == [5.0]


def test_gives_up_and_reports_timeout(app, registered):
    authorize(registered)
    c, t = client_with(app, TransportTimeout("t"), TransportTimeout("t"), TransportTimeout("t"))
    with session_scope(app) as s:
        res = c.lookup_doi(s, "10.1038/nature12373")
    assert res.result.outcome == ApiOutcome.TIMEOUT and len(t.calls) == 3 and res.record is None


def test_malformed_json_is_a_provider_error_not_a_crash(app, registered):
    authorize(registered)
    c, _ = client_with(app, HttpResponse(200, {}, b"<html>oops</html>"))
    with session_scope(app) as s:
        res = c.lookup_doi(s, "10.1038/nature12373")
    assert res.result.outcome == ApiOutcome.SERVER_ERROR and res.record is None


def test_redirects_are_not_followed(app, registered):
    authorize(registered)
    c, t = client_with(app, HttpResponse(302, {"location": "http://169.254.169.254/"}, b""))
    with session_scope(app) as s:
        res = c.lookup_doi(s, "10.1038/nature12373")
    assert res.result.outcome == ApiOutcome.CLIENT_ERROR and len(t.calls) == 1


def test_circuit_breaker_opens_and_recovers(app, registered):
    authorize(registered)
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, cooldown_s=30, clock=lambda: now[0])
    c, t = client_with(app, *([TransportError("x")] * 6), ok(WORK), breaker=breaker)
    c.settings = type(c.settings)(max_attempts=1)
    with session_scope(app) as s:
        assert c.lookup_doi(s, "10.1038/nature12373").result.outcome == ApiOutcome.SERVER_ERROR
        assert c.lookup_doi(s, "10.1038/nature12373").result.outcome == ApiOutcome.SERVER_ERROR
        calls = len(t.calls)
        assert c.lookup_doi(s, "10.1038/nature12373").result.outcome == ApiOutcome.CIRCUIT_OPEN
        assert len(t.calls) == calls  # no call while open
        now[0] = 31
        t.responses = [ok(WORK)]
        assert c.lookup_doi(s, "10.1038/nature12373").result.outcome == ApiOutcome.OK


def test_search_is_bounded_and_query_is_not_stored(app, registered):
    authorize(registered)
    body = {"status": "ok", "message": {"items": [WORK["message"], {"DOI": "bad"}, WORK["message"]]}}
    c, t = client_with(app, ok(body))
    secret_title = "Confidential unpublished invention title " * 20
    with session_scope(app) as s:
        res = c.search(s, secret_title, rows=50)
    assert res.result.outcome == ApiOutcome.OK and [r.doi for r in res.records] == ["10.1038/nature12373"] * 2
    url = t.calls[0][0]
    assert "rows=5" in url and len(url) < 700  # rows capped, query truncated
    with session_scope(app) as s:
        row = s.scalars(select(ApiRequest)).one()
        stored = json.dumps({c.name: str(getattr(row, c.name)) for c in ApiRequest.__table__.columns})
        assert "Confidential" not in stored and row.result_count == 3


def test_fingerprint_is_keyed(app):
    c, _ = client_with(app)
    fp = c.fingerprint("doi_lookup", {"doi": "10.1/x"})
    import hashlib
    assert fp != hashlib.sha256(b'crossref:{"op": "doi_lookup", "p": {"doi": "10.1/x"}}').hexdigest()
    assert fp == c.fingerprint("doi_lookup", {"doi": "10.1/x"})


def test_adapter_cannot_be_pointed_at_another_host(app):
    c, _ = client_with(app)
    with pytest.raises(ValueError):
        c._url("@169.254.169.254/latest")
    with pytest.raises(ValueError):
        c.lookup_doi(None, "not a doi")


def test_operator_contact_in_user_agent(app):
    from dataclasses import replace

    app.config["XI_SETTINGS"] = replace(app.config["XI_SETTINGS"], crossref_mailto="ops@example.org")
    c, _ = client_with(app)
    assert c.user_agent.endswith("(mailto:ops@example.org)")


def test_mailto_is_validated():
    from integrity.config import ConfigError, Settings

    with pytest.raises(ConfigError):
        Settings(env="testing", crossref_mailto="not-an-email").validate()


# ------------------------------------------------------------------ real transport against a local server

@pytest.fixture()
def local_server():
    import http.server
    import threading
    import time as _t

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/slow":
                _t.sleep(2)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data")
                self.end_headers()
                return
            body = b"x" * (5000 if self.path == "/big" else 10)
            self.send_response(404 if self.path == "/missing" else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_urllib_transport_behaviour(local_server):
    from integrity.integrations.base import UrllibTransport

    t = UrllibTransport()
    assert t.get(local_server + "/ok", {}, 2, 100).body == b"x" * 10
    assert t.get(local_server + "/missing", {}, 2, 100).status == 404
    r = t.get(local_server + "/redirect", {}, 2, 100)
    assert r.status == 302  # returned, not followed
    with pytest.raises(TransportError):
        t.get(local_server + "/big", {}, 2, 100)
    with pytest.raises(TransportTimeout):
        t.get(local_server + "/slow", {}, 0.3, 100)
    with pytest.raises(TransportError):
        t.get("http://127.0.0.1:1/", {}, 1, 100)  # connection refused
