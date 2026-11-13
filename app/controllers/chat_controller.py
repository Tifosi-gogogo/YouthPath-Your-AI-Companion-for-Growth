import logging

from PySide6.QtCore import QObject, QTimer, Signal

from app.models import AIResult, AppError, Message, RequestContext, RequestState, Session, new_id
from app.services.chat_worker import ChatWorker, DemoWorker, MockWorker
from app.services.character_config import load_character
from app.services.prompt_builder import build_messages
from app.services.demo_service import DemoService
from app.services.safety_service import SAFETY_TEXT, blocks_harmful_instructions, has_immediate_risk


class ChatController(QObject):
    message_added = Signal(object)
    message_updated = Signal(object)
    busy_changed = Signal(bool)
    status_changed = Signal(str)
    session_reset = Signal()
    worker_stopped = Signal()
    state_changed = Signal(object)
    safety_changed = Signal(str)
    save_status_changed = Signal(str)
    mode_changed = Signal(str)

    def __init__(self, parent=None, worker_factory=MockWorker, mode="mock", history_store=None,
                 character_version="", restore=True, settings_store=None, online_worker_factory=ChatWorker):
        super().__init__(parent)
        self.session_id = new_id()
        self.messages: list[Message] = []
        self.active: RequestContext | None = None
        self.worker = None
        self.worker_factory = worker_factory
        self.settings_store = settings_store
        self.online_worker_factory = online_worker_factory
        self.character = load_character()
        self.state = RequestState.IDLE
        self.retry_message_id: str | None = None
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.mode = mode
        self.history_store = history_store
        self.character_version = character_version
        self.demo_service = DemoService() if mode == "demo" else None
        self.demo_case_id = "study-tasks" if mode == "demo" else None
        self.session = Session(session_id=self.session_id, mode=mode, character_version=character_version,
                               demo_case_id=self.demo_case_id, messages=self.messages)
        self.startup_warning = ""
        self.save_error = ""
        if history_store and restore:
            try:
                previous = history_store.latest()
                if previous and (previous.mode == mode or
                                 previous.mode in ("online", "demo") and mode in ("online", "demo")):
                    self._adopt(previous)
            except AppError as error:
                self.startup_warning = error.message

    @property
    def busy(self) -> bool:
        return self.worker is not None

    def _set_state(self, state: RequestState) -> None:
        self.state = state
        self.state_changed.emit(state)

    def send(self, text: str) -> bool:
        text = text.strip()
        if self.busy:
            self.status_changed.emit("正在回应，请等待当前任务结束。" if self.active else "正在结束上一次任务，请稍候。")
            return False
        if not text:
            self.status_changed.emit("先写下你想聊的事情。")
            return False
        if len(text) > 2000:
            self.status_changed.emit("单条消息最多 2000 个字符，请缩短后再发送。")
            return False
        risk = has_immediate_risk(text)
        if risk:
            self.safety_changed.emit(SAFETY_TEXT)
        if self.mode == "online" and not self._online_ready():
            return False
        if self.mode == "demo":
            try:
                self.demo_service.result_for(self.demo_case_id, self.completed_turns, text)
            except AppError as error:
                self.status_changed.emit(error.message)
                return False
        message = Message(role="user", text=text, source=self.mode, demo_case_id=self.demo_case_id,
                          safety_support=risk)
        self.messages.append(message)
        self.message_added.emit(message)
        self.retry_message_id = None
        self._start(message)
        return True

    def _start(self, message: Message) -> None:
        message.status = "pending"
        self.message_updated.emit(message)
        self.active = RequestContext(self.session_id, message.message_id)
        if self.mode == "online":
            try:
                settings = self.settings_store.current
                settings.validate()
                messages = build_messages(self.character, self.messages, message)
                self.worker = self.online_worker_factory(self.active, settings, messages, self)
            except AppError as error:
                self._failure(self.active, error)
                self._set_state(RequestState.IDLE)
                self.busy_changed.emit(False)
                return
        elif self.mode == "demo":
            try:
                result = self.demo_service.result_for(self.demo_case_id, self.completed_turns, message.text)
            except AppError as error:
                self._failure(self.active, error)
                self._set_state(RequestState.IDLE)
                self.busy_changed.emit(False)
                return
            self.worker = DemoWorker(self.active, result, self)
        else:
            self.worker = self.worker_factory(self.active, self)
        self.worker.succeeded.connect(self._success)
        self.worker.failed.connect(self._failure)
        self.worker.finished.connect(self._finished)
        self.deadline.start(settings.request_deadline_seconds * 1000 if self.mode == "online" else 50_000)
        self._set_state(RequestState.SENDING)
        self.busy_changed.emit(True)
        self.status_changed.emit("正在展示许青的预设回应…" if self.mode == "demo" else
                                 "正在请求 AI 服务…" if self.mode == "online" else "正在回应…（开发 mock，无 API 调用）")
        self.save()
        self.worker.start()

    def _current_message(self, context: RequestContext) -> Message | None:
        if context != self.active or context.session_id != self.session_id:
            return None
        return next((m for m in self.messages if m.message_id == context.user_message_id), None)

    def _success(self, context: RequestContext, result: AIResult) -> None:
        message = self._current_message(context)
        if message is None:
            return
        support = message.safety_support or result.risk_level in ("elevated", "urgent")
        if support:
            self.safety_changed.emit(SAFETY_TEXT)
        if blocks_harmful_instructions(result.reply + "\n" + "\n".join(result.action_suggestions)):
            result = AIResult("我们先关注你此刻的安全。请联系身边可信任的人或当地紧急服务，避免独处。",
                              risk_level="urgent", warnings=("safety_fallback",))
            support = True
            self.safety_changed.emit(SAFETY_TEXT)
        message.status = "completed"
        self.message_updated.emit(message)
        reply = Message(role="assistant", text=result.reply, status="completed", result=result,
                        source=self.mode, demo_case_id=self.demo_case_id, safety_support=support)
        self.messages.append(reply)
        self.message_added.emit(reply)
        self.active = None
        self.retry_message_id = None
        self.deadline.stop()
        self._set_state(RequestState.FINISHING)
        self.status_changed.emit("许青的预设回应已展示" if self.mode == "demo" else
                                 "已收到 AI 服务回复" if self.mode == "online" else "开发 mock 回复已展示")
        self.save()
        logging.getLogger("qingyu").info("request=%s mode=%s status=success", context.request_id, self.mode)

    def _failure(self, context: RequestContext, error: str | AppError) -> None:
        message = self._current_message(context)
        if message is None:
            return
        message.status = "failed"
        self.message_updated.emit(message)
        self.retry_message_id = message.message_id
        self.active = None
        self.deadline.stop()
        self._set_state(RequestState.FINISHING)
        self.status_changed.emit(error.message if isinstance(error, AppError) else str(error))
        self.save()
        logging.getLogger("qingyu").warning("request=%s error=worker_failure", context.request_id)

    def _finished(self) -> None:
        if self.active is not None:
            self._failure(self.active, AppError("worker_incomplete", "任务未完成，请重试。"))
        self.deadline.stop()
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_state(RequestState.IDLE)
        self.busy_changed.emit(False)
        self.worker_stopped.emit()

    def retry(self) -> bool:
        if self.busy or not self.retry_message_id:
            return False
        message = next((m for m in self.messages if m.message_id == self.retry_message_id), None)
        if message is None:
            return False
        if self.mode == "online" and not self._online_ready():
            return False
        self.retry_message_id = None
        self._start(message)
        return True

    def cancel(self) -> None:
        if self.active is not None:
            message = self._current_message(self.active)
            if message is not None:
                message.status = "cancelled"
                self.retry_message_id = message.message_id
                self.message_updated.emit(message)
        self.active = None
        self.deadline.stop()
        self.save()
        if self.worker is not None:
            self._set_state(RequestState.STOPPING)
            self.worker.requestInterruption()
            self.status_changed.emit("已停止等待，正在结束上一次任务…")

    def _timeout(self) -> None:
        if self.active is not None:
            self._failure(self.active, "本次等待超时，可以稍后重试。")
        if self.worker is not None:
            self._set_state(RequestState.STOPPING)
            self.worker.requestInterruption()

    def new_session(self, case_id=None) -> bool:
        self.cancel()
        if not self.save():
            return False
        if case_id is not None:
            self.demo_case_id = case_id
        self.session_id = new_id()
        self.messages = []
        self.session = Session(session_id=self.session_id, character_version=self.character_version,
                               mode=self.mode, demo_case_id=self.demo_case_id, messages=self.messages)
        self.retry_message_id = None
        self.session_reset.emit()
        self.safety_changed.emit("")
        self.status_changed.emit("已创建新演示会话" if self.mode == "demo" else "已创建新会话")
        self.save()
        return True

    @property
    def completed_turns(self):
        return sum(item.role == "assistant" and item.status == "completed" for item in self.messages)

    def next_demo_question(self):
        if self.mode != "demo":
            return ""
        turn = self.demo_service.next_turn(self.demo_case_id, self.completed_turns)
        return turn.question if turn else ""

    def select_case(self, case_id):
        if self.busy or self.mode != "demo":
            return False
        self.demo_service.get(case_id)
        return self.new_session(case_id)

    def save(self):
        if not self.history_store:
            return True
        try:
            self.history_store.save(self.session)
            self.save_error = ""
            self.save_status_changed.emit("已保存到本机")
            return True
        except AppError as error:
            self.save_error = error.message
            self.save_status_changed.emit(error.message)
            return False

    def _adopt(self, session):
        if session.mode != self.mode:
            if session.mode not in ("demo", "online") or self.mode not in ("demo", "online"):
                raise AppError("history_mode", "无法在正式聊天中打开开发测试记录。")
        demo = DemoService() if session.mode == "demo" else None
        if demo:
            demo.get(session.demo_case_id)
        changed = self.mode != session.mode
        self.mode = session.mode
        self.demo_service = demo
        self.session = session
        self.session_id = session.session_id
        self.messages = session.messages
        self.demo_case_id = session.demo_case_id
        last = self.messages[-1] if self.messages else None
        self.retry_message_id = last.message_id if last and last.role == "user" and last.status in ("failed", "cancelled") else None
        if changed:
            self.mode_changed.emit(self.mode)

    def _online_ready(self):
        try:
            if self.settings_store is None:
                raise AppError("configuration", "请打开设置，填写 API 根地址、模型编号和 API Key。")
            self.settings_store.current.validate()
            return True
        except AppError as error:
            self.status_changed.emit(error.message + " 请打开右上角“设置”。")
            return False

    def switch_mode(self, mode):
        if self.busy or mode not in ("demo", "online"):
            return False
        if mode == self.mode:
            return True
        if not self.save():
            return False
        session = Session(mode=mode, character_version=self.character_version,
                          demo_case_id="study-tasks" if mode == "demo" else None)
        self._adopt(session)
        self.session_reset.emit()
        self.safety_changed.emit("")
        self.status_changed.emit("在线聊天：发送后会将当前问题及近期对话传给配置的 AI 服务。" if mode == "online" else "离线案例：预设回复，不调用 API。")
        self.save()
        return True

    def restore_session(self, session):
        if self.busy:
            return False
        if not self.save():
            return False
        try:
            self._adopt(session)
        except AppError as error:
            self.status_changed.emit(error.message)
            return False
        self.session_reset.emit()
        self.safety_changed.emit(SAFETY_TEXT if any(item.safety_support for item in self.messages) else "")
        self.status_changed.emit("已恢复本机会话；没有重新发出请求")
        self.save()
        return True

    def clear_session(self):
        if self.busy:
            return False
        if self.history_store:
            try:
                self.history_store.delete(self.session)
            except AppError as error:
                self.status_changed.emit(error.message)
                return False
        self.messages = []
        self.session_id = new_id()
        self.session = Session(session_id=self.session_id, mode=self.mode, character_version=self.character_version,
                               demo_case_id=self.demo_case_id, messages=self.messages)
        self.retry_message_id = None
        self.save_error = ""
        self.save_status_changed.emit("已清空当前会话")
        self.session_reset.emit()
        self.safety_changed.emit("")
        self.status_changed.emit("已清空当前会话；其他历史和导出文件保留")
        return True
