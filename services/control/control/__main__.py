"""python -m control: the bastion's control plane (web UI, mini app, orchestrator)."""

import asyncio
import logging
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


async def fake_servers(orch: Orchestrator) -> None:
    """task control:dev: the pretend servers answer a few seconds after their VM is up."""
    while True:
        for name, spec in orch.s.servers.items():
            row = orch.row(name)
            if row.status == "booting" and spec.wg_ip not in orch.nodes.up:
                await asyncio.sleep(4)
                orch.nodes.up.add(spec.wg_ip)
            elif row.status in ("off", "stopping"):
                orch.nodes.up.discard(spec.wg_ip)
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
