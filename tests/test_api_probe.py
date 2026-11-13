import pytest
import requests

from tools.check_api import build_endpoint, check_api


@pytest.mark.parametrize("url", ["http://example.com", "https://key@example.com", "https://example.com/v1/chat/completions", "https://example.com?key=secret"])
def test_invalid_endpoint_rejected(url):
    with pytest.raises(ValueError):
        build_endpoint(url)


def test_root_path_appended_once():
    assert build_endpoint("https://api.deepseek.com/") == "https://api.deepseek.com/chat/completions"
    assert build_endpoint("https://example.com/v1/") == "https://example.com/v1/chat/completions"


@pytest.mark.parametrize("status,body,expected", [
    (200, {"choices": [{"message": {"content": "你好"}}]}, None),
    (200, {"choices": []}, "invalid_envelope"),
    (200, {"choices": [{"message": {"content": ""}}]}, "empty_content"),
    (401, {"error": "secret"}, "authentication"),
    (429, {"error": "secret"}, "rate_or_quota"),
    (503, {"error": "secret"}, "service_unavailable"),
])
def test_api_contract_and_redacted_report(monkeypatch, status, body, expected):
    class Response:
        status_code = status

        def json(self):
            return body

        def iter_content(self, chunk_size):
            import json
            yield json.dumps(body).encode()

    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "post", post)
    report = check_api("https://api.deepseek.com", "deepseek-flash", "secret")
    assert report["success"] is (expected is None)
    assert report.get("error_type") == expected
    assert "secret" not in str(report)
    assert len(calls) == 1
    assert calls[0][1]["json"]["stream"] is False
    assert calls[0][1]["timeout"] == (5, 40)
    assert calls[0][1]["allow_redirects"] is False


def test_timeout_not_retried(monkeypatch):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout("must not disclose exception data")

    monkeypatch.setattr(requests, "post", post)
    report = check_api("https://api.deepseek.com", "deepseek-flash", "secret")
    assert report["error_type"] == "timeout"
    assert len(calls) == 1
    assert "disclose" not in str(report)
