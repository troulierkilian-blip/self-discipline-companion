from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QDateTime, QTime, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QDateTimeEdit, QDialog, QDoubleSpinBox,
                             QComboBox, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QSpinBox,
                             QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from .storage import KINDS, Store, sleep_goal_minutes
from .widgets import button, duration, label, panel


class PlanForm(QWidget):
    def __init__(self, plan):
        super().__init__()
        layout = QFormLayout(self)
        layout.setContentsMargins(20, 22, 20, 18)
        layout.setVerticalSpacing(16)
        self.fields = {}
        for key, text in (("study_minutes", "学习目标"), ("exercise_minutes", "运动目标")):
            field = QSpinBox()
            field.setRange(1, 1440)
            field.setSuffix(" 分钟 / 天")
            field.setValue(plan[key])
            self.fields[key] = field
            layout.addRow(text, field)
        for key, text in (("study_time", "学习提醒"), ("exercise_time", "运动提醒"), ("bedtime", "计划就寝"), ("wake_time", "计划起床")):
            field = QTimeEdit(QTime.fromString(plan[key], "HH:mm"))
            field.setDisplayFormat("HH:mm")
            self.fields[key] = field
            layout.addRow(text, field)
        self.summary = label("", "muted")
        layout.addRow("睡眠目标", self.summary)
        for key in ("bedtime", "wake_time"):
            self.fields[key].timeChanged.connect(self.update_summary)
        self.update_summary()

    def values(self):
        return {key: field.value() if isinstance(field, QSpinBox) else field.time().toString("HH:mm") for key, field in self.fields.items()}

    def update_summary(self):
        plan = self.values()
        self.summary.setText("就寝与起床时间需不同" if plan["bedtime"] == plan["wake_time"] else duration(sleep_goal_minutes(plan)))


class PlanDialog(QDialog):
    def __init__(self, store: Store, parent=None, initial=False):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("欢迎使用自律伴侣" if initial else "编辑每日计划")
        self.setMinimumWidth(490)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        layout.addWidget(label("从你的日常节奏开始" if initial else "安排你的每日节奏", "section"))
        layout.addWidget(label("下面是可修改的示例，请按自己的目标和作息填写。" if initial else "修改从明天起生效，已经记录的每日目标会保留。", "muted", True))
        tabs = QTabWidget()
        plans = store.plans()
        self.forms = {kind: PlanForm(plan) for kind, plan in plans.items()}
        tabs.addTab(self.forms["weekday"], "工作日 · 周一至周五")
        tabs.addTab(self.forms["weekend"], "周末 · 周六与周日")
        layout.addWidget(tabs)
        self.confirm = QCheckBox("我已按自己的情况确认目标和作息")
        self.confirm.setVisible(initial)
        layout.addWidget(self.confirm)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("稍后设置" if initial else "取消", self.reject))
        self.save_button = button("开始使用" if initial else "保存计划", self.save, primary=True, name="check")
        self.save_button.setEnabled(not initial)
        if initial:
            self.confirm.toggled.connect(self.save_button.setEnabled)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

    def save(self):
        try:
            self.store.save_plans({kind: form.values() for kind, form in self.forms.items()}, datetime.now())
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "检查计划", str(exc))
            return
        self.accept()


