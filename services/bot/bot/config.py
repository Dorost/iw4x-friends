"""Settings from the environment. A test bot only needs other values, no code changes."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

# the zones every card shows, east to west: label -> IANA name
ZONES = {"NL": "Europe/Amsterdam", "ET": "America/New_York", "PT": "America/Los_Angeles"}


def _servers(raw: str) -> list[str]:
    return [s if s.startswith("http") else f"https://{s}" for s in raw.replace(",", " ").split()]


@dataclass(frozen=True)
class Settings:
    token: str = ""
    chat_id: str = ""
    db_path: Path = Path("bot.db")
    default_tz: str = "Europe/Amsterdam"
    min_players: int = 3
    servers: list[str] = field(default_factory=list)
    fake_state: Path | None = None  # JSON file instead of the game servers (task bot:dev)
    dev_user_id: int = 0  # mini app in a plain browser as this Telegram user (task bot:dev)
    host: str = "127.0.0.1"
    port: int = 8090
    poll_seconds: float = 20.0

    @property
    def connect_host(self) -> str:
        return urlsplit(self.servers[0]).hostname if self.servers else "mw2-nl.dorost.nl"

    @property
    def bot_id(self) -> int:
        head = self.token.partition(":")[0]
        return int(head) if head.isdigit() else 0


def load() -> Settings:
    env = os.environ.get
    fake = env("BOT_FAKE_STATE", "").strip()
    return Settings(
        token=env("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
        db_path=Path(env("BOT_DB_PATH", "bot.db")),
        default_tz=env("BOT_DEFAULT_TZ", "Europe/Amsterdam").strip(),
        min_players=int(env("BOT_MIN_PLAYERS", "3")),
        servers=_servers(env("TELEGRAM_APP_SERVERS", "")),
        fake_state=Path(fake) if fake else None,
        dev_user_id=int(env("BOT_DEV_USER_ID", "0") or 0),
        host=env("BOT_HOST", "127.0.0.1"),
        port=int(env("BOT_PORT", "8090")),
        poll_seconds=float(env("BOT_POLL_SECONDS", "20")),
    )
