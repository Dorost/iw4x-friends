"""When a game server should run: schedule windows and the idle rule, without the database or
any cloud. All times are UTC unix seconds; schedules are wall clock times in their own zone, so
summer time moves the UTC time, not the local one.

The rule (README "Schedules"):
- in a schedule window (from LEAD minutes before its start) the server runs, players or not
- outside one, it runs until nobody (no human, bots don't count) has been on for IDLE minutes,
  counted from when it came up. So a boot nobody joins stops after IDLE minutes, and a window
  that ends with players on keeps going until IDLE minutes after the last one left
- shut down by hand inside a window, it stays off until that window ends
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from control.db import BOOTING, PROVISIONING, RUNNING

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class BadSchedule(ValueError):
    pass


@dataclass(frozen=True)
class Weekly:
    """A schedule as the logic needs it (db.Schedule holds the same in strings)."""

    servers: frozenset[str]
    days: frozenset[int]  # 0 = Monday
    start: tuple[int, int]
    end: tuple[int, int]
    tz: str
    enabled: bool = True
    id: int = 0


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    schedule: int = 0


def parse_hhmm(text: str) -> tuple[int, int]:
    m = HHMM.match(text.strip())
    if not m:
        raise BadSchedule(f"{text!r} is not a time like 20:00")
    return int(m[1]), int(m[2])


def valid_zone(name: str) -> str:
    if name not in available_timezones():
        raise BadSchedule(f"unknown time zone {name!r}")
    return name


def weekly(servers: str, days: str, start: str, end: str, tz: str, enabled=True, id=0) -> Weekly:
    """From the strings db.Schedule stores, or BadSchedule."""
    try:
        day_set = frozenset(int(d) for d in days.split(",") if d.strip())
    except ValueError:
        raise BadSchedule(f"days {days!r}: numbers 0 (Mon) to 6 (Sun)") from None
    if not day_set or not day_set <= set(range(7)):
        raise BadSchedule("pick at least one day")
    names = frozenset(s.strip() for s in servers.split(",") if s.strip())
    if not names:
        raise BadSchedule("pick at least one server")
    return Weekly(names, day_set, parse_hhmm(start), parse_hhmm(end), valid_zone(tz), enabled, id)


def occurrences(s: Weekly, now: int, days_back: int = 1, days_ahead: int = 8) -> list[Window]:
    """The schedule's windows that start from days_back days before now to days_ahead after."""
    try:
        z = ZoneInfo(s.tz)
    except ZoneInfoNotFoundError:
        return []
    today = datetime.fromtimestamp(now, z).date()
    out = []
    for offset in range(-days_back, days_ahead + 1):
        d = today + timedelta(days=offset)
        if d.weekday() not in s.days:
            continue
        start = _at(d, s.start, z)
        end_day = d if s.end > s.start else d + timedelta(days=1)
        out.append(Window(start, _at(end_day, s.end, z), s.id))
    return out


def _at(d: date, hm: tuple[int, int], z: ZoneInfo) -> int:
    # fold=0 and the round trip through UTC handle the summer time gap and overlap
    return int(datetime(d.year, d.month, d.day, *hm, tzinfo=z).astimezone(UTC).timestamp())


def active_window(schedules: list[Weekly], server: str, now: int, lead: int) -> Window | None:
    """The window the server is in now (counting lead seconds before its start), the one that
    ends last when several overlap."""
    hits = [
        w
        for s in schedules
        if s.enabled and server in s.servers
        for w in occurrences(s, now)
        if w.start - lead <= now < w.end
    ]
    return max(hits, key=lambda w: w.end, default=None)


def next_window(schedules: list[Weekly], server: str, now: int) -> Window | None:
    later = [
        w
        for s in schedules
        if s.enabled and server in s.servers
        for w in occurrences(s, now)
        if w.start > now
    ]
    return min(later, key=lambda w: w.start, default=None)


@dataclass(frozen=True)
class Decision:
    on: bool
    reason: str
    stops_at: int | None = None  # when the idle rule stops it, if nothing changes


def decide(
    status: str,
    window: Window | None,
    now: int,
    idle: int,
    ready_at: int | None = None,
    last_human_at: int | None = None,
    hold_off_until: int | None = None,
) -> Decision:
    """Should the server be up now? See the module docstring for the rule."""
    if hold_off_until and now < hold_off_until:
        return Decision(False, "shut down by hand until the schedule window ends")
    if window:
        return Decision(True, "scheduled", window.end)
    if status in (PROVISIONING, BOOTING):
        return Decision(True, "starting")
    if status == RUNNING:
        since = max(ready_at or now, last_human_at or 0)
        stops = since + idle
        if now < stops:
            playing = last_human_at is not None and now - last_human_at < 30
            return Decision(True, "players on" if playing else "idle", stops)
        return Decision(False, f"nobody played for {idle // 60} min")
    return Decision(False, "")


def describe(s: Weekly) -> str:
    """'Mon, Fri 20:00 to 23:30 (Europe/Amsterdam)'"""
    days = ", ".join(DAY_NAMES[d] for d in sorted(s.days))
    if s.days == frozenset(range(7)):
        days = "Every day"
    elif s.days == frozenset(range(5)):
        days = "Weekdays"
    elif s.days == frozenset({5, 6}):
        days = "Weekends"
    hm = "{:02d}:{:02d}"
    return f"{days} {hm.format(*s.start)} to {hm.format(*s.end)} ({s.tz})"
