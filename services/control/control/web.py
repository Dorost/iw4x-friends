"""The bastion's web side, behind Caddy on https://<bastion domain>:

/            the fleet page: every server, boot and shut down, schedules (UI_PASSWORD login)
/costs       what the fleet costs, per server and the bastion (control/costs.py), and what is
             left on each cloud account (UI_PASSWORD login)
/s/<name>/   a running server's own control page (services/ui), passed through over WireGuard
/tg/         the Telegram mini app: map, mode, bots, boot and shut down, costs (members of the
             group)
/node/       reports from the game servers while they set up (WireGuard only, their token)
"""

import hashlib
import hmac
import ipaddress
import re
import secrets
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel
from sqlalchemy import select
from starlette.background import BackgroundTask

from control import keys
from control.costs import BadMonth, Costs, for_providers
from control.db import RUNNING, UP, Event
from control.db import Schedule as ScheduleRow
from control.nodes import NodeError, auth_header
from control.orchestrator import Busy, Orchestrator
from control.schedule import BadSchedule, describe, next_window, weekly
from control.telegram import BadInitData, TelegramError, esc, verify_init_data

STATIC = Path(__file__).with_name("static")
SESSION_COOKIE = "iw4x_fleet"
SESSION_DAYS = 30
# headers that belong to one hop, or that the bastion sets itself
HOP = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "host",
    "content-length", "authorization", "cookie", "set-cookie", "proxy-authorization",
}  # fmt: skip
MAP_ID = re.compile(r"^mp_\w+$")


class Login(BaseModel):
    password: str


class ScheduleIn(BaseModel):
    servers: list[str]
    days: list[int]
    start: str
    end: str
    tz: str
    enabled: bool = True
    note: str = ""


class Progress(BaseModel):
    step: str
    failed: bool = False
    event: bool = False  # a new step of the bootstrap (not a heartbeat): kept in the events


def page(name: str) -> HTMLResponse:
    return HTMLResponse((STATIC / name).read_text())


