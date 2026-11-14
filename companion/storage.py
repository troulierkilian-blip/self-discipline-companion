from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path

DEFAULT_PLANS = {
    "weekday": {"study_minutes": 120, "exercise_minutes": 30, "study_time": "09:00",
                "exercise_time": "18:00", "bedtime": "23:00", "wake_time": "07:00"},
    "weekend": {"study_minutes": 90, "exercise_minutes": 40, "study_time": "10:00",
                "exercise_time": "17:00", "bedtime": "23:30", "wake_time": "08:00"},
}
KINDS = {"study": "学习", "exercise": "运动", "bedtime": "就寝", "wake": "起床"}
REMINDER_FIELDS = {"study": "study_time", "exercise": "exercise_time", "bedtime": "bedtime", "wake": "wake_time"}


def sleep_goal_minutes(plan: dict) -> int:
    start = datetime.combine(date(2000, 1, 1), time.fromisoformat(plan.get("sleep_bedtime", plan["bedtime"])))
    end = datetime.combine(date(2000, 1, 1), time.fromisoformat(plan["wake_time"]))
    if end <= start:
        end += timedelta(days=1)
    return int((end - start).total_seconds() // 60)


def validate_plan(plan: dict) -> dict:
    result = {key: plan[key] for key in DEFAULT_PLANS["weekday"]}
    for key in ("study_minutes", "exercise_minutes"):
        if not isinstance(result[key], int) or not 1 <= result[key] <= 1440:
            raise ValueError("每日目标需为 1 至 1440 分钟。")
    for key in REMINDER_FIELDS.values():
        result[key] = time.fromisoformat(result[key]).strftime("%H:%M")
    if "sleep_bedtime" in plan:
        result["sleep_bedtime"] = time.fromisoformat(plan["sleep_bedtime"]).strftime("%H:%M")
    if result["bedtime"] == result["wake_time"]:
        raise ValueError("就寝与起床时间不能相同。")
    return result


class Store:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "companion.sqlite3"
        self._connect()

    def _connect(self):
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans (kind TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS daily_goals (day TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, title TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                target_seconds INTEGER NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL, ended TEXT);
            CREATE TABLE IF NOT EXISTS segments (
                session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
                day TEXT NOT NULL, seconds REAL NOT NULL, PRIMARY KEY(session_id, day));
            CREATE TABLE IF NOT EXISTS exercise (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, title TEXT NOT NULL,
                minutes REAL NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS manual_study (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, title TEXT NOT NULL,
                minutes REAL NOT NULL CHECK(minutes>=0.1 AND minutes<=1440),
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sleep (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE,
                start TEXT NOT NULL, end TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminders (
                key TEXT PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL,
                scheduled TEXT NOT NULL, due TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', acted TEXT);
        """)
        for kind, plan in DEFAULT_PLANS.items():
            self.db.execute("INSERT OR IGNORE INTO plans VALUES (?,?)", (kind, json.dumps(plan)))
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version','1')")
        self.db.commit()

    def close(self):
        self.db.close()

    def get_meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key: str, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def plans(self) -> dict:
        return {row["kind"]: json.loads(row["payload"]) for row in self.db.execute("SELECT * FROM plans")}

    def save_plans(self, plans: dict, now: datetime):
        validated = {kind: validate_plan(plans[kind]) for kind in DEFAULT_PLANS}
        initial = not self.get_meta("setup_complete", False)
        if not initial:
            self.ensure_history(now.date())
        with self.db:
            for kind, plan in validated.items():
                self.db.execute("UPDATE plans SET payload=? WHERE kind=?", (json.dumps(plan), kind))
            if not self.get_meta("setup_complete", False):
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('start_date',?)", (json.dumps(now.date().isoformat()),))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('setup_complete','true')")
        self.ensure_day(now.date())
        if initial:
            with self.db:
                self.db.execute("UPDATE reminders SET state='expired',acted=? WHERE day=? AND due<?", (now.isoformat(), now.date().isoformat(), now.isoformat()))

    def plan_for(self, day: date) -> dict:
        row = self.db.execute("SELECT payload FROM daily_goals WHERE day=?", (day.isoformat(),)).fetchone()
        if row:
            return json.loads(row[0])
        return self.plans()["weekend" if day.weekday() >= 5 else "weekday"]

    def ensure_day(self, day: date):
        if not self.get_meta("setup_complete", False):
            return
        key = day.isoformat()
        if self.db.execute("SELECT 1 FROM daily_goals WHERE day=?", (key,)).fetchone():
            return
        plan = dict(self.plan_for(day))
        # The night's bedtime belongs to the preceding day's schedule, while
        # wake-up belongs to this day. Freeze both at weekday/weekend transitions.
        plan["sleep_bedtime"] = self.plan_for(day - timedelta(days=1))["bedtime"]
        with self.db:
            self.db.execute("INSERT INTO daily_goals VALUES (?,?)", (key, json.dumps(plan)))
            for kind, field in REMINDER_FIELDS.items():
                at = datetime.combine(day, time.fromisoformat(plan[field])).isoformat()
                self.db.execute("INSERT OR IGNORE INTO reminders VALUES (?,?,?,?,?,'pending',NULL)",
                                (f"{key}:{kind}", key, kind, at, at))

    def ensure_history(self, today: date):
        first = date.fromisoformat(self.get_meta("start_date", today.isoformat()))
        # Bound catch-up after a very long absence; statistics need at most 30 days.
        first = max(first, today - timedelta(days=30))
        while first <= today:
            self.ensure_day(first)
            first += timedelta(days=1)

    def add_task(self, day: date, title: str) -> int:
        title = title.strip()
        if not title or len(title) > 200:
            raise ValueError("任务名称需为 1 至 200 个字符。")
        with self.db:
            return self.db.execute("INSERT INTO tasks(day,title,created) VALUES (?,?,?)",
                                   (day.isoformat(), title, datetime.now().isoformat())).lastrowid

    def tasks(self, day: date):
        return [dict(row) for row in self.db.execute("SELECT * FROM tasks WHERE day=? ORDER BY done,id", (day.isoformat(),))]

    def update_task(self, task_id: int, title: str | None = None, done: bool | None = None):
        with self.db:
            if title is not None:
                if not title.strip() or len(title.strip()) > 200:
                    raise ValueError("任务名称需为 1 至 200 个字符。")
                self.db.execute("UPDATE tasks SET title=? WHERE id=?", (title.strip(), task_id))
            if done is not None:
                self.db.execute("UPDATE tasks SET done=? WHERE id=?", (int(done), task_id))

    def delete_task(self, task_id: int):
        with self.db:
            self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def create_session(self, kind: str, title: str, target_seconds: int, now: datetime, task_id=None) -> int:
        with self.db:
            return self.db.execute("INSERT INTO sessions(kind,title,task_id,target_seconds,state,created) VALUES (?,?,?,?,'running',?)",
                                   (kind, title, task_id, target_seconds, now.isoformat())).lastrowid

    def add_segments(self, session_id: int, portions: dict[str, float]):
        with self.db:
            for day, seconds in portions.items():
                self.ensure_day(date.fromisoformat(day))
                self.db.execute("INSERT INTO segments VALUES (?,?,?) ON CONFLICT(session_id,day) DO UPDATE SET seconds=seconds+excluded.seconds",
                                (session_id, day, seconds))

    def session_seconds(self, session_id: int) -> float:
        return self.db.execute("SELECT COALESCE(SUM(seconds),0) FROM segments WHERE session_id=?", (session_id,)).fetchone()[0]

    def set_session_state(self, session_id: int, state: str, now: datetime):
        with self.db:
            self.db.execute("UPDATE sessions SET state=?,ended=? WHERE id=?",
                            (state, now.isoformat() if state == "finished" else None, session_id))

    def active_session(self):
        row = self.db.execute("SELECT * FROM sessions WHERE state IN ('running','paused') ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def session_records(self, day: date):
        return [dict(row) for row in self.db.execute("""
            SELECT s.id,s.kind,s.title,s.state,g.seconds/60 AS minutes
            FROM sessions s JOIN segments g ON g.session_id=s.id WHERE g.day=? ORDER BY s.id DESC
        """, (day.isoformat(),))]

    def update_session_record(self, session_id: int, day: date, title: str, minutes: float):
        if not title.strip() or not 0 < minutes <= 1440:
            raise ValueError("请填写名称和有效时长。")
        row = self.db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row or row[0] != "finished":
            raise ValueError("请先结束计时，再编辑它的记录。")
        with self.db:
            self.db.execute("UPDATE sessions SET title=? WHERE id=?", (title.strip(), session_id))
            self.db.execute("UPDATE segments SET seconds=? WHERE session_id=? AND day=?", (minutes * 60, session_id, day.isoformat()))

    def add_exercise(self, day: date, title: str, minutes: float, record_id=None):
        if not title.strip() or not 0 < minutes <= 1440:
            raise ValueError("请填写运动类型，以及 0 至 1440 分钟之间的时长。")
        self.ensure_day(day)
        with self.db:
            if record_id is None:
                self.db.execute("INSERT INTO exercise(day,title,minutes,created) VALUES (?,?,?,?)",
                                (day.isoformat(), title.strip(), minutes, datetime.now().isoformat()))
            else:
                self.db.execute("UPDATE exercise SET day=?,title=?,minutes=? WHERE id=?", (day.isoformat(), title.strip(), minutes, record_id))

    def add_study_record(self, day: date, title: str, minutes: float, task_id=None, record_id=None) -> int:
        if not isinstance(day, date) or isinstance(day, datetime) or day > date.today():
            raise ValueError("请选择今天或过去的学习日期。")
        if not title.strip() or len(title.strip()) > 200:
            raise ValueError("学习名称需为 1 至 200 个字符。")
        try:
            minutes = float(minutes)
        except (ValueError, TypeError) as exc:
            raise ValueError("学习时长需为 0.1 至 1440 分钟。") from exc
        if not math.isfinite(minutes) or not 0.1 <= minutes <= 1440:
            raise ValueError("学习时长需为 0.1 至 1440 分钟。")
        minutes = round(minutes, 1)
        if task_id is not None:
            task = self.db.execute("SELECT day FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["day"] != day.isoformat():
                raise ValueError("关联的学习任务须属于所选日期。")
        if record_id is not None and not self.db.execute("SELECT 1 FROM manual_study WHERE id=?", (record_id,)).fetchone():
            raise ValueError("这条学习记录已不存在，请刷新后重试。")
        self.ensure_day(day)
        with self.db:
            if record_id is None:
                return self.db.execute("INSERT INTO manual_study(day,title,minutes,task_id,created) VALUES (?,?,?,?,?)",
                                       (day.isoformat(), title.strip(), minutes, task_id, datetime.now().isoformat())).lastrowid
            self.db.execute("UPDATE manual_study SET day=?,title=?,minutes=?,task_id=? WHERE id=?",
                            (day.isoformat(), title.strip(), minutes, task_id, record_id))
        return record_id

    def study_records(self, day: date):
        return [dict(row) for row in self.db.execute("SELECT * FROM manual_study WHERE day=? ORDER BY id DESC", (day.isoformat(),))]

    def exercise_records(self, day: date):
        return [dict(row) for row in self.db.execute("SELECT * FROM exercise WHERE day=? ORDER BY id DESC", (day.isoformat(),))]

    def save_sleep(self, start: datetime, end: datetime, record_id=None):
        seconds = (end - start).total_seconds()
        if not 0 < seconds <= 24 * 3600:
            raise ValueError("起床时间须晚于入睡时间，单次睡眠最长为 24 小时。")
        self.ensure_day(end.date())
        existing = self.db.execute("SELECT id FROM sleep WHERE day=?", (end.date().isoformat(),)).fetchone()
        if existing and existing[0] != record_id:
            raise ValueError("该起床日期已有睡眠记录，请编辑已有记录。")
        with self.db:
            if record_id is None:
                self.db.execute("INSERT INTO sleep(day,start,end) VALUES (?,?,?)", (end.date().isoformat(), start.isoformat(), end.isoformat()))
            else:
                self.db.execute("UPDATE sleep SET day=?,start=?,end=? WHERE id=?", (end.date().isoformat(), start.isoformat(), end.isoformat(), record_id))

    def sleep_record(self, day: date):
        row = self.db.execute("SELECT * FROM sleep WHERE day=?", (day.isoformat(),)).fetchone()
        return dict(row) if row else None

    def delete_record(self, table: str, record_id: int):
        if table not in ("exercise", "sleep", "sessions", "manual_study"):
            raise ValueError("未知记录类型。")
        with self.db:
            self.db.execute(f"DELETE FROM {table} WHERE id=?", (record_id,))

    def summary(self, day: date) -> dict:
        key = day.isoformat()
        plan = self.plan_for(day)
        totals = {"study": 0.0, "exercise": 0.0}
        for row in self.db.execute("SELECT s.kind,SUM(g.seconds)/60 FROM segments g JOIN sessions s ON s.id=g.session_id WHERE g.day=? GROUP BY s.kind", (key,)):
            totals[row[0]] = row[1]
        totals["exercise"] += self.db.execute("SELECT COALESCE(SUM(minutes),0) FROM exercise WHERE day=?", (key,)).fetchone()[0]
        totals["study"] += self.db.execute("SELECT COALESCE(SUM(minutes),0) FROM manual_study WHERE day=?", (key,)).fetchone()[0]
        sleep = self.sleep_record(day)
        sleep_minutes = (datetime.fromisoformat(sleep["end"]) - datetime.fromisoformat(sleep["start"])).total_seconds() / 60 if sleep else None
        goals = {"study": plan["study_minutes"], "exercise": plan["exercise_minutes"], "sleep": sleep_goal_minutes(plan)}
        totals["sleep"] = sleep_minutes
        achieved = {kind: totals[kind] is not None and totals[kind] + 0.01 >= goals[kind] for kind in goals}
        return {"day": key, "plan": plan, "totals": totals, "goals": goals, "achieved": achieved, "sleep": sleep,
                "has_plan": bool(self.db.execute("SELECT 1 FROM daily_goals WHERE day=?", (key,)).fetchone())}

    def due_reminders(self, now: datetime):
        cutoff = (now - timedelta(hours=24)).isoformat()
        with self.db:
            self.db.execute("UPDATE reminders SET state='expired',acted=? WHERE state IN ('pending','shown','snoozed') AND due<?", (now.isoformat(), cutoff))
        return [dict(row) for row in self.db.execute("SELECT * FROM reminders WHERE state IN ('pending','shown','snoozed') AND due<=? AND due>=? ORDER BY due", (now.isoformat(), cutoff))]

    def reminder_action(self, key: str, action: str, now: datetime):
        with self.db:
            if action == "snoozed":
                self.db.execute("UPDATE reminders SET state=?,due=?,acted=? WHERE key=?", (action, (now + timedelta(minutes=10)).isoformat(), now.isoformat(), key))
            else:
                self.db.execute("UPDATE reminders SET state=?,acted=? WHERE key=?", (action, now.isoformat(), key))

    def reminder_history(self, day: date):
        return [dict(row) for row in self.db.execute("SELECT * FROM reminders WHERE day=? ORDER BY scheduled", (day.isoformat(),))]

    def export_csv(self, path: Path, end: date, days: int):
        with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["日期", "学习分钟", "学习目标分钟", "运动分钟", "运动目标分钟", "睡眠分钟", "睡眠目标分钟", "入睡时间", "起床时间", "学习达标", "运动达标", "睡眠达标"])
            for offset in reversed(range(days)):
                s = self.summary(end - timedelta(days=offset))
                sl = s["sleep"] or {}
                writer.writerow([s["day"], round(s["totals"]["study"], 2), s["goals"]["study"], round(s["totals"]["exercise"], 2), s["goals"]["exercise"],
                                 round(s["totals"]["sleep"], 2) if s["totals"]["sleep"] is not None else "", s["goals"]["sleep"], sl.get("start", ""), sl.get("end", ""),
                                 *["是" if s["achieved"][k] else ("未记录" if k == "sleep" and not sl else "否") for k in ("study", "exercise", "sleep")]])

    def backup(self, path: Path):
        if Path(path).resolve() == self.path.resolve():
            raise ValueError("请选择另一个文件作为备份。")
        with closing(sqlite3.connect(path)) as target:
            self.db.backup(target)

    def restore(self, path: Path) -> Path:
        source = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        staged = self.directory / "restore-staged.sqlite3"
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("备份文件校验失败。")
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"meta", "plans", "daily_goals", "tasks", "sessions", "segments", "exercise", "sleep", "reminders"}.issubset(tables):
                raise ValueError("这不是自律伴侣的数据备份。")
            # manual_study is additive: older v1.0 backups legitimately omit it.
            # _connect creates the missing table after restoring an old backup.
            if "manual_study" in tables:
                source.execute("SELECT id,day,title,minutes,task_id,created FROM manual_study LIMIT 0")
            version = source.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if not version or json.loads(version[0]) != 1:
                raise ValueError("备份版本不兼容。")
            plans = {r[0]: validate_plan(json.loads(r[1])) for r in source.execute("SELECT * FROM plans")}
            if set(plans) != set(DEFAULT_PLANS):
                raise ValueError("备份缺少每日计划。")
            for row in source.execute("SELECT payload FROM daily_goals"):
                validate_plan(json.loads(row[0]))
            with closing(sqlite3.connect(staged)) as target:
                source.backup(target)
        except (sqlite3.DatabaseError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("备份格式无效或文件已损坏。") from exc
        finally:
            source.close()
        previous = self.directory / f"恢复前备份-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
        self.backup(previous)
        self.close()
        try:
            os.replace(staged, self.path)
        finally:
            self._connect()
        return previous
