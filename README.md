# Project Watchdog

A private Telegram bot that watches selected GitHub repositories, sends one daily stale-project report, and requires an explicit decision for every flagged project before the report can be acknowledged.

## What is included

- `/add owner/repo 7 | next action` registers an existing repository.
- `/new repo-name | description` creates a private repository and registers it.
- `/report` runs today's report manually.
- Daily reports show every active repository and its latest commit age in hours.
- A repository with no commits is stale immediately, regardless of its creation time.
- Each repository shows linked ticket IDs under `Next` and a truncated latest commit subject under `Last`.
- Every stale project gets one compact decision row: **Work today (#N)** or **Snooze 3d (#N)**.
- The final acknowledgement is rejected while a project remains undecided.
- Unacknowledged reports trigger scheduled Telegram reminders.
- State and acknowledgement history are stored in SQLite.
- The contents of `alarm_header.txt`, when nonblank, are prepended to every report.

This is intentionally a skeleton. “Activity” currently means a push; PR, issue, and explicit progress-heartbeat activity can be added later.

## Credentials

You need:

1. A Telegram **bot token** from `@BotFather`.
2. Your numeric Telegram **chat ID**. Send the bot a message, then inspect the bot's `getUpdates` response, or use a trusted ID helper.
3. A GitHub token that can read the watched private repositories. To use `/new`, it must also be allowed to create repositories for the configured owner.

A Telegram user session is neither needed nor desired. `TELEGRAM_CHAT_ID` also acts as the allowlist: messages from other chats are ignored.

## Run locally

```bash
cd /Users/peteryoo/project-watchdog
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env, then export it into the shell:
set -a
source .env
set +a
python -m watchdog.bot
```

The process must remain running because Telegram button callbacks arrive after the daily report has been sent.

To add your own message above every alarm, edit `alarm_header.txt`. Leave it blank to show no header. The file is reread whenever a report is sent or refreshed, so changing it does not require a restart.

Run the local tests with:

```bash
python -m unittest discover -s tests
```

## Run with Docker

```bash
cp .env.example .env
# Edit .env
docker compose up -d --build
```

The SQLite database is persisted in `./data`.

## Suggested first interaction

```text
/start
/add your-name/existing-project 7 | Write the smallest runnable prototype
/report
```

## Optional template repository

Set `GITHUB_TEMPLATE_REPO=owner/template-name`. Then `/new` generates the new private repository from that GitHub template. When unset, it creates an empty private repository.

## Deliberately deferred

- Custom snooze date picker
- Editing `next_action` from Telegram
- Weekly overview
- GitHub Issues as a durable mirror
- PR/issue/heartbeat activity sources
- Escalation to a second channel
- AI-written change summaries

Those should be added after the basic acknowledgement loop proves useful.
