from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.models import Message


class MessageBubble(QFrame):
    def __init__(self, message: Message, character_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("messageRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        card = QFrame()
        card.setObjectName("userBubble" if message.role == "user" else "aiBubble")
        card.setMaximumWidth(820)
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 12, 18, 12)
        suffix = {"demo": "预设回应", "online": "AI", "mock": "MOCK"}.get(message.source, "AI")
        title = QLabel("你" if message.role == "user" else f"{character_name} · {suffix}")
        title.setObjectName("bubbleTitle")
        title.setTextFormat(Qt.PlainText)
        body.addWidget(title)
        text = QLabel(message.text)
        text.setTextFormat(Qt.PlainText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(text)
        if message.result:
            if message.result.emotion_tags:
                row = QHBoxLayout()
                for value in message.result.emotion_tags:
                    tag = QLabel(value)
                    tag.setObjectName("emotionTag")
                    tag.setTextFormat(Qt.PlainText)
                    row.addWidget(tag)
                row.addStretch()
                body.addLayout(row)
            if message.result.action_suggestions:
                label = QLabel("行动建议" if message.source != "mock" else "行动建议（开发测试内容）")
                label.setObjectName("suggestionTitle")
                body.addWidget(label)
            for index, item in enumerate(message.result.action_suggestions, 1):
                suggestion = QLabel(f"{index:02d}  {item}")
                suggestion.setObjectName("suggestion")
                suggestion.setTextFormat(Qt.PlainText)
                suggestion.setWordWrap(True)
                body.addWidget(suggestion)
        self.meta = QLabel()
        self.meta.setObjectName("muted")
        self.created_time = message.created_at[11:16]
        self.update_status(message)
        body.addWidget(self.meta)
        if message.role == "user":
            layout.addStretch(1)
        layout.addWidget(card, 4)
        if message.role != "user":
            layout.addStretch(1)

    def update_status(self, message: Message) -> None:
        statuses = {"pending": "等待回复", "completed": "已完成", "failed": "失败，可重试",
                    "cancelled": "已停止"}
        self.meta.setText(f"{self.created_time} · {statuses.get(message.status, message.status)}")
