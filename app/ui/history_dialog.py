from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


class HistoryDialog(QDialog):
    def __init__(self, sessions, invalid_count=0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本机历史")
        self.resize(640, 440)
        self.selected_session = None
        root = QVBoxLayout(self)
        note = QLabel("聊天记录保存在本机。打开历史不会重新发出请求。")
        note.setWordWrap(True)
        root.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索聊天内容")
        self.search.setClearButtonEnabled(True)
        root.addWidget(self.search)
        self.items = QListWidget()
        for session in sessions:
            title = next((item.text for item in session.messages if item.role == "user"), "新会话")
            mode = {"demo": "预设演示", "online": "在线", "mock": "开发 MOCK"}[session.mode]
            item = QListWidgetItem(f"{session.updated_at[:16].replace('T', ' ')}  ·  {mode}\n{title[:65]}")
            item.setData(Qt.UserRole, session)
            self.items.addItem(item)
        root.addWidget(self.items)
        self.empty = QLabel("没有匹配的聊天记录。")
        root.addWidget(self.empty)
        if invalid_count:
            root.addWidget(QLabel(f"有 {invalid_count} 份记录无法读取，原文件已保留。"))
        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        self.open_button = buttons.button(QDialogButtonBox.Open)
        self.open_button.setText("打开")
        buttons.button(QDialogButtonBox.Cancel).setText("关闭")
        buttons.accepted.connect(self._open)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.items.itemDoubleClicked.connect(self._open)
        self.items.currentItemChanged.connect(self._selection_changed)
        self.search.textChanged.connect(self._filter)
        self._filter("")

    def _selection_changed(self, *args):
        item = self.items.currentItem()
        self.open_button.setEnabled(item is not None and not item.isHidden())

    def _filter(self, text):
        query = text.strip().casefold()
        first = None
        for index in range(self.items.count()):
            item = self.items.item(index)
            session = item.data(Qt.UserRole)
            contents = "\n".join(message.text for message in session.messages)
            matches = not query or query in contents.casefold() or query in item.text().casefold()
            item.setHidden(not matches)
            if matches and first is None:
                first = item
        current = self.items.currentItem()
        if current is None or current.isHidden():
            self.items.setCurrentItem(first)
        self.empty.setText("还没有可打开的记录。" if not self.items.count() else "没有匹配的聊天记录。")
        self.empty.setVisible(first is None)
        self._selection_changed()

    def _open(self, *args):
        item = self.items.currentItem()
        if item and not item.isHidden():
            self.selected_session = item.data(Qt.UserRole)
            self.accept()
