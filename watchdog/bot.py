from __future__ import annotations

from datetime import datetime
import logging
import re

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

from .config import Config
from .db import Store
from .github import GitHub, GitHubError
from .service import Watchdog


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # Telegram URLs contain the bot token.
LOG = logging.getLogger(__name__)


class BotApp:
    def __init__(self, config: Config):
        self.config = config
        self.store = Store(config.database_path)
        self.github = GitHub(config.github_token, config.github_owner, config.github_owner_type, config.template_repo)
        self.watchdog = Watchdog(self.store, self.github)

    def authorized(self, update: Update) -> bool:
        return bool(update.effective_chat and update.effective_chat.id == self.config.chat_id)

    def with_header(self, text: str) -> str:
        try:
            with open(self.config.alarm_header_path, encoding="utf-8") as file:
                header = file.read().strip()
        except FileNotFoundError:
            header = ""
        return f"{header}\n\n{text}" if header else text

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            return
        await update.message.reply_text(
            "Project Watchdog is running.\n\n"
            "/add owner/repo [stale-days] [| next action]\n"
            "/new repo-name [| description]\n"
            "/list\n/report"
        )

    async def add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            return
        raw = " ".join(context.args)
        left, _, next_action = raw.partition("|")
        parts = left.split()
        if not parts or "/" not in parts[0]:
            await update.message.reply_text("Usage: /add owner/repo [stale-days] [| next action]")
            return
        repo = parts[0]
        try:
            stale_days = int(parts[1]) if len(parts) > 1 else self.config.default_stale_days
            if stale_days < 1:
                raise ValueError("stale-days must be positive")
            self.github.repository(repo)
            self.store.add_project(repo, stale_days, next_action.strip() or None)
            await update.message.reply_text(f"Added {repo}; alarm after {stale_days} idle days.")
        except (GitHubError, ValueError) as error:
            await update.message.reply_text(f"Could not add project: {error}")

    async def new(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            return
        raw = " ".join(context.args)
        name, _, description = raw.partition("|")
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            await update.message.reply_text("Usage: /new repo-name [| short description]")
            return
        try:
            repo = self.github.create_repository(name, description.strip())
            self.store.add_project(repo["full_name"], self.config.default_stale_days, "Define the first next action")
            await update.message.reply_text(f"Created and registered {repo['html_url']}")
        except GitHubError as error:
            await update.message.reply_text(f"Could not create repository: {error}")

    async def list_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            return
        rows = self.store.projects()
        text = "No projects registered." if not rows else "\n".join(
            f"• {row['repo']} — {row['state']}, {row['stale_after_days']}d" for row in rows
        )
        await update.message.reply_text(text)

    async def send_report(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        local_today = datetime.now(self.config.timezone).date()
        existing = self.store.report_for_date(local_today)
        if existing:
            return
        try:
            stale, _healthy = self.watchdog.scan(local_today)
        except GitHubError as error:
            LOG.exception("GitHub scan failed")
            await context.bot.send_message(self.config.chat_id, f"⚠️ Project scan failed: {error}")
            return
        report_id = self.store.create_report(local_today, stale + _healthy)
        text, markup = self.watchdog.render(report_id, local_today.isoformat())
        message = await context.bot.send_message(
            self.config.chat_id, self.with_header(text), reply_markup=markup
        )
        self.store.set_message_id(report_id, message.message_id)

    async def report_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            return
        local_today = datetime.now(self.config.timezone).date()
        existing = self.store.report_for_date(local_today)
        try:
            stale, healthy = self.watchdog.scan(local_today)
        except GitHubError as error:
            await update.message.reply_text(f"⚠️ Project scan failed: {error}")
            return

        if existing:
            report_id = existing["id"]
            self.store.replace_report_items(report_id, stale + healthy)
            if existing["message_id"]:
                try:
                    await context.bot.delete_message(self.config.chat_id, existing["message_id"])
                except TelegramError:
                    pass
        else:
            report_id = self.store.create_report(local_today, stale + healthy)

        text, markup = self.watchdog.render(report_id, local_today.isoformat())
        message = await update.message.reply_text(self.with_header(text), reply_markup=markup)
        self.store.set_message_id(report_id, message.message_id)

    async def reminder(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        report = self.store.latest_unacknowledged()
        if report:
            await context.bot.send_message(
                self.config.chat_id,
                f"⏰ Your {report['report_date']} project review is still waiting for acknowledgement.",
            )

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update) or not update.callback_query:
            return
        query = update.callback_query
        data = query.data or ""
        if data.startswith("d:"):
            _, report_id, project_id, decision = data.split(":", 3)
            local_today = datetime.now(self.config.timezone).date()
            self.store.decide(int(report_id), int(project_id), decision, local_today)
            await query.answer()
            report_date = self._report_date(int(report_id))
            text, markup = self.watchdog.render(int(report_id), report_date)
            await query.edit_message_text(self.with_header(text), reply_markup=markup)
        elif data.startswith("ack:"):
            report_id = int(data.split(":", 1)[1])
            if not self.store.acknowledge(report_id):
                await query.answer("Choose an action for every flagged project first.", show_alert=True)
                return
            await query.answer("Report acknowledged.")
            report_date = self._report_date(report_id)
            text, _ = self.watchdog.render(report_id, report_date)
            await query.edit_message_text(self.with_header(text) + "\n\n✅ Acknowledged.")

    def _report_date(self, report_id: int) -> str:
        with self.store.connection() as conn:
            row = conn.execute("SELECT report_date FROM reports WHERE id=?", (report_id,)).fetchone()
            return row["report_date"]

    def build(self):
        application = ApplicationBuilder().token(self.config.telegram_token).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("add", self.add))
        application.add_handler(CommandHandler("new", self.new))
        application.add_handler(CommandHandler("list", self.list_projects))
        application.add_handler(CommandHandler("report", self.report_command))
        application.add_handler(CallbackQueryHandler(self.callback))

        job_queue = application.job_queue
        if job_queue is None:
            raise RuntimeError('Install the "job-queue" optional dependency')
        report_time = self.config.report_time.replace(tzinfo=self.config.timezone)
        job_queue.run_daily(self.send_report, report_time, name="daily-report")
        for reminder_time in self.config.reminder_times:
            scheduled = reminder_time.replace(tzinfo=self.config.timezone)
            job_queue.run_daily(self.reminder, scheduled, name=f"reminder-{reminder_time}")
        return application


def main() -> None:
    config = Config.from_env()
    BotApp(config).build().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
