"""Telegram: the mini app's login (initData that Telegram signs with the bot token, from members
of the group only), and messages to the group. The planner bot (services/bot) reads the bot's
updates; this never does, so the two don't get in each other's way."""

import asyncio
import hashlib
import hmac
import html
import json
import logging
import time
from urllib.parse import parse_qsl

import httpx

log = logging.getLogger("control.telegram")
API = "https://api.telegram.org"
INIT_DATA_MAX_AGE = 86400  # an app left open longer has to be opened again
MEMBER_CACHE = (600, 60)  # seconds to trust "in the group" and "not in the group"


class TelegramError(Exception):
    def __init__(self, code: int, description: str, parameters: dict | None = None):
        super().__init__(f"{code} {description}")
        self.code, self.description, self.parameters = code, description, parameters or {}


class BadInitData(ValueError):
    pass


def verify_init_data(token: str, raw: str, now: float | None = None) -> dict:
    """The user Telegram signed this initData for (mini app, or the planner bot signing as
    itself), or BadInitData."""
    fields = dict(parse_qsl(raw, keep_blank_values=True))
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()) if k != "hash")
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    good = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    if not token or not hmac.compare_digest(good, fields.get("hash", "")):
        raise BadInitData("not signed by Telegram for this bot")
    if (now or time.time()) - int(fields.get("auth_date") or 0) > INIT_DATA_MAX_AGE:
        raise BadInitData("open the app again from Telegram")
    user = json.loads(fields.get("user") or "{}")
    if not user.get("id"):
        raise BadInitData("no user")
    return user


def esc(s: str) -> str:
    return html.escape(s, quote=False)


class Telegram:
    def __init__(self, token: str, chat_id: str, http: httpx.AsyncClient | None = None):
        self.token, self.chat_id = token, chat_id
        self.http = http or httpx.AsyncClient()
        self.members: dict[int, tuple[float, bool]] = {}
        self.outbox: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        self.button: dict | None = None
        self.button_checked = 0.0

    @property
    def on(self) -> bool:
        return bool(self.token and self.chat_id)

    async def call(self, method: str, wait: float = 20, **params):
        try:
            r = await self.http.post(f"{API}/bot{self.token}/{method}", json=params, timeout=wait)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            # str(e) never holds the URL (and with it the token)
            raise TelegramError(0, type(e).__name__) from None
        if not data.get("ok"):
            raise TelegramError(
                data.get("error_code", r.status_code),
                data.get("description", ""),
                data.get("parameters"),
            )
        return data["result"]

    async def is_member(self, user_id: int) -> bool:
        hit = self.members.get(user_id)
        if hit and time.monotonic() - hit[0] < MEMBER_CACHE[0 if hit[1] else 1]:
            return hit[1]
        try:
            m = await self.call("getChatMember", chat_id=self.chat_id, user_id=user_id)
            ok = m.get("status") in ("creator", "administrator", "member") or bool(
                m.get("is_member")
            )
        except TelegramError as e:
            if e.code != 400:  # 400: not in the group
                raise
            ok = False
        self.members[user_id] = (time.monotonic(), ok)
        return ok

    async def app_button(self) -> dict | None:
        """The "🎮 Servers" button under the group messages, once BotFather has the mini app.
        Asked again every 10 minutes, so setting it up needs no restart."""
        if time.monotonic() - self.button_checked > 600 or not self.button_checked:
            try:
                me = await self.call("getMe")
                self.button_checked = time.monotonic()
                self.button = (
                    {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "🎮 Servers",
                                    "url": f"https://t.me/{me['username']}?startapp",
                                }
                            ]
                        ]
                    }
                    if me.get("has_main_web_app")
                    else None
                )
            except TelegramError:
                pass
        return self.button

    def post(self, text: str, silent: bool = False) -> None:
        """Queues a message to the group (HTML); send_loop sends them in order."""
        if self.on:
            self.outbox.put_nowait((text, silent))

    async def send_loop(self) -> None:
        while True:
            text, silent = await self.outbox.get()
            for attempt in range(6):
                try:
                    extra = {"reply_markup": b} if (b := await self.app_button()) else {}
                    await self.call(
                        "sendMessage",
                        chat_id=self.chat_id,
                        text=text,
                        parse_mode="HTML",
                        disable_notification=silent,
                        link_preview_options={"is_disabled": True},
                        **extra,
                    )
                    break
                except TelegramError as e:
                    if migrate := e.parameters.get("migrate_to_chat_id"):
                        log.warning("the group has a new id, set TELEGRAM_CHAT_ID=%s", migrate)
                        self.chat_id = str(migrate)
                        continue
                    log.warning("message not sent: %s", e.description)
                    if 400 <= e.code < 500 and e.code != 429:
                        break  # e.g. a wrong chat id: sending it again won't help
                    await asyncio.sleep(e.parameters.get("retry_after") or 5 * 2**attempt)

    async def close(self) -> None:
        await self.http.aclose()


