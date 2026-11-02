"""The planner's logic, without Telegram or the database: cards, reminders and overlaps."""

import html
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from bot.config import ZONES
from bot.when import DAYS, both_zones, until, zone

STATUSES = {"in": "✅ In", "maybe": "🤔 Maybe", "out": "❌ Out"}
REMINDERS = (30, 5)  # minutes before the start
WEEK = 7 * 24


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def rsvp_keyboard(plan_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": label, "callback_data": f"rsvp:{plan_id}:{s}"}
                for s, label in STATUSES.items()
            ]
        ]
    }


def render_card(
    starts_at: datetime,
    people: list[tuple[str, str]],
    now: datetime,
    min_players: int,
    by: str = "",
) -> str:
    """The /play card: when in both zones, then who is in, maybe and out.
    people: (name, status) pairs."""
    lines = [f"🎮 <b>Tonight?</b>{f' · {esc(by)} asks' if by else ''}"]
    lines.append(f"🗓 {both_zones(starts_at)}")
    ins = sum(1 for _, s in people if s == "in")
    if starts_at > now:
        need = max(0, min_players - ins)
        tail = "🔥 <b>match on</b>" if need == 0 else f"need <b>{need}</b> more"
        lines.append(f"⏳ {until(starts_at, now)} · {tail}")
    else:
        lines.append("🏁 started")
    lines.append("")
    for status, label in STATUSES.items():
        names = sorted((n for n, s in people if s == status), key=str.lower)
        who = ", ".join(f"<b>{esc(n)}</b>" if status == "in" else esc(n) for n in names)
        lines.append(f"{label} ({len(names)}){': ' + who if names else ''}")
    return "\n".join(lines)


def match_on_text(starts_at: datetime, names: list[str], connect: str) -> str:
    who = ", ".join(f"<b>{esc(n)}</b>" for n in sorted(names, key=str.lower))
    return (
        f"🔥 <b>Match on!</b> {both_zones(starts_at)}\n"
        f"👥 {len(names)} in: {who}\n"
        f"🎯 <code>connect {esc(connect)}</code>"
    )


def due_reminder(starts_at: datetime, sent: set[int], now: datetime) -> int | None:
    """The reminder to send now (30 or 5 minutes), or None. Only the latest one that is due: after
    a restart the bot doesn't send a 30-minute reminder 2 minutes before the start."""
    left = starts_at - now
    if left <= timedelta(minutes=-5):
        return None
    for minutes in sorted(REMINDERS):  # 5 first: the closest one wins
        if left <= timedelta(minutes=minutes):
            return None if minutes in sent else minutes
    return None


def reminder_text(minutes: int, starts_at: datetime, connect: str) -> str:
    head = "⏰ <b>5 min</b> to go!" if minutes == 5 else f"⏰ <b>{minutes} min</b> to go"
    return f"{head} {both_zones(starts_at)}\n🎯 <code>connect {esc(connect)}</code>"


# ---------- availability ----------


@dataclass(frozen=True)
class Window:
    start: datetime  # UTC
    hours: int
    people: frozenset[int]

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=self.hours)


def hour_floor(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def free_hours(
    slots: dict[int, tuple[str, set[tuple[int, int]]]], now: datetime
) -> dict[datetime, set[int]]:
    """Who is free in each UTC hour of the coming week. slots: user id -> (zone, {(weekday, hour)})
    in that user's own zone, so DST moves the UTC hour, not the local one."""
    start = hour_floor(now) + timedelta(hours=1)
    end = start + timedelta(hours=WEEK)
    free: dict[datetime, set[int]] = {}
    for user, (tz, marks) in slots.items():
        z = zone(tz)
        today = now.astimezone(z).date()
        for d in range(9):  # a day either side for the zone offset
            date = today + timedelta(days=d - 1)
            for weekday, hour in marks:
                if weekday != date.weekday():
                    continue
                t = datetime(date.year, date.month, date.day, hour, tzinfo=z).astimezone(UTC)
                if start <= t < end:
                    free.setdefault(t, set()).add(user)
    return free


def best_windows(free: dict[datetime, set[int]], min_people: int = 2, top: int = 3) -> list[Window]:
    """Runs of hours with the same people free, most people first, then longest, then soonest."""
    windows: list[Window] = []
    run: Window | None = None
    for t in sorted(free):
        people = frozenset(free[t])
        if len(people) < min_people:
            continue
        if run and run.end == t and run.people == people:
            run = Window(run.start, run.hours + 1, people)
            windows[-1] = run
        else:
            run = Window(t, 1, people)
            windows.append(run)
    windows.sort(key=lambda w: (-len(w.people), -w.hours, w.start))
    return windows[:top]


def heat(free: dict[datetime, set[int]], tz: str, skip: int | None = None) -> dict[str, int]:
    """How many are free at each "weekday-hour" of the viewer's zone (leaving out the viewer)."""
    z = zone(tz)
    out: dict[str, int] = {}
    for t, people in free.items():
        n = len(people - {skip})
        if n:
            local = t.astimezone(z)
            key = f"{local.weekday()}-{local.hour}"
            out[key] = max(out.get(key, 0), n)
    return out


def window_text(w: Window, names: dict[int, str]) -> str:
    """'Sat 20:00 to 23:00 NL · 11:00 to 14:00 CA', with who."""
    parts = []
    for label, name in ZONES.items():
        a, b = w.start.astimezone(zone(name)), w.end.astimezone(zone(name))
        parts.append(f"<b>{DAYS[a.weekday()].title()} {a:%H:%M}</b> to {b:%H:%M} {label}")
    who = ", ".join(sorted((esc(names.get(u, "?")) for u in w.people), key=str.lower))
    return f"{' · '.join(parts)}\n    👥 {len(w.people)}: {who}"
