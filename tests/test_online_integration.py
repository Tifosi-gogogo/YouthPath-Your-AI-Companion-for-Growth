import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QCoreApplication, QThread

from app.controllers.chat_controller import ChatController
from app.models import AppError
from app.services.chat_worker import ChatWorker
from app.services.history_store import HistoryStore
from app.services.llm_client import Completion, LLMClient, MAX_RESPONSE_BYTES
from app.services.settings_store import APISettings, SettingsStore
from app.ui.main_window import MainWindow
from tests.conftest import spin_until


VALID = APISettings("https://api.openai.com/v1", "gpt-5.4-mini", "test-secret")


def online(tmp_path, client):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(VALID)
    factory = lambda ctx, cfg, msgs, parent: ChatWorker(ctx, cfg, msgs, parent, client_factory=client)
    return ChatController(mode="online", settings_store=settings, history_store=HistoryStore(tmp_path),
                          online_worker_factory=factory, restore=False)


def answer(text="我会陪你一起梳理这个问题。", risk="normal"):
    return Completion(json.dumps({"reply": text, "emotion_tags": ["担心"],
        "action_suggestions": ["今天列出一件可以着手的小事。"], "risk_level": risk}), 200, 1)


def test_online_three_turns_worker_context_and_restore(qt_app, tmp_path):
    calls = []

    class Client:
        def __init__(self, settings):
            assert settings == VALID

        def complete(self, messages, request_id):
            assert QThread.currentThread() != QCoreApplication.instance().thread()
            calls.append(messages)
            return answer()

    controller = online(tmp_path, Client)
    for text in ("我最近总是拖延论文", "最难的是开始动笔", "能把刚才的建议细化一下吗"):
        assert controller.send(text)
        assert not controller.send(text)
        spin_until(lambda: not controller.busy)
    assert [len(call) for call in calls] == [2, 4, 6]
    assert calls[2][-1]["content"] == "能把刚才的建议细化一下吗"
    assert calls[2][1]["content"] == "我最近总是拖延论文"
    assert len(controller.messages) == 6
    restored = ChatController(mode="demo", history_store=controller.history_store,
                              settings_store=controller.settings_store)
    assert restored.mode == "online" and len(restored.messages) == 6
    assert not restored.busy and len(calls) == 3


def test_online_missing_key_preserves_draft_and_local_safety(qt_app, tmp_path):
    class Never:
        def __init__(self, *args):
            raise AssertionError("No network without a key")

    controller = online(tmp_path, Never)
    controller.settings_store.save(APISettings(VALID.api_base_url, VALID.model))
    window = MainWindow(controller=controller)
    cards = []
    controller.safety_changed.connect(cards.append)
    window.input.setPlainText("我现在想自杀")
    window._send()
    assert window.input.toPlainText() == "我现在想自杀"
    assert cards and not controller.messages and not controller.busy
    assert "API Key" in window.status.text()
    window.close()


def test_online_retry_uses_new_settings_without_duplicate_user(qt_app, tmp_path):
    calls = []

    class Client:
        def __init__(self, settings):
            self.settings = settings

        def complete(self, messages, request_id):
            calls.append((self.settings, messages, request_id))
            if len(calls) == 1:
                raise AppError("authentication", "API Key 无效")
            return answer()

    controller = online(tmp_path, Client)
    assert controller.send("担心实习面试")
    spin_until(lambda: not controller.busy)
    message_id = controller.retry_message_id
    controller.settings_store.save(APISettings(VALID.api_base_url, VALID.model, "corrected-key"))
    assert controller.retry()
    spin_until(lambda: not controller.busy)
    assert len(controller.messages) == 2 and controller.messages[0].message_id == message_id
    assert calls[1][0].api_key == "corrected-key" and calls[0][2] != calls[1][2]
    assert all(message.status == "completed" for message in controller.messages)


def test_online_cancel_rejects_late_result_and_mode_switch(qt_app, tmp_path):
    gate = threading.Event()

    class Client:
        def __init__(self, settings):
            pass

        def complete(self, messages, request_id):
            gate.wait(2)
            return answer("迟到的结果")

    controller = online(tmp_path, Client)
    assert controller.send("我对未来很迷茫")
    controller.cancel()
    assert not controller.switch_mode("demo")
    gate.set()
    spin_until(lambda: not controller.busy)
    assert len(controller.messages) == 1 and controller.messages[0].status == "cancelled"
    assert controller.switch_mode("demo")
    assert not controller.messages and controller.session.mode == "demo"


