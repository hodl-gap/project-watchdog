from __future__ import annotations

from datetime import date, datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .db import Store
from .github import GitHub


LAST_MESSAGE_LIMIT = 72


def _parse_github_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Watchdog:
    def __init__(self, store: Store, github: GitHub):
        self.store = store
        self.github = github

    def scan(self, today: date) -> tuple[list[dict], list[dict]]:
        stale, healthy = [], []
        now = datetime.now(timezone.utc)
        for project in self.store.active_projects(today):
            repo = self.github.repository(project["repo"])
            raw_pushed_at = repo.get("pushed_at")
            pushed_at = _parse_github_time(raw_pushed_at) if raw_pushed_at else None
            last_message = self.github.latest_commit_message(project["repo"])
            if pushed_at and last_message:
                idle_seconds = max(0, int((now - pushed_at).total_seconds()))
                hours_idle = idle_seconds // 3600
                days_idle = idle_seconds // 86400
                needs_decision = idle_seconds >= project["stale_after_days"] * 86400
            else:
                pushed_at = None
                hours_idle = 0
                days_idle = 0
                needs_decision = True
            item = {
                "project_id": project["id"],
                "repo": project["repo"],
                "days_idle": days_idle,
                "hours_idle": hours_idle,
                "last_push": pushed_at.isoformat() if pushed_at else None,
                "last_commit_message": last_message,
                "next_action": project["next_action"],
                "needs_decision": needs_decision,
            }
            (stale if needs_decision else healthy).append(item)
        return stale, healthy

    def render(self, report_id: int, report_date: str) -> tuple[str, InlineKeyboardMarkup]:
        items = self.store.report_items(report_id)
        pending = self.store.report_pending_items(report_id)
        stale = [item for item in items if item["needs_decision"]]
        healthy = [item for item in items if not item["needs_decision"]]
        lines = [f"Project check-in · {report_date}", ""]
        buttons = []
        if not stale and not pending:
            lines.append("✅ No projects need a decision today.")
        else:
            lines.append(f"{len(stale) + len(pending)} item(s) need a decision:")
            for number, item in enumerate(stale, start=1):
                mark = "✅" if item["decision"] else "🔴"
                lines.extend([
                    "",
                    f"#{number} {mark} {item['repo']} — {self._age(item)}",
                    f"Next: {item['next_action'] or 'not defined'}",
                    f"Last: {self._truncate(item['last_commit_message']) if item['last_commit_message'] else 'No commits yet'}",
                    f"Decision: {item['decision'] or 'pending'}",
                ])
                if not item["decision"]:
                    prefix = f"d:{report_id}:{item['project_id']}:"
                    buttons.append([
                        InlineKeyboardButton(f"Work today (#{number})", callback_data=prefix + "today"),
                        InlineKeyboardButton(f"Snooze 3d (#{number})", callback_data=prefix + "snooze3"),
                    ])
            for number, item in enumerate(pending, start=len(stale) + 1):
                mark = "✅" if item["decision"] else "🔴"
                lines.extend([
                    "",
                    f"#{number} {mark} {item['code']} — {item['title']}",
                    "Repo: not attached",
                    f"Decision: {item['decision'] or 'pending'}",
                ])
                if not item["decision"]:
                    prefix = f"p:{report_id}:{item['pending_task_id']}:"
                    buttons.append([
                        InlineKeyboardButton(f"Work today (#{number})", callback_data=prefix + "today"),
                        InlineKeyboardButton(f"Snooze 3d (#{number})", callback_data=prefix + "snooze3"),
                    ])
        if healthy:
            lines.extend(["", "Healthy:"])
            lines.extend(f"🟢 {item['repo']} — {self._age(item)}" for item in healthy)
        buttons.append([InlineKeyboardButton("Acknowledge report", callback_data=f"ack:{report_id}")])
        return "\n".join(lines), InlineKeyboardMarkup(buttons)

    @staticmethod
    def _truncate(value: str) -> str:
        if len(value) <= LAST_MESSAGE_LIMIT:
            return value
        return value[: LAST_MESSAGE_LIMIT - 1].rstrip() + "…"

    @staticmethod
    def _age(item) -> str:
        if not item["last_push"]:
            return "no commits yet"
        hours = item["hours_idle"]
        return f"last commit {hours} hr{'s' if hours != 1 else ''} ago"
