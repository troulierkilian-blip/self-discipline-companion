from __future__ import annotations

import ctypes
import logging
import sys
from datetime import date, datetime, timedelta

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QMainWindow, QMenu,
                             QMessageBox, QScrollArea, QStackedWidget,
                             QSystemTrayIcon, QVBoxLayout, QWidget)

from . import APP_NAME
from .dialogs import PlanDialog, ReminderDialog, SleepDialog, StudyDialog
from .pages import FocusPage, RecordsPage, SettingsPage, StatsPage, TodayPage
from .services import FocusTimer, ReminderService
from .storage import Store
from .widgets import STYLE, app_pixmap, button, duration, icon, label


class PowerEvents(QAbstractNativeEventFilter):
    def __init__(self, window):
        super().__init__()
        self.window = window

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            from ctypes import wintypes
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0218 and msg.wParam == 0x0004:  # WM_POWERBROADCAST / PBT_APMSUSPEND
                    self.window.timer.pause("电脑已进入休眠，点击继续后恢复计时。")
                    self.window.refresh()
                elif msg.message == 0x0218 and msg.wParam in (0x0007, 0x0012):
                    self.window.timer.pause("电脑已从休眠恢复，点击继续后恢复计时。")
                    self.window.timer._baseline()
                    self.window.refresh()
            except Exception:
                logging.exception("Unable to handle Windows power event")
        return False, 0


