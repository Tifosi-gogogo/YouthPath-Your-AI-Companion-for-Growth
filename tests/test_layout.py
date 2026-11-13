from PySide6.QtWidgets import QPushButton

from app.ui.main_window import MainWindow
from tests.conftest import spin_until


def test_minimum_window_keeps_controls_at_their_minimum_size(qt_app):
    window = MainWindow()
    window.resize(900, 600)
    window.show()
    spin_until(lambda: window.send.isVisible())
    qt_app.processEvents()
    for button in window.findChildren(QPushButton):
        if button.isVisible():
            assert button.height() >= button.minimumSizeHint().height()
    assert window.send.isEnabled()
    window.close()
