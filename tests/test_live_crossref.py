"""Opt-in live call to Crossref. Requires network access to api.crossref.org.

    XI_TEST_CROSSREF_LIVE=1 python -m pytest tests/test_live_crossref.py

It authorises the source inside a throwaway test database only.
"""

import os

import pytest

from integrity.domain.enums import ApiOutcome
from integrity.infrastructure.db.session import session_scope
from integrity.integrations.factory import crossref_client

pytestmark = pytest.mark.skipif(os.environ.get("XI_TEST_CROSSREF_LIVE") != "1", reason="XI_TEST_CROSSREF_LIVE not set")


def test_live_doi_lookup_and_not_found(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["integrity", "sources-sync"])
    r = runner.invoke(args=["integrity", "source-review", "--code", "crossref", "--reviewed-by", "live-test",
                            "--terms-url", "https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
                            "--authorization", "authorized", "--allow", "commercial_use", "--enable"])
    assert r.exit_code == 0, r.output
    c = crossref_client(app)
    with session_scope(app) as s:
        found = c.lookup_doi(s, "10.1038/nature12373")
        assert found.result.outcome == ApiOutcome.OK, found.result
        assert found.record.year == 2013 and found.record.container
        missing = c.lookup_doi(s, "10.5555/integrity-test-does-not-exist-0000")
        assert missing.result.outcome == ApiOutcome.NOT_FOUND
