import json
import threading

from PySide6.QtCore import QCoreApplication, QThread, QTimer
from PySide6.QtWidgets import QLineEdit

from app.controllers.connection_controller import ConnectionController
from app.models import Message, RequestContext
from app.services.chat_worker import ChatWorker, ConnectionTestWorker
from app.services.llm_client import Completion
from app.services.settings_store import APISettings, SettingsStore
from app.ui.settings_dialog import SettingsDialog
from app.ui.main_window import MainWindow
from tests.conftest import spin_until


VALID = APISettings("https://api.deepseek.com", "deepseek-flash", "test-secret")


class ProbeClient:
    def __init__(self, settings):
        self.settings = settings

    def complete(self, messages, request_id):
        assert QThread.currentThread() != QCoreApplication.instance().thread()
        return Completion("这是一条真实 worker 的受控测试内容。", 200, 10)


def probe_factory(request_id, settings, parent):
    return ConnectionTestWorker(request_id, settings, parent, client_factory=ProbeClient)


def test_settings_hidden_key_save_and_validation(qt_app, tmp_path, monkeypatch):
    monkeypatch.delenv("QINGYU_API_KEY", raising=False)
    store = SettingsStore(tmp_path / "settings.json")
    dialog = SettingsDialog(store)
    dialog.show()
    assert dialog.key.echoMode() == QLineEdit.Password
    dialog.base.clear()
    dialog._test()
    assert not dialog.controller.busy
    assert "根地址" in dialog.hint.text()
    dialog.base.setText(VALID.api_base_url)
    dialog.model.setText(VALID.model)
    dialog.key.setText(VALID.api_key)
    dialog._save()
    assert store.current.api_key == VALID.api_key
    assert VALID.api_key not in store.path.read_text(encoding="utf-8")
    assert dialog.key.text() == ""
    assert not dialog.isVisible()


def test_add_deepseek_key_test_save_and_reopen(qt_app, tmp_path, monkeypatch):
    monkeypatch.delenv("QINGYU_API_KEY", raising=False)
    store = SettingsStore(tmp_path / "settings.json")
    controller = ConnectionController(worker_factory=probe_factory)
    dialog = SettingsDialog(store, controller=controller)
    dialog.show()
    dialog.deepseek_button.click()
    dialog.key.setText(VALID.api_key)
    dialog.show_key_button.click()
    assert dialog.key.echoMode() == QLineEdit.Normal
    dialog.show_key_button.click()
    assert dialog.key.echoMode() == QLineEdit.Password
    dialog.test_button.click()
    assert not dialog.deepseek_button.isEnabled()
    spin_until(lambda: not controller.busy)
    assert "连接成功" in dialog.hint.text()
    dialog.save_button.click()
    assert store.current.api_base_url == VALID.api_base_url
    assert store.current.model == VALID.model
    assert store.current.api_key == VALID.api_key
    assert VALID.api_key not in store.path.read_text(encoding="utf-8")
    reopened = SettingsDialog(store)
    assert reopened.key.text() == VALID.api_key
    assert reopened.key.echoMode() == QLineEdit.Password
    reopened.openai_button.click()
    assert reopened.key.text() == ""
    reopened.reject()


def test_settings_can_save_address_without_key(qt_app, tmp_path, monkeypatch):
    monkeypatch.delenv("QINGYU_API_KEY", raising=False)
    store = SettingsStore(tmp_path / "settings.json")
    dialog = SettingsDialog(store)
    dialog.base.setText(VALID.api_base_url)
    dialog.model.setText(VALID.model)
    dialog.key.clear()
    dialog._save()
    assert store.path.is_file()
    dialog._test()
    assert "API Key" in dialog.hint.text()
    assert not dialog.controller.busy


def test_connection_async_result_and_no_duplicate(qt_app):
    controller = ConnectionController(worker_factory=probe_factory)
    statuses = []
    controller.status_changed.connect(statuses.append)
    assert controller.start(VALID)
    assert not controller.start(VALID)
    spin_until(lambda: not controller.busy)
    assert any("连接成功" in status for status in statuses)


