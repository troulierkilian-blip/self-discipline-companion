from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QFileDialog,
                             QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
                             QLineEdit, QMessageBox, QSpinBox, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import VERSION
from .dialogs import ExerciseDialog, PlanDialog, SleepDialog
from .storage import KINDS, sleep_goal_minutes
from .widgets import COLORS, GoalCard, TrendChart, button, duration, icon, label, panel


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(45)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setMinimumHeight(180)
    return t


def fill_table(t, rows):
    t.setRowCount(len(rows))
    for i, values in enumerate(rows):
        for j, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            t.setItem(i, j, cell)


class TodayPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        banner = panel()
        banner.setStyleSheet("QFrame#panel { background: #EEF3FF; border: 1px solid #E0E8FD; }")
        line = QHBoxLayout(banner)
        line.setContentsMargins(22, 18, 22, 18)
        texts = QVBoxLayout()
        self.greeting = label("今天，也向目标靠近一点", "section")
        self.caption = label("学习、运动、好好休息，让每天都有清晰的节奏。", "subtitle", True)
        texts.addWidget(self.greeting)
        texts.addWidget(self.caption)
        line.addLayout(texts, 1)
        self.progress = label("0 / 3 项达标", "section")
        line.addWidget(self.progress)
        layout.addWidget(banner)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.cards = {}
        for kind, title, action, callback in (
            ("study", "学习", "开始一段专注", lambda: app.navigate(1)),
            ("exercise", "运动", "记录今天的运动", lambda: app.open_records(0)),
            ("sleep", "睡眠", "记录昨晚的睡眠", lambda: app.open_records(1)),
        ):
            card = GoalCard(kind, title, action, callback)
            self.cards[kind] = card
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        lower = QHBoxLayout()
        lower.setSpacing(18)
        task_box = panel()
        tasks = QVBoxLayout(task_box)
        tasks.setContentsMargins(20, 20, 20, 20)
        heading = QHBoxLayout()
        heading.addWidget(label("今天的学习任务", "section"))
        heading.addStretch()
        heading.addWidget(button("管理任务", lambda: app.navigate(1), name="arrow"))
        tasks.addLayout(heading)
        self.task_list = QVBoxLayout()
        self.task_list.setSpacing(13)
        tasks.addLayout(self.task_list)
        tasks.addStretch()
        lower.addWidget(task_box, 3)
        rhythm_box = panel()
        rhythm = QVBoxLayout(rhythm_box)
        rhythm.setContentsMargins(20, 20, 20, 20)
        rhythm.setSpacing(16)
        rhythm.addWidget(label("今日节奏", "section"))
        self.schedule = {}
        for kind in ("wake", "study", "exercise", "bedtime"):
            row = QHBoxLayout()
            mark = label()
            mark.setPixmap(icon("sleep" if kind in ("wake", "bedtime") else kind, "#8695AC", 18).pixmap(18, 18))
            row.addWidget(mark)
            row.addWidget(label(KINDS[kind], "muted"))
            row.addStretch()
            value = label("", "cardTitle")
            self.schedule[kind] = value
            row.addWidget(value)
            rhythm.addLayout(row)
        rhythm.addStretch()
        lower.addWidget(rhythm_box, 2)
        layout.addLayout(lower)
        next_box = panel()
        next_row = QHBoxLayout(next_box)
        next_row.setContentsMargins(18, 13, 18, 13)
        bell = label()
        bell.setPixmap(icon("bell", "#5278ED", 20).pixmap(20, 20))
        next_row.addWidget(bell)
        self.next_label = label("", "muted", True)
        next_row.addWidget(self.next_label, 1)
        next_row.addWidget(button("调整计划", app.edit_plan))
        layout.addWidget(next_box)
        layout.addStretch()

    def refresh(self):
        s = self.app.summary(date.today())
        for card in self.cards.values():
            card.refresh(s)
        complete = sum(s["achieved"].values())
        self.progress.setText(f"{complete} / 3 项达标")
        setup = self.app.store.get_meta("setup_complete", False)
        if not setup:
            for card in self.cards.values():
                card.amount.setText("—")
                card.goal.setText("请先确认每日目标")
                card.badge.setText("待设置")
                card.detail.setText("在计划与设置中，填写适合自己的目标和作息。")
                card.ring.set_progress(0)
        self.greeting.setText("今天的三个目标都完成了" if complete == 3 else "今天，也向目标靠近一点" if setup else "欢迎，先安排你的每日节奏")
        self.caption.setText("记录今天的收获，给自己留一点休息时间。" if complete == 3 else "学习、运动、好好休息，让每天都有清晰的节奏。" if setup else "点击「调整计划」，确认工作日与周末的目标和作息。")
        while self.task_list.count():
            item = self.task_list.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        items = self.app.store.tasks(date.today())
        if not items:
            self.task_list.addWidget(label("还没有任务\n添加一件今天想完成的事，然后开始专注。", "muted", True))
        else:
            for item in items[:4]:
                row = QWidget()
                line = QHBoxLayout(row)
                line.setContentsMargins(0, 0, 0, 0)
                line.setSpacing(8)
                mark = label()
                mark.setPixmap(icon("check" if item["done"] else "clock", "#98A4B7" if item["done"] else "#5278ED", 17).pixmap(17, 17))
                line.addWidget(mark)
                line.addWidget(label(item["title"], "muted" if item["done"] else "", True), 1)
                self.task_list.addWidget(row)
            if len(items) > 4:
                self.task_list.addWidget(label(f"还有 {len(items) - 4} 项任务，在专注页面查看", "muted"))
        fields = {"wake": "wake_time", "study": "study_time", "exercise": "exercise_time", "bedtime": "bedtime"}
        for kind, field in fields.items():
            self.schedule[kind].setText(s["plan"][field])
        self.next_label.setText("下一条提醒 · " + self.app.reminders.next_text())


class FocusPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        timer_box = panel()
        timer = QVBoxLayout(timer_box)
        timer.setContentsMargins(26, 22, 26, 22)
        timer.setSpacing(12)
        self.state = label("准备开始一段专注", "section")
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer.addWidget(self.state)
        self.clock = label("25:00", "timer")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer.addWidget(self.clock)
        self.info = label("一次只做一件事，休息时间不计入学习时长。", "muted", True)
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer.addWidget(self.info)
        controls = QHBoxLayout()
        controls.addStretch()
        self.task_combo = QComboBox()
        self.task_combo.setMinimumWidth(230)
        controls.addWidget(self.task_combo)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 1440)
        self.minutes.setValue(app.store.get_meta("focus_minutes", 25))
        self.minutes.setSuffix(" 分钟")
        self.minutes.valueChanged.connect(self.update_timer)
        controls.addWidget(self.minutes)
        controls.addStretch()
        timer.addLayout(controls)
        actions = QHBoxLayout()
        actions.addStretch()
        self.start = button("开始专注", self.start_timer, primary=True, name="play")
        self.pause = button("暂停", app.toggle_pause, name="pause")
        self.stop = button("结束并保存", app.finish_timer, name="check")
        self.supplement = button("补记学习", lambda: app.supplement_study(date.today(), task_id=self.task_combo.currentData()), name="plus")
        actions.addWidget(self.start)
        actions.addWidget(self.pause)
        actions.addWidget(self.stop)
        actions.addWidget(self.supplement)
        actions.addStretch()
        timer.addLayout(actions)
        layout.addWidget(timer_box)
        tasks_box = panel()
        tasks = QVBoxLayout(tasks_box)
        tasks.setContentsMargins(20, 20, 20, 20)
        top = QHBoxLayout()
        top.addWidget(label("学习任务清单", "section"))
        top.addStretch()
        top.addWidget(button("添加任务", self.add_task, primary=True, name="plus"))
        top.addWidget(button("编辑", self.edit_task))
        top.addWidget(button("删除", self.delete_task))
        tasks.addLayout(top)
        self.task_table = table(["完成", "任务名称", "专注"])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(0, 65)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(2, 120)
        self.task_table.itemChanged.connect(self.task_changed)
        self.task_table.cellDoubleClicked.connect(lambda row, col: self.edit_task() if col == 1 else None)
        tasks.addWidget(self.task_table)
        tasks.addWidget(label("勾选代表任务完成；专注计时与学习补记一起累计时长。", "muted", True))
        layout.addWidget(tasks_box)
        layout.addStretch()
        self.task_items = []

    def start_timer(self):
        task_id = self.task_combo.currentData()
        title = self.task_combo.currentText()
        self.app.store.set_meta("focus_minutes", self.minutes.value())
        self.app.start_timer("study", title, self.minutes.value(), task_id)

    def add_task(self):
        text, ok = QInputDialog.getText(self, "添加学习任务", "今天想完成什么？")
        if ok and text.strip():
            try:
                self.app.store.add_task(date.today(), text)
                self.app.refresh()
            except ValueError as exc:
                self.app.warn(str(exc))

    def selected_task(self):
        row = self.task_table.currentRow()
        if not 0 <= row < len(self.task_items):
            self.app.warn("请先选择一项任务。")
            return None
        return self.task_items[row]

    def edit_task(self):
        item = self.selected_task()
        if not item:
            return
        text, ok = QInputDialog.getText(self, "编辑学习任务", "任务名称", text=item["title"])
        if ok:
            try:
                self.app.store.update_task(item["id"], title=text)
                self.app.refresh()
            except ValueError as exc:
                self.app.warn(str(exc))

    def delete_task(self):
        item = self.selected_task()
        if item and QMessageBox.question(self, "删除任务", "删除这项任务？已经累计的学习时长会保留。") == QMessageBox.StandardButton.Yes:
            self.app.store.delete_task(item["id"])
            self.app.refresh()

    def task_changed(self, item):
        if item.column() == 0:
            self.app.store.update_task(item.data(Qt.ItemDataRole.UserRole), done=item.checkState() == Qt.CheckState.Checked)
            self.app.refresh()

    def start_task(self, task):
        self.task_combo.setCurrentIndex(max(0, self.task_combo.findData(task["id"])))
        self.app.start_timer("study", task["title"], self.minutes.value(), task["id"])

    def refresh(self):
        selected = self.task_combo.currentData()
        self.task_combo.clear()
        self.task_combo.addItem("自由专注", None)
        self.task_items = self.app.store.tasks(date.today())
        self.task_table.blockSignals(True)
        self.task_table.setRowCount(len(self.task_items))
        for i, task in enumerate(self.task_items):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if task["done"] else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, task["id"])
            self.task_table.setItem(i, 0, check)
            text = QTableWidgetItem(task["title"])
            text.setToolTip(task["title"])
            if task["done"]:
                text.setForeground(QColor("#99A4B6"))
            self.task_table.setItem(i, 1, text)
            begin = button("开始", lambda checked=False, t=task: self.start_task(t), name="play")
            begin.setEnabled(not task["done"] and self.app.timer.session is None)
            self.task_table.setCellWidget(i, 2, begin)
            if not task["done"]:
                self.task_combo.addItem(task["title"], task["id"])
        self.task_table.blockSignals(False)
        self.task_combo.setCurrentIndex(max(0, self.task_combo.findData(selected)))
        self.update_timer()

    def update_timer(self):
        timer = self.app.timer
        active = timer.session is not None
        self.start.setVisible(not active)
        self.pause.setVisible(active)
        self.stop.setVisible(active)
        self.task_combo.setEnabled(not active)
        self.minutes.setEnabled(not active)
        remaining = max(0, int(timer.session["target_seconds"] - timer.seconds + 0.999)) if active else self.minutes.value() * 60
        mins, secs = divmod(remaining, 60)
        self.clock.setText(f"{mins:02d}:{secs:02d}")
        if active:
            kind = "学习专注" if timer.session["kind"] == "study" else "运动计时"
            self.state.setText(f"{kind} · {'进行中' if timer.running else '已暂停'}")
            self.info.setText(timer.pause_reason or f"{timer.session['title']} · 已累计 {duration(timer.seconds / 60)}")
            self.pause.setText("暂停" if timer.running else "继续")
        else:
            self.state.setText("准备开始一段专注")
            self.info.setText("一次只做一件事，休息时间不计入学习时长。")


class RecordsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        top = QHBoxLayout()
        top.addWidget(label("查看日期", "muted"))
        self.day = QDateEdit(QDate.currentDate())
        self.day.setDisplayFormat("yyyy-MM-dd")
        self.day.setCalendarPopup(True)
        self.day.setMaximumDate(QDate.currentDate())
        self.day.dateChanged.connect(self.refresh)
        top.addWidget(self.day)
        top.addStretch()
        top.addWidget(button("回到今天", lambda: self.day.setDate(QDate.currentDate())))
        layout.addLayout(top)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.build_exercise()
        self.build_sleep()
        self.build_study_history()
        self.build_reminder_history()
        layout.addStretch()

    def build_exercise(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setSpacing(18)
        timer_box = panel()
        timer = QVBoxLayout(timer_box)
        timer.setContentsMargins(20, 20, 20, 20)
        timer.addWidget(label("计时一次运动", "section"))
        self.exercise_hint = label("填写运动类型，完成后会自动保存实际时长。", "muted", True)
        timer.addWidget(self.exercise_hint)
        line = QHBoxLayout()
        self.exercise_type = QComboBox()
        self.exercise_type.setEditable(True)
        self.exercise_type.addItems(["散步", "跑步", "力量训练", "骑行", "瑜伽", "其他运动"])
        line.addWidget(self.exercise_type, 1)
        self.exercise_minutes = QSpinBox()
        self.exercise_minutes.setRange(1, 1440)
        self.exercise_minutes.setValue(30)
        self.exercise_minutes.setSuffix(" 分钟")
        line.addWidget(self.exercise_minutes)
        self.exercise_start = button("开始运动", lambda: self.app.start_timer("exercise", self.exercise_type.currentText(), self.exercise_minutes.value()), primary=True, name="play")
        line.addWidget(self.exercise_start)
        self.exercise_pause = button("暂停", app_callback(self.app, "toggle_pause"))
        self.exercise_stop = button("结束并保存", app_callback(self.app, "finish_timer"))
        line.addWidget(self.exercise_pause)
        line.addWidget(self.exercise_stop)
        timer.addLayout(line)
        layout.addWidget(timer_box)
        actions = QHBoxLayout()
        self.exercise_total = label("", "section")
        actions.addWidget(self.exercise_total, 1)
        actions.addWidget(button("补记运动", self.add_exercise, primary=True, name="plus"))
        actions.addWidget(button("编辑", self.edit_exercise))
        actions.addWidget(button("删除", self.delete_exercise))
        layout.addLayout(actions)
        self.exercise_table = table(["运动类型", "实际时长", "记录方式"])
        layout.addWidget(self.exercise_table)
        self.exercise_rows = []
        self.tabs.addTab(page, "运动")

    def build_sleep(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setSpacing(18)
        overview = panel()
        block = QVBoxLayout(overview)
        block.setContentsMargins(24, 22, 24, 22)
        block.setSpacing(15)
        self.sleep_amount = label("未记录睡眠", "metric")
        self.sleep_detail = label("", "muted", True)
        self.sleep_deviation = label("", "", True)
        self.sleep_pending = label("", "muted", True)
        block.addWidget(self.sleep_amount)
        block.addWidget(self.sleep_detail)
        block.addWidget(self.sleep_deviation)
        block.addWidget(self.sleep_pending)
        actions = QHBoxLayout()
        self.bed_button = button("准备睡觉", self.app.start_sleep, name="sleep")
        self.wake_button = button("已经起床", self.app.wake_sleep, primary=True, name="check")
        actions.addWidget(self.bed_button)
        actions.addWidget(self.wake_button)
        actions.addStretch()
        block.addLayout(actions)
        layout.addWidget(overview)
        tools = QHBoxLayout()
        tools.addWidget(label("该日起床的睡眠记录", "section"), 1)
        tools.addWidget(button("补录", self.add_sleep, primary=True, name="plus"))
        tools.addWidget(button("编辑", self.edit_sleep))
        tools.addWidget(button("删除", self.delete_sleep))
        layout.addLayout(tools)
        self.sleep_table = table(["实际入睡", "实际起床", "睡眠时长"])
        layout.addWidget(self.sleep_table)
        layout.addWidget(label("「准备睡觉」记录当前时间作为入睡估计，醒来后可以修正。", "muted", True))
        self.sleep_row = None
        self.tabs.addTab(page, "睡眠")

    def build_study_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        self.study_total = label("", "section")
        layout.addWidget(self.study_total)
        layout.addWidget(label("跨午夜的专注会按实际发生日期拆分。", "muted", True))
        actions = QHBoxLayout()
        actions.addStretch()
        self.study_add = button("补记学习", lambda: self.app.supplement_study(self.current_day()), primary=True, name="plus")
        actions.addWidget(self.study_add)
        actions.addWidget(button("编辑记录", self.edit_study))
        actions.addWidget(button("删除记录", self.delete_study))
        layout.addLayout(actions)
        self.study_table = table(["学习任务", "当日实际时长", "记录方式", "状态"])
        layout.addWidget(self.study_table)
        self.study_rows = []
        self.tabs.addTab(page, "学习记录")

    def build_reminder_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.addWidget(label("计划提醒与处理结果", "section"))
        self.reminder_table = table(["提醒", "计划时间", "当前提醒时间", "处理结果"])
        layout.addWidget(self.reminder_table)
        self.tabs.addTab(page, "提醒记录")

    def current_day(self):
        return self.day.date().toPython()

    def add_exercise(self):
        if ExerciseDialog(self.app.store, self.current_day(), self).exec():
            self.app.refresh()

    def selected(self, t, rows):
        index = t.currentRow()
        if 0 <= index < len(rows):
            return rows[index]
        self.app.warn("请先选择一条记录。")
        return None

    def edit_exercise(self):
        row = self.selected(self.exercise_table, self.exercise_rows)
        if row and ExerciseDialog(self.app.store, self.current_day(), self, row, session=row["source"] == "sessions").exec():
            self.app.refresh()

    def delete_exercise(self):
        row = self.selected(self.exercise_table, self.exercise_rows)
        if row:
            self.delete_selected(row["source"], row["id"])

    def delete_selected(self, source, record_id):
        if source == "sessions" and self.app.timer.session and self.app.timer.session["id"] == record_id:
            self.app.warn("请先结束这段计时。")
            return
        text = "删除整段计时及其所有日期的累计时长？" if source == "sessions" else "删除这条记录？"
        if QMessageBox.question(self, "删除记录", text) == QMessageBox.StandardButton.Yes:
            self.app.store.delete_record(source, record_id)
            self.app.refresh()

    def add_sleep(self):
        if self.sleep_row:
            self.app.warn("该日期已有睡眠记录，请选择编辑。")
            return
        if SleepDialog(self.app.store, self.current_day(), self).exec():
            self.app.refresh()

    def edit_sleep(self):
        if self.sleep_row:
            if SleepDialog(self.app.store, self.current_day(), self, self.sleep_row).exec():
                self.app.refresh()
        else:
            self.app.warn("该日期还没有睡眠记录。")

    def delete_sleep(self):
        if self.sleep_row:
            self.delete_selected("sleep", self.sleep_row["id"])

    def edit_study(self):
        row = self.selected(self.study_table, self.study_rows)
        if not row:
            return
        if row["source"] == "manual_study":
            self.app.supplement_study(self.current_day(), record=row)
            return
        title, ok = QInputDialog.getText(self, "编辑学习记录", "任务名称", text=row["title"])
        if not ok:
            return
        minutes, ok = QInputDialog.getDouble(self, "编辑学习记录", "该日实际学习分钟数", row["minutes"], 0.1, 1440, 1)
        if ok:
            try:
                self.app.store.update_session_record(row["id"], self.current_day(), title, minutes)
                self.app.refresh()
            except ValueError as exc:
                self.app.warn(str(exc))

    def delete_study(self):
        row = self.selected(self.study_table, self.study_rows)
        if row:
            self.delete_selected(row["source"], row["id"])

    def update_timer(self):
        timer = self.app.timer
        active = timer.session is not None
        exercise = active and timer.session["kind"] == "exercise"
        self.exercise_start.setVisible(not exercise)
        self.exercise_start.setEnabled(not active)
        self.exercise_type.setEnabled(not active)
        self.exercise_minutes.setEnabled(not active)
        self.exercise_pause.setVisible(exercise)
        self.exercise_stop.setVisible(exercise)
        self.exercise_pause.setText("暂停" if timer.running else "继续")
        if exercise:
            remaining = max(0, int(timer.session["target_seconds"] - timer.seconds + 0.999))
            self.exercise_hint.setText(f"{timer.session['title']} · {'进行中' if timer.running else '已暂停'} · 剩余 {remaining // 60:02d}:{remaining % 60:02d}")
        else:
            self.exercise_hint.setText("填写运动类型，完成后会自动保存实际时长。")

    def refresh(self):
        if not hasattr(self, "sleep_table"):
            return
        self.day.setMaximumDate(QDate.currentDate())
        day = self.current_day()
        s = self.app.summary(day)
        self.exercise_total.setText("当天运动 · " + duration(s["totals"]["exercise"]))
        manual = self.app.store.exercise_records(day)
        sessions = self.app.store.session_records(day)
        self.exercise_rows = [{**r, "source": "exercise"} for r in manual] + [{**r, "source": "sessions"} for r in sessions if r["kind"] == "exercise"]
        fill_table(self.exercise_table, [(r["title"], duration(r["minutes"]), "手动记录" if r["source"] == "exercise" else "计时记录") for r in self.exercise_rows])
        self.sleep_row = s["sleep"]
        if self.sleep_row:
            start = datetime.fromisoformat(self.sleep_row["start"])
            end = datetime.fromisoformat(self.sleep_row["end"])
            self.sleep_amount.setText(duration(s["totals"]["sleep"]))
            self.sleep_detail.setText(f"目标 {duration(s['goals']['sleep'])} · {'睡眠时长已达标' if s['achieved']['sleep'] else '睡眠时长未达目标'}")
            wake_plan = datetime.combine(day, time.fromisoformat(s["plan"]["wake_time"]))
            bedtime_plan = wake_plan - timedelta(minutes=sleep_goal_minutes(s["plan"]))
            bed_delta = round((start - bedtime_plan).total_seconds() / 60)
            wake_delta = round((end - wake_plan).total_seconds() / 60)
            fmt = lambda n: "准时" if n == 0 else f"{'晚' if n > 0 else '早'} {abs(n)} 分钟"
            self.sleep_deviation.setText(f"与计划相比 · 入睡{fmt(bed_delta)} · 起床{fmt(wake_delta)}")
            fill_table(self.sleep_table, [(f"{start:%m/%d %H:%M}", f"{end:%m/%d %H:%M}", duration(s["totals"]["sleep"]))])
        else:
            self.sleep_amount.setText("未记录睡眠")
            self.sleep_detail.setText(f"入睡参考 {s['plan'].get('sleep_bedtime', s['plan']['bedtime'])} · 起床 {s['plan']['wake_time']} · 目标 {duration(s['goals']['sleep'])}")
            self.sleep_deviation.setText("补录实际时间后，即可查看时长与作息偏差。")
            self.sleep_table.setRowCount(0)
        sleeping = self.app.store.get_meta("sleep_started")
        self.sleep_pending.setText(f"已于 {datetime.fromisoformat(sleeping):%m/%d %H:%M} 确认准备睡觉，醒来后点击「已经起床」。" if sleeping else "")
        self.bed_button.setEnabled(not bool(sleeping))
        self.study_total.setText("当天学习 · " + duration(s["totals"]["study"]))
        self.study_rows = [{**r, "source": "manual_study", "state": "finished"} for r in self.app.store.study_records(day)]
        self.study_rows += [{**r, "source": "sessions"} for r in sessions if r["kind"] == "study"]
        states = {"running": "计时中", "paused": "已暂停", "finished": "已保存"}
        fill_table(self.study_table, [(r["title"], duration(r["minutes"]), "手动补记" if r["source"] == "manual_study" else "专注计时", states.get(r["state"], r["state"])) for r in self.study_rows])
        states = {"pending": "待提醒", "shown": "已展示，待处理", "snoozed": "延后十分钟", "started": "已开始", "skipped": "今日跳过", "expired": "已过期", "fulfilled": "目标已完成"}
        fill_table(self.reminder_table, [(KINDS[r["kind"]], datetime.fromisoformat(r["scheduled"]).strftime("%H:%M"), datetime.fromisoformat(r["due"]).strftime("%m/%d %H:%M"), states.get(r["state"], r["state"])) for r in self.app.store.reminder_history(day)])
        self.update_timer()


def app_callback(app, name):
    return lambda: getattr(app, name)()


class StatsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        top = QHBoxLayout()
        top.addWidget(label("一点点积累，看得见的变化", "section"), 1)
        self.range = QComboBox()
        self.range.addItem("最近 7 天", 7)
        self.range.addItem("最近 30 天", 30)
        self.range.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.range)
        top.addWidget(button("导出 CSV", self.export))
        layout.addLayout(top)
        boxes = QHBoxLayout()
        self.metrics = {}
        for kind, text in (("study", "学习达标"), ("exercise", "运动达标"), ("sleep", "睡眠达标")):
            box = panel()
            column = QVBoxLayout(box)
            column.setContentsMargins(20, 18, 20, 18)
            column.addWidget(label(text, "muted"))
            amount = label("0 天", "metric")
            amount.setStyleSheet(f"color: {COLORS[kind]};")
            column.addWidget(amount)
            self.metrics[kind] = amount
            boxes.addWidget(box, 1)
        layout.addLayout(boxes)
        chart_box = panel()
        chart = QVBoxLayout(chart_box)
        chart.setContentsMargins(20, 18, 20, 18)
        heading = QHBoxLayout()
        heading.addWidget(label("每日目标完成比例", "section"), 1)
        for kind, text in (("study", "学习"), ("exercise", "运动"), ("sleep", "睡眠")):
            key = label("● " + text, "muted")
            key.setStyleSheet(f"color: {COLORS[kind]};")
            heading.addWidget(key)
        chart.addLayout(heading)
        self.chart = TrendChart()
        chart.addWidget(self.chart)
        chart.addWidget(label("缺失的睡眠记录保留为空白；曲线最高显示 120%，原始时长完整保留。", "muted", True))
        layout.addWidget(chart_box)
        self.history = table(["日期", "学习 / 目标", "运动 / 目标", "睡眠 / 目标", "达标项"])
        layout.addWidget(self.history)
        self.note = label("", "muted", True)
        layout.addWidget(self.note)
        layout.addStretch()

    def refresh(self):
        if not hasattr(self, "history"):
            return
        days = self.range.currentData()
        data = [self.app.summary(date.today() - timedelta(days=i)) for i in reversed(range(days))]
        for kind in self.metrics:
            self.metrics[kind].setText(f"{sum(s['achieved'][kind] and s['has_plan'] for s in data)} 天")
        self.chart.set_data(data)
        fill_table(self.history, [(date.fromisoformat(s["day"]).strftime("%m/%d"), *[f"{duration(s['totals'][k])} / {duration(s['goals'][k])}" if s["has_plan"] else "尚未设置计划" for k in ("study", "exercise", "sleep")], f"{sum(s['achieved'].values())} / 3" if s["has_plan"] else "—") for s in reversed(data)])
        self.note.setText("每日使用当日保存的目标计算；计划修改不会重新计算已有日期的目标。")

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出最近记录", f"自律伴侣-{date.today()}.csv", "CSV 文件 (*.csv)")
        if path:
            self.app.timer.flush()
            self.app.store.export_csv(Path(path), date.today(), self.range.currentData())
            self.app.info("导出完成，可用 Excel 打开。")


class SettingsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        plans_box = panel()
        plans = QVBoxLayout(plans_box)
        plans.setContentsMargins(24, 22, 24, 22)
        heading = QHBoxLayout()
        heading.addWidget(label("你的每日计划", "section"), 1)
        heading.addWidget(button("编辑计划", app.edit_plan, primary=True))
        plans.addLayout(heading)
        self.plan_labels = {}
        for kind, text in (("weekday", "工作日 · 周一至周五"), ("weekend", "周末 · 周六与周日")):
            plans.addWidget(label(text, "cardTitle"))
            detail = label("", "muted", True)
            self.plan_labels[kind] = detail
            plans.addWidget(detail)
        plans.addWidget(label("已保存日期沿用原目标，计划修改从明天起生效。\n睡眠归入起床日，结合前一日的就寝计划计算目标。", "muted", True))
        layout.addWidget(plans_box)
        data_box = panel()
        data = QVBoxLayout(data_box)
        data.setContentsMargins(24, 22, 24, 22)
        data.setSpacing(12)
        data.addWidget(label("数据与备份", "section"))
        path = label(str(app.store.directory), "muted", True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        data.addWidget(path)
        actions = QHBoxLayout()
        actions.addWidget(button("备份数据", self.backup))
        actions.addWidget(button("恢复备份", self.restore))
        actions.addWidget(button("打开数据目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app.store.directory)))))
        actions.addStretch()
        data.addLayout(actions)
        data.addWidget(label("恢复前会自动保存当前数据的备份，方便找回。", "muted", True))
        layout.addWidget(data_box)
        about_box = panel()
        about = QVBoxLayout(about_box)
        about.setContentsMargins(24, 22, 24, 22)
        about.setSpacing(12)
        about.addWidget(label(f"自律伴侣 {VERSION}", "section"))
        about.addWidget(label("关闭窗口后仍在系统托盘运行；右键托盘图标可以彻底退出。\n提醒需要电脑开机且软件运行。电脑休眠时计时自动暂停。\n睡眠依照你确认或补录的实际时间统计。", "muted", True))
        action = QHBoxLayout()
        action.addWidget(button("使用说明", self.app.show_help))
        action.addWidget(button("彻底退出", self.app.quit_app))
        action.addStretch()
        about.addLayout(action)
        layout.addWidget(about_box)
        layout.addStretch()

    def refresh(self):
        for kind, plan in self.app.store.plans().items():
            self.plan_labels[kind].setText(f"学习 {duration(plan['study_minutes'])} · {plan['study_time']} 提醒\n运动 {duration(plan['exercise_minutes'])} · {plan['exercise_time']} 提醒\n{plan['bedtime']} 就寝 → {plan['wake_time']} 起床 · 睡眠目标 {duration(sleep_goal_minutes(plan))}")

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "备份全部数据", f"自律伴侣备份-{date.today()}.sqlite3", "数据库备份 (*.sqlite3)")
        if path:
            self.app.timer.flush()
            try:
                self.app.store.backup(Path(path))
                self.app.info("全部数据已备份。")
            except (ValueError, OSError) as exc:
                self.app.warn(str(exc))

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择数据备份", "", "数据库备份 (*.sqlite3)")
        if not path:
            return
        if QMessageBox.question(self, "恢复备份", "将使用备份中的数据替换当前数据。当前数据会自动另存备份。继续恢复？") != QMessageBox.StandardButton.Yes:
            return
        self.app.timer.pause("恢复备份前已暂停。")
        if self.app.reminder_dialog:
            self.app.reminder_dialog.reject()
        try:
            saved = self.app.store.restore(Path(path))
            self.app.timer.recover()
            self.app.store.ensure_history(date.today())
            self.app.refresh()
            self.app.info(f"恢复完成。原数据备份：\n{saved}")
        except Exception as exc:
            self.app.warn(f"无法恢复备份：{exc}")
