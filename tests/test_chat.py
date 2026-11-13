import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from app.controllers.chat_controller import ChatController
from app.models import AIResult, RequestContext
from app.services.chat_worker import MockWorker
from app.ui.main_window import MainWindow
from tests.conftest import spin_until


@pytest.fixture
def controller(qt_app):
    instance = ChatController()
    yield instance
    instance.cancel()
    spin_until(lambda: not instance.busy)


@pytest.mark.parametrize("text", ["", "  \n\t", "长" * 2001])
def test_invalid_input_does_not_create_message(controller, text):
    assert not controller.send(text)
    assert not controller.messages
    assert not controller.busy


def test_double_send_and_multilingual_content(controller):
    text = "  中文 English 🌱\n下一行 <script>alert(1)</script>  "
    assert controller.send(text)
    assert not controller.send("第二次")
    spin_until(lambda: not controller.busy)
    assert [message.role for message in controller.messages] == ["user", "assistant"]
    assert controller.messages[0].text == text.strip()
    assert all(message.status == "completed" for message in controller.messages)
    assert "mock" in controller.messages[1].text


def test_cancel_ignores_late_result_and_retry_reuses_message(controller):
    controller.send("同一个问题")
    old_context = controller.active
    controller.cancel()
    controller._success(old_context, AIResult("迟到回复"))
    assert len(controller.messages) == 1
    assert controller.messages[0].status == "cancelled"
    assert not controller.send("旧 worker 未结束时不得开启新任务")
    spin_until(lambda: not controller.busy)
    assert controller.retry()
    spin_until(lambda: not controller.busy)
    assert len(controller.messages) == 2
    assert controller.messages[0].status == "completed"


def test_new_session_ignores_old_reply(controller):
    controller.send("旧会话")
    old_context = controller.active
    controller.new_session()
    controller._success(old_context, AIResult("旧会话回复"))
    spin_until(lambda: not controller.busy)
    assert controller.session_id != old_context.session_id
    assert not controller.messages
    assert controller.retry_message_id is None


def test_wrong_request_id_is_rejected(controller):
    controller.send("请求匹配")
    wrong = RequestContext(controller.session_id, controller.messages[0].message_id)
    controller._success(wrong, AIResult("错误请求结果"))
    assert len(controller.messages) == 1
    assert controller.active is not None


def test_deadline_restores_retry(controller):
    controller.send("超时")
    controller._timeout()
    spin_until(lambda: not controller.busy)
    assert controller.messages[0].status == "failed"
    assert controller.retry_message_id == controller.messages[0].message_id


class FailingWorker(MockWorker):
    def run(self):
        self.failed.emit(self.context, "受控失败，可重试")


def test_worker_failure_updates_original_message(qt_app):
    controller = ChatController(worker_factory=FailingWorker)
    controller.send("失败测试")
    spin_until(lambda: not controller.busy)
    assert len(controller.messages) == 1
    assert controller.messages[0].status == "failed"
    controller.worker_factory = MockWorker
    assert controller.retry()
    spin_until(lambda: not controller.busy)
    assert len(controller.messages) == 2


def test_keyboard_draft_and_plain_text(qt_app):
    window = MainWindow(controller=ChatController())
    window.show()
    window.input.setPlainText("<b>你好</b> 🌱")
    QTest.keyClick(window.input, Qt.Key_End, Qt.ControlModifier)
    QTest.keyClick(window.input, Qt.Key_Return)
    assert window.input.toPlainText().endswith("\n")
    QTest.keyClick(window.input, Qt.Key_Return, Qt.ControlModifier)
    assert window.controller.busy
    assert not window.send.isEnabled()
    assert not window.input.toPlainText()
    window.input.setPlainText("下一条草稿")
    spin_until(lambda: not window.controller.busy)
    assert window.input.toPlainText() == "下一条草稿"
    bubble = next(iter(window.bubbles.values()))
    labels = bubble.findChildren(QLabel)
    assert any(label.text().startswith("<b>你好</b>") and label.textFormat() == Qt.PlainText for label in labels)
    window.close()


def test_close_during_worker_finishes_cleanly(qt_app):
    window = MainWindow(controller=ChatController())
    window.show()
    window.controller.send("关闭测试")
    window.close()
    assert window.closing
    spin_until(lambda: not window.controller.busy and not window.isVisible())
