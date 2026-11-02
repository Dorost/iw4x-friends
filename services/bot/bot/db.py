"""SQLite tables (SQLAlchemy) and the alembic upgrade that creates them.
Times are UTC unix seconds."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

HERE = Path(__file__).resolve().parent.parent


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    name: Mapped[str] = mapped_column(String(64))
    username: Mapped[str | None] = mapped_column(String(64))
    tz: Mapped[str | None] = mapped_column(String(64))  # None: BOT_DEFAULT_TZ
    ingame: Mapped[str | None] = mapped_column(String(64))  # /link
    dm: Mapped[bool] = mapped_column(Boolean, default=False)  # started the bot in private


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    starts_at: Mapped[int] = mapped_column(Integer, index=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    match_on: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_30: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_5: Mapped[bool] = mapped_column(Boolean, default=False)


class Rsvp(Base):
    __tablename__ = "rsvps"
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(8))  # in, maybe, out
    at: Mapped[int] = mapped_column(Integer)


class Slot(Base):
    """An hour a user is usually free, in their own zone (weekday 0 = Monday)."""

    __tablename__ = "slots"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer, primary_key=True)
    hour: Mapped[int] = mapped_column(Integer, primary_key=True)


class Watch(Base):
    """user_id gets a DM when the in-game name (lower case) joins a server."""

    __tablename__ = "watches"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)


def migrate(db_path: Path) -> None:
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def connect(db_path: Path) -> sessionmaker[Session]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(db_path)
    return sessionmaker(create_engine(f"sqlite:///{db_path}"), expire_on_commit=False)
