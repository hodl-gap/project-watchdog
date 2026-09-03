FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY watchdog ./watchdog
RUN mkdir -p /app/data

ENV DATABASE_PATH=/app/data/watchdog.sqlite3
CMD ["python", "-m", "watchdog.bot"]

