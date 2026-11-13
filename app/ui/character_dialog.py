from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.services.character_config import CharacterConfig


class CharacterDialog(QDialog):
    def __init__(self, character: CharacterConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("角色介绍")
        self.resize(760, 600)
        self.setMinimumSize(620, 480)
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        columns = QHBoxLayout(content)
        columns.setSpacing(24)
        portrait = character.image_path("portrait")
        if portrait:
            pixmap = QPixmap(str(portrait))
            if not pixmap.isNull():
                image = QLabel()
                image.setFixedWidth(180)
                image.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
                ratio = self.devicePixelRatioF()
                pixmap = pixmap.scaled(round(180 * ratio), round(460 * ratio), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pixmap.setDevicePixelRatio(ratio)
                image.setPixmap(pixmap)
                columns.addWidget(image, 0, Qt.AlignTop)
        details = QWidget()
        form = QFormLayout(details)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fields = [("姓名", character.name), ("身份", character.identity),
                  ("年龄设定", character.age_description),
                  ("性格", "、".join(character.traits)), ("人物简介", character.bio),
                  ("欢迎语", character.welcome), ("服务范围", "学业压力、考研就业、情感、人际与成长迷茫"),
                  ("使用边界", character.disclaimer)]
        for label, value in reversed([("昵称", character.nickname), ("性别设定", character.gender),
                                      ("音色设计", character.voice_design), ("角色背景", character.background),
                                      ("外观", character.appearance), ("沟通方式", character.communication_style)]):
            if value:
                fields.insert(2, (label, value))
        for label, value in fields:
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextFormat(Qt.PlainText)
            form.addRow(label, value_label)
        if character.warnings:
            warning = QLabel("部分角色配置或图片暂缺，当前使用开发默认内容。正式材料到达后替换。")
            warning.setWordWrap(True)
            form.addRow("资源状态", warning)
        columns.addWidget(details, 1)
        scroll.setWidget(content)
        root.addWidget(scroll)
