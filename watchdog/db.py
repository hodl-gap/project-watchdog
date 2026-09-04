from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
import os
import sqlite3
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    repo TEXT NOT NULL UNIQUE,
    stale_after_days INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    next_action TEXT,
    snoozed_until TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    report_date TEXT NOT NULL UNIQUE,
    message_id INTEGER,
    acknowledged_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_items (
    report_id INTEGER NOT NULL REFERENCES reports(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    days_idle INTEGER NOT NULL,
    hours_idle INTEGER NOT NULL DEFAULT 0,
    last_push TEXT,
    last_commit_message TEXT,
    needs_decision INTEGER NOT NULL,
    decision TEXT,
    PRIMARY KEY (report_id, project_id)
);
CREATE TABLE IF NOT EXISTS pending_tasks (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE,
    title TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    linked_repo TEXT,
    created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(report_items)")}
            if "last_commit_message" not in columns:
                conn.execute("ALTER TABLE report_items ADD COLUMN last_commit_message TEXT")
            if "hours_idle" not in columns:
                conn.execute("ALTER TABLE report_items ADD COLUMN hours_idle INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_project(self, repo: str, stale_days: int, next_action: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO projects(repo, stale_after_days, next_action, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(repo) DO UPDATE SET
                     stale_after_days=excluded.stale_after_days,
                     next_action=COALESCE(excluded.next_action, projects.next_action),
                     state='active'""",
                (repo, stale_days, next_action, datetime.now().isoformat()),
            )

    def projects(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute("SELECT * FROM projects ORDER BY repo"))

    def add_pending_task(self, title: str) -> str:
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT code FROM pending_tasks WHERE lower(title)=lower(?) AND state='pending'",
                (title,),
            ).fetchone()
            if existing:
                return existing["code"]
            cursor = conn.execute(
                "INSERT INTO pending_tasks(title, created_at) VALUES (?, ?)",
                (title, datetime.now().isoformat()),
            )
            code = f"P-{int(cursor.lastrowid):04d}"
            conn.execute("UPDATE pending_tasks SET code=? WHERE id=?", (code, cursor.lastrowid))
            return code

    def pending_tasks(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM pending_tasks WHERE state='pending' ORDER BY id"
                )
            )

    def pending_task(self, code: str):
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM pending_tasks WHERE upper(code)=upper(?)", (code,)
            ).fetchone()

    def mark_pending_linked(self, code: str, repo: str) -> None:
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE pending_tasks SET state='linked', linked_repo=?
                   WHERE upper(code)=upper(?) AND state='pending'""",
                (repo, code),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Pending task {code} was not found or is already linked")

    def active_projects(self, today: date) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(
                conn.execute(
                    """SELECT * FROM projects
                       WHERE state='active'
                         AND (snoozed_until IS NULL OR snoozed_until <= ?)
                       ORDER BY repo""",
                    (today.isoformat(),),
                )
            )

    def create_report(self, report_date: date, items: list[dict]) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO reports(report_date, created_at) VALUES (?, ?)",
                (report_date.isoformat(), datetime.now().isoformat()),
            )
            report_id = int(cursor.lastrowid)
            conn.executemany(
                """INSERT INTO report_items(
                       report_id, project_id, days_idle, hours_idle, last_push,
                       last_commit_message, needs_decision
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        report_id,
                        item["project_id"],
                        item["days_idle"],
                        item["hours_idle"],
                        item["last_push"],
                        item.get("last_commit_message"),
                        int(item["needs_decision"]),
                    )
                    for item in items
                ],
            )
            return report_id

    def replace_report_items(self, report_id: int, items: list[dict]) -> None:
        """Replace a report snapshot after an explicit manual refresh."""
        with self.connection() as conn:
            conn.execute("DELETE FROM report_items WHERE report_id=?", (report_id,))
            conn.executemany(
                """INSERT INTO report_items(
                       report_id, project_id, days_idle, hours_idle, last_push,
                       last_commit_message, needs_decision
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        report_id,
                        item["project_id"],
                        item["days_idle"],
                        item["hours_idle"],
                        item["last_push"],
                        item.get("last_commit_message"),
                        int(item["needs_decision"]),
                    )
                    for item in items
                ],
            )
            conn.execute("UPDATE reports SET acknowledged_at=NULL WHERE id=?", (report_id,))

    def report_for_date(self, report_date: date):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM reports WHERE report_date=?", (report_date.isoformat(),)).fetchone()

    def set_message_id(self, report_id: int, message_id: int) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE reports SET message_id=? WHERE id=?", (message_id, report_id))

    def report_items(self, report_id: int) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(
                conn.execute(
                    """SELECT i.*, p.repo, p.next_action, p.state, p.snoozed_until
                       FROM report_items i JOIN projects p ON p.id=i.project_id
                       WHERE i.report_id=? ORDER BY i.days_idle DESC, p.repo""",
                    (report_id,),
                )
            )

    def decide(self, report_id: int, project_id: int, decision: str, today: date | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE report_items SET decision=? WHERE report_id=? AND project_id=?",
                (decision, report_id, project_id),
            )
            if decision == "snooze3":
                reference_date = today or date.today()
                conn.execute(
                    "UPDATE projects SET snoozed_until=? WHERE id=?",
                    ((reference_date + timedelta(days=3)).isoformat(), project_id),
                )
            elif decision in {"paused", "archived"}:
                conn.execute("UPDATE projects SET state=? WHERE id=?", (decision, project_id))

    def acknowledge(self, report_id: int) -> bool:
        with self.connection() as conn:
            unresolved = conn.execute(
                """SELECT COUNT(*) FROM report_items
                   WHERE report_id=? AND needs_decision=1 AND decision IS NULL""",
                (report_id,),
            ).fetchone()[0]
            if unresolved:
                return False
            conn.execute(
                "UPDATE reports SET acknowledged_at=? WHERE id=?",
                (datetime.now().isoformat(), report_id),
            )
            return True

    def latest_unacknowledged(self):
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM reports WHERE acknowledged_at IS NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
