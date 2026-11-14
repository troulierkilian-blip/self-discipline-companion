from __future__ import annotations

import argparse
import ctypes
import json
import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="自律伴侣 — 每日学习、运动与睡眠记录")
    parser.add_argument("--data-dir", type=Path, help="指定独立的数据目录")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--screenshot-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--quit-after", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QMessageBox
    from companion import APP_NAME, VERSION
    from companion.instance import SingleInstance
    from companion.storage import Store
    from companion.window import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("DailyCompanion")
    app.setQuitOnLastWindowClosed(False)
    # The offscreen plugin does not discover installed Windows fonts itself.
    font_root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for font_name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
        font_file = font_root / font_name
        if font_file.exists():
            QFontDatabase.addApplicationFont(str(font_file))
    app.setFont(QFont("Microsoft YaHei", 10))
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DailyCompanion.Desktop.1")
    directory = args.data_dir or (Path(tempfile.mkdtemp(prefix="companion-qa-")) if args.smoke_test else Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / APP_NAME)
    directory.mkdir(parents=True, exist_ok=True)
    if args.smoke_test and (directory / "companion.sqlite3").exists():
        # Keep fixture records away from an existing personal database.
        directory = directory / ("qa-" + __import__("uuid").uuid4().hex)
        directory.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(directory / "companion.log", maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    guard = None
    store = None
    try:
        if not args.smoke_test:
            guard = SingleInstance(directory)
            if not guard.is_primary:
                return 0
        store = Store(directory)
        window = MainWindow(store, testing=args.smoke_test or bool(args.quit_after))
        ready_state = {"pid": os.getpid(), "frozen": bool(getattr(sys, "frozen", False)), "version": VERSION, "activations": 0}

        def instance_activated():
            if not args.background:
                window.activate()
            ready_state["activations"] += 1
            if args.ready_file:
                args.ready_file.write_text(json.dumps(ready_state), encoding="utf-8")

        if guard:
            guard.activated.connect(instance_activated)
        if not args.background:
            window.show()
        logging.info("Started %s %s", APP_NAME, VERSION)
        if args.ready_file:
            args.ready_file.parent.mkdir(parents=True, exist_ok=True)
            args.ready_file.write_text(json.dumps(ready_state), encoding="utf-8")

        def exception_hook(exc_type, exc, traceback):
            logging.error("Unhandled application exception", exc_info=(exc_type, exc, traceback))
            if args.smoke_test or args.quit_after:
                app.exit(1)
            else:
                QMessageBox.warning(window, APP_NAME, f"操作未完成：{exc}\n详细原因已保存到数据目录的日志。")

        sys.excepthook = exception_hook
        if args.smoke_test:
            from companion.qa import run_ui_checks

            def run_checks():
                try:
                    report = run_ui_checks(window, args.screenshot_dir or directory / "screenshots")
                    report["frozen"] = bool(getattr(sys, "frozen", False))
                    (directory / "smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    window.quit_app()
                    app.exit(0)
                except Exception as exc:
                    logging.exception("UI smoke test failed")
                    (directory / "smoke-report.json").write_text(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
                    app.exit(1)

            QTimer.singleShot(150, run_checks)
        if args.quit_after:
            QTimer.singleShot(args.quit_after * 1000, window.quit_app)
        result = app.exec()
        window.heartbeat.stop()
        window.timer.pause("程序关闭，已保存。")
        window.timer.flush()
        return result
    except Exception as exc:
        logging.exception("Startup failed")
        if not args.smoke_test and not args.quit_after:
            QMessageBox.critical(None, APP_NAME, f"无法启动：{exc}\n可查看数据目录中的 companion.log。")
        return 1
    finally:
        if store:
            store.close()
        if guard:
            guard.close()


if __name__ == "__main__":
    sys.exit(main())