def blocking_factory(gate):
    class Client:
        def __init__(self, settings):
            pass

        def complete(self, messages, request_id):
            gate.wait(2)
            return Completion("迟到的连接测试结果", 200, 100)

    return lambda request_id, settings, parent: ConnectionTestWorker(
        request_id, settings, parent, client_factory=Client)


def test_connection_timeout_ignores_late_success(qt_app):
    gate = threading.Event()
    controller = ConnectionController(worker_factory=blocking_factory(gate))
    statuses = []
    controller.status_changed.connect(statuses.append)
    controller.start(VALID)
    QTimer.singleShot(10, controller._timeout)
    spin_until(lambda: controller.active is None)
    assert controller.busy
    assert not controller.start(VALID)
    gate.set()
    spin_until(lambda: not controller.busy)
    assert not any("连接成功" in item for item in statuses)
    assert "超时" in statuses[-1]


def test_settings_close_waits_for_running_request(qt_app, tmp_path):
    gate = threading.Event()
    controller = ConnectionController(worker_factory=blocking_factory(gate))
    dialog = SettingsDialog(SettingsStore(tmp_path / "settings.json"), controller=controller)
    dialog.show()
    controller.start(VALID)
    assert not dialog.save_button.isEnabled()
    assert not dialog.test_button.isEnabled()
    dialog.reject()
    assert dialog.closing and dialog.isVisible()
    gate.set()
    spin_until(lambda: not controller.busy and not dialog.isVisible())


def test_real_worker_snapshots_messages_and_parses_contract(qt_app):
    source = [{"role": "user", "content": "测试原始问题"}]
    received = []
    errors = []

    class Client:
        def __init__(self, settings):
            pass

        def complete(self, messages, request_id):
            assert messages[0]["content"] == "测试原始问题"
            return Completion(json.dumps({"reply": "验证返回值", "emotion_tags": ["测试"],
                "action_suggestions": ["测试操作"], "risk_level": "elevated"}), 200, 10)

    context = RequestContext("session", "message")
    worker = ChatWorker(context, VALID, source, client_factory=Client)
    source[0]["content"] = "主线程后来的修改"
    worker.succeeded.connect(lambda request, result: received.append((request, result)))
    worker.failed.connect(lambda request, error: errors.append(error))
    worker.start()
    spin_until(lambda: not worker.isRunning() and (received or errors))
    assert not errors
    assert received[0][0] == context
    assert received[0][1].emotion_tags == ["测试"]
    assert received[0][1].risk_level == "elevated"


def test_real_worker_reports_parser_error(qt_app):
    class Client:
        def __init__(self, settings):
            pass

        def complete(self, messages, request_id):
            return Completion('{"reply": null}', 200, 10)

    errors = []
    worker = ChatWorker(RequestContext("s", "m"), VALID, [], client_factory=Client)
    worker.failed.connect(lambda context, error: errors.append(error))
    worker.start()
    spin_until(lambda: not worker.isRunning() and bool(errors))
    assert errors[0].code == "invalid_result"


def test_small_window_follows_new_content_and_preserves_reading_position(qt_app):
    window = MainWindow()
    window.resize(900, 600)
    window.show()
    bar = window.scroll.verticalScrollBar()
    window._add_message(Message("assistant", "联调长回复。" * 300, status="completed"))
    spin_until(lambda: bar.maximum() > 0 and bar.value() == bar.maximum())
    bar.setValue(0)
    assert not window.follow_bottom
    previous_maximum = bar.maximum()
    window._add_message(Message("assistant", "另一条长回复。" * 300, status="completed"))
    spin_until(lambda: bar.maximum() > previous_maximum)
    QCoreApplication.processEvents()
    assert bar.value() == 0
    assert window.new_reply.isVisible()
    window.new_reply.click()
    spin_until(lambda: bar.value() == bar.maximum())
    window.close()
