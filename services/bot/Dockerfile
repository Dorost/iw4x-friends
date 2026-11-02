# The "Tonight?" planner bot (README: "Tonight? planner bot")
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations migrations
COPY bot bot
ENV PATH=/app/.venv/bin:$PATH BOT_DB_PATH=/data/bot.db
VOLUME /data
CMD ["python", "-m", "bot"]
