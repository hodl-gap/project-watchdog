from __future__ import annotations

from dataclasses import dataclass
from datetime import time
import os
from zoneinfo import ZoneInfo


def _clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    chat_id: int
    github_token: str
    github_owner: str
    github_owner_type: str
    template_repo: str | None
    timezone: ZoneInfo
    report_time: time
    reminder_times: tuple[time, ...]
    default_stale_days: int
    database_path: str
    alarm_header_path: str

    @classmethod
    def from_env(cls) -> "Config":
        required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN", "GITHUB_OWNER"]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

        reminders = tuple(
            _clock(value.strip())
            for value in os.getenv("REMINDER_TIMES", "15:00,20:00").split(",")
            if value.strip()
        )
        return cls(
            telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=int(os.environ["TELEGRAM_CHAT_ID"]),
            github_token=os.environ["GITHUB_TOKEN"],
            github_owner=os.environ["GITHUB_OWNER"],
            github_owner_type=os.getenv("GITHUB_OWNER_TYPE", "user"),
            template_repo=os.getenv("GITHUB_TEMPLATE_REPO") or None,
            timezone=ZoneInfo(os.getenv("TIMEZONE", "Asia/Seoul")),
            report_time=_clock(os.getenv("DAILY_REPORT_TIME", "10:30")),
            reminder_times=reminders,
            default_stale_days=int(os.getenv("DEFAULT_STALE_DAYS", "7")),
            database_path=os.getenv("DATABASE_PATH", "data/watchdog.sqlite3"),
            alarm_header_path=os.getenv("ALARM_HEADER_PATH", "alarm_header.txt"),
        )
