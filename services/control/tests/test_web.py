import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import pytest
from fakes import TOKEN, at, make
from fastapi import FastAPI
from fastapi.testclient import TestClient

from control.costs import Costs, fake_billings
from control.db import RUNNING
from control.web import routes

NOW = at(2026, 11, 4, 18)
AMIN, STRANGER = 11, 99


def init_data(user_id: int, token: str = TOKEN, age: int = 0) -> str:
    fields = {
        "auth_date": str(int(time.time()) - age),
        "user": json.dumps({"id": user_id, "first_name": "Amin"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def tma(user_id: int, **kw) -> dict:
    return {"Authorization": "tma " + init_data(user_id, **kw)}


class Upstream:
    """A game server's web UI, as the proxy sees it."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"path": request.url.path}, headers={"set-cookie": "x=1"})


@pytest.fixture
def web(tmp_path):
    orch, _, _ = make(tmp_path, NOW)
    calls = []

    async def boot_now(name, by):
        calls.append(("boot", name, by))

    async def shutdown_now(name, by):
        calls.append(("shutdown", name, by))

    async def is_member(user_id):
        return user_id == AMIN

    orch.boot_now, orch.shutdown_now, orch.tg.is_member = boot_now, shutdown_now, is_member
    upstream = Upstream()
    app = FastAPI()
    costs = Costs(orch.s.fleet, fake_billings(), clock=NOW.timestamp)
    routes(app, orch, httpx.AsyncClient(transport=httpx.MockTransport(upstream)), costs)
    return TestClient(app, follow_redirects=False), orch, calls, upstream


def login(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={"password": "pw"}).status_code == 200


def test_the_fleet_page_needs_the_password(web):
    client, _, _, _ = web
    assert client.get("/").headers["location"] == "/login"
    assert client.get("/api/fleet").status_code == 401
    assert client.post("/api/servers/nl/boot").status_code == 401
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    login(client)
    fleet = client.get("/api/fleet").json()
    assert [s["name"] for s in fleet["servers"]] == ["nl", "us", "ist"]
    ist = fleet["servers"][2]
    assert not ist["available"] and ist["provider"] == "zenlayer"  # no Zenlayer key here
    assert client.get("/").status_code == 200


def test_boot_and_shutdown_from_the_page(web):
    client, _, calls, _ = web
    login(client)
    assert client.post("/api/servers/nl/boot").status_code == 200
    assert client.post("/api/servers/us/shutdown").status_code == 200
    assert client.post("/api/servers/ist/boot").status_code == 409  # no Zenlayer key
    assert client.post("/api/servers/xx/boot").status_code == 404
    assert client.post("/api/servers/nl/explode").status_code == 404
    assert calls == [("boot", "nl", "the web UI"), ("shutdown", "us", "the web UI")]


def test_schedules(web):
    client, _, _, _ = web
    login(client)
    good = {"servers": ["nl", "us"], "days": [4, 5], "start": "20:00", "end": "23:30",
            "tz": "Europe/Amsterdam", "note": "Friday night"}  # fmt: skip
    for bad in ({"start": "8pm"}, {"servers": ["moon"]}, {"days": []}, {"tz": "Mars/Base"},
                {"end": "20:00"}):  # fmt: skip
        assert client.post("/api/schedules", json={**good, **bad}).status_code == 400, bad
    sid = client.post("/api/schedules", json=good).json()["id"]
    [sc] = client.get("/api/fleet").json()["schedules"]
    assert sc["text"] == "Fri, Sat 20:00 to 23:30 (Europe/Amsterdam)" and sc["enabled"]
    assert client.put(f"/api/schedules/{sid}", json={**good, "enabled": False}).status_code == 200
    assert not client.get("/api/fleet").json()["schedules"][0]["enabled"]
    fleet = client.get("/api/fleet").json()
    assert fleet["servers"][0]["next_window"] is None  # off schedules don't count
    assert client.delete(f"/api/schedules/{sid}").status_code == 200
    assert client.get("/api/fleet").json()["schedules"] == []


def running(orch, name="nl", token="tok"):
    orch.update(name, status=RUNNING, token=token, ip="192.0.2.5", ready_at=orch.now())


def test_a_servers_own_page_goes_through_with_its_token(web):
    client, orch, _, upstream = web
    assert client.get("/s/nl/").headers["location"] == "/login"
    login(client)
    assert client.get("/s/nl/").headers["location"] == "/"  # off
    assert client.get("/s/nl/api/state").status_code == 503
    running(orch)
    r = client.post("/s/nl/api/config?x=1", json={"a": 1}, headers={"Authorization": "Basic evil"})
    assert r.status_code == 200 and "set-cookie" not in r.headers
    sent = upstream.requests[-1]
    assert str(sent.url) == "http://10.66.0.11:8080/api/config?x=1"
    assert sent.headers["authorization"] == "Basic OnRvaw=="  # ":tok", not what the browser sent
    assert "cookie" not in sent.headers  # the fleet page's session stays here
    assert client.get("/s/nl").headers["location"] == "/s/nl/"


def test_mini_app_needs_telegram_and_the_group(web):
    client, orch, calls, upstream = web
    assert client.get("/tg/api/fleet").status_code == 401
    assert client.get("/tg/api/fleet", headers=tma(AMIN, token="1:other-bot")).status_code == 401
    assert client.get("/tg/api/fleet", headers=tma(AMIN, age=2 * 86400)).status_code == 401
    assert client.get("/tg/api/fleet", headers=tma(STRANGER)).status_code == 403
    fleet = client.get("/tg/api/fleet", headers=tma(AMIN)).json()
    assert [s["name"] for s in fleet["servers"]] == ["nl", "us"]  # no Istanbul: no key
    assert client.post("/tg/api/servers/nl/boot", headers=tma(AMIN), json={}).status_code == 200
    assert calls == [("boot", "nl", "Amin in Telegram")]
    play = {"map": "mp_rust", "mode": "war", "now": True}
    assert client.post("/tg/api/servers/nl/play", headers=tma(AMIN), json=play).status_code == 409
    running(orch)
    orch.nodes.requests.clear()
    assert client.post("/tg/api/servers/nl/play", headers=tma(AMIN), json=play).status_code == 200
    assert orch.nodes.requests == [("10.66.0.11", "POST", "/tg/api/play")]


def test_states_for_the_planner_bot(web):
    client, orch, _, _ = web
    running(orch, "us")
    orch.states["us"] = {"status": "match", "players": ["Amin"]}
    states = client.get("/tg/api/states", headers=tma(AMIN)).json()
    assert states["https://mw2-us.dorost.nl"] == {"status": "match", "players": ["Amin"]}
    assert states["https://mw2-nl.dorost.nl"]["status"] == "offline"


def test_game_servers_report_over_wireguard_only(tmp_path, web):
    _, orch, _, _ = web
    app = FastAPI()
    routes(app, orch)
    orch.update("nl", status="booting", token="tok")
    inside = TestClient(app, client=("10.66.0.11", 40000))
    outside = TestClient(app, client=("203.0.113.9", 40000))
    auth = {"Authorization": "Bearer tok"}
    assert outside.post("/node/progress", json={"step": "x"}, headers=auth).status_code == 404
    through_caddy = {**auth, "X-Forwarded-For": "203.0.113.9"}
    assert (
        inside.post("/node/progress", json={"step": "x"}, headers=through_caddy).status_code == 404
    )
    assert (
        inside.post(
            "/node/progress", json={"step": "x"}, headers={"Authorization": "Bearer no"}
        ).status_code
        == 401
    )
    assert (
        inside.post("/node/progress", json={"step": "mounting its disk"}, headers=auth).status_code
        == 200
    )
    assert orch.row("nl").step == "mounting its disk"
    step = {"step": "getting its settings (at 50s)", "event": True}
    assert inside.post("/node/progress", json=step, headers=auth).status_code == 200
    assert orch.row("nl").step == "getting its settings (at 50s)"
    config = inside.get("/node/config?has_game=0", headers=auth).json()
    assert config["setup_password"] == "setup" and config["join_host"] == "mw2-nl.dorost.nl"
    assert inside.get("/node/config?has_game=1", headers=auth).json()["setup_password"] == ""


def test_open_to_everyone_from_the_page_and_the_mini_app(web):
    client, orch, _, _ = web
    assert client.post("/api/servers/nl/public").status_code == 401
    login(client)
    assert client.post("/api/servers/nl/public").status_code == 200
    nl = client.get("/api/fleet").json()["servers"][0]
    assert nl["public"] and nl["lockable"]
    assert (
        client.post("/tg/api/servers/nl/protect", headers=tma(STRANGER), json={}).status_code == 403
    )
    assert client.post("/tg/api/servers/nl/protect", headers=tma(AMIN), json={}).status_code == 200
    assert not orch.row("nl").join_public


def test_mini_app_fast_restart_goes_to_the_server(web):
    client, orch, _, _ = web
    assert client.post("/tg/api/servers/nl/restart", headers=tma(AMIN), json={}).status_code == 409
    running(orch)
    orch.nodes.requests.clear()
    assert (
        client.post("/tg/api/servers/nl/restart", headers=tma(STRANGER), json={}).status_code == 403
    )
    assert client.post("/tg/api/servers/nl/restart", headers=tma(AMIN), json={}).status_code == 200
    assert orch.nodes.requests == [("10.66.0.11", "POST", "/tg/api/restart")]


def test_mini_app_kick_goes_to_the_server_and_the_group_hears_it(web):
    client, orch, _, _ = web
    kick = {"num": 3, "guid": "abc123"}
    assert client.post("/tg/api/servers/nl/kick", headers=tma(AMIN), json=kick).status_code == 409
    running(orch)
    sent = []

    async def request(ip, token, method, path, body=None, user=None):
        sent.append((ip, method, path, body, user["first_name"]))
        return httpx.Response(200, json={"ok": True, "name": "XerS"})

    orch.nodes.request = request
    assert (
        client.post("/tg/api/servers/nl/kick", headers=tma(STRANGER), json=kick).status_code == 403
    )
    assert client.post("/tg/api/servers/nl/kick", headers=tma(AMIN), json=kick).status_code == 200
    assert sent == [("10.66.0.11", "POST", "/tg/api/kick", kick, "Amin")]
    message = orch.tg.outbox.get_nowait()[0]
    assert message == "👢 <b>Amin</b> kicked <b>XerS</b> from NL"


def test_costs_on_the_fleet_page_with_what_is_left_on_the_accounts(web):
    client, _, _, _ = web
    assert client.get("/costs").headers["location"] == "/login"
    assert client.get("/api/costs").status_code == 401
    login(client)
    assert client.get("/costs").status_code == 200
    costs = client.get("/api/costs").json()
    assert costs["month"] == "2026-11" and costs["months"] == ["2026-11", "2026-10"]
    assert [g["key"] for g in costs["groups"]] == ["nl", "us", "ist", "bastion", "other"]
    assert [b["label"] for b in costs["balances"]] == ["Credit left", "Prepaid balance"]
    assert client.get("/api/costs?month=2026-10").json()["month"] == "2026-10"
    assert client.get("/api/costs?month=2027-01").status_code == 400


def test_costs_in_the_mini_app_without_the_accounts(web):
    client, _, _, _ = web
    assert client.get("/tg/api/costs").status_code == 401
    assert client.get("/tg/api/costs", headers=tma(STRANGER)).status_code == 403
    costs = client.get("/tg/api/costs", headers=tma(AMIN)).json()
    assert "balances" not in costs
    # the fleet's servers and the bastion only: the old VPS ("other") is on the fleet page
    assert [g["key"] for g in costs["groups"]] == ["nl", "us", "ist", "bastion"]
    assert costs["total"] == round(sum(g["total"] for g in costs["groups"]), 2)
