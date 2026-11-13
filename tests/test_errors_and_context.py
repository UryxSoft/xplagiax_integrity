import pytest


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/api/v1/nope")
    body = r.get_json()
    assert r.status_code == 404
    assert body["error"]["code"] == "not_found"
    assert body["error"]["correlation_id"] == r.headers["X-Request-ID"]


def test_method_not_allowed(client):
    r = client.post("/api/v1/health/live")
    assert r.status_code == 405 and r.get_json()["error"]["code"] == "method_not_allowed"


def test_request_too_large(app, client):
    app.config["MAX_CONTENT_LENGTH"] = 10
    app.add_url_rule("/_echo", "echo", lambda: str(len(__import__("flask").request.get_data())), methods=["POST"])
    r = client.post("/_echo", data=b"x" * 100)
    assert r.status_code == 413
    assert r.get_json()["error"]["code"] == "request_entity_too_large"


def test_unhandled_exception_hides_details(app, client):
    def boom():
        raise RuntimeError("SELECT * FROM secrets -- internal detail")

    app.add_url_rule("/_boom", "boom", boom)
    r = client.get("/_boom")
    assert r.status_code == 500
    assert "internal detail" not in r.get_data(as_text=True)
    assert r.get_json()["error"]["code"] == "internal_error"


def test_valid_inbound_request_id_is_echoed(client):
    r = client.get("/api/v1/health/live", headers={"X-Request-ID": "abc-12345678"})
    assert r.headers["X-Request-ID"] == "abc-12345678"


@pytest.mark.parametrize("bad", ["short", "has space 12345", "x" * 65, "<script>alert(1)</script>"])
def test_unsafe_inbound_request_id_is_replaced(client, bad):
    r = client.get("/api/v1/health/live", headers={"X-Request-ID": bad})
    assert r.headers["X-Request-ID"] != bad
    assert len(r.headers["X-Request-ID"]) == 32
