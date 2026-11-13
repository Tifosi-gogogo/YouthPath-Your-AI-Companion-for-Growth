from PySide6.QtCore import QTimer, Qt, Signal
from pathlib import Path
from PySide6.QtGui import QCloseEvent, QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QMainWindow, QMessageBox, QPlainTextEdit, QFileDialog,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.controllers.chat_controller import ChatController
from app.models import AppError, RequestState
from app.services.history_store import HistoryStore
from app.services.character_config import CharacterConfig, load_character
from app.services.settings_store import SettingsStore
from app.ui.character_dialog import CharacterDialog
from app.ui.history_dialog import HistoryDialog
from app.ui.message_bubble import MessageBubble
from app.ui.settings_dialog import SettingsDialog
from app.utils.paths import resource_path
from app import __version__


SCENES = [
    ("学业压力", "最近课程任务堆在一起，我不知道该从哪里开始。"),
    ("考研就业", "面对考研和找工作，我很担心自己做错选择。"),
    ("情感困惑", "一段关系让我很疲惫，我想先理清自己的感受。"),
    ("人际关系", "我和室友最近有些矛盾，不知道如何开口沟通。"),
    ("成长迷茫", "我不知道自己擅长什么，对接下来的方向很迷茫。"),
]


class Composer(QPlainTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, controller=None, history_store=None, restore=True):
        super().__init__()
        self.character: CharacterConfig = load_character()
        self.settings_store = SettingsStore()
        self.settings_dialog = None
        self.controller = controller or ChatController(self, mode="demo", history_store=history_store or HistoryStore(),
            character_version=self.character.version, restore=restore, settings_store=self.settings_store)
        if controller is not None and controller.settings_store is not None:
            self.settings_store = controller.settings_store
        else:
            self.controller.settings_store = self.settings_store
        self.is_demo = self.controller.mode == "demo"
        self.case_buttons = []
        self.bubbles = {}
        self.closing = False
        self.follow_bottom = True
        self.setWindowTitle("青语伴行 · 许青")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)
        self.setFont(QFont("Microsoft YaHei", 10))
        self.setStyleSheet(resource_path("app/ui/style.qss").read_text(encoding="utf-8"))
        self._build()
        self.controller.message_added.connect(self._add_message)
        self.controller.message_updated.connect(self._update_message)
        self.controller.busy_changed.connect(self._busy_changed)
        self.controller.state_changed.connect(self._state_changed)
        self.controller.status_changed.connect(lambda text: self.status.setText(text))
        self.controller.mode_changed.connect(self._mode_changed)
        self.controller.session_reset.connect(self._reset_messages)
        self.controller.worker_stopped.connect(self._worker_stopped)
        self.controller.safety_changed.connect(self._show_safety)
        self.controller.save_status_changed.connect(self._save_status)
        self._reset_messages()
        if self.controller.startup_warning:
            self.status.setText(self.controller.startup_warning)
        elif self.controller.messages:
            self.status.setText("已恢复本机记录 · 没有重新请求接口")
        if any(item.safety_support for item in self.controller.messages):
            from app.services.safety_service import SAFETY_TEXT
            self._show_safety(SAFETY_TEXT)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        header = QFrame()
        header.setObjectName("header")
        top = QHBoxLayout(header)
        top.setContentsMargins(24, 16, 24, 16)
        title = QLabel("青语伴行")
        title.setObjectName("appTitle")
        top.addWidget(title)
        top.addStretch()
        mode = QLabel("预设案例 · 非实时 AI 回复" if self.is_demo else
                      "在线聊天 · 发送至 AI 服务" if self.controller.mode == "online" else "开发 MOCK · 非实时 AI 回复")
        mode.setObjectName("modeLabel")
        top.addWidget(mode)
        self.mode_button = QPushButton("切换在线聊天" if self.is_demo else "切换离线案例")
        self.mode_button.clicked.connect(lambda: self.controller.switch_mode("online" if self.is_demo else "demo"))
        top.addWidget(self.mode_button)
        character_button = QPushButton("角色介绍")
        character_button.clicked.connect(self._show_character)
        top.addWidget(character_button)
        self.settings_button = QPushButton("设置 / API Key")
        self.settings_button.clicked.connect(self._show_settings)
        top.addWidget(self.settings_button)
        page.addWidget(header)

        middle = QHBoxLayout()
        middle.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        left = QVBoxLayout(sidebar)
        left.setSizeConstraint(QLayout.SetMinimumSize)
        left.setContentsMargins(24, 20, 24, 18)
        left.setSpacing(10)
        avatar = QLabel("青")
        self.avatar = avatar
        avatar.setObjectName("avatar")
        avatar.setFixedSize(64, 64)
        avatar.setAlignment(Qt.AlignCenter)
        avatar_path = self.character.image_path()
        if avatar_path:
            pixmap = QPixmap(str(avatar_path))
            if not pixmap.isNull():
                ratio = self.devicePixelRatioF()
                pixmap = pixmap.scaled(round(64 * ratio), round(64 * ratio), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pixmap.setDevicePixelRatio(ratio)
                avatar.setPixmap(pixmap)
        left.addWidget(avatar)
        name = QLabel(self.character.name)
        name.setTextFormat(Qt.PlainText)
        name.setObjectName("characterName")
        name.setWordWrap(True)
        left.addWidget(name)
        identity = QLabel(self.character.identity)
        identity.setTextFormat(Qt.PlainText)
        identity.setWordWrap(True)
        identity.setObjectName("muted")
        left.addWidget(identity)
        tagline = QLabel(self.character.tagline)
        tagline.setTextFormat(Qt.PlainText)
        tagline.setWordWrap(True)
        tagline.setObjectName("tagline")
        left.addWidget(tagline)
        left.addSpacing(8)
        scene_title = QLabel("选择一段故事" if self.is_demo else "想聊些什么")
        scene_title.setObjectName("sectionLabel")
        left.addWidget(scene_title)
        scenes = [(case.title, case.case_id) for case in self.controller.demo_service.cases] if self.is_demo else SCENES
        for label, question in scenes:
            button = QPushButton(label)
            button.setObjectName("sceneButton")
            if self.is_demo:
                button.setCheckable(True)
                button.setProperty("caseId", question)
                button.clicked.connect(lambda checked=False, case_id=question: self._select_case(case_id))
            else:
                button.clicked.connect(lambda checked=False, text=question: self._fill(text))
            self.case_buttons.append(button)
            left.addWidget(button)
        left.addStretch()
        new = QPushButton("新会话")
        new.clicked.connect(self._new_session)
        left.addWidget(new)
        self.new_session_button = new
        history = QPushButton("本机历史")
        history.clicked.connect(self._show_history)
        left.addWidget(history)
        export = QPushButton("导出记录")
        export.clicked.connect(self._export)
        left.addWidget(export)
        clear = QPushButton("清空本会话")
        clear.clicked.connect(self._clear)
        left.addWidget(clear)
        self.history_button, self.clear_button = history, clear
        version = QLabel(f"v{__version__}")
        version.setObjectName("muted")
        left.addWidget(version)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebarScroll")
        sidebar_scroll.setFixedWidth(244)
        self.sidebar_scroll = sidebar_scroll
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setWidget(sidebar)
        middle.addWidget(sidebar_scroll)

        chat = QWidget()
        right = QVBoxLayout(chat)
        right.setContentsMargins(24, 20, 24, 18)
        right.setSpacing(12)
        subtitle = QLabel("许青的陪伴时刻")
        subtitle.setObjectName("conversationTitle")
        right.addWidget(subtitle)
        self.case_title = QLabel()
        self.case_title.setObjectName("caseTitle")
        right.addWidget(self.case_title)
        self.safety = QLabel()
        self.safety.setTextFormat(Qt.PlainText)
        self.safety.setWordWrap(True)
        self.safety.setObjectName("safetyCard")
        self.safety.hide()
        safety_scroll = QScrollArea()
        safety_scroll.setWidgetResizable(True)
        safety_scroll.setMaximumHeight(170)
        safety_scroll.setWidget(self.safety)
        safety_scroll.hide()
        self.safety_scroll = safety_scroll
        right.addWidget(safety_scroll)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_container = QWidget()
        self.message_container.setObjectName("messages")
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(0, 0, 8, 0)
        self.message_layout.setSpacing(8)
        self.message_layout.addStretch()
        self.scroll.setWidget(self.message_container)
        self.scroll.verticalScrollBar().valueChanged.connect(self._scroll_changed)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._scroll_range_changed)
        right.addWidget(self.scroll, 1)
        self.new_reply = QPushButton("有新回复 ↓")
        self.new_reply.clicked.connect(self._jump_bottom)
        self.new_reply.hide()
        right.addWidget(self.new_reply)
        self.waiting = QLabel("正在回应…")
        self.waiting.setObjectName("muted")
        self.waiting.hide()
        right.addWidget(self.waiting)
        self.input = Composer()
        self.input.setPlaceholderText("选择左侧案例，点击“填入示例”，再发送。" if self.is_demo else "写下你最近想聊的事情…")
        self.input.setFixedHeight(88)
        self.input.textChanged.connect(self._draft_changed)
        self.input.send_requested.connect(self._send)
        right.addWidget(self.input)
        actions = QHBoxLayout()
        self.counter = QLabel("0 / 2000")
        self.counter.setObjectName("muted")
        actions.addWidget(self.counter)
        hint = QLabel("Enter 换行 · Ctrl + Enter 发送")
        hint.setObjectName("muted")
        actions.addWidget(hint)
        actions.addStretch()
        self.example = QPushButton("填入示例")
        self.example.clicked.connect(lambda: self._fill(self.controller.next_demo_question()))
        self.example.setVisible(self.is_demo)
        actions.addWidget(self.example)
        self.retry = QPushButton("重试")
        self.retry.hide()
        self.retry.clicked.connect(self.controller.retry)
        actions.addWidget(self.retry)
        self.stop = QPushButton("停止等待")
        self.stop.hide()
        self.stop.clicked.connect(self.controller.cancel)
        actions.addWidget(self.stop)
        self.send = QPushButton("发送")
        self.send.setObjectName("primaryButton")
        self.send.setFixedSize(96, 38)
        self.send.setToolTip("发送消息（Ctrl + Enter）")
        self.send.clicked.connect(self._send)
        actions.addWidget(self.send)
        right.addLayout(actions)
        middle.addWidget(chat, 1)
        page.addLayout(middle, 1)
        footer = QFrame()
        footer.setObjectName("footer")
        bottom = QVBoxLayout(footer)
        bottom.setContentsMargins(24, 10, 24, 10)
        bottom.setSpacing(4)
        self.status = QLabel("选择预设故事，与许青一起梳理下一步。" if self.is_demo else "在线聊天：请先在右上角设置 API。")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        bottom.addWidget(self.status)
        self.save_label = QLabel("本机保存 · 预设案例演示" if self.is_demo else "在线聊天 · 记录保存在本机")
        self.save_label.setObjectName("muted")
        bottom.addWidget(self.save_label)
        self.save_retry = QPushButton("重试保存")
        self.save_retry.clicked.connect(self.controller.save)
        self.save_retry.hide()
        bottom.addWidget(self.save_retry)
        disclaimer = QLabel("AI 成长陪伴，不替代专业心理咨询。记录保存在本机；在线发送会将当前问题和近期对话传给设置中的 AI 服务。")
        disclaimer.setTextFormat(Qt.PlainText)
        disclaimer.setObjectName("muted")
        disclaimer.setWordWrap(True)
        bottom.addWidget(disclaimer)
        page.addWidget(footer)

    def _fill(self, text):
        self.input.setPlainText(text)
        self.input.setFocus()

    def _mode_changed(self, mode):
        self.is_demo = mode == "demo"
        old = self.takeCentralWidget()
        self.case_buttons = []
        self.bubbles = {}
        self._build()
        if old:
            old.deleteLater()

    def _draft_changed(self):
        count = len(self.input.toPlainText())
        self.counter.setText(f"{count} / 2000" + (" · 已超出" if count > 2000 else ""))
        self.counter.setStyleSheet("color: #b42318;" if count > 2000 else "")

    def _send(self):
        if self.controller.send(self.input.toPlainText()):
            self.input.clear()

    def _new_session(self):
        if self.controller.busy:
            return
        if self.controller.messages:
            answer = QMessageBox.question(self, "新会话", "当前记录会保留在本机历史中。开始新的会话？")
            if answer != QMessageBox.Yes:
                return
        if self.controller.save():
            self.controller.new_session()

    def _reset_messages(self):
        self.bubbles.clear()
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        welcome = QLabel(self.character.welcome)
        welcome.setObjectName("welcome")
        welcome.setWordWrap(True)
        welcome.setTextFormat(Qt.PlainText)
        welcome.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.message_layout.insertWidget(0, welcome)
        for message in self.controller.messages:
            self._add_message(message)
        if self.is_demo:
            case = self.controller.demo_service.get(self.controller.demo_case_id)
            self.case_title.setText(f"{case.scene}  /  {case.title}")
            for button in self.case_buttons:
                button.setChecked(button.property("caseId") == case.case_id)
        else:
            self.case_title.setText("在线聊天 · 真实 API 回复" if self.controller.mode == "online" else "开发联调 · 固定回复")
        self.input.clear()
        self.follow_bottom = True
        self.new_reply.hide()
        self._busy_changed(self.controller.busy)

    def _scroll_changed(self, value):
        bar = self.scroll.verticalScrollBar()
        self.follow_bottom = bar.maximum() - value < 24
        if self.follow_bottom:
            self.new_reply.hide()

    def _scroll_range_changed(self, minimum, maximum):
        # 气泡的最终高度由 Qt 布局稍后确定，首次追加时的滚动范围可能仍为旧值。
        if self.follow_bottom:
            QTimer.singleShot(0, self._jump_bottom)

    def _add_message(self, message):
        should_follow = self.follow_bottom
        bubble = MessageBubble(message, self.character.name)
        self.bubbles[message.message_id] = bubble
        self.message_layout.insertWidget(self.message_layout.count() - 1, bubble)
        if should_follow:
            QTimer.singleShot(0, self._jump_bottom)
        else:
            self.new_reply.show()

    def _update_message(self, message):
        if message.message_id in self.bubbles:
            self.bubbles[message.message_id].update_status(message)

    def _jump_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.follow_bottom = True
        self.new_reply.hide()

    def _busy_changed(self, busy):
        self.send.setEnabled(not busy and not self.closing)
        self.stop.setVisible(busy and not self.closing)
        self.waiting.setVisible(busy)
        self.retry.setVisible(not busy and bool(self.controller.retry_message_id))
        self.settings_button.setEnabled(not busy and not self.closing)
        self.mode_button.setEnabled(not busy and not self.closing)
        self.example.setEnabled(not busy and bool(self.controller.next_demo_question()))
        for widget in [self.new_session_button, self.history_button, self.clear_button, *self.case_buttons]:
            widget.setEnabled(not busy and not self.closing)

    def _state_changed(self, state):
        self.waiting.setText(("许青的预设回应即将展开…" if self.is_demo else "正在回应…")
                             if state == RequestState.SENDING else "正在结束上一次任务…")
        self.stop.setEnabled(state == RequestState.SENDING and not self.closing)

    def _worker_stopped(self):
        if self.closing and not self.controller.busy and not self._settings_busy():
            QTimer.singleShot(0, self.close)

    def _settings_busy(self):
        return self.settings_dialog is not None and self.settings_dialog.controller.busy

    def closeEvent(self, event: QCloseEvent):
        if self.controller.busy or self._settings_busy():
            self.closing = True
            self.controller.cancel()
            if self._settings_busy():
                self.settings_dialog.reject()
            self.status.setText("正在结束后台任务，完成后关闭窗口…")
            self._busy_changed(True)
            event.ignore()
        else:
            if self.controller.history_store and not self.controller.save():
                answer = QMessageBox.question(self, "记录尚未保存",
                    "当前记录未保存。可返回后导出或重试保存，仍要关闭窗口？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    self.closing = False
                    self._busy_changed(False)
                    event.ignore()
                    return
            event.accept()

    def _show_character(self):
        dialog = CharacterDialog(self.character, self)
        dialog.exec()
        dialog.deleteLater()

    def _show_settings(self):
        if self.controller.busy or self.closing:
            return
        dialog = SettingsDialog(self.settings_store, self)
        self.settings_dialog = dialog
        dialog.controller.stopped.connect(self._worker_stopped)
        dialog.settings_saved.connect(lambda settings: self.status.setText(
            "接口设置已保存。点击“切换在线聊天”开始真实对话。" if self.is_demo else "接口设置已保存，可以发送或重试。"))
        dialog.exec()
        self.settings_dialog = None
        dialog.deleteLater()

    def _select_case(self, case_id):
        if not self.controller.save():
            return
        if self.controller.select_case(case_id):
            self._fill(self.controller.next_demo_question())

    def _show_safety(self, text):
        self.safety.setText("安全支持提示\n" + text if text else "")
        self.safety.setVisible(bool(text))
        self.safety_scroll.setVisible(bool(text))

    def _save_status(self, text):
        self.save_label.setText(text)
        self.save_retry.setVisible(bool(self.controller.save_error))
        self.save_label.setStyleSheet("color: #ad4a32;" if self.controller.save_error else "")

    def _show_history(self):
        if self.controller.busy or not self.controller.history_store:
            return
        sessions, invalid = self.controller.history_store.list_sessions()
        dialog = HistoryDialog(sessions, invalid, self)
        if dialog.exec() and dialog.selected_session:
            self.controller.restore_session(dialog.selected_session)
        dialog.deleteLater()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出当前会话", "许青_聊天记录.txt", "文本 (*.txt);;JSON (*.json)")
        if path:
            try:
                HistoryStore.export(self.controller.session, Path(path))
                self.status.setText("记录已导出，包含会话模式标识")
            except AppError as error:
                self.status.setText(error.message)

    def _clear(self):
        if self.controller.busy:
            return
        if QMessageBox.question(self, "清空当前会话", "只删除当前会话的本机记录；其他会话和已导出文件保留。继续？") == QMessageBox.Yes:
            self.controller.clear_session()

