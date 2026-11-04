"""Settings: the fleet catalog (deploy/fleet.toml) and the environment (secrets from GitHub)."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROVIDERS = ("vultr", "zenlayer")
BASTION_LABEL = "iw4x-bastion"  # the name of the bastion's VM and disk at Vultr


@dataclass(frozen=True)
class Bastion:
    domain: str
    provider: str
    region: str
    plan: str
    volume_gb: int
    wg_ip: str
    wg_port: int = 51820


@dataclass(frozen=True)
class ServerSpec:
    """A game server of the catalog. region is the Vultr region or the Zenlayer zone, plan the
    Vultr plan or the Zenlayer instance type."""

    name: str
    title: str
    hostname: str
    provider: str
    region: str
    plan: str
    domain: str
    wg_ip: str
    volume_gb: int
    options: dict = field(default_factory=dict)  # provider extras (bandwidth_mbps, ...)

    @property
    def label(self) -> str:
        """The name of its VM and its disk at the provider."""
        return f"iw4x-fleet-{self.name}"


@dataclass(frozen=True)
class Fleet:
    repo: str
    bastion: Bastion
    servers: dict[str, ServerSpec]


SERVER_KEYS = {"title", "hostname", "provider", "region", "plan", "domain", "wg_ip", "volume_gb"}


def load_fleet(path: Path) -> Fleet:
    raw = tomllib.loads(path.read_text())
    servers = {}
    for name, s in raw.get("servers", {}).items():
        if s["provider"] not in PROVIDERS:
            raise ValueError(f"servers.{name}: unknown provider {s['provider']!r}")
        servers[name] = ServerSpec(
            name=name,
            title=s.get("title", name.upper()),
            hostname=s.get("hostname", ""),
            provider=s["provider"],
            region=s["region"],
            plan=s["plan"],
            domain=s["domain"],
            wg_ip=s["wg_ip"],
            volume_gb=int(s.get("volume_gb", 40)),
            options={k: v for k, v in s.items() if k not in SERVER_KEYS},
        )
    ips = [s.wg_ip for s in servers.values()] + [raw["bastion"]["wg_ip"]]
    if len(set(ips)) != len(ips):
        raise ValueError("two WireGuard addresses are the same in the fleet")
    return Fleet(repo=raw["repo"], bastion=Bastion(**raw["bastion"]), servers=servers)


def _list(raw: str) -> list[str]:
    """One item per line or separated by ';' (SSH keys have spaces)."""
    return [x.strip() for x in raw.replace(";", "\n").splitlines() if x.strip()]


@dataclass(frozen=True)
class Settings:
    fleet: Fleet
    data_dir: Path = Path("data")
    host: str = (
        "0.0.0.0"  # also the WireGuard side: nodes report to /node/ (ufw keeps it off the internet)
    )
    port: int = 8070
    ui_password: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    vultr_api_key: str = ""
    zenlayer_key_id: str = ""
    zenlayer_key_password: str = ""
    cloudflare_token: str = ""
    setup_password: str = ""  # decrypts the game download links in the setup scripts
    game_password: str = ""  # the join password of every game server; empty: each keeps its own
    admin_ssh_keys: list[str] = field(default_factory=list)
    version: str = ""  # the commit deployed here: game servers run the same one
    idle_minutes: int = 15  # outside a schedule window, a server with nobody on stops after this
    lead_minutes: int = 10  # a scheduled server boots this long before its window starts
    wg_interface: str = "wg0"
    fake_cloud: bool = False  # task control:dev: pretend clouds and game servers

    def has_provider(self, provider: str) -> bool:
        if self.fake_cloud:
            return True
        if provider == "vultr":
            return bool(self.vultr_api_key)
        return bool(self.zenlayer_key_id and self.zenlayer_key_password)

    @property
    def servers(self) -> dict[str, ServerSpec]:
        """The catalog's servers whose provider has credentials here."""
        return {n: s for n, s in self.fleet.servers.items() if self.has_provider(s.provider)}

    @property
    def telegram_on(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


def load() -> Settings:
    env = os.environ.get
    # FLEET_FILE in Docker; from the repo, deploy/fleet.toml
    fleet_path = Path(
        env("FLEET_FILE") or Path(__file__).resolve().parents[3] / "deploy/fleet.toml"
    )
    return Settings(
        fleet=load_fleet(fleet_path),
        data_dir=Path(env("CONTROL_DATA_DIR", "data")),
        host=env("CONTROL_HOST", "0.0.0.0"),
        port=int(env("CONTROL_PORT", "8070")),
        ui_password=env("UI_PASSWORD", ""),
        telegram_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
        vultr_api_key=env("VULTR_API_KEY", "").strip(),
        zenlayer_key_id=env("ZENLAYER_ACCESS_KEY_ID", "").strip(),
        zenlayer_key_password=env("ZENLAYER_ACCESS_KEY_PASSWORD", "").strip(),
        cloudflare_token=env("CLOUDFLARE_DNS_TOKEN", "").strip(),
        setup_password=env("MW_SETUP_PASSWORD", ""),
        game_password=env("GAME_JOIN_PASSWORD", ""),
        admin_ssh_keys=_list(env("ADMIN_SSH_KEYS", "")),
        version=env("IMAGE_TAG", "").strip(),
        idle_minutes=int(env("IDLE_MINUTES", "") or 15),
        lead_minutes=int(env("LEAD_MINUTES", "") or 10),
        fake_cloud=env("CONTROL_FAKE_CLOUD", "") == "1",
    )
