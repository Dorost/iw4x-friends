"""python -m bot: the planner bot (getUpdates, reminders, friend alerts) and its mini app API."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from bot import config
from bot.core import Bot
from bot.db import connect
from bot.telegram import Telegram, TelegramError
from bot.web import routes

REMINDER_SECONDS = 30


async def check_token(token: str) -> None:
    tg = Telegram(token)
    try:
        await tg.call("getMe")
    finally:
        await tg.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # httpx logs each request URL at INFO, and Bot API URLs hold the token
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = config.load()
    if not (s.token and s.chat_id):
        sys.exit(
            "set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (for task bot:dev: BOT_DEV_TOKEN, "
            "BOT_DEV_CHAT_ID)"
        )
    try:
        asyncio.run(check_token(s.token))
    except TelegramError as e:
        sys.exit(f"Telegram refused the bot token: {e.description or e.code}")
    holder: dict[str, Bot] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bot = Bot(s, Telegram(s.token), connect(s.db_path))
        holder["bot"] = bot
        await bot.setup()
        if s.fake_state:
            logging.getLogger("bot").info("game servers: fake state from %s", s.fake_state)
        tasks = [
            asyncio.create_task(bot.poll_updates()),
            asyncio.create_task(bot.every(REMINDER_SECONDS, bot.tick)),
            asyncio.create_task(bot.every(s.poll_seconds, bot.watch_servers)),
        ]
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    routes(app, lambda: holder["bot"])
    uvicorn.run(app, host=s.host, port=s.port, timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
