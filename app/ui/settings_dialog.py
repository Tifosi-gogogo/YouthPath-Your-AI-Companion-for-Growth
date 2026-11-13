from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton, QSpinBox, QVBoxLayout

from app.controllers.connection_controller import ConnectionController
from app.models import AppError
from app.services.settings_store import APISettings, SettingsStore


class SettingsDialog(QDialog):
    settings_saved = Signal(object)

    def __init__(self, store: SettingsStore, parent=None, controller=None):
        super().__init__(parent)
        self.store = store
        self.controller = controller or ConnectionController(self)
        self.closing = False
        self.setWindowTitle("API 设置 · 添加密钥")
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        intro = QLabel("添加你的 API Key，即可使用真实 AI 对话。默认使用 DeepSeek Flash。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        providers = QHBoxLayout()
        self.deepseek_button = QPushButton("使用 DeepSeek Flash")
        self.deepseek_button.clicked.connect(self._fill_deepseek)
        self.openai_button = QPushButton("填入 OpenAI 配置")
        self.openai_button.clicked.connect(self._fill_openai)
        providers.addWidget(self.deepseek_button)
        providers.addWidget(self.openai_button)
        providers.addStretch()
        layout.addLayout(providers)
        form = QFormLayout()
        self.base = QLineEdit()
        self.base.setPlaceholderText("https://api.deepseek.com")
        self.model = QLineEdit()
        self.model.setPlaceholderText("deepseek-flash")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("在这里粘贴你的 API Key")
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        self.show_key_button = QPushButton("显示")
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._toggle_key)
        key_row.addWidget(self.show_key_button)
        self.connect_timeout = self._spin(5)
        self.read_timeout = self._spin(40)
        form.addRow("API 根地址", self.base)
        form.addRow("模型编号", self.model)
        form.addRow("API Key", key_row)
        form.addRow("连接超时（秒）", self.connect_timeout)
        form.addRow("读取超时（秒）", self.read_timeout)
        layout.addLayout(form)
        notice = QLabel("API 根地址不要包含 /chat/completions。密钥仅在本进程使用，关闭软件后需重新输入，"
                        "或通过 QINGYU_API_KEY 提供。地址和模型会保存在本机。")
        notice.setWordWrap(True)
        notice.setTextFormat(Qt.PlainText)
        layout.addWidget(notice)
        self.hint = QLabel("尚未测试连接。保存后可在主窗口切换在线聊天；在线消息将发送给此地址的服务。")
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.PlainText)
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        self.save_button.setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("关闭")
        self.test_button = buttons.addButton("测试连接（一次 API 调用）", QDialogButtonBox.ActionRole)
        self.stop_button = buttons.addButton("停止等待", QDialogButtonBox.ActionRole)
        self.stop_button.clicked.connect(self.controller.cancel)
        self.stop_button.hide()
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.test_button.clicked.connect(self._test)
        layout.addWidget(buttons)
        self.controller.busy_changed.connect(self._busy_changed)
        self.controller.status_changed.connect(self.hint.setText)
        self.controller.stopped.connect(self._stopped)
        self._load()

    @staticmethod
    def _spin(value):
        spin = QSpinBox()
        spin.setRange(1, 120)
        spin.setValue(value)
        return spin

    def _fill_openai(self):
        if self.base.text().strip().rstrip("/") != "https://api.openai.com/v1":
            self.key.clear()
            self.show_key_button.setChecked(False)
        self.base.setText("https://api.openai.com/v1")
        self.model.setText("gpt-5.4-mini")
        self.hint.setText("已填入 OpenAI 地址和模型。请填入你自己的 API Key，再测试连接。")

    def _fill_deepseek(self):
        if self.base.text().strip().rstrip("/") != "https://api.deepseek.com":
            self.key.clear()
            self.show_key_button.setChecked(False)
        self.base.setText("https://api.deepseek.com")
        self.model.setText("deepseek-flash")
        self.hint.setText("已填入 DeepSeek Flash 配置。请粘贴你的 API Key，测试连接成功后保存。")
        self.key.setFocus()

    def _toggle_key(self, visible):
        self.key.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.show_key_button.setText("隐藏" if visible else "显示")

    def _load(self):
        settings = self.store.current
        self.base.setText(settings.api_base_url)
        self.model.setText(settings.model)
        self.key.setText(settings.api_key)
        self.connect_timeout.setValue(settings.connect_timeout_seconds)
        self.read_timeout.setValue(settings.read_timeout_seconds)
        if self.store.load_warning:
            self.hint.setText(self.store.load_warning + " " + self.hint.text())

    def _settings(self):
        return APISettings(self.base.text(), self.model.text(), self.key.text(),
                           self.connect_timeout.value(), self.read_timeout.value(),
                           self.store.current.request_deadline_seconds)

    def _test(self):
        try:
            settings = self._settings()
            settings.validate()
        except AppError as error:
            self.hint.setText(error.message)
            return
        self.controller.start(settings)

    def _busy_changed(self, busy):
        self.test_button.setEnabled(not busy and not self.closing)
        self.save_button.setEnabled(not busy and not self.closing)
        self.openai_button.setEnabled(not busy and not self.closing)
        self.deepseek_button.setEnabled(not busy and not self.closing)
        self.show_key_button.setEnabled(not busy and not self.closing)
        self.stop_button.setVisible(busy and not self.closing)
        for field in (self.base, self.model, self.key, self.connect_timeout, self.read_timeout):
            field.setEnabled(not busy and not self.closing)

    def _stopped(self):
        if self.closing:
            QTimer.singleShot(0, self.reject)

    def _save(self):
        if self.controller.busy or self.closing:
            return
        try:
            settings = self._settings()
            settings.validate(require_key=False)
            self.store.save(settings)
        except AppError as error:
            self.hint.setText(error.message)
            return
        self.settings_saved.emit(settings)
        self.key.clear()
        self.accept()

    def reject(self):
        if self.controller.busy:
            self.closing = True
            self.controller.cancel()
            self.hint.setText("正在结束后台连接测试，完成后关闭设置…")
            self._busy_changed(True)
            return
        self.key.clear()
        super().reject()

    def closeEvent(self, event):
        if self.controller.busy:
            self.reject()
            event.ignore()
        else:
            self.key.clear()
            event.accept()
