from dataclasses import replace

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLineEdit, QLabel, QPushButton, QVBoxLayout

from app.controllers.connection_controller import ConnectionController
from app.models import AppError
from app.services.settings_store import SettingsStore


class SettingsDialog(QDialog):
    settings_saved = Signal(object)

    def __init__(self, store: SettingsStore, parent=None, controller=None):
        super().__init__(parent)
        self.store = store
        self.controller = controller or ConnectionController(self)
        self.closing = False
        self.setWindowTitle("API 接入设置")
        self.setObjectName("apiSettings")
        self.setMinimumWidth(600)
        self.setStyleSheet("""
            QDialog#apiSettings { background: #f7f9f8; }
            QDialog#apiSettings QLabel, QDialog#apiSettings QLineEdit,
            QDialog#apiSettings QPushButton {
                color: #185c49; font-size: 15px; font-weight: 700;
            }
            QFrame#apiForm { background: #ffffff; border: 1px solid #dfe7e3; border-radius: 12px; }
            QDialog#apiSettings QLineEdit {
                background: #f7faf8; border: 1px solid #cddbd3; border-radius: 7px;
                padding: 10px 12px; selection-background-color: #b8dfcb;
            }
            QDialog#apiSettings QLineEdit:focus { border: 1px solid #23795c; background: #ffffff; }
            QDialog#apiSettings QPushButton {
                background: #ffffff; border: 1px solid #ccd8d1; border-radius: 7px; padding: 9px 16px;
            }
            QDialog#apiSettings QPushButton:hover { background: #e5eee9; border-color: #90b7a3; }
            QDialog#apiSettings QPushButton:pressed { background: #d8e7de; }
            QDialog#apiSettings QPushButton:disabled { color: #8b9892; background: #edf0ee; }
            QDialog#apiSettings QPushButton#apiSave { background: #deece0; border-color: #90b7a3; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        card = QFrame()
        card.setObjectName("apiForm")
        form = QFormLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.base = QLineEdit()
        self.base.setPlaceholderText("请输入 API 根地址")
        self.model = QLineEdit()
        self.model.setPlaceholderText("请输入模型编号")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("请输入你自己的 API Key")
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        self.show_key_button = QPushButton("显示")
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._toggle_key)
        key_row.addWidget(self.show_key_button)
        form.addRow("API 根地址", self.base)
        form.addRow("模型编号", self.model)
        form.addRow("API Key", key_row)
        layout.addWidget(card)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.PlainText)
        self.hint.hide()
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        self.save_button.setText("保存")
        self.save_button.setObjectName("apiSave")
        buttons.button(QDialogButtonBox.Cancel).setText("关闭")
        self.test_button = buttons.addButton("测试连接", QDialogButtonBox.ActionRole)
        self.stop_button = buttons.addButton("停止等待", QDialogButtonBox.ActionRole)
        self.stop_button.clicked.connect(self.controller.cancel)
        self.stop_button.hide()
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.test_button.clicked.connect(self._test)
        layout.addWidget(buttons)
        self.controller.busy_changed.connect(self._busy_changed)
        self.controller.status_changed.connect(self._show_status)
        self.controller.stopped.connect(self._stopped)
        self._load()

    def _show_status(self, text):
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def _toggle_key(self, visible):
        self.key.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.show_key_button.setText("隐藏" if visible else "显示")

    def _load(self):
        settings = self.store.current
        self.base.setText(settings.api_base_url)
        self.model.setText(settings.model)
        self.key.setText(settings.api_key)
        if self.store.load_warning:
            self._show_status(self.store.load_warning)

    def _settings(self):
        return replace(self.store.current, api_base_url=self.base.text(),
                       model=self.model.text(), api_key=self.key.text())

    def _test(self):
        try:
            settings = self._settings()
            settings.validate()
        except AppError as error:
            self._show_status(error.message)
            return
        self.controller.start(settings)

    def _busy_changed(self, busy):
        self.test_button.setEnabled(not busy and not self.closing)
        self.save_button.setEnabled(not busy and not self.closing)
        self.show_key_button.setEnabled(not busy and not self.closing)
        self.stop_button.setVisible(busy and not self.closing)
        for field in (self.base, self.model, self.key):
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
            self._show_status(error.message)
            return
        self.settings_saved.emit(settings)
        self.key.clear()
        self.accept()

    def reject(self):
        if self.controller.busy:
            self.closing = True
            self.controller.cancel()
            self._show_status("正在结束连接测试…")
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
