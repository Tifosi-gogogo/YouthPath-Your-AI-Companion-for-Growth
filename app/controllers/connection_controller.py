from PySide6.QtCore import QObject, QTimer, Signal

from app.models import AppError, new_id
from app.services.chat_worker import ConnectionTestWorker


class ConnectionController(QObject):
    busy_changed = Signal(bool)
    status_changed = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None, worker_factory=ConnectionTestWorker):
        super().__init__(parent)
        self.worker_factory = worker_factory
        self.worker = None
        self.active = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)

    @property
    def busy(self):
        return self.worker is not None

    def start(self, settings) -> bool:
        if self.busy:
            return False
        try:
            settings.validate()
        except AppError as error:
            self.status_changed.emit(error.message)
            return False
        self.active = new_id()
        self.worker = self.worker_factory(self.active, settings, self)
        self.worker.succeeded.connect(self._success)
        self.worker.failed.connect(self._failure)
        self.worker.finished.connect(self._finished)
        self.timer.start(settings.request_deadline_seconds * 1000)
        self.busy_changed.emit(True)
        self.status_changed.emit("正在测试连接…")
        self.worker.start()
        return True

    def _success(self, request_id, completion):
        if request_id != self.active:
            return
        self.active = None
        self.timer.stop()
        self.status_changed.emit(f"连接成功（HTTP {completion.http_status}，{completion.elapsed_ms} ms）。"
                                 "测试消息不会进入会话；请切换在线聊天验证角色回复。")

    def _failure(self, request_id, error):
        if request_id != self.active:
            return
        self.active = None
        self.timer.stop()
        self.status_changed.emit(error.message)

    def cancel(self):
        self.active = None
        self.timer.stop()
        if self.worker is not None:
            self.worker.requestInterruption()
            self.status_changed.emit("已停止等待，正在结束上一次连接测试…")

    def _timeout(self):
        self.cancel()
        self.status_changed.emit("本次连接测试等待超时，后台任务结束后可重试。")

    def _finished(self):
        if self.active is not None:
            self.status_changed.emit("连接测试未完成，请重试。")
        self.active = None
        self.timer.stop()
        self.worker.deleteLater()
        self.worker = None
        self.busy_changed.emit(False)
        self.stopped.emit()
