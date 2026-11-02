"""Times people type ("sat 20:00", "tomorrow 9pm") and times the bot shows (both zones)."""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from bot.config import ZONES

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = {
    **{d: i for i, d in enumerate(DAYS)},
    **{
        n: i
        for i, n in enumerate(
            ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        )
    },
    "tues": 1,
    "wednes": 2,
    "thur": 3,
    "thurs": 3,
}
# a zone at the end, "sat 20:00 ca": the time is in that zone instead of the sender's
ZONE_WORDS = {"nl": ZONES["NL"], "cet": ZONES["NL"], "ca": ZONES["CA"], "pt": ZONES["CA"]}
TONIGHT_HOUR = 21
TIME = re.compile(r"^(\d{1,2})(?:[:.h](\d{2}))?\s*(am|pm)?$")
IN = re.compile(r"^in\s+(\d+)\s*(m|min|mins|minutes?|h|hr|hrs|hours?)$")


class BadTime(ValueError):
    pass


def zone(name: str | None, default: str = ZONES["NL"]) -> ZoneInfo:
    try:
        return ZoneInfo(name or default)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(default)


def valid_zone(name: str) -> str | None:
    """The IANA name, case fixed ("europe/london" -> "Europe/London"), or None."""
    by_lower = {z.lower(): z for z in available_timezones()}
    return by_lower.get(name.strip().lower())


def _clock(text: str) -> tuple[int, int]:
    m = TIME.match(text)
    if not m:
        raise BadTime(text)
    hour, minute, ampm = int(m[1]), int(m[2] or 0), m[3]
    if ampm:
        if not 1 <= hour <= 12:
            raise BadTime(text)
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    if hour > 23 or minute > 59:
        raise BadTime(text)
    return hour, minute


def parse_when(text: str, tz: str, now: datetime | None = None) -> datetime:
    """The next moment the text means, in UTC. tz is the sender's zone (IANA name).

    "20:00", "8pm", "tonight", "today 21:00", "tomorrow 9pm", "sat 20:00", "saturday",
    "in 2h", "in 30m"; an "nl" or "ca" at the end reads the time in that zone."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    words = text.strip().lower().replace(",", " ").split()
    if not words:
        raise BadTime(text)
    if m := IN.match(" ".join(words)):
        n = int(m[1])
        return now + (timedelta(hours=n) if m[2].startswith("h") else timedelta(minutes=n))
    if words[-1] in ZONE_WORDS:
        tz = ZONE_WORDS[words.pop()]
    local_tz = zone(tz)
    local_now = now.astimezone(local_tz)

    day: int | None = None  # days from today
    weekday: int | None = None
    clock: tuple[int, int] | None = None
    rest = []
    for w in words:
        if w in ("today", "tonight"):
            day = 0
            if w == "tonight":
                clock = clock or (TONIGHT_HOUR, 0)
        elif w in ("tomorrow", "tmr", "tmrw"):
            day = 1
        elif w in DAY_NAMES:
            weekday = DAY_NAMES[w]
        elif w in ("at", "@"):
            continue
        else:
            rest.append(w)
    if rest:
        clock = _clock("".join(rest))  # "8 pm" -> "8pm"
    if clock is None:
        if day is None and weekday is None:
            raise BadTime(text)
        clock = (TONIGHT_HOUR, 0)

    date = local_now.date()
    if weekday is not None:
        date += timedelta(days=(weekday - local_now.weekday()) % 7)
    elif day is not None:
        date += timedelta(days=day)
    # fold=0 and normalizing through UTC handles the DST gap and overlap
    local = datetime(date.year, date.month, date.day, *clock, tzinfo=local_tz)
    when = local.astimezone(UTC)
    if when <= now and day is None:  # "20:00" after 20:00, "sat" on Saturday evening
        local += timedelta(days=7 if weekday is not None else 1)  # same wall clock time
        when = local.astimezone(UTC)
    if when <= now:
        raise BadTime(text)
    return when


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


def day_hhmm(t: datetime) -> str:
    return f"{DAYS[t.weekday()].title()} {hhmm(t)}"


def both_zones(when: datetime, bold: bool = True) -> str:
    """'Sat 20:00 NL · 11:00 CA' (the second day only when it differs)."""
    parts = []
    first = None
    for label, name in ZONES.items():
        local = when.astimezone(ZoneInfo(name))
        text = day_hhmm(local) if first is None or local.date() != first.date() else hhmm(local)
        first = first or local
        parts.append(f"<b>{text}</b> {label}" if bold else f"{text} {label}")
    return " · ".join(parts)


def until(when: datetime, now: datetime) -> str:
    mins = max(0, round((when - now).total_seconds() / 60))
    if mins < 60:
        return f"in {mins} min"
    h, m = divmod(mins, 60)
    if h < 24:
        return f"in {h}h {m:02d}m" if m else f"in {h}h"
    return f"in {h // 24}d {h % 24}h" if h % 24 else f"in {h // 24}d"
