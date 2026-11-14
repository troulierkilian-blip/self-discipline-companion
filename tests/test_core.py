from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from companion.services import FocusTimer, ReminderService
from companion.storage import DEFAULT_PLANS, Store, sleep_goal_minutes


class FakeClock:
    def __init__(self, now):
        self.wall, self.mono = now, 0.0

    def now(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds, wall_seconds=None):
        self.wall += timedelta(seconds=seconds if wall_seconds is None else wall_seconds)
        self.mono += seconds


class CoreTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / "artifacts" / "core-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.now = datetime(2026, 10, 7, 8, 0)
        self.store.save_plans(DEFAULT_PLANS, self.now)
        self.clock = FakeClock(self.now)
        self.timer = FocusTimer(self.store, self.clock.now, self.clock.monotonic)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def advance(self, seconds):
        for _ in range(seconds):
            self.clock.advance(1)
            self.timer.tick()

    def test_weekday_weekend(self):
        self.assertEqual(self.store.plan_for(date(2026, 10, 9))["study_minutes"], 120)
        self.assertEqual(self.store.plan_for(date(2026, 10, 10))["study_minutes"], 90)

    def test_sleep_targets_follow_weekday_weekend_transition(self):
        self.store.ensure_history(date(2026, 10, 12))
        self.assertEqual(self.store.summary(date(2026, 10, 10))["goals"]["sleep"], 540)
        self.assertEqual(self.store.summary(date(2026, 10, 11))["goals"]["sleep"], 510)
        self.assertEqual(self.store.summary(date(2026, 10, 12))["goals"]["sleep"], 450)
        changed = {k: dict(v) for k, v in DEFAULT_PLANS.items()}
        changed["weekend"]["bedtime"] = "22:00"
        self.store.save_plans(changed, datetime(2026, 10, 12, 9))
        self.assertEqual(self.store.summary(date(2026, 10, 12))["goals"]["sleep"], 450)

    def test_snapshot_and_missed_dates_preserved_before_plan_change(self):
        changed = {k: dict(v) for k, v in DEFAULT_PLANS.items()}
        changed["weekday"]["study_minutes"] = 180
        self.store.save_plans(changed, datetime(2026, 10, 9, 12))
        for day in (7, 8, 9):
            self.assertEqual(self.store.summary(date(2026, 10, day))["goals"]["study"], 120)
        self.assertEqual(self.store.plan_for(date(2026, 10, 12))["study_minutes"], 180)

    def test_task_edit_complete_delete_keeps_time(self):
        task = self.store.add_task(self.now.date(), "读书")
        self.store.update_task(task, title="读两章", done=True)
        self.timer.start("study", "读书", 25, task)
        self.advance(6)
        self.timer.finish()
        self.store.delete_task(task)
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 0.1)
        self.assertIsNone(self.store.db.execute("SELECT task_id FROM sessions").fetchone()[0])

    def test_pause_resume_excludes_break(self):
        self.timer.start("study", "学习", 25)
        self.advance(12)
        self.timer.pause()
        self.advance(60)
        self.assertAlmostEqual(self.timer.seconds, 12)
        self.timer.resume()
        self.advance(8)
        self.timer.finish()
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 20 / 60)

    def test_midnight_split(self):
        self.clock.wall = datetime(2026, 10, 7, 23, 59, 58)
        self.timer.start("study", "跨午夜", 25)
        self.clock.advance(5)
        self.timer.tick()
        self.timer.finish()
        self.assertAlmostEqual(self.store.summary(date(2026, 10, 7))["totals"]["study"], 2 / 60)
        self.assertAlmostEqual(self.store.summary(date(2026, 10, 8))["totals"]["study"], 3 / 60)

    def test_sleep_gap_and_clock_change_pause(self):
        self.timer.start("study", "专注", 25)
        self.advance(5)
        self.clock.advance(300)
        self.assertEqual(self.timer.tick(), "suspended")
        self.assertFalse(self.timer.running)
        self.assertAlmostEqual(self.timer.seconds, 5)
        self.timer.resume()
        self.clock.advance(1, 3601)
        self.assertEqual(self.timer.tick(), "suspended")
        self.assertAlmostEqual(self.timer.seconds, 5)

    def test_recovery_never_counts_closed_time(self):
        self.timer.start("study", "恢复", 25)
        self.advance(7)
        self.timer.flush()
        self.clock.advance(600)
        recovered = FocusTimer(self.store, self.clock.now, self.clock.monotonic)
        self.assertTrue(recovered.recovered)
        self.assertFalse(recovered.running)
        self.assertAlmostEqual(recovered.seconds, 7)
        recovered.resume()
        self.clock.advance(2)
        recovered.tick()
        recovered.finish()
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 9 / 60)

    def test_target_completion_caps_at_target(self):
        self.timer.start("exercise", "拉伸", 1)
        self.advance(58)
        self.clock.advance(5)
        self.assertEqual(self.timer.tick(), "completed")
        self.assertIsNone(self.timer.session)
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["exercise"], 1)

    def test_manual_exercise_edit_delete(self):
        self.store.add_exercise(self.now.date(), "跑步", 20)
        row = self.store.exercise_records(self.now.date())[0]
        self.store.add_exercise(self.now.date(), "散步", 35, row["id"])
        self.assertTrue(self.store.summary(self.now.date())["achieved"]["exercise"])
        self.store.delete_record("exercise", row["id"])
        self.assertEqual(self.store.summary(self.now.date())["totals"]["exercise"], 0)

    def test_sleep_cross_midnight_missing_and_edit(self):
        day = self.now.date()
        self.assertIsNone(self.store.summary(day)["totals"]["sleep"])
        self.store.save_sleep(datetime(2026, 10, 6, 23), datetime(2026, 10, 7, 7))
        self.assertTrue(self.store.summary(day)["achieved"]["sleep"])
        self.assertEqual(self.store.summary(day)["totals"]["sleep"], 480)
        row = self.store.sleep_record(day)
        self.store.save_sleep(datetime(2026, 10, 7, 0), datetime(2026, 10, 7, 7), row["id"])
        self.assertFalse(self.store.summary(day)["achieved"]["sleep"])
        with self.assertRaises(ValueError):
            self.store.save_sleep(datetime(2026, 10, 6, 23), datetime(2026, 10, 7, 7))
        with self.assertRaises(ValueError):
            self.store.save_sleep(datetime(2026, 10, 7, 7), datetime(2026, 10, 7, 6))

    def test_active_session_cannot_be_edited(self):
        self.timer.start("exercise", "跑步", 25)
        self.advance(6)
        sid = self.timer.session["id"]
        with self.assertRaises(ValueError):
            self.store.update_session_record(sid, self.now.date(), "跑步", 100)
        self.timer.finish()
        self.store.update_session_record(sid, self.now.date(), "散步", 30)
        self.assertEqual(self.store.summary(self.now.date())["totals"]["exercise"], 30)

    def test_initial_setup_does_not_notify_past_events(self):
        self.assertEqual(self.store.due_reminders(self.now), [])

    def test_reminder_snooze_skip_and_no_duplicates(self):
        self.clock.wall = datetime(2026, 10, 7, 9)
        service = ReminderService(self.store, self.clock.now)
        items = service.due()
        self.assertEqual(len(items), 1)
        key = items[0]["key"]
        self.store.ensure_day(self.now.date())
        self.assertEqual(len(self.store.reminder_history(self.now.date())), 4)
        self.store.reminder_action(key, "snoozed", self.clock.now())
        self.assertEqual(service.due(), [])
        self.clock.advance(600)
        self.assertEqual(len(service.due()), 1)
        self.store.reminder_action(key, "skipped", self.clock.now())
        self.assertEqual(service.due(), [])

    def test_missed_reminders_are_returned_together(self):
        self.clock.wall = datetime(2026, 10, 7, 23, 30)
        items = ReminderService(self.store, self.clock.now).due()
        self.assertEqual({r["kind"] for r in items}, {"study", "exercise", "bedtime"})

    def test_achieved_exercise_suppresses_reminder(self):
        self.store.add_exercise(self.now.date(), "跑步", 35)
        self.clock.wall = datetime(2026, 10, 7, 18)
        items = ReminderService(self.store, self.clock.now).due()
        self.assertNotIn("exercise", [r["kind"] for r in items])

    def test_backup_restore_retains_previous_database(self):
        task = self.store.add_task(self.now.date(), "备份时的任务")
        backup = self.root / "backup.sqlite3"
        self.store.backup(backup)
        self.store.update_task(task, title="恢复前任务")
        previous = self.store.restore(backup)
        self.assertEqual(self.store.tasks(self.now.date())[0]["title"], "备份时的任务")
        with closing(sqlite3.connect(previous)) as old:
            self.assertEqual(old.execute("SELECT title FROM tasks").fetchone()[0], "恢复前任务")

    def test_invalid_backup_preserves_existing_data(self):
        self.store.add_task(self.now.date(), "保留")
        bad = self.root / "invalid.sqlite3"
        bad.write_bytes(b"not a sqlite database")
        with self.assertRaises(ValueError):
            self.store.restore(bad)
        self.assertEqual(self.store.tasks(self.now.date())[0]["title"], "保留")

    def test_csv_keeps_missing_sleep_blank_and_chinese(self):
        path = self.root / "report.csv"
        self.store.export_csv(path, self.now.date(), 1)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][0], "日期")
        self.assertEqual(rows[1][5], "")
        self.assertEqual(rows[1][-1], "未记录")

    def test_empty_task_and_invalid_plan_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_task(self.now.date(), "  ")
        plans = {k: dict(v) for k, v in DEFAULT_PLANS.items()}
        plans["weekday"]["bedtime"] = plans["weekday"]["wake_time"]
        with self.assertRaises(ValueError):
            self.store.save_plans(plans, self.now)

    def test_manual_study_merges_with_timed_minutes_and_keeps_task_incomplete(self):
        task = self.store.add_task(self.now.date(), "阅读")
        self.timer.start("study", "阅读", 25, task)
        self.advance(12)
        self.timer.finish()
        record_id = self.store.add_study_record(self.now.date(), "阅读补记", 30.5, task_id=task)
        self.assertEqual(self.store.study_records(self.now.date())[0]["id"], record_id)
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 30.7)
        self.assertFalse(self.store.tasks(self.now.date())[0]["done"])
        self.store.close()
        self.store = Store(self.root)
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 30.7)
        self.assertEqual(self.store.study_records(self.now.date())[0]["task_id"], task)

    def test_manual_study_edit_moves_date_and_delete_updates_both_days(self):
        day = self.now.date()
        past = day - timedelta(days=1)
        rid = self.store.add_study_record(day, "阅读", 30.5)
        self.store.add_study_record(past, "习题", 60.1, record_id=rid)
        self.assertEqual(self.store.summary(day)["totals"]["study"], 0)
        self.assertEqual(self.store.summary(past)["totals"]["study"], 60.1)
        self.assertEqual(self.store.study_records(past)[0]["title"], "习题")
        self.store.delete_record("manual_study", rid)
        self.assertEqual(self.store.summary(past)["totals"]["study"], 0)

    def test_supplement_does_not_pause_or_reset_active_timer(self):
        self.timer.start("study", "正在专注", 25)
        active_id = self.timer.session["id"]
        self.advance(12)
        self.store.add_study_record(self.now.date(), "之前的学习", 30.5)
        self.assertTrue(self.timer.running)
        self.assertEqual(self.timer.session["id"], active_id)
        self.assertEqual(self.timer.seconds, 12)
        self.advance(7)
        self.timer.flush()
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 30.5 + 19 / 60)

    def test_manual_study_achievement_suppresses_due_reminder(self):
        self.store.add_study_record(self.now.date(), "课程学习", 120)
        self.clock.wall = datetime(2026, 10, 7, 9)
        self.assertTrue(self.store.summary(self.now.date())["achieved"]["study"])
        self.assertEqual(ReminderService(self.store, self.clock.now).due(), [])
        row = next(r for r in self.store.reminder_history(self.now.date()) if r["kind"] == "study")
        self.assertEqual(row["state"], "fulfilled")

    def test_manual_study_keeps_saved_goal_snapshot(self):
        self.store.add_study_record(self.now.date(), "学习", 120)
        plans = {k: dict(v) for k, v in DEFAULT_PLANS.items()}
        plans["weekday"]["study_minutes"] = 240
        self.store.save_plans(plans, self.now)
        s = self.store.summary(self.now.date())
        self.assertEqual(s["goals"]["study"], 120)
        self.assertTrue(s["achieved"]["study"])

    def test_manual_study_bounds_and_invalid_input_do_not_insert(self):
        for minutes in (0, -1, 0.05, 1440.1, float("nan"), float("inf"), "invalid"):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                self.store.add_study_record(self.now.date(), "阅读", minutes)
        for title in ("  ", "x" * 201):
            with self.subTest(title=title), self.assertRaises(ValueError):
                self.store.add_study_record(self.now.date(), title, 30)
        with self.assertRaises(ValueError):
            self.store.add_study_record(date.today() + timedelta(days=1), "阅读", 30)
        self.assertEqual(self.store.study_records(self.now.date()), [])
        self.store.add_study_record(self.now.date(), "最短", 0.1)
        self.store.add_study_record(self.now.date(), "最长", 1440)
        self.assertEqual(self.store.summary(self.now.date())["totals"]["study"], 1440.1)

    def test_manual_study_task_date_validation_and_task_deletion(self):
        task = self.store.add_task(self.now.date(), "任务")
        with self.assertRaises(ValueError):
            self.store.add_study_record(self.now.date() - timedelta(days=1), "任务", 30, task_id=task)
        self.store.add_study_record(self.now.date(), "任务", 30, task_id=task)
        self.store.delete_task(task)
        self.assertIsNone(self.store.study_records(self.now.date())[0]["task_id"])
        self.assertEqual(self.store.summary(self.now.date())["totals"]["study"], 30)

    def test_manual_study_csv_matches_summary(self):
        self.store.add_study_record(self.now.date(), "阅读", 30.5)
        self.store.add_study_record(self.now.date(), "习题", 89.5)
        path = self.root / "manual-study.csv"
        self.store.export_csv(path, self.now.date(), 1)
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(float(rows[1][1]), 120)
        self.assertEqual(rows[1][-3], "是")

    def test_manual_study_backup_roundtrip_and_preserved_previous_data(self):
        rid = self.store.add_study_record(self.now.date(), "阅读", 30.5)
        path = self.root / "manual-study-backup.sqlite3"
        self.store.backup(path)
        self.store.add_study_record(self.now.date(), "调整", 70, record_id=rid)
        previous = self.store.restore(path)
        self.assertEqual(self.store.summary(self.now.date())["totals"]["study"], 30.5)
        with closing(sqlite3.connect(previous)) as old:
            self.assertEqual(old.execute("SELECT minutes FROM manual_study").fetchone()[0], 70)

    def test_old_database_upgrade_preserves_records(self):
        task = self.store.add_task(self.now.date(), "原任务")
        self.timer.start("study", "原计时", 25, task)
        self.advance(6)
        self.timer.finish()
        with self.store.db:
            self.store.db.execute("DROP TABLE manual_study")
        self.store.close()
        self.store = Store(self.root)
        self.assertEqual(self.store.study_records(self.now.date()), [])
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 0.1)
        self.assertEqual(self.store.tasks(self.now.date())[0]["title"], "原任务")
        self.store.add_study_record(self.now.date(), "补记", 10.5)
        self.assertAlmostEqual(self.store.summary(self.now.date())["totals"]["study"], 10.6)

    def test_old_backup_restores_without_manual_table(self):
        self.store.add_task(self.now.date(), "旧版任务")
        self.store.add_exercise(self.now.date(), "原运动", 20)
        self.store.save_sleep(datetime(2026, 10, 6, 23), datetime(2026, 10, 7, 7))
        with self.store.db:
            self.store.db.execute("DROP TABLE manual_study")
        old_backup = self.root / "v1.0-backup.sqlite3"
        self.store.backup(old_backup)
        self.store.close()
        self.store = Store(self.root)
        self.store.add_study_record(self.now.date(), "新版记录", 30.5)
        self.store.restore(old_backup)
        self.assertEqual(self.store.study_records(self.now.date()), [])
        self.assertEqual(self.store.summary(self.now.date())["totals"]["exercise"], 20)
        self.assertEqual(self.store.summary(self.now.date())["totals"]["sleep"], 480)
        self.assertEqual(self.store.tasks(self.now.date())[0]["title"], "旧版任务")


if __name__ == "__main__":
    unittest.main()
