"""The control plane with a pretend cloud, DNS, WireGuard, game servers and Telegram."""

from datetime import UTC, datetime
from pathlib import Path

from control.config import Settings, load_fleet
from control.db import connect
from control.dns import FakeDns
from control.nodes import FakeNodes
from control.orchestrator import Orchestrator
from control.providers.fake import FakeCloud
from control.telegram import Telegram
from control.wireguard import FakeWireGuard

FLEET = Path(__file__).resolve().parents[3] / "deploy/fleet.toml"
TOKEN = "123456:TEST-not-a-real-token"
GROUP = "-1001"
SHA = "a" * 40


class Clock:
    def __init__(self, t: datetime):
        self.t = t.timestamp()

    def __call__(self) -> float:
        return self.t

    def advance(self, minutes: float) -> None:
        self.t += minutes * 60


def at(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make(tmp: Path, now: datetime, **settings) -> tuple[Orchestrator, FakeCloud, Clock]:
    s = Settings(
        fleet=load_fleet(FLEET),
        data_dir=tmp,
        ui_password="pw",
        telegram_token=TOKEN,
        telegram_chat_id=GROUP,
        vultr_api_key="v",
        cloudflare_token="c",
        setup_password="setup",
        version=SHA,
        **{"game_password": "join", **settings},
    )
    cloud = FakeCloud("vultr", boot_polls=1)
    clock = Clock(now)
    orch = Orchestrator(
        s,
        connect(tmp / "control.db"),
        {"vultr": cloud},
        FakeDns(),
        FakeWireGuard(),
        FakeNodes(),
        Telegram(TOKEN, GROUP),
        now=clock,
        poll=0,
    )
    return orch, cloud, clock


def posts(orch: Orchestrator) -> list[str]:
    """The group messages queued so far (emptied)."""
    out = []
    while not orch.tg.outbox.empty():
        out.append(orch.tg.outbox.get_nowait()[0])
    return out
