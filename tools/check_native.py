"""Targeted native Windows tray and suspend/resume integration checks."""
from __future__ import annotations

import ctypes
import json
import os
import sys
import uuid
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from companion.storage import DEFAULT_PLANS, Store
from companion.window import MainWindow

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
directory = root / "artifacts" / ("native-integration-" + uuid.uuid4().hex[:8])
store = Store(directory)
store.save_plans(DEFAULT_PLANS, datetime.now())
window = MainWindow(store, testing=True)
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
window.show()
app.processEvents()
checks = []
try:
    window.start_timer("study", "休眠事件验证", 25)
    message = wintypes.MSG()
    message.message = 0x0218
    message.wParam = 0x0004
    window.power_events.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message))
    assert not window.timer.running, "Suspend must pause timer"
    checks.append("Windows 休眠事件暂停计时")
    message.wParam = 0x0012
    window.power_events.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message))
    assert not window.timer.running, "Resume must await explicit continue"
    checks.append("Windows 恢复事件保持暂停")
    available = QSystemTrayIcon.isSystemTrayAvailable()
    if available:
        window.testing = False
        window.tray.show()
        app.processEvents()
        assert window.tray.isVisible()
        window.close()
        assert not window.isVisible() and window.heartbeat.isActive()
        checks.append("关闭窗口后托盘继续运行")
        window.activate()
        app.processEvents()
        assert window.isVisible()
        checks.append("托盘打开窗口行为")
    window.quit_app()
    assert not window.heartbeat.isActive() and not window.tray.isVisible()
    checks.append("退出停止提醒并隐藏托盘")
    result = {"passed": True, "system_tray_available": available, "checks": checks}
finally:
    window.heartbeat.stop()
    window.tray.hide()
    window.timer.pause()
    window.timer.flush()
    store.close()
directory.mkdir(exist_ok=True)
(root / "artifacts" / "native-integration-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
