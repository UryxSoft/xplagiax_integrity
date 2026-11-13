import json
import logging

from integrity.core.logging import REDACTED, JsonFormatter, redact


def test_redact_nested():
    out = redact({"Authorization": "Bearer x", "nested": {"api_key": "k", "ok": 1}, "list": [{"password": "p"}]})
    assert out == {"Authorization": REDACTED, "nested": {"api_key": REDACTED, "ok": 1}, "list": [{"password": REDACTED}]}


def test_formatter_emits_json_and_redacts_extra():
    rec = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": "hello", "secret_value": "s3cr3t", "doc_id": "d1"})
    payload = json.loads(JsonFormatter().format(rec))
    assert payload["msg"] == "hello" and payload["doc_id"] == "d1"
    assert payload["secret_value"] == REDACTED


def test_access_log_has_path_but_not_query(client, caplog):
    with caplog.at_level(logging.INFO, logger="integrity.access"):
        client.get("/api/v1/health/live?token=abc123")
    records = [r for r in caplog.records if r.name == "integrity.access"]
    assert len(records) == 1
    rendered = JsonFormatter().format(records[0])
    payload = json.loads(rendered)
    assert payload["path"] == "/api/v1/health/live" and payload["status"] == 200
    assert "abc123" not in rendered