class MainWindow(QMainWindow):
    def __init__(self, store: Store, testing=False):
        super().__init__()
        self.store, self.testing = store, testing
        self.timer = FocusTimer(store)
        self.reminders = ReminderService(store)
        self.reminder_dialog = None
        self.quitting = False
        self.last_day = date.today()
        self.store.ensure_history(date.today())
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(app_pixmap()))
        self.setMinimumSize(1030, 650)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, screen.width() - 40), min(810, screen.height() - 50))
        self.move(screen.center() - self.rect().center())
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        base = QHBoxLayout(root)
        base.setContentsMargins(0, 0, 0, 0)
        base.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        rail = QVBoxLayout(sidebar)
        rail.setContentsMargins(14, 25, 14, 20)
        rail.setSpacing(8)
        brand = QHBoxLayout()
        brand.setContentsMargins(7, 0, 0, 0)
        mark = label()
        mark.setPixmap(app_pixmap(34))
        brand.addWidget(mark)
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch()
        rail.addLayout(brand)
        tagline = label("让每天，都有好节奏", "muted")
        tagline.setContentsMargins(10, 5, 0, 22)
        rail.addWidget(tagline)
        self.nav = []
        for i, (name, symbol) in enumerate((("今日概览", "today"), ("学习专注", "study"), ("日常记录", "records"), ("历史统计", "stats"), ("计划与设置", "settings"))):
            b = button(name, lambda checked=False, page=i: self.navigate(page), name=symbol)
            b.setProperty("role", "nav")
            b.setCheckable(True)
            rail.addWidget(b)
            self.nav.append(b)
        rail.addStretch()
        hint = label("●  本地记录 · 离线可用", "muted")
        hint.setContentsMargins(10, 0, 0, 8)
        rail.addWidget(hint)
        rail.addWidget(button("使用说明", self.show_help, name="study"))
        base.addWidget(sidebar)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(28, 26, 26, 12)
        column.setSpacing(22)
        heading = QHBoxLayout()
        headings = QVBoxLayout()
        headings.setSpacing(7)
        self.page_title = label("今日概览", "title")
        self.page_subtitle = label("照顾好今天的学习、运动与睡眠", "subtitle")
        headings.addWidget(self.page_title)
        headings.addWidget(self.page_subtitle)
        heading.addLayout(headings, 1)
        self.date_label = label("", "muted")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        heading.addWidget(self.date_label)
        column.addLayout(heading)
        self.stack = QStackedWidget()
        self.pages = [TodayPage(self), FocusPage(self), RecordsPage(self), StatsPage(self), SettingsPage(self)]
        for page in self.pages:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        column.addWidget(self.stack, 1)
        footer = QHBoxLayout()
        self.status = label("关闭窗口后仍在托盘提醒", "muted")
        footer.addWidget(self.status, 1)
        self.timer_link = button("", lambda: self.navigate(1), name="clock")
        self.timer_link.hide()
        footer.addWidget(self.timer_link)
        column.addLayout(footer)
        base.addWidget(content, 1)
        self.setup_tray()
        self.power_events = PowerEvents(self)
        QApplication.instance().installNativeEventFilter(self.power_events)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.timeout.connect(self.on_tick)
        self.heartbeat.start()
        self.ticks = 0
        self.navigate(0)
        self.refresh()
        if not testing:
            QTimer.singleShot(350, self.welcome)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(QIcon(app_pixmap()), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        for title, callback in (("打开自律伴侣", self.activate), ("开始学习", lambda: self.navigate_and_activate(1)), ("记录运动", lambda: self.open_records(0)), ("记录睡眠", lambda: self.open_records(1))):
            action = QAction(title, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.quit_app)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.activate() if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.messageClicked.connect(self.show_pending_reminders)
        if not self.testing and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def welcome(self):
        if not self.store.get_meta("setup_complete", False):
            self.edit_plan()
        elif self.timer.recovered:
            self.navigate(1)
            self.info("上次的计时已经恢复为暂停状态。已保存的时长保留，点击「继续」即可接着进行。")
        self.check_reminders()

    def summary(self, day):
        s = self.store.summary(day)
        for kind in ("study", "exercise"):
            s["totals"][kind] += self.timer.pending_for(day, kind)
            s["achieved"][kind] = s["totals"][kind] + 0.01 >= s["goals"][kind]
        return s

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, nav in enumerate(self.nav):
            nav.setChecked(i == index)
            nav.setIcon(icon(("today", "study", "records", "stats", "settings")[i], "#4169DD" if i == index else "#7A879C"))
        self.page_title.setText(("今日概览", "学习专注", "日常记录", "历史统计", "计划与设置")[index])
        self.page_subtitle.setText(("照顾好今天的学习、运动与睡眠", "把注意力，放回你想完成的事情", "留下实际记录，了解自己的日常节奏", "回看积累，用记录调整下一步", "按自己的生活，安排可持续的目标")[index])
        self.pages[index].refresh()

    def navigate_and_activate(self, index):
        self.navigate(index)
        self.activate()

    def open_records(self, index):
        self.pages[2].day.setDate(self.pages[2].day.date().currentDate())
        self.pages[2].tabs.setCurrentIndex(index)
        self.navigate_and_activate(2)

    def activate(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def refresh(self):
        weekday = "一二三四五六日"[date.today().weekday()]
        self.date_label.setText(f"{date.today():%Y 年 %m 月 %d 日}  周{weekday}\n{'周末计划' if date.today().weekday() >= 5 else '工作日计划'}")
        for page in self.pages:
            page.refresh()
        self.update_timer_widgets()

    def update_timer_widgets(self):
        self.pages[1].update_timer()
        self.pages[2].update_timer()
        active = self.timer.session is not None
        self.timer_link.setVisible(active)
        if active:
            kind = "专注" if self.timer.session["kind"] == "study" else "运动"
            state = "进行中" if self.timer.running else "已暂停"
            self.timer_link.setText(f"{kind}{state} · {duration(self.timer.seconds / 60)}")
            self.tray.setToolTip(f"{APP_NAME} · {kind}{state}")
        else:
            self.tray.setToolTip(APP_NAME)

    def edit_plan(self):
        initial = not self.store.get_meta("setup_complete", False)
        if PlanDialog(self.store, self, initial=initial).exec():
            self.refresh()

    def start_timer(self, kind, title, minutes, task_id=None):
        if not self.store.get_meta("setup_complete", False):
            self.edit_plan()
            if not self.store.get_meta("setup_complete", False):
                return
        if not title.strip():
            self.warn("请填写计时名称。")
            return
        try:
            self.timer.start(kind, title.strip(), minutes, task_id)
            self.refresh()
        except ValueError as exc:
            self.warn(str(exc))

    def toggle_pause(self):
        if self.timer.running:
            self.timer.pause()
        else:
            self.timer.resume()
        self.refresh()

    def supplement_study(self, day: date, task_id=None, record=None):
        if not self.store.get_meta("setup_complete", False):
            self.edit_plan()
            if not self.store.get_meta("setup_complete", False):
                return
        dialog = StudyDialog(self.store, day, self, record=record, task_id=task_id)
        if dialog.exec():
            if self.stack.currentIndex() == 2 and self.pages[2].tabs.currentIndex() == 2:
                self.pages[2].day.setDate(dialog.day.date())
            self.refresh()
            self.status.setText(f"{dialog.day.date().toString('yyyy-MM-dd')} 的学习补记已自动计入统计。")
            if not self.testing:
                self.check_reminders()

    def finish_timer(self):
        self.timer.finish()
        self.status.setText("本段计时已保存，给自己一个短暂的休息。")
        self.refresh()

    def start_sleep(self):
        pending = self.store.get_meta("sleep_started")
        if pending:
            self.warn("已有待确认的睡眠，请先记录起床时间或在睡眠页面处理。")
            return
        if QMessageBox.question(self, "准备睡觉", "将现在记为入睡估计时间。起床后可修正实际时间。确认准备睡觉？") == QMessageBox.StandardButton.Yes:
            self.timer.pause("准备睡觉，计时已暂停。")
            self.store.set_meta("sleep_started", datetime.now().isoformat())
            self.refresh()

    def wake_sleep(self):
        pending = self.store.get_meta("sleep_started")
        existing = self.store.sleep_record(date.today())
        if existing and pending:
            if QMessageBox.question(self, "已有睡眠记录", "今天已有睡眠记录。是否编辑该记录，并清除待确认的入睡时间？") != QMessageBox.StandardButton.Yes:
                return
        dialog = SleepDialog(self.store, date.today(), self, record=existing, start=pending)
        if pending and (datetime.now() - datetime.fromisoformat(pending)).total_seconds() > 86400:
            self.warn("这次入睡确认已超过 24 小时，请在弹窗中修正实际时间。")
        if dialog.exec():
            self.store.set_meta("sleep_started", None)
            self.refresh()

    def on_tick(self):
        self.ticks += 1
        title = self.timer.session["title"] if self.timer.session else ""
        event = self.timer.tick()
        if event:
            message = f"{title} · 本轮计时已完成，实际时长已保存。" if event == "completed" else "检测到休眠或时钟变化，计时已暂停。"
            self.status.setText(message)
            if not self.testing:
                self.tray.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Information, 7000)
            self.refresh()
        self.update_timer_widgets()
        if date.today() != self.last_day:
            self.last_day = date.today()
            self.store.ensure_day(self.last_day)
            self.refresh()
        elif self.ticks % 15 == 0:
            self.refresh()
        if self.ticks % 5 == 0 and not self.testing:
            self.check_reminders()

    def check_reminders(self):
        items = self.reminders.due()
        if self.reminder_dialog:
            due_keys = {item["key"] for item in items}
            for key in list(self.reminder_dialog.items):
                if key not in due_keys:
                    row, _ = self.reminder_dialog.items.pop(key)
                    row.hide()
                    row.deleteLater()
            if not self.reminder_dialog.items and not items:
                self.reminder_dialog.accept()
        if not items:
            return
        if self.reminder_dialog is None:
            self.reminder_dialog = ReminderDialog(self)
            self.reminder_dialog.action.connect(self.handle_reminder)
            self.reminder_dialog.finished.connect(self.reminders_closed)
        fresh = [item for item in items if item["key"] not in self.reminder_dialog.items]
        if fresh:
            self.reminder_dialog.add_items(fresh)
            for item in fresh:
                self.store.reminder_action(item["key"], "shown", datetime.now())
            if not self.testing:
                self.tray.showMessage(APP_NAME, f"有 {len(fresh)} 条计划提醒，点击查看。", QSystemTrayIcon.MessageIcon.Information, 7000)
            self.reminder_dialog.show()
            self.reminder_dialog.raise_()

    def handle_reminder(self, key, action):
        self.store.reminder_action(key, action, datetime.now())
        if action == "started":
            kind = key.rsplit(":", 1)[1]
            if kind == "study":
                self.navigate_and_activate(1)
                if not self.timer.session:
                    self.pages[1].start_timer()
            elif kind == "exercise":
                self.open_records(0)
                if not self.timer.session:
                    self.start_timer("exercise", self.pages[2].exercise_type.currentText(), self.pages[2].exercise_minutes.value())
            elif kind == "bedtime":
                self.open_records(1)
                self.start_sleep()
            else:
                self.open_records(1)
                self.wake_sleep()
        self.refresh()

    def reminders_closed(self):
        if self.reminder_dialog:
            self.reminder_dialog.deleteLater()
        self.reminder_dialog = None

    def show_pending_reminders(self):
        if self.reminder_dialog:
            self.reminder_dialog.show()
            self.reminder_dialog.raise_()
        else:
            self.activate()
            self.check_reminders()

    def warn(self, message):
        if self.testing:
            raise ValueError(message)
        QMessageBox.warning(self, APP_NAME, message)

    def info(self, message):
        if not self.testing:
            QMessageBox.information(self, APP_NAME, message)

    def show_help(self):
        QMessageBox.information(self, "使用说明", "1. 在「计划与设置」填写工作日、周末目标和提醒时间。\n2. 添加学习任务开始专注，或用「补记学习」填写已经完成的时长；两者自动合计。暂停和休眠不累计时间。\n3. 运动可以计时，也可以手动补记实际分钟数。\n4. 睡前确认准备睡觉，醒来确认起床；实际时间可修正。\n5. 在「历史统计」查看趋势或导出 CSV。\n6. 关闭窗口仍在托盘运行；右键托盘图标选择退出。\n7. 在设置中备份数据；恢复前自动保留原数据备份。")

    def closeEvent(self, event: QCloseEvent):
        if self.quitting or self.testing:
            event.accept()
            return
        if self.tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            self.timer.flush()
            self.hide()
            event.ignore()
            if not self.store.get_meta("tray_hint_shown", False):
                self.tray.showMessage(APP_NAME, "软件仍在系统托盘运行，右键图标可退出。", QSystemTrayIcon.MessageIcon.Information, 5000)
                self.store.set_meta("tray_hint_shown", True)
        else:
            self.quit_app()
            event.accept()

    def quit_app(self):
        self.quitting = True
        self.heartbeat.stop()
        self.timer.pause("退出前已暂停，下次打开可继续。")
        self.timer.flush()
        if self.reminder_dialog:
            self.reminder_dialog.reject()
        self.tray.hide()
        QApplication.instance().quit()
