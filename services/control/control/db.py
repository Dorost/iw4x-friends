"""SQLite tables (SQLAlchemy) and the alembic upgrade that creates them. Times are UTC unix
seconds."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

HERE = Path(__file__).resolve().parent.parent

# where a game server is in its life; the orchestrator moves it along
OFF, PROVISIONING, BOOTING, RUNNING, STOPPING, FAILED = (
    "off",
    "provisioning",
    "booting",
    "running",
    "stopping",
    "failed",
)
UP = (PROVISIONING, BOOTING, RUNNING)  # a VM exists or is on its way


class Base(DeclarativeBase):
    pass


class Server(Base):
    """A game server of the catalog (deploy/fleet.toml) and its VM, when it has one."""

    __tablename__ = "servers"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default=OFF)
    step: Mapped[str] = mapped_column(String(200), default="")  # what it is doing now
    error: Mapped[str] = mapped_column(Text, default="")
    instance_id: Mapped[str | None] = mapped_column(String(64))
    volume_id: Mapped[str | None] = mapped_column(String(64))  # its disk, kept between runs
    ip: Mapped[str | None] = mapped_column(String(64))
    wg_public: Mapped[str | None] = mapped_column(String(64))  # WireGuard key of this run
    token: Mapped[str | None] = mapped_column(String(64))  # its web UI password, this run only
    version: Mapped[str | None] = mapped_column(String(40))  # commit it runs
    boot_by: Mapped[str] = mapped_column(String(64), default="")
    booted_at: Mapped[int | None] = mapped_column(Integer)
    ready_at: Mapped[int | None] = mapped_column(Integer)
    last_human_at: Mapped[int | None] = mapped_column(Integer)  # a player (not a bot) was on
    hold_off_until: Mapped[int | None] = mapped_column(Integer)  # shut down by hand in a window
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # failed boots in a row
    changed_at: Mapped[int] = mapped_column(Integer, default=0)
    # open to everyone instead of GAME_JOIN_PASSWORD (fleet page, mini app), until it shuts down
    join_public: Mapped[bool] = mapped_column(Boolean, default=False)
    run_id: Mapped[int | None] = mapped_column(Integer)  # this run's row in runs
    # how far the kills of its stats file (services/ui/app.py, Stats) are in: the file's id and
    # the last event number taken in
    stats_log: Mapped[str | None] = mapped_column(String(32))
    stats_seq: Mapped[int] = mapped_column(Integer, default=0)


class Schedule(Base):
    """Weekly hours some servers are up for, in a time zone. days: weekdays, "0,4" = Mon, Fri.
    A window ending at or before its start ends the next day (20:00 to 02:00)."""

    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    servers: Mapped[str] = mapped_column(String(200))  # "nl,us"
    days: Mapped[str] = mapped_column(String(20))
    start: Mapped[str] = mapped_column(String(5))  # "20:00"
    end: Mapped[str] = mapped_column(String(5))
    tz: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(100), default="")


class Event(Base):
    """What happened, for the web UI: boots, shutdowns, schedule changes."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[int] = mapped_column(Integer, index=True)
    server: Mapped[str] = mapped_column(String(32), default="")
    text: Mapped[str] = mapped_column(Text)


# ---------- kill stats (control/stats.py) ----------


class Run(Base):
    """A server's time up, from its boot to its shutdown."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server: Mapped[str] = mapped_column(String(32), index=True)
    booted_at: Mapped[int] = mapped_column(Integer)
    ready_at: Mapped[int | None] = mapped_column(Integer)
    stopped_at: Mapped[int | None] = mapped_column(Integer)
    boot_by: Mapped[str] = mapped_column(String(64), default="")


class Person(Base):
    """Someone who plays: one or more game identities (players), linked on the fleet page."""

    __tablename__ = "people"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[int] = mapped_column(Integer)


class Player(Base):
    """A game identity: the IW4x guid, which a new install of the game makes new."""

    __tablename__ = "players"
    guid: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(64))  # the last one it played with
    first_seen: Mapped[int] = mapped_column(Integer)
    last_seen: Mapped[int] = mapped_column(Integer)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)  # "same person?": no


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("server", "log", "node_match"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    log: Mapped[str] = mapped_column(String(32))  # the server's stats file and its match number
    node_match: Mapped[int] = mapped_column(Integer)
    map: Mapped[str] = mapped_column(String(64))
    map_name: Mapped[str] = mapped_column(String(64))
    gametype: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32))  # as the mini app has them: gungame is one
    mode_name: Mapped[str] = mapped_column(String(64))
    rule: Mapped[str] = mapped_column(String(64), default="")  # weapons rule, "snipers only"
    started_at: Mapped[int] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer)


class Kill(Base):
    """A death with a person on at least one side (bot-vs-bot ones aren't kept). killer_guid is
    None when the world killed (a fall, the map's kill zone)."""

    __tablename__ = "kills"
    __table_args__ = (UniqueConstraint("server", "log", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    match_id: Mapped[int | None] = mapped_column(Integer, index=True)
    log: Mapped[str] = mapped_column(String(32))
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[int] = mapped_column(Integer, index=True)
    killer_guid: Mapped[str | None] = mapped_column(String(64), index=True)
    killer_name: Mapped[str] = mapped_column(String(64), default="")
    killer_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    killer_team: Mapped[str] = mapped_column(String(16), default="")
    killer_ping: Mapped[int | None] = mapped_column(Integer)
    victim_guid: Mapped[str] = mapped_column(String(64), index=True)
    victim_name: Mapped[str] = mapped_column(String(64))
    victim_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    victim_team: Mapped[str] = mapped_column(String(16), default="")
    victim_ping: Mapped[int | None] = mapped_column(Integer)
    weapon: Mapped[str] = mapped_column(String(64))
    means: Mapped[str] = mapped_column(String(32))  # MOD_HEAD_SHOT, MOD_MELEE, ...
    hit: Mapped[str] = mapped_column(String(32))  # body part: head, torso_upper, ..., none
    damage: Mapped[int] = mapped_column(Integer, default=0)
    headshot: Mapped[bool] = mapped_column(Boolean, default=False)
    suicide: Mapped[bool] = mapped_column(Boolean, default=False)  # by own hand or the world
    team_kill: Mapped[bool] = mapped_column(Boolean, default=False)


class PlaySession(Base):
    """A person on a server, from loading into its first map to leaving (services/ui/app.py,
    Stats: J and Q lines). until is when they were last seen there while it goes on."""

    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("server", "log", "node_session"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    log: Mapped[str] = mapped_column(String(32))  # the server's stats file and its session number
    node_session: Mapped[int] = mapped_column(Integer)
    guid: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64))
    since: Mapped[int] = mapped_column(Integer)
    until: Mapped[int] = mapped_column(Integer, index=True)


def migrate(db_path: Path) -> None:
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def connect(db_path: Path) -> sessionmaker[Session]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(db_path)
    return sessionmaker(create_engine(f"sqlite:///{db_path}"), expire_on_commit=False)
