"""SQLite tables (SQLAlchemy) and the alembic upgrade that creates them. Times are UTC unix
seconds."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, Integer, String, Text, create_engine
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


def migrate(db_path: Path) -> None:
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def connect(db_path: Path) -> sessionmaker[Session]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(db_path)
    return sessionmaker(create_engine(f"sqlite:///{db_path}"), expire_on_commit=False)
