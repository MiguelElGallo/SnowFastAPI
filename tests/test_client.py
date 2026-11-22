import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import client


@pytest.mark.parametrize(
    ("status", "hint"),
    [
        (302, "sign-in"),
        (401, "--cursor"),
        (403, "role"),
        (422, "--limit"),
        (429, "Retry after 5 seconds"),
        (504, "query history"),
    ],
)
def test_client_guidance_names_the_failure(status, hint):
    with pytest.raises(RuntimeError) as caught:
        client.page_json(status, "application/json", b'{"detail":"private data"}', "5")
    assert f"HTTP {status}" in str(caught.value) and hint in str(caught.value)
    assert "private data" not in str(caught.value)


@pytest.mark.parametrize("payload", [b"not JSON", b'{"code":"invalid session"}', b'{"items":[]}'])
def test_client_rejects_non_page_before_printing(payload):
    with pytest.raises(RuntimeError, match="HTTP 200"):
        client.page_json(200, "application/json", payload)


def test_named_connection_client_resumes_from_cursor(monkeypatch, capsys):
    conn = MagicMock()
    db = conn.cursor.return_value
    db.description = [SimpleNamespace(name="url")]
    db.fetchone.return_value = ["fixture.snowflake.app"]
    conn._rest._token_request.return_value = {"data": {"sessionToken": "fixture"}}
    monkeypatch.setattr("snowflake.connector.connect", lambda **kwargs: conn)
    http = MagicMock()
    monkeypatch.setattr(client, "HTTPSConnection", lambda *args, **kwargs: http)
    res = http.getresponse.return_value.__enter__.return_value
    res.status = 200
    res.getheader.return_value = "application/json"
    res.read.return_value = b'{"items":[{"ID":3}],"next_cursor":null}'
    monkeypatch.setattr(sys, "argv", ["client.py", "demo", "-c", "fixture", "--cursor", "page-two"])
    client.main()
    assert http.request.call_args.args == ("GET", "/v1/tables/demo?limit=2&cursor=page-two")
    assert json.loads(capsys.readouterr().out)["items"] == [{"ID": 3}]
    conn.close.assert_called_once()


@pytest.mark.parametrize("data_status", [200, 429])
def test_browser_releases_each_response_and_resumes(monkeypatch, capsys, data_status):
    playwright = MagicMock()
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: playwright)
    browser = playwright.__enter__.return_value.chromium.launch.return_value
    context = browser.new_context.return_value
    pending, health, data = MagicMock(), MagicMock(), MagicMock()
    pending.status = 302
    health.status = 200
    health.headers = {"content-type": "application/json"}
    health.json.return_value = {"status": "ok"}
    data.status = data_status
    data.headers = {"content-type": "application/json", "retry-after": "3"}
    data.body.return_value = b'{"items":[],"next_cursor":null}'
    context.request.get.side_effect = [pending, health, data]
    monkeypatch.setattr("client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        sys, "argv", ["client.py", "http://127.0.0.1", "demo", "--cursor", "page-two"]
    )
    if data_status == 200:
        client.main()
        assert json.loads(capsys.readouterr().out) == {"items": [], "next_cursor": None}
    else:
        with pytest.raises(RuntimeError, match="Retry after 3 seconds"):
            client.main()
    last = context.request.get.call_args
    assert last.kwargs["params"]["cursor"] == "page-two" and last.kwargs["max_redirects"] == 0
    for response in (pending, health, data):
        response.dispose.assert_called_once()
    context.close.assert_called_once()
    browser.close.assert_called_once()