def test_mode_ui_switch_and_history_never_mix_demo_context(qt_app, tmp_path):
    calls = []

    class Client:
        def __init__(self, settings):
            pass

        def complete(self, messages, request_id):
            calls.append(messages)
            return answer(risk="elevated")

    controller = online(tmp_path, Client)
    window = MainWindow(controller=controller)
    assert controller.switch_mode("demo")
    assert window.is_demo and window.example.isHidden() is False
    assert controller.send(controller.next_demo_question())
    spin_until(lambda: not controller.busy)
    demo = controller.session
    window.mode_button.click()
    assert not window.is_demo and window.example.isHidden()
    assert controller.send("自定义的新问题")
    spin_until(lambda: not controller.busy)
    assert len(calls[0]) == 2 and calls[0][-1]["content"] == "自定义的新问题"
    assert window.safety.text() and "AI 服务回复" in window.status.text()
    online_session = controller.session
    assert controller.restore_session(demo) and window.is_demo
    assert controller.restore_session(online_session) and not window.is_demo
    assert len(calls) == 1
    window.close()


def test_online_close_waits_for_actual_worker_exit(qt_app, tmp_path):
    gate = threading.Event()

    class Client:
        def __init__(self, settings):
            pass

        def complete(self, messages, request_id):
            gate.wait(2)
            return answer()

    controller = online(tmp_path, Client)
    window = MainWindow(controller=controller)
    window.show()
    assert controller.send("测试关闭时请求尚未完成")
    window.close()
    assert window.closing and window.isVisible() and controller.busy
    gate.set()
    spin_until(lambda: not controller.busy and not window.isVisible())
    assert len(controller.messages) == 1 and controller.messages[0].status == "cancelled"


@pytest.mark.parametrize("body,code", [
    (b"x" * (MAX_RESPONSE_BYTES + 1), "response_too_large"),
    (b"[" * 1500 + b"]" * 1500, "invalid_envelope"),
    (b'{"choices": []}', "invalid_envelope"),
], ids=["oversized", "nested", "empty_choices"])
def test_http_response_limits_and_redaction(body, code, caplog):
    closed = []
    calls = []

    class Response:
        status_code = 200

        def iter_content(self, chunk_size):
            for offset in range(0, len(body), chunk_size):
                yield body[offset:offset + chunk_size]

        def close(self):
            closed.append(True)

    def post(url, **kwargs):
        calls.append(kwargs)
        return Response()

    with pytest.raises(AppError) as exc:
        LLMClient(VALID, post).complete([{"role": "user", "content": "private-text"}], "req")
    assert exc.value.code == code and closed and len(calls) == 1
    assert "test-secret" not in caplog.text and "private-text" not in caplog.text
    assert calls[0]["json"]["store"] is False
    assert calls[0]["json"]["response_format"] == {"type": "json_object"}


def test_deeply_nested_settings_and_latest_pointer_preserved(tmp_path):
    raw = "[" * 1500 + "]" * 1500
    settings = tmp_path / "settings.json"
    settings.write_text(raw)
    store = SettingsStore(settings)
    assert store.load_warning and settings.read_text() == raw
    history = HistoryStore(tmp_path)
    history.pointer.write_text(raw)
    with pytest.raises(AppError):
        history.latest()
    assert history.pointer.read_text() == raw


def test_main_chat_full_http_roundtrip_with_local_service(qt_app, tmp_path):
    """完整请求链路走本机受控 HTTP 服务；不代表外部供应商实测。"""
    import requests

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers.get("Authorization"), payload))
            body = json.dumps({"choices": [{"message": {"content": answer().content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class LocalClient(LLMClient):
        def __init__(self, settings):
            def post(url, **kwargs):
                assert url == "https://api.openai.com/v1/chat/completions"
                return requests.post(f"http://127.0.0.1:{server.server_port}/v1/chat/completions", **kwargs)
            super().__init__(settings, post)

    try:
        controller = online(tmp_path, LocalClient)
        for prompt in ("论文和社团冲突，如何安排？", "我只有周末有空", "给我一个周末计划"):
            assert controller.send(prompt)
            spin_until(lambda: not controller.busy)
        assert [len(row[2]["messages"]) for row in received] == [2, 4, 6]
        assert all(row[1] == "Bearer test-secret" for row in received)
        assert all(row[2]["store"] is False for row in received)
        assert len(controller.messages) == 6
        assert all(message.status == "completed" for message in controller.messages)
        assert len(controller.history_store.load(controller.session_id).messages) == 6
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