def routes(
    app: FastAPI,
    orch: Orchestrator,
    proxy_http: httpx.AsyncClient | None = None,
    costs: Costs | None = None,
) -> None:
    s = orch.s
    costs = costs or for_providers(s.fleet, orch.providers, s.fake_cloud)
    session_key = keys.secret_file(Path(s.data_dir) / "session.key")
    # no read timeout: the servers' pages keep a live update stream open
    proxy_http = proxy_http or httpx.AsyncClient(timeout=httpx.Timeout(10, read=None))
    thumbs = Path(s.data_dir) / "thumbs"
    wg_net = ipaddress.ip_network(f"{s.fleet.bastion.wg_ip}/24", strict=False)

    # ---------- login ----------

    def cookie_value() -> str:
        expires = str(int(time.time()) + SESSION_DAYS * 86400)
        return expires + "." + hmac.new(session_key, expires.encode(), hashlib.sha256).hexdigest()

    def logged_in(request: Request) -> bool:
        if not s.ui_password:
            return False  # no password set: nobody gets in
        expires, _, sig = request.cookies.get(SESSION_COOKIE, "").partition(".")
        good = hmac.new(session_key, expires.encode(), hashlib.sha256).hexdigest()
        return expires.isdigit() and int(expires) > time.time() and hmac.compare_digest(sig, good)

    def need_login(request: Request) -> None:
        if not logged_in(request):
            raise HTTPException(401, "log in first")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": s.version}

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        return page("login.html")

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response):
        if not s.ui_password or not secrets.compare_digest(
            body.password.encode(), s.ui_password.encode()
        ):
            time.sleep(1)  # slows down guessing
            raise HTTPException(401, "wrong password")
        response.set_cookie(
            SESSION_COOKIE,
            cookie_value(),
            max_age=SESSION_DAYS * 86400,
            httponly=True,
            secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
            samesite="strict",
        )
        return {"ok": True}

    @app.post("/api/auth/logout")  # also what a server's own page calls (services/ui)
    def logout(response: Response):
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    # ---------- the fleet page ----------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login")
        return page("fleet.html")

    def server_view(name: str, schedules) -> dict:
        spec = s.fleet.servers[name]
        row = orch.row(name)
        d = orch.decision(row, schedules)
        nxt = next_window(schedules, name, orch.now())
        state = orch.states.get(name) if row.status == RUNNING else None
        return {
            "name": name,
            "title": spec.title,
            "domain": spec.domain,
            "provider": spec.provider,
            "region": spec.region,
            "plan": spec.plan,
            "available": name in s.servers,
            "status": row.status,
            "step": row.step,
            "error": row.error,
            "busy": orch.busy(name),
            "ip": row.ip,
            "version": row.version,
            "outdated": bool(row.version and s.version and row.version != s.version),
            "boot_by": row.boot_by,
            "booted_at": row.booted_at,
            "ready_at": row.ready_at,
            "last_human_at": row.last_human_at,
            "hold_off_until": row.hold_off_until,
            "reason": d.reason,
            "stops_at": d.stops_at if row.status == RUNNING else None,
            "next_window": nxt and {"start": nxt.start, "end": nxt.end},
            "public": row.join_public,  # open to everyone instead of GAME_JOIN_PASSWORD
            "lockable": bool(s.game_password),  # there is a join password to switch to
            "game": state,
        }

    def fleet_view() -> dict:
        schedules = orch.schedules()
        return {
            "now": orch.now(),
            "version": s.version,
            "idle_minutes": s.idle_minutes,
            "lead_minutes": s.lead_minutes,
            "servers": [server_view(n, schedules) for n in s.fleet.servers],
        }

    @app.get("/api/fleet")
    def fleet(request: Request):
        need_login(request)
        with orch.db.begin() as db:
            rows = list(db.scalars(select(ScheduleRow).order_by(ScheduleRow.id)))
            events = list(db.scalars(select(Event).order_by(Event.id.desc()).limit(60)))
        schedules = []
        for r in rows:
            try:
                text = describe(weekly(r.servers, r.days, r.start, r.end, r.tz))
            except BadSchedule as e:
                text = f"invalid: {e}"
            schedules.append(
                {
                    "id": r.id,
                    "servers": [x for x in r.servers.split(",") if x],
                    "days": [int(d) for d in r.days.split(",") if d],
                    "start": r.start,
                    "end": r.end,
                    "tz": r.tz,
                    "enabled": r.enabled,
                    "note": r.note,
                    "text": text,
                }
            )
        return {
            **fleet_view(),
            "schedules": schedules,
            "events": [{"at": e.at, "server": e.server, "text": e.text} for e in events],
        }

    async def act(name: str, action: str, by: str) -> dict:
        if name not in s.fleet.servers:
            raise HTTPException(404, "no such server")
        if name not in s.servers:
            raise HTTPException(409, f"no {s.fleet.servers[name].provider} API key on the bastion")
        try:
            if action == "boot":
                await orch.boot_now(name, by)
            elif action == "shutdown":
                await orch.shutdown_now(name, by)
            elif action == "update":
                await orch.update_now(name)
            elif action in ("public", "protect"):
                await orch.set_public(name, action == "public", by)
            else:
                raise HTTPException(404, "no such action")
        except Busy as e:
            raise HTTPException(409, str(e)) from None
        return {"ok": True}

    @app.post("/api/servers/{name}/{action}")
    async def server_action(name: str, action: str, request: Request):
        need_login(request)
        return await act(name, action, "the web UI")

    # ---------- costs ----------

    async def costs_view(month: str, balances: bool) -> dict:
        try:
            return await costs.view(month, balances=balances)
        except BadMonth as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/costs", response_class=HTMLResponse)
    def costs_page(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login")
        return page("costs.html")

    @app.get("/api/costs")
    async def fleet_costs(request: Request, month: str = ""):
        need_login(request)
        return await costs_view(month, balances=True)

    # ---------- schedules ----------

    def checked(body: ScheduleIn) -> dict:
        unknown = set(body.servers) - set(s.fleet.servers)
        if unknown:
            raise HTTPException(400, f"unknown server: {', '.join(sorted(unknown))}")
        fields = {
            "servers": ",".join(sorted(set(body.servers))),
            "days": ",".join(str(d) for d in sorted(set(body.days))),
            "start": body.start.strip(),
            "end": body.end.strip(),
            "tz": body.tz.strip(),
            "enabled": body.enabled,
            "note": body.note.strip()[:100],
        }
        try:
            w = weekly(fields["servers"], fields["days"], fields["start"], fields["end"], body.tz)
        except BadSchedule as e:
            raise HTTPException(400, str(e)) from None
        if w.start == w.end:
            raise HTTPException(400, "the window starts and ends at the same time")
        return fields

    @app.post("/api/schedules")
    def add_schedule(body: ScheduleIn, request: Request):
        need_login(request)
        fields = checked(body)
        with orch.db.begin() as db:
            row = ScheduleRow(**fields)
            db.add(row)
            db.flush()
            sid = row.id
        orch.event(
            "", f"schedule {sid} added: {fields['servers']} {fields['start']}-{fields['end']}"
        )
        return {"id": sid}

    @app.put("/api/schedules/{sid}")
    def edit_schedule(sid: int, body: ScheduleIn, request: Request):
        need_login(request)
        fields = checked(body)
        with orch.db.begin() as db:
            row = db.get(ScheduleRow, sid)
            if not row:
                raise HTTPException(404, "no such schedule")
            for k, v in fields.items():
                setattr(row, k, v)
        state = "on" if fields["enabled"] else "off"
        orch.event("", f"schedule {sid} changed ({state}): {fields['servers']}")
        return {"ok": True}

    @app.delete("/api/schedules/{sid}")
    def delete_schedule(sid: int, request: Request):
        need_login(request)
        with orch.db.begin() as db:
            row = db.get(ScheduleRow, sid)
            if row:
                db.delete(row)
        orch.event("", f"schedule {sid} deleted")
        return {"ok": True}

    # ---------- a server's own control page ----------

    @app.get("/s/{name}")
    def server_page_slash(name: str):
        return RedirectResponse(f"/s/{name}/")

    @app.api_route("/s/{name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def server_page(name: str, path: str, request: Request):
        if not logged_in(request):
            if request.method == "GET" and not path.startswith("api/"):
                return RedirectResponse("/login")
            raise HTTPException(401, "log in first")
        spec = s.fleet.servers.get(name)
        row = orch.row(name) if spec else None
        if not row or row.status not in UP or not row.token:
            if request.method == "GET" and not path:
                return RedirectResponse("/")
            raise HTTPException(503, "that server is off")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        headers["authorization"] = auth_header(row.token)
        upstream = proxy_http.build_request(
            request.method,
            f"http://{spec.wg_ip}:8080/{path}",
            params=request.query_params,
            headers=headers,
            content=await request.body(),
        )
        try:
            resp = await proxy_http.send(upstream, stream=True)
        except httpx.HTTPError:
            raise HTTPException(502, "the server doesn't answer") from None
        # decoded as it comes (also the live update stream), so no content-encoding goes along
        return StreamingResponse(
            resp.aiter_bytes(),
            status_code=resp.status_code,
            headers={
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in HOP and k.lower() != "content-encoding"
            },
            background=BackgroundTask(resp.aclose),
        )

    # ---------- Telegram mini app ----------

    async def tg_user(request: Request) -> dict:
        if not orch.tg.on:
            raise HTTPException(503, "Telegram is not set up on the bastion")
        header = request.headers.get("authorization", "")
        if not header.startswith("tma "):
            raise HTTPException(401, "open this from Telegram")
        try:
            user = verify_init_data(s.telegram_token, header[4:])
        except BadInitData as e:
            raise HTTPException(401, str(e)) from None
        try:
            member = await orch.tg.is_member(user["id"])
        except TelegramError:
            raise HTTPException(503, "Telegram can't be reached, try again") from None
        if not member:
            raise HTTPException(403, "only for members of the group")
        return user

    @app.get("/tg/", response_class=HTMLResponse)
    def tg_page():
        return page("tg.html")

    @app.get("/tg/api/fleet")
    async def tg_fleet(request: Request):
        await tg_user(request)
        view = fleet_view()
        view["servers"] = [v for v in view["servers"] if v["available"]]
        return view

    @app.get("/tg/api/costs")
    async def tg_costs(request: Request, month: str = ""):
        """The same as the fleet page's, without what is left on the accounts."""
        await tg_user(request)
        return await costs_view(month, balances=False)

    def running(name: str):
        spec = s.servers.get(name)
        if not spec:
            raise HTTPException(404, "no such server")
        row = orch.row(name)
        if row.status != RUNNING or not row.token:
            raise HTTPException(409, f"{spec.title} is not running")
        return spec, row

    @app.post("/tg/api/servers/{name}/{action}")
    async def tg_action(name: str, action: str, request: Request):
        user = await tg_user(request)
        who = user.get("first_name") or str(user["id"])
        if action in ("boot", "shutdown", "public", "protect"):
            return await act(name, action, f"{who} in Telegram")
        if action not in ("play", "bots", "restart", "kick"):
            raise HTTPException(404, "no such action")
        spec, row = running(name)
        try:
            r = await orch.nodes.request(
                spec.wg_ip, row.token, "POST", f"/tg/api/{action}", await request.json(), user
            )
        except NodeError as e:
            raise HTTPException(502, str(e)) from None
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            raise HTTPException(r.status_code, data.get("detail") or "the server said no")
        if action == "kick":  # the group sees who kicked whom
            kicked = data.get("name") or "a player"
            orch.event(name, f"{kicked} kicked by {who} in Telegram")
            orch.tg.post(f"👢 <b>{esc(who)}</b> kicked <b>{esc(kicked)}</b> from {esc(spec.title)}")
        return data

    @app.get("/tg/thumb/{name}/{map_id}.jpg")
    async def tg_thumb(name: str, map_id: str):
        """A map's loading screen, from a running server's game files; kept here, as the maps
        are the same on every server."""
        if not MAP_ID.match(map_id):
            raise HTTPException(404)
        path = thumbs / f"{map_id}.jpg"
        if not path.exists():
            spec, row = running(name)
            try:
                r = await orch.nodes.request(
                    spec.wg_ip, row.token, "GET", f"/tg/thumb/{map_id}.jpg"
                )
            except NodeError:
                raise HTTPException(404) from None
            if r.status_code != 200:
                raise HTTPException(404)
            thumbs.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{secrets.token_hex(4)}.tmp")
            tmp.write_bytes(r.content)
            tmp.replace(path)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/tg/api/states")
    async def tg_states(request: Request):
        """Every server's /tg/api/state by its address, "offline" when it is off: for the
        planner bot's /online and friend alerts (services/bot, BOT_STATES_URL)."""
        await tg_user(request)
        out = {}
        for name, spec in s.servers.items():
            row = orch.row(name)
            state = orch.states.get(name) if row.status == RUNNING else None
            if state is None and row.status not in UP:
                state = {"status": "offline", "name": spec.title, "address": spec.domain}
            out[f"https://{spec.domain}"] = state
        return out

    # ---------- the game servers, over WireGuard ----------

    def node_of(request: Request) -> str:
        client = request.client.host if request.client else ""
        try:
            inside = ipaddress.ip_address(client) in wg_net
        except ValueError:
            inside = False
        if not inside or "x-forwarded-for" in request.headers:  # not through Caddy
            raise HTTPException(404)
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        name = orch.server_of_token(token) if token else None
        if not name:
            raise HTTPException(401)
        return name

    @app.post("/node/progress")
    def node_progress(body: Progress, request: Request):
        orch.node_progress(node_of(request), body.step, body.failed, body.event)
        return {"ok": True}

    @app.get("/node/config")
    def node_config(request: Request, has_game: int = 1):
        """Its .env settings; the setup password only when it still has to download the game."""
        return orch.node_config(node_of(request), need_game=not has_game)