class StudyDialog(QDialog):
    def __init__(self, store: Store, day: date, parent=None, record=None, task_id=None):
        super().__init__(parent)
        self.store, self.record = store, record
        self.saved = False
        self.setWindowTitle("编辑学习补记" if record else "补记学习")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("记录你完成的学习", "section"))
        layout.addWidget(label("补记未被计时器记录的学习，保存后自动计入学习总时长。", "muted", True))
        form = QFormLayout()
        form.setVerticalSpacing(14)
        self.day = QDateEdit(QDate(day.year, day.month, day.day))
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("yyyy-MM-dd")
        self.day.setMaximumDate(QDate.currentDate())
        self.task = QComboBox()
        self.task.setEditable(True)
        self.task.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.task.lineEdit().setMaxLength(200)
        self.task.lineEdit().setPlaceholderText("选择当天的任务，或输入学习内容")
        self.minutes = QDoubleSpinBox()
        self.minutes.setDecimals(1)
        self.minutes.setRange(0.1, 1440)
        self.minutes.setSuffix(" 分钟")
        self.minutes.setValue(record["minutes"] if record else 30)
        form.addRow("学习日期", self.day)
        form.addRow("学习任务", self.task)
        form.addRow("实际时长", self.minutes)
        layout.addLayout(form)
        self.error = label("", "muted", True)
        self.error.setStyleSheet("color: #C74F5A;")
        layout.addWidget(self.error)
        layout.addWidget(label("关联任务的完成状态保持原样，可以在清单中自行勾选。", "muted", True))
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("取消", self.reject))
        self.save_button = button("保存并计入", self.save, primary=True, name="check")
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        initial_task = record.get("task_id") if record else task_id
        self.reload_tasks(initial_task, record["title"] if record else None)
        self.day.dateChanged.connect(lambda: self.reload_tasks())

    def reload_tasks(self, task_id=None, title=None):
        previous_text = self.task.currentText() if title is None else title
        previous_id = self.task.currentData() if task_id is None else task_id
        self.task.clear()
        for task in self.store.tasks(self.day.date().toPython()):
            self.task.addItem(task["title"], task["id"])
        index = self.task.findData(previous_id) if previous_id is not None else -1
        self.task.setCurrentIndex(index)
        if previous_text:
            self.task.setEditText(previous_text)
        elif index < 0:
            self.task.setEditText("")

    def save(self):
        if self.saved:
            return
        self.save_button.setEnabled(False)
        index = self.task.currentIndex()
        selected = self.task.currentData() if index >= 0 and self.task.currentText() == self.task.itemText(index) else None
        try:
            self.record_id = self.store.add_study_record(self.day.date().toPython(), self.task.currentText(), self.minutes.value(),
                                                        task_id=selected, record_id=self.record["id"] if self.record else None)
        except ValueError as exc:
            self.error.setText(str(exc))
            self.save_button.setEnabled(True)
            return
        self.saved = True
        self.accept()


class ExerciseDialog(QDialog):
    def __init__(self, store, day: date, parent=None, record=None, session=False):
        super().__init__(parent)
        self.store, self.record, self.session, self.original_day = store, record, session, day
        self.setWindowTitle("编辑运动记录" if record else "补记运动")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("记录你完成的运动", "section"))
        form = QFormLayout()
        form.setVerticalSpacing(14)
        self.day = QDateEdit(QDate(day.year, day.month, day.day))
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("yyyy-MM-dd")
        self.day.setMaximumDate(QDate.currentDate())
        self.day.setEnabled(not session)
        self.title = QLineEdit(record["title"] if record else "")
        self.title.setPlaceholderText("例如：散步、跑步、力量训练")
        self.title.setMaxLength(200)
        self.minutes = QDoubleSpinBox()
        self.minutes.setRange(0.1, 1440)
        self.minutes.setDecimals(1)
        self.minutes.setSuffix(" 分钟")
        self.minutes.setValue(record["minutes"] if record else 30)
        form.addRow("运动日期", self.day)
        form.addRow("运动类型", self.title)
        form.addRow("实际时长", self.minutes)
        layout.addLayout(form)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("取消", self.reject))
        actions.addWidget(button("保存记录", self.save, primary=True, name="check"))
        layout.addLayout(actions)

    def save(self):
        try:
            if self.session:
                self.store.update_session_record(self.record["id"], self.original_day, self.title.text(), self.minutes.value())
            else:
                self.store.add_exercise(self.day.date().toPython(), self.title.text(), self.minutes.value(), self.record["id"] if self.record else None)
        except ValueError as exc:
            QMessageBox.warning(self, "检查记录", str(exc))
            return
        self.accept()


