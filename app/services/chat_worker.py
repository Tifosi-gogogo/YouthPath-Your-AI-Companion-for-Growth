import json
import logging

from PySide6.QtCore import QThread, Signal

from app.models import AppError, RequestContext
from app.services.llm_client import LLMClient
from app.services.response_parser import parse_response
from app.services.settings_store import APISettings


class MockWorker(QThread):
    """开发 UI 联调数据也通过正式解析契约，不分析用户输入。"""

    succeeded = Signal(object, object)
    failed = Signal(object, object)

    def __init__(self, context: RequestContext, parent=None):
        super().__init__(parent)
        self.context = context

    def run(self) -> None:
        for _ in range(14):
            if self.isInterruptionRequested():
                return
            self.msleep(50)
        if not self.isInterruptionRequested():
            try:
                result = parse_response(json.dumps({
                    "reply": "这是一条用于界面联调的固定 mock 回复。你的输入已完成发送、等待和气泡展示流程。"
                             "当前尚未接入真实 AI，这条内容没有分析你的问题，也不能作为个人建议。",
                    "emotion_tags": ["测试标签"],
                    "action_suggestions": ["联调操作：在输入框编辑下一条草稿。", "联调操作：打开设置页检查接口配置。"],
                    "risk_level": "normal",
                }, ensure_ascii=False))
                self.succeeded.emit(self.context, result)
            except AppError as error:
                self.failed.emit(self.context, error)


class DemoWorker(QThread):
    succeeded = Signal(object, object)
    failed = Signal(object, object)

    def __init__(self, context, result, parent=None, delay_ms=1100):
        super().__init__(parent)
        self.context = context
        self.result = result
        self.delay_ms = delay_ms

    def run(self):
        for _ in range(max(1, self.delay_ms // 50)):
            if self.isInterruptionRequested():
                return
            self.msleep(50)
        if not self.isInterruptionRequested():
            self.succeeded.emit(self.context, self.result)


class ChatWorker(QThread):
    """后台真实请求：接收独立上下文快照，不读写 UI 和控制器历史。"""

    succeeded = Signal(object, object)
    failed = Signal(object, object)

    def __init__(self, context: RequestContext, settings: APISettings, messages: list[dict],
                 parent=None, client_factory=LLMClient):
        super().__init__(parent)
        self.context = context
        self.settings = settings
        self.messages = [dict(message) for message in messages]
        self.client_factory = client_factory

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            completion = self.client_factory(self.settings).complete(self.messages, self.context.request_id)
            if self.isInterruptionRequested():
                return
            result = parse_response(completion.content)
            logging.getLogger("qingyu").info("request=%s parse=%s", self.context.request_id,
                                              ",".join(result.warnings) or "valid")
            self.succeeded.emit(self.context, result)
        except AppError as error:
            logging.getLogger("qingyu").warning("request=%s worker_error=%s", self.context.request_id, error.code)
            if not self.isInterruptionRequested():
                self.failed.emit(self.context, error)
        except Exception:
            logging.getLogger("qingyu").error("request=%s error=worker_internal", self.context.request_id)
            if not self.isInterruptionRequested():
                self.failed.emit(self.context, AppError("worker_internal", "任务未完成，请重试。"))


class ConnectionTestWorker(QThread):
    succeeded = Signal(str, object)
    failed = Signal(str, object)

    def __init__(self, request_id: str, settings: APISettings, parent=None, client_factory=LLMClient):
        super().__init__(parent)
        self.request_id = request_id
        self.settings = settings
        self.client_factory = client_factory

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            completion = self.client_factory(self.settings).complete([
                {"role": "system", "content": "Reply with a JSON object containing a short Chinese greeting in the reply field."},
                {"role": "user", "content": "请用中文说一句简短的问候。"},
            ], self.request_id)
            if not self.isInterruptionRequested():
                self.succeeded.emit(self.request_id, completion)
        except AppError as error:
            if not self.isInterruptionRequested():
                self.failed.emit(self.request_id, error)
        except Exception:
            logging.getLogger("qingyu").error("request=%s error=test_internal", self.request_id)
            if not self.isInterruptionRequested():
                self.failed.emit(self.request_id, AppError("test_internal", "连接测试未完成，请重试。"))
