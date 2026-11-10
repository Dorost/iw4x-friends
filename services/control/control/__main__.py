"""python -m control: the bastion's control plane (web UI, mini app, orchestrator)."""

import asyncio
import logging
import random
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from control import config
from control.db import connect
from control.dns import Cloudflare, FakeDns
from control.nodes import FakeNodes, Nodes
from control.orchestrator import Orchestrator
from control.providers.fake import FakeCloud
from control.providers.vultr import Vultr
from control.providers.zenlayer import Zenlayer
from control.telegram import Telegram
from control.web import routes
from control.wireguard import FakeWireGuard, WireGuard


def build(s: config.Settings) -> Orchestrator:
    if s.fake_cloud:
        providers = {"vultr": FakeCloud("vultr"), "zenlayer": FakeCloud("zenlayer")}
        dns, wg, nodes = FakeDns(), FakeWireGuard(), FakeNodes()
    else:
        providers = {}
        if s.vultr_api_key:
            providers["vultr"] = Vultr(s.vultr_api_key)
        if s.zenlayer_key_id and s.zenlayer_key_password:
            providers["zenlayer"] = Zenlayer(s.zenlayer_key_id, s.zenlayer_key_password)
        dns = Cloudflare(s.cloudflare_token) if s.cloudflare_token else None
        wg = WireGuard(s.wg_interface)
        nodes = Nodes(s.data_dir / "ssh" / "id_ed25519")
    return Orchestrator(
        s,
        connect(s.data_dir / "control.db"),
        providers,
        dns,
        wg,
        nodes,
        Telegram(s.telegram_token, s.telegram_chat_id),
    )


FAKE_PEOPLE = [("1111aaaa1111aaaa", "Yashar"), ("2222bbbb2222bbbb", "Amin"), ("3333cccc", "Sara")]
FAKE_BOTS = ["Pedro", "Jose", "Ahmed"]
FAKE_WEAPONS = [
    ("cheytac_fmj_mp", "MOD_HEAD_SHOT", "head"),
    ("m4_reflex_mp", "MOD_RIFLE_BULLET", "torso_upper"),
    ("ump45_silencer_mp", "MOD_PISTOL_BULLET", "right_arm_lower"),
    ("spas12_mp", "MOD_RIFLE_BULLET", "left_leg_upper"),
    ("usp_tactical_mp", "MOD_MELEE", "torso_lower"),
    ("frag_grenade_mp", "MOD_GRENADE_SPLASH", "none"),
    ("ac130_105mm_mp", "MOD_PROJECTILE_SPLASH", "none"),
]


def fake_kill(orch: Orchestrator, ip: str) -> None:
    """task control:dev: a running pretend server writes down a random kill (a new match now
    and then), for the stats."""
    events = orch.nodes.stats.get(ip, [])
    matches = [e for e in events if e["type"] == "match"]
    if not matches or random.random() < 0.03:
        mp, mode = random.choice(
            [("mp_rust", "war"), ("mp_terminal", "sd"), ("mp_highrise", "dom")]
        )
        name = {"war": "Team Deathmatch", "sd": "Search & Destroy", "dom": "Domination"}[mode]
        orch.nodes.add_event(
            ip,
            type="match",
            match=len(matches) + 1,
            at=orch.now(),
            map=mp,
            map_name=mp[3:].title(),
            gametype=mode,
            mode=mode,
            mode_name=name,
        )
        return
    sides = [
        {"guid": g, "name": n, "bot": False, "ping": random.randint(30, 120)}
        for g, n in FAKE_PEOPLE
    ]
    sides += [{"guid": "bot" + n.lower(), "name": n, "bot": True, "ping": 0} for n in FAKE_BOTS]
    killer, victim = random.sample(sides, 2)
    if killer["bot"] and victim["bot"]:
        return
    killer, victim = {**killer, "team": "allies"}, {**victim, "team": "axis"}
    weapon, means, hit = random.choice(FAKE_WEAPONS)
    orch.nodes.add_event(
        ip,
        type="kill",
        match=len(matches),
        at=orch.now(),
        victim=victim,
        killer=killer,
        weapon=weapon,
        damage=100,
        means=means,
        hit=hit,
    )


async def fake_servers(orch: Orchestrator) -> None:
    """task control:dev: the pretend servers answer a few seconds after their VM is up, and
    then kills happen on them."""
    while True:
        for name, spec in orch.s.servers.items():
            row = orch.row(name)
            if row.status == "booting" and spec.wg_ip not in orch.nodes.up:
                await asyncio.sleep(4)
                orch.nodes.up.add(spec.wg_ip)
            elif row.status in ("off", "stopping"):
                orch.nodes.up.discard(spec.wg_ip)
            elif row.status == "running":
                fake_kill(orch, spec.wg_ip)
        await asyncio.sleep(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its URLs hold the bot token
    s = config.load()
    if not s.ui_password:
        sys.exit("set UI_PASSWORD: the password of the fleet page")
    s.data_dir.mkdir(parents=True, exist_ok=True)
    orch = build(s)
    if not s.servers:
        logging.warning("no cloud API key set (VULTR_API_KEY, ZENLAYER_*): no server can boot")
    if not s.telegram_on:
        logging.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing: no mini app, no messages")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(orch.run())]
        if s.telegram_on:
            tasks.append(asyncio.create_task(orch.tg.send_loop()))
        if s.fake_cloud:
            tasks.append(asyncio.create_task(fake_servers(orch)))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    routes(app, orch)
    uvicorn.run(app, host=s.host, port=s.port, timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
