import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="青语伴行 Qt 在线聊天与离线案例")
    parser.add_argument("--smoke-test", action="store_true", help="完成一次预设案例对话后退出")
    parser.add_argument("--screenshot", help="冒烟测试时保存窗口截图")
    parser.add_argument("--fresh-demo", action="store_true", help="开始新演示，不恢复旧记录；旧文件保留")
    args = parser.parse_args()
    if args.smoke_test and sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow
    from app import __version__
    from app.utils.logging_config import configure_logging

    application = QApplication(sys.argv[:1])
    application.setApplicationName("Qingyu")
    application.setOrganizationName("QingyuCompanion")
    application.setApplicationVersion(__version__)
    configure_logging()
    if args.smoke_test:
        import tempfile
        from pathlib import Path
        from app.services.history_store import HistoryStore
        smoke_directory = tempfile.TemporaryDirectory(prefix="qingyu-smoke-")
        window = MainWindow(history_store=HistoryStore(Path(smoke_directory.name)), restore=False)
    else:
        window = MainWindow(restore=not args.fresh_demo)
    window.show()
    if args.smoke_test:
        window.input.setPlainText(window.controller.next_demo_question())
        window._send()

        def finish():
            if window.controller.busy:
                QTimer.singleShot(50, finish)
                return
            # 留出布局与绘制事件，避免截图只有已完成的用户气泡。
            QTimer.singleShot(150, capture_and_exit)

        def capture_and_exit():
            messages = window.controller.messages
            valid = len(messages) == 2 and all(m.status == "completed" for m in messages)
            if args.screenshot:
                valid = window.grab().save(args.screenshot) and valid
            window.close()
            application.exit(0 if valid else 1)

        QTimer.singleShot(1000, finish)
        QTimer.singleShot(10_000, lambda: application.exit(2))
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
