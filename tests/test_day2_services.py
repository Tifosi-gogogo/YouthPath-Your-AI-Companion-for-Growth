import json

import pytest
import requests

from app.models import AppError
from app.services.character_config import load_character
from app.services.llm_client import LLMClient
from app.services.response_parser import parse_response
from app.services.settings_store import APISettings, SettingsStore, build_endpoint


def test_parser_contract_and_plain_text_fallback():
    result = parse_response(json.dumps({
        "reply": "  可以先把问题写下来。 ",
        "emotion_tags": ["焦虑", "焦虑", "太长" * 5, 1, ""],
        "action_suggestions": ["今天先做一件小事。", "今天先做一件小事。", "x" * 121, None],
        "risk_level": "unexpected",
        "internal": "never displayed",
    }, ensure_ascii=False))
    assert result.reply == "可以先把问题写下来。"
    assert result.emotion_tags == ["焦虑"]
    assert result.action_suggestions == ["今天先做一件小事。"]
    assert result.risk_level == "unknown"
    assert "risk_unknown" in result.warnings
    plain = parse_response("这是一段服务商返回的普通文本。")
    assert plain.reply.startswith("这是一段")
    assert "plain_text_fallback" in plain.warnings


@pytest.mark.parametrize("content", ["", "{}", "[]", "```json\n{\"reply\": \"\"}\n```", "{" + "x" * 3100 + "}"])
def test_parser_rejects_unusable_content(content):
    with pytest.raises(AppError):
        parse_response(content)


def test_settings_store_is_atomic_and_never_writes_key(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = APISettings("https://api.deepseek.com", "deepseek-flash", "secret-key")
    store.save(settings)
    saved = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "secret-key" not in saved
    assert json.loads(saved)["model"] == "deepseek-flash"
    assert store.current.api_key == "secret-key"
    assert build_endpoint("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"


def test_settings_store_damaged_file_is_preserved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{bad", encoding="utf-8")
    store = SettingsStore(path)
    assert store.load_warning
    assert path.read_text(encoding="utf-8") == "{bad"


def test_character_config_falls_back_and_preserves_good_fields(tmp_path):
    missing = load_character(tmp_path / "missing.json")
    assert "character_config_unavailable" in missing.warnings
    path = tmp_path / "character.json"
    path.write_text(json.dumps({"name": "替换角色", "traits": "wrong", "avatar": "../outside.png"}), encoding="utf-8")
    partial = load_character(path)
    assert partial.name == "替换角色"
    assert partial.traits == ("温和", "尊重", "务实")
    assert partial.image_path() is None


@pytest.mark.parametrize("reply", ["x" * 3001, "{\"reply\":\"" + "x" * 3001 + "\"}"])
def test_long_reply_is_not_silently_truncated(reply):
    with pytest.raises(AppError) as error:
        parse_response(reply)
    assert error.value.code == "reply_too_long"


def test_parser_code_fence_auxiliary_fields_and_limit():
    content = json.dumps({"reply": "有效正文", "emotion_tags": ["一", "二", "三", "四"],
        "action_suggestions": {"wrong": "type"}, "risk_level": "urgent"})
    result = parse_response("```json\n" + content + "\n```")
    assert result.emotion_tags == ["一", "二", "三"]
    assert result.action_suggestions == []
    assert result.risk_level == "urgent"
    assert "action_suggestions_invalid" in result.warnings


@pytest.mark.parametrize("base", ["http://localhost", "https://user:pass@host", "https://example.com:bad", "https://example.com/v1/chat/completions/"])
def test_settings_reject_unsafe_or_full_request_urls(base):
    with pytest.raises(AppError):
        APISettings(base, "model", "key").validate()


def test_settings_failed_save_preserves_memory_and_old_file(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json")
    settings = APISettings("https://api.deepseek.com", "deepseek-flash", "secret-key")
    store.save(settings)
    old_file = store.path.read_bytes()

    def fail_replace(*args):
        raise OSError("raw path details")

    monkeypatch.setattr("app.services.settings_store.os.replace", fail_replace)
    with pytest.raises(AppError) as error:
        store.save(APISettings("https://example.com", "new-model", "new-secret"))
    assert error.value.code == "settings_save"
    assert store.path.read_bytes() == old_file
    assert store.current == settings
    assert list(tmp_path.glob("*.tmp")) == []


class FakeResponse:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"reply": "你好", "risk_level": "normal"})}}]}

    def iter_content(self, chunk_size):
        yield json.dumps(self.json()).encode()

    def close(self):
        pass


def test_llm_client_is_non_streaming_and_maps_network_errors():
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    settings = APISettings("https://api.deepseek.com", "deepseek-flash", "secret")
    completion = LLMClient(settings, post=post).complete([{"role": "user", "content": "hi"}], "req")
    assert completion.content.startswith("{")
    assert calls[0][1]["json"]["stream"] is False
    assert calls[0][1]["allow_redirects"] is False

    def timeout(*args, **kwargs):
        raise requests.Timeout()

    with pytest.raises(AppError) as error:
        LLMClient(settings, post=timeout).complete([], "req")
    assert error.value.code == "timeout"


@pytest.mark.parametrize("status,code", [(401, "authentication"), (402, "insufficient_balance"),
    (403, "permission"), (404, "endpoint_or_model"), (429, "rate_or_quota"), (503, "service_unavailable")])
def test_http_errors_use_controlled_messages_and_no_retries(status, code):
    calls = []

    class Response:
        status_code = status

        def json(self):
            raise AssertionError("error response must not be parsed")

    def post(*args, **kwargs):
        calls.append(1)
        return Response()

    with pytest.raises(AppError) as error:
        LLMClient(APISettings("https://example.com", "model", "secret"), post).complete([], "req")
    assert error.value.code == code
    assert error.value.http_status == status
    assert "secret" not in str(error.value)
    assert len(calls) == 1


def test_key_does_not_survive_store_reload_without_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("QINGYU_API_KEY", raising=False)
    store = SettingsStore(tmp_path / "settings.json")
    store.save(APISettings("https://example.com", "model", "process-secret"))
    reloaded = SettingsStore(store.path)
    assert reloaded.current.api_base_url == "https://example.com"
    assert reloaded.current.api_key == ""
