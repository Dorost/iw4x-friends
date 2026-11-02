"""A fake Telegram: records every call and answers like the Bot API would."""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from bot.config import Settings
from bot.core import Bot
from bot.db import connect
from bot.telegram import TelegramError

GROUP = "-1001"
BOT_TOKEN = "123456:TEST-not-a-real-token"


class FakeTelegram:
    def __init__(self, members: set[int] | None = None, no_dm: set[int] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.members = members if members is not None else set()
        self.no_dm = no_dm or set()  # users who never started the bot in private
        self.next_id = 100

    async def call(self, method: str, wait: float = 20, **params):
        self.calls.append((method, params))
        if method == "getMe":
            return {"id": 123456, "username": "tonight_test_bot", "has_main_web_app": True}
        if method == "getChatMember":
            if params["user_id"] in self.members:
                return {"status": "member"}
            raise TelegramError(400, "Bad Request: user not found")
        if method == "sendMessage":
            if params["chat_id"] in self.no_dm:
                raise TelegramError(403, "Forbidden: bot can't initiate conversation with a user")
            self.next_id += 1
            return {"message_id": self.next_id, "chat": {"id": params["chat_id"]}}
        return True

    def sent(self, chat_id=None) -> list[str]:
        return [
            p["text"]
            for m, p in self.calls
            if m == "sendMessage" and (chat_id is None or str(p["chat_id"]) == str(chat_id))
        ]

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def make_bot(
    tmp: Path, now: datetime, members=(), no_dm=(), fake_state: Path | None = None, **settings
) -> tuple[Bot, FakeTelegram, Clock, sessionmaker[Session]]:
    s = Settings(
        token=BOT_TOKEN,
        chat_id=GROUP,
        db_path=tmp / "bot.db",
        servers=["https://mw2-nl.dorost.nl", "https://mw2.dorost.nl"],
        fake_state=fake_state,
        **settings,
    )
    tg = FakeTelegram(set(members), set(no_dm))
    clock = Clock(now)
    sessions = connect(s.db_path)
    bot = Bot(s, tg, sessions, now=clock)
    bot.username = "tonight_test_bot"
    bot.has_app = True
    return bot, tg, clock, sessions


def msg(text: str, user: int, name: str, chat=None, private=False, mid=1) -> dict:
    chat = chat or (
        {"id": user, "type": "private"} if private else {"id": int(GROUP), "type": "supergroup"}
    )
    return {
        "update_id": mid,
        "message": {
            "message_id": mid,
            "date": int(datetime.now(UTC).timestamp()),
            "text": text,
            "from": {"id": user, "first_name": name, "username": name.lower()},
            "chat": chat,
        },
    }


def press(data: str, user: int, name: str, message_id: int = 101) -> dict:
    return {
        "update_id": 1,
        "callback_query": {
            "id": f"cb{user}",
            "data": data,
            "from": {"id": user, "first_name": name},
            "message": {"message_id": message_id, "chat": {"id": int(GROUP), "type": "supergroup"}},
        },
    }
