"""Who plays where: the game servers' /tg/api/state, and the joins the bot DMs watchers about.

The game servers only answer Telegram-signed requests (initData) from members of the group. The
bot is a member and has the token, so it signs its own initData: no change on the game servers.
With BOT_FAKE_STATE (task bot:dev) a JSON file stands in for them."""

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

INIT_DATA_MAX_AGE = 86400
GONE_AFTER = 120.0  # seconds missing from a running match before a name counts as left


class BadInitData(ValueError):
    pass


def _key(token: str) -> bytes:
    return hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()


def sign_init_data(token: str, user: dict, auth_date: int | None = None) -> str:
    fields = {"auth_date": str(auth_date or int(time.time())), "user": json.dumps(user)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(_key(token), check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def verify_init_data(token: str, raw: str, now: float | None = None) -> dict:
    """The user Telegram signed this initData for, or BadInitData."""
    fields = dict(parse_qsl(raw, keep_blank_values=True))
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()) if k != "hash")
    good = hmac.new(_key(token), check.encode(), hashlib.sha256).hexdigest()
    if not token or not hmac.compare_digest(good, fields.get("hash", "")):
        raise BadInitData("not signed by Telegram for this bot")
    if (now or time.time()) - int(fields.get("auth_date") or 0) > INIT_DATA_MAX_AGE:
        raise BadInitData("open the app again from Telegram")
    user = json.loads(fields.get("user") or "{}")
    if not user.get("id"):
        raise BadInitData("no user")
    return user


def short(base: str) -> str:
    """mw2-nl.dorost.nl -> mw2-nl"""
    return (urlsplit(base).hostname or base).split(".")[0]


async def fetch_states(
    servers: list[str],
    token: str,
    bot_id: int,
    http: httpx.AsyncClient,
    fake: Path | None = None,
    states_url: str = "",
) -> dict[str, dict | None]:
    """server -> its state ({status, players, map_name, mode_name, ...}), None when unreachable.
    With states_url (BOT_STATES_URL), the bastion's control plane answers for all of them at
    once (services/control: /tg/api/states), "offline" for a server that is shut down."""
    if fake:
        try:
            data = json.loads(fake.read_text())
        except (OSError, ValueError):
            return {}
        return {(k if k.startswith("http") else f"https://{k}"): v for k, v in data.items()}
    auth = {"Authorization": "tma " + sign_init_data(token, {"id": bot_id, "first_name": "bot"})}
    if states_url:
        try:
            r = await http.get(states_url, headers=auth, timeout=8)
            data = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            data = None
        if not isinstance(data, dict):
            return dict.fromkeys(servers)
        return data
    out: dict[str, dict | None] = {}
    for base in servers:
        try:
            r = await http.get(f"{base}/tg/api/state", headers=auth, timeout=8)
            out[base] = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            out[base] = None
    return out


class Joins:
    """Turns player lists into joins. Only a running match counts: between maps the list is
    empty, and that is not everyone leaving."""

    def __init__(self) -> None:
        self.seen: dict[str, dict[str, float]] = {}  # server -> name (lower) -> last seen
        self.ready: set[str] = set()  # servers seen once: their first list is not news

    def update(self, server: str, state: dict | None, now: float) -> list[str]:
        if not state or state.get("status") != "match":
            return []
        seen = self.seen.setdefault(server, {})
        for name in [n for n, t in seen.items() if now - t > GONE_AFTER]:
            del seen[name]
        joined = [p for p in state.get("players", []) if p.lower() not in seen]
        for p in state.get("players", []):
            seen[p.lower()] = now
        if server not in self.ready:
            self.ready.add(server)
            return []
        return joined
