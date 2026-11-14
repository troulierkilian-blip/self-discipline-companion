from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .dialogs import ExerciseDialog, PlanDialog, ReminderDialog, SleepDialog, StudyDialog
from .storage import DEFAULT_PLANS
from .widgets import duration


def run_ui_checks(window, output: Path):
    """Exercise real Qt widgets and slots in an isolated database, then render every page."""
    output.mkdir(parents=True, exist_ok=True)
    window.heartbeat.stop()
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    store = window.store
    today = date.today()
    setup = PlanDialog(store, window, initial=True)
    check("首次设置须确认个人目标", not setup.save_button.isEnabled())
    setup.confirm.setChecked(True)
    setup.save_button.click()
    check("两套计划保存", store.get_meta("setup_complete") and setup.result() == QDialog.DialogCode.Accepted)
    title = "阅读《深度学习》第二章"
    task = store.add_task(today, title)
    store.add_task(today, "完成今天的练习与复盘")
    window.refresh()
    focus = window.pages[1]
    check("任务进入专注选择器", focus.task_combo.findData(task) >= 0)
    focus.task_combo.setCurrentIndex(focus.task_combo.findData(task))
    focus.start.click()
    check("学习按钮启动计时", window.timer.running and window.timer.session["task_id"] == task)
    focus.pause.click()
    check("暂停按钮有效", not window.timer.running)
    focus.pause.click()
    check("继续按钮有效", window.timer.running)
    active_id = window.timer.session["id"]

    def save_focus_supplement(dialog):
        check("补记预选当前任务", dialog.task.currentData() == task)
        dialog.minutes.setValue(20.5)
        dialog.save_button.click()
        dialog.save()  # A queued second click must not create a second row.
        return dialog.result()

    with patch("companion.window.StudyDialog.exec", save_focus_supplement):
        focus.supplement.click()
    check("专注页补记按钮保存一条记录", len(store.study_records(today)) == 1 and store.study_records(today)[0]["minutes"] == 20.5)
    check("补记时计时继续且任务状态不变", window.timer.running and window.timer.session["id"] == active_id and not next(t for t in store.tasks(today) if t["id"] == task)["done"])
    focus.stop.click()
    check("结束按钮保存计时", window.timer.session is None)
    focus.task_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    check("任务完成勾选持久化", any(t["id"] == task and t["done"] for t in store.tasks(today)))
    ex = ExerciseDialog(store, today, window)
    ex.title.setText("户外散步")
    ex.minutes.setValue(35)
    ex.save()
    check("运动补记弹窗保存", store.summary(today)["totals"]["exercise"] >= 35)
    row = store.exercise_records(today)[0]
    edit = ExerciseDialog(store, today, window, row)
    edit.minutes.setValue(40)
    edit.save()
    check("运动编辑弹窗保存", store.exercise_records(today)[0]["minutes"] == 40)
    yesterday = today - timedelta(days=1)
    record_page = window.pages[2]
    window.navigate(2)
    record_page.tabs.setCurrentIndex(2)
    record_page.day.setDate(yesterday)

    def save_past_supplement(dialog):
        check("记录页默认补录查看日期", dialog.day.date().toPython() == yesterday)
        dialog.task.setEditText("昨日复盘")
        dialog.minutes.setValue(10.1)
        dialog.save_button.click()
        return dialog.result()

    with patch("companion.window.StudyDialog.exec", save_past_supplement):
        record_page.study_add.click()
    check("历史日期补记保存", store.summary(yesterday)["totals"]["study"] == 10.1)
    check("学习表区分手动来源", record_page.study_table.item(0, 2).text() == "手动补记")
    record_page.study_table.selectRow(0)

    def edit_past_supplement(dialog):
        dialog.day.setDate(today)
        dialog.task.setEditText("复盘修正")
        dialog.minutes.setValue(10.5)
        dialog.save_button.click()
        return dialog.result()

    with patch("companion.window.StudyDialog.exec", edit_past_supplement):
        record_page.edit_study()
    check("编辑补记移动日期", store.summary(yesterday)["totals"]["study"] == 0 and record_page.current_day() == today)
    moved = next(i for i, r in enumerate(record_page.study_rows) if r["title"] == "复盘修正")
    record_page.study_table.selectRow(moved)
    with patch("companion.pages.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        record_page.delete_study()
    # Button tests may finish within the Windows monotonic clock's resolution;
    # a zero-duration session still exists even when it has no timed segments.
    check("删除手动记录保留专注记录", len(store.study_records(today)) == 1 and store.db.execute("SELECT COUNT(*) FROM sessions WHERE kind='study'").fetchone()[0] >= 1)
    invalid = StudyDialog(store, today, window)
    invalid.save_button.click()
    check("空名称报错后可继续填写", not invalid.saved and bool(invalid.error.text()) and invalid.save_button.isEnabled())
    check("学习补记限制未来日期", invalid.day.maximumDate().toPython() == today)
    invalid.reject()
    check("小数分钟显示准确", duration(20.5) == "20.5 分钟" and duration(70.5) == "1 小时 10.5 分")
    record_page.day.setDate(today)
    store.ensure_day(yesterday)
    sl = SleepDialog(store, yesterday, window)
    # Previous day's record is always in the past, regardless of test execution time.
    sl.begin.setDateTime(datetime.combine(yesterday - timedelta(days=1), datetime.strptime("23:00", "%H:%M").time()))
    sl.end.setDateTime(datetime.combine(yesterday, datetime.strptime("07:00", "%H:%M").time()))
    sl.save()
    check("跨午夜睡眠弹窗保存", store.summary(yesterday)["totals"]["sleep"] == 480)
    store.save_sleep(datetime.combine(today - timedelta(days=1), datetime.strptime("22:40", "%H:%M").time()), datetime.combine(today, datetime.strptime("07:00", "%H:%M").time()))
    sid = store.create_session("study", title, 1500, datetime.now(), task)
    store.add_segments(sid, {today.isoformat(): 4200})
    store.set_session_state(sid, "finished", datetime.now())
    window.refresh()
    check("学习合计包含补记与计时", abs(window.summary(today)["totals"]["study"] - store.summary(today)["totals"]["study"]) < 0.001 and window.summary(today)["totals"]["study"] >= 90.5)
    check("记录表同时显示两种来源", {record_page.study_table.item(i, 2).text() for i in range(record_page.study_table.rowCount())} == {"手动补记", "专注计时"})
    for i in range(1, 7):
        day = today - timedelta(days=i)
        store.ensure_day(day)
        sid = store.create_session("study", "学习记录", 120 * 60, datetime.now())
        store.add_segments(sid, {day.isoformat(): (65 + (i * 17) % 75) * 60})
        store.set_session_state(sid, "finished", datetime.now())
        store.add_exercise(day, "活动身体", 20 + i * 4)
        if not store.sleep_record(day):
            end = datetime.combine(day, datetime.strptime("07:00", "%H:%M").time())
            store.save_sleep(end - timedelta(minutes=410 + i * 10), end)
    record_page = window.pages[2]
    record_page.exercise_start.click()
    check("运动按钮启动计时", window.timer.session["kind"] == "exercise")
    record_page.exercise_pause.click()
    check("运动暂停有效", not window.timer.running)
    record_page.exercise_stop.click()
    check("运动结束有效", window.timer.session is None)
    sample = {"key": f"{today}:study", "day": str(today), "kind": "study", "scheduled": datetime.now().isoformat()}
    reminder = ReminderDialog(window)
    actions = []
    reminder.action.connect(lambda key, action: actions.append((key, action)))
    reminder.add_items([sample, sample])
    check("提醒弹窗去重", len(reminder.items) == 1)
    reminder.reject()
    check("关闭提醒会延后", actions == [(sample["key"], "snoozed")])
    export = output / "export.csv"
    store.export_csv(export, today, 7)
    check("CSV 导出可读", "睡眠目标分钟" in export.read_text(encoding="utf-8-sig"))
    backup = output / "backup.sqlite3"
    store.backup(backup)
    old = store.restore(backup)
    check("恢复保留原数据备份", old.exists() and len(store.tasks(today)) == 2)
    check("恢复保留学习补记与关联", store.study_records(today)[0]["minutes"] == 20.5 and store.study_records(today)[0]["task_id"] == task)
    window.timer.recover()
    window.refresh()
    screenshots = []
    for i, name in enumerate(("01-今日概览", "02-学习专注", "03-运动记录", "04-历史统计", "05-计划设置")):
        window.navigate(i)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        image = output / f"{name}.png"
        check(f"截图 {name}", window.grab().save(str(image)))
        if i == 0:
            from PySide6.QtGui import QFontMetrics
            metric = window.pages[0].cards["study"].amount
            check("小数学习时长完整显示", QFontMetrics(metric.font()).horizontalAdvance(metric.text()) <= metric.contentsRect().width())
        screenshots.append(str(image))
        page = window.pages[i]
        check(f"页面 {name} 无横向溢出", page.width() <= window.stack.width())
    window.open_records(1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    image = output / "06-睡眠记录.png"
    check("睡眠页面截图", window.grab().save(str(image)))
    screenshots.append(str(image))
    window.navigate(1)
    focus.minutes.setValue(25)
    focus.start.click()
    window.timer.pause()
    window.refresh()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    image = output / "07-暂停计时.png"
    check("暂停计时截图", window.grab().save(str(image)))
    screenshots.append(str(image))
    window.open_records(2)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    image = output / "08-学习补记记录.png"
    check("学习补记记录截图", window.grab().save(str(image)))
    screenshots.append(str(image))
    supplement = StudyDialog(store, today, window, task_id=task)
    supplement.minutes.setValue(30.5)
    supplement.show()
    QApplication.processEvents()
    image = output / "09-补记学习弹窗.png"
    check("学习补记弹窗截图", supplement.grab().save(str(image)))
    screenshots.append(str(image))
    supplement.reject()
    window.timer.finish()
    window.navigate(0)
    return {"passed": True, "checks": checks, "screenshots": screenshots, "window_size": [window.width(), window.height()], "device_pixel_ratio": window.devicePixelRatio()}
