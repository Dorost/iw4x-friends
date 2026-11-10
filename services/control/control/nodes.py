"""Talking to a running game server, over WireGuard: its web UI (services/ui/app.py) with the
token of this run as the password, and SSH with the control plane's key. WireGuard already
proves which server answers, so SSH doesn't check host keys (they are new on every boot)."""

import asyncio
import base64
import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger("control.nodes")
UI_PORT = 8080


class NodeError(Exception):
    pass


def auth_header(token: str) -> str:
    return "Basic " + base64.b64encode(f":{token}".encode()).decode()


class Nodes:
    def __init__(self, ssh_key: Path, http: httpx.AsyncClient | None = None):
        self.ssh_key = ssh_key
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(10, read=30))

    def url(self, ip: str, path: str) -> str:
        return f"http://{ip}:{UI_PORT}/{path.lstrip('/')}"

    async def request(
        self, ip: str, token: str, method: str, path: str, body=None, user: dict | None = None
    ) -> httpx.Response:
        headers = {"Authorization": auth_header(token)}
        if user:  # who did it, for the server's log (Telegram mini app)
            headers["X-Telegram-User"] = json.dumps(
                {"id": user.get("id"), "first_name": user.get("first_name", "")}
            )
        try:
            return await self.http.request(
                method, self.url(ip, path), json=body, headers=headers, timeout=60
            )
        except httpx.HTTPError as e:
            raise NodeError(f"the game server doesn't answer ({type(e).__name__})") from None

    async def state(self, ip: str, token: str) -> dict | None:
        """The server's /tg/api/state (map, mode, players, ...): what the poll loop of its web UI
        last saw, so asking costs the game nothing. None when it doesn't answer."""
        try:
            r = await self.http.get(
                self.url(ip, "/tg/api/state"),
                headers={"Authorization": auth_header(token)},
                timeout=5,
            )
            return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    async def stats_events(
        self, ip: str, token: str, after: int, limit: int, final: bool = False
    ) -> dict | None:
        """The kills, matches and sessions the server wrote down after event number after (its
        /api/stats/events): {"log": file id, "last": number, "events": [...]}; final: the
        sessions that go on up to now. None when it doesn't answer, or runs a version from before
        the stats."""
        try:
            r = await self.http.get(
                self.url(ip, "/api/stats/events"),
                params={"after": after, "limit": limit, "final": int(final)},
                headers={"Authorization": auth_header(token)},
                timeout=15,
            )
            data = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            return None
        log_id = data.get("log")
        return data if isinstance(log_id, str) and 0 < len(log_id) <= 32 else None

    async def ssh(self, ip: str, command: str, timeout: float = 600) -> tuple[int, str]:
        """Runs command as root on the server; (exit code, output)."""
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-i",
            str(self.ssh_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ConnectTimeout=15",
            f"root@{ip}",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            return 124, "timed out"
        return proc.returncode or 0, out.decode(errors="replace")

    async def close(self) -> None:
        await self.http.aclose()


class FakeNodes:
    """Game servers that answer once they are up (task control:dev, tests): a match on Rust,
    with the players set in self.players."""

    def __init__(self) -> None:
        self.up: set[str] = set()  # IPs that answer
        self.players: dict[str, list[str]] = {}
        self.ssh_calls: list[tuple[str, str]] = []
        self.requests: list[tuple[str, str, str]] = []
        self.bodies: list = []
        self.stats: dict[str, list[dict]] = {}  # IP -> the events its stats file has
        self.stats_log: dict[str, str] = {}  # IP -> that file's id

    async def state(self, ip: str, token: str) -> dict | None:
        if ip not in self.up:
            return None
        players = self.players.get(ip, [])
        return {
            "name": "Fake server",
            "address": ip,
            "status": "match",
            "map": "mp_rust",
            "map_name": "Rust",
            "mode": "war",
            "mode_name": "Team Deathmatch",
            "players": players,
            "bots": 2,
            "lobby_count": 0,
            "maps": [{"id": "mp_rust", "name": "Rust", "stock": True}],
            "modes": [{"id": "war", "name": "Team Deathmatch"}],
            "bot_settings": {"fill": 4, "add": False, "skill": "0"},
            "bot_skills": [{"id": "0", "name": "Mixed"}],
        }

    async def request(self, ip, token, method, path, body=None, user=None) -> httpx.Response:
        self.requests.append((ip, method, path))
        self.bodies.append(body)
        return httpx.Response(200, json={"ok": True})

    async def stats_events(
        self, ip: str, token: str, after: int, limit: int, final: bool = False
    ) -> dict | None:
        if ip not in self.up:
            return None
        events = self.stats.get(ip, [])
        return {
            "log": self.stats_log.setdefault(ip, f"log-{ip}"),
            "last": events[-1]["seq"] if events else 0,
            "events": [e for e in events if e["seq"] > after][:limit],
        }

    def add_event(self, ip: str, **event) -> dict:
        """The pretend server writes down a kill or a match (tests, task control:dev)."""
        events = self.stats.setdefault(ip, [])
        event = {**event, "seq": (events[-1]["seq"] if events else 0) + 1}
        events.append(event)
        return event

    async def ssh(self, ip: str, command: str, timeout: float = 600) -> tuple[int, str]:
        self.ssh_calls.append((ip, command))
        return 0, ""

    async def close(self) -> None:
        pass