# ---------- who joins and leaves ----------
# What the game servers' web UI did on each server (services/ui/app.py, Presence), now in one
# place: the game servers don't get the bot token. Someone counts as gone after LEAVE_SECONDS
# away while the server answers, so a map change or a crash they come back from posts nothing.

LEAVE_SECONDS = 60


def humans_of(state: dict | None) -> dict[str, str] | None:
    """The players (not bots) on a server, id -> name, from its /tg/api/state: by guid when the
    server sends them (humans), else by name. None when that isn't known: no answer, or a lobby
    with people in it (IW4x can't list them). Slots without a name don't count."""
    if state is None:
        return None
    status = state.get("status")
    if status == "offline":
        return {}
    if status == "match":
        if isinstance(state.get("humans"), dict):
            return {g: n for g, n in state["humans"].items() if str(n).strip()}
        return {n: n for n in state.get("players") or [] if str(n).strip()}
    if status == "lobby" and not state.get("lobby_count"):
        return {}
    return None


class Presence:
    def __init__(self) -> None:
        self.players: dict[str, str] = {}  # id -> name: joined and not left yet
        self.away: dict[str, float] = {}
        self.known = False  # the first list after a (re)start is taken as is
        self.last = 0.0

    def update(self, humans: dict[str, str] | None, now: float) -> tuple[list[str], list[str]]:
        """Names that joined and that left since the last call (now: time.monotonic())."""
        dt = min(now - self.last, 10.0) if self.last else 0.0
        self.last = now
        if humans is None:
            return [], []
        if not self.known:
            self.players, self.known = dict(humans), True
            return [], []
        joined = sorted((n for i, n in humans.items() if i not in self.players), key=str.lower)
        left = []
        for i in [i for i in self.players if i not in humans]:
            self.away[i] = self.away.get(i, 0.0) + dt
            if self.away[i] >= LEAVE_SECONDS:
                del self.away[i]
                left.append(self.players.pop(i))
        for i in humans:
            self.away.pop(i, None)
        self.players.update(humans)  # also takes new names
        return joined, sorted(left, key=str.lower)

    def reset(self) -> None:
        """The server went away: the next one starts with nobody known."""
        self.players, self.away, self.known, self.last = {}, {}, False, 0.0


def presence_text(server: str, joined: list[str], left: list[str], playing) -> str:
    def bold(names: list[str]) -> str:
        return ", ".join(f"<b>{esc(n)}</b>" for n in names)

    lines = []
    if joined:
        lines.append(f"🟢 {bold(joined)} joined {esc(server)}")
    if left:
        lines.append(f"🔴 {bold(left)} left {esc(server)}")
    names = sorted(playing, key=str.lower)
    lines.append(
        f"Playing ({len(names)}): {esc(', '.join(names))}" if names else "Nobody playing now"
    )
    return "\n".join(lines)