class SleepDialog(QDialog):
    def __init__(self, store, day: date, parent=None, record=None, start=None):
        super().__init__(parent)
        self.store, self.record = store, record
        self.setWindowTitle("编辑睡眠记录" if record else "记录睡眠")
        self.setMinimumWidth(490)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("让睡眠也有迹可循", "section"))
        layout.addWidget(label("填写实际入睡、起床时间，记录归入起床当天。", "muted", True))
        plan = store.plan_for(day)
        end = datetime.combine(day, datetime.strptime(plan["wake_time"], "%H:%M").time())
        beginning = end - timedelta(minutes=sleep_goal_minutes(plan))
        if start:
            beginning, end = datetime.fromisoformat(start), datetime.now()
        if record:
            beginning, end = datetime.fromisoformat(record["start"]), datetime.fromisoformat(record["end"])
        self.begin = QDateTimeEdit(QDateTime(beginning))
        self.end = QDateTimeEdit(QDateTime(end))
        form = QFormLayout()
        form.setVerticalSpacing(14)
        for field, text in ((self.begin, "实际入睡"), (self.end, "实际起床")):
            field.setDisplayFormat("yyyy-MM-dd HH:mm")
            field.setCalendarPopup(True)
            field.setMaximumDateTime(QDateTime.currentDateTime())
            form.addRow(text, field)
        self.summary = label("", "muted")
        form.addRow("睡眠时长", self.summary)
        self.begin.dateTimeChanged.connect(self.update_summary)
        self.end.dateTimeChanged.connect(self.update_summary)
        layout.addLayout(form)
        self.update_summary()
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("取消", self.reject))
        actions.addWidget(button("保存睡眠", self.save, primary=True, name="check"))
        layout.addLayout(actions)

    def update_summary(self):
        delta = self.begin.dateTime().secsTo(self.end.dateTime())
        self.summary.setText(duration(delta / 60) if 0 < delta <= 86400 else "请检查入睡与起床时间")

    def save(self):
        try:
            self.store.save_sleep(self.begin.dateTime().toPython(), self.end.dateTime().toPython(), self.record["id"] if self.record else None)
        except ValueError as exc:
            QMessageBox.warning(self, "检查睡眠时间", str(exc))
            return
        self.accept()


class ReminderDialog(QDialog):
    action = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自律伴侣 · 每日提醒")
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(15)
        layout.addWidget(label("到你安排的时间了", "section"))
        layout.addWidget(label("选一个小行动，继续今天的节奏。错过的提醒会合并在这里。", "muted", True))
        self.rows = QVBoxLayout()
        layout.addLayout(self.rows)
        layout.addWidget(label("关闭此窗口会将未处理的提醒延后十分钟。", "muted"))
        self.items = {}

    def add_items(self, items):
        for item in items:
            key = item["key"]
            if key in self.items:
                continue
            row = panel()
            line = QHBoxLayout(row)
            line.setContentsMargins(14, 12, 14, 12)
            at = datetime.fromisoformat(item["scheduled"])
            line.addWidget(label(f"{KINDS[item['kind']]}\n{at:%m/%d %H:%M}", wrap=True), 1)
            for text, act, primary in (("开始", "started", True), ("稍后十分钟", "snoozed", False), ("今日跳过", "skipped", False)):
                line.addWidget(button(text, lambda checked=False, k=key, a=act: self.resolve(k, a), primary=primary))
            self.rows.addWidget(row)
            self.items[key] = (row, item)

    def resolve(self, key, action):
        if key not in self.items:
            return
        row, _ = self.items.pop(key)
        row.deleteLater()
        self.action.emit(key, action)
        if not self.items:
            self.accept()

    def reject(self):
        for key in list(self.items):
            self.resolve(key, "snoozed")
        super().reject()
