from __future__ import annotations

import time as clock
from datetime import date, datetime, time, timedelta

from .storage import REMINDER_FIELDS, Store


class FocusTimer:
    """Accrue measured active time only. Clock sources are injectable for boundary tests."""
    def __init__(self, store: Store, now=datetime.now, monotonic=clock.monotonic):
        self.store, self.now, self.monotonic = store, now, monotonic
        self.session = None
        self.pending: dict[str, float] = {}
        self.last_wall = self.now()
        self.last_tick = self.monotonic()
        self.last_flush = self.last_tick
        self.pause_reason = ""
        self.recovered = False
        self.recover()

    def recover(self):
        self.pending = {}
        self.session = self.store.active_session()
        self.recovered = bool(self.session)
        if self.session:
            self.session["state"] = "paused"
            self.store.set_session_state(self.session["id"], "paused", self.now())
        self._baseline()

    def _baseline(self):
        self.last_wall, self.last_tick = self.now(), self.monotonic()
        self.last_flush = self.last_tick

    @property
    def running(self):
        return self.session is not None and self.session["state"] == "running"

    @property
    def seconds(self):
        if not self.session:
            return 0.0
        return self.store.session_seconds(self.session["id"]) + sum(self.pending.values())

    def start(self, kind: str, title: str, minutes: int, task_id=None):
        if self.session:
            raise ValueError("已有一段计时，请先暂停或结束它。")
        if kind not in ("study", "exercise") or not 1 <= minutes <= 1440:
            raise ValueError("计时目标无效。")
        session_id = self.store.create_session(kind, title, minutes * 60, self.now(), task_id)
        self.session = {"id": session_id, "kind": kind, "title": title, "task_id": task_id, "state": "running", "target_seconds": minutes * 60}
        self.pending = {}
        self.pause_reason = ""
        self.recovered = False
        self._baseline()

    def tick(self) -> str | None:
        now, mono = self.now(), self.monotonic()
        elapsed = mono - self.last_tick
        wall_elapsed = (now - self.last_wall).total_seconds()
        event = None
        if self.running:
            if elapsed < 0 or elapsed > 15 or abs(wall_elapsed - elapsed) > 3:
                self.flush()
                self.session["state"] = "paused"
                self.store.set_session_state(self.session["id"], "paused", now)
                self.pause_reason = "检测到休眠、长时间挂起或时钟变化，计时已暂停。"
                event = "suspended"
            else:
                remaining = max(0, self.session["target_seconds"] - self.seconds)
                active = min(elapsed, remaining)
                # Proportionally split the measured interval at local midnight.
                start, end = self.last_wall, now
                if wall_elapsed > 0 and active > 0:
                    end = start + timedelta(seconds=wall_elapsed * active / elapsed) if elapsed else start
                    cursor = start
                    while cursor < end:
                        boundary = datetime.combine(cursor.date() + timedelta(days=1), time.min)
                        stop = min(boundary, end)
                        portion = active * (stop - cursor).total_seconds() / (end - start).total_seconds()
                        key = cursor.date().isoformat()
                        self.pending[key] = self.pending.get(key, 0) + portion
                        cursor = stop
                elif active > 0:
                    key = now.date().isoformat()
                    self.pending[key] = self.pending.get(key, 0) + active
                if mono - self.last_flush >= 5:
                    self.flush()
                    self.last_flush = mono
                if self.seconds >= self.session["target_seconds"] - 0.001:
                    self._finish()
                    event = "completed"
        self.last_wall, self.last_tick = now, mono
        return event

    def flush(self):
        if self.session and self.pending:
            self.store.add_segments(self.session["id"], self.pending)
            self.pending = {}

    def pause(self, reason=""):
        if self.running:
            self.tick()
            if self.session:
                self.flush()
                self.session["state"] = "paused"
                self.store.set_session_state(self.session["id"], "paused", self.now())
                self.pause_reason = reason

    def resume(self):
        if self.session:
            self.session["state"] = "running"
            self.store.set_session_state(self.session["id"], "running", self.now())
            self.pause_reason = ""
            self._baseline()

    def _finish(self):
        self.flush()
        if self.session:
            self.store.set_session_state(self.session["id"], "finished", self.now())
        self.session = None
        self.pending = {}

    def finish(self):
        if self.running:
            self.tick()
        self._finish()

    def pending_for(self, day: date, kind: str) -> float:
        return self.pending.get(day.isoformat(), 0) / 60 if self.session and self.session["kind"] == kind else 0


class ReminderService:
    def __init__(self, store: Store, now=datetime.now):
        self.store, self.now = store, now

    def due(self):
        now = self.now()
        if not self.store.get_meta("setup_complete", False):
            return []
        self.store.ensure_day(now.date())
        items = []
        for item in self.store.due_reminders(now):
            summary = self.store.summary(date.fromisoformat(item["day"]))
            kind = item["kind"]
            fulfilled = (kind in ("study", "exercise") and summary["achieved"][kind]) or (kind == "wake" and summary["sleep"] is not None)
            sleeping = self.store.get_meta("sleep_started")
            if kind == "bedtime" and sleeping:
                fulfilled = datetime.fromisoformat(sleeping).date().isoformat() == item["day"]
            if fulfilled:
                self.store.reminder_action(item["key"], "fulfilled", now)
            else:
                items.append(item)
        return items

    def next_text(self):
        now = self.now()
        if not self.store.get_meta("setup_complete", False):
            return "先设置你的每日计划"
        from .storage import KINDS
        pending = self.store.db.execute("SELECT * FROM reminders WHERE state IN ('pending','snoozed','shown') AND due>=? ORDER BY due LIMIT 1", (now.isoformat(),)).fetchone()
        if pending:
            at = datetime.fromisoformat(pending["due"])
            prefix = "明天 " if at.date() > now.date() else ""
            return f"{prefix}{at:%H:%M} · {KINDS[pending['kind']]}提醒"
        tomorrow = now.date() + timedelta(days=1)
        plan = self.store.plan_for(tomorrow)
        kind = min(REMINDER_FIELDS, key=lambda k: plan[REMINDER_FIELDS[k]])
        return f"明天 {plan[REMINDER_FIELDS[kind]]} · {KINDS[kind]}提醒"
