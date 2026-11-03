from datetime import UTC, datetime

import pytest

from control.db import BOOTING, OFF, PROVISIONING, RUNNING
from control.schedule import (
    BadSchedule,
    Window,
    active_window,
    decide,
    describe,
    next_window,
    occurrences,
    weekly,
)

MIN = 60
IDLE = 15 * MIN


def ts(*args) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


FRIDAY_NIGHT = weekly("nl,us", "4", "20:00", "23:30", "Europe/Amsterdam", id=1)


def test_wall_clock_time_follows_summer_time():
    # Friday 2026-07-03, summer (UTC+2), and Friday 2026-11-06, winter (UTC+1)
    summer = occurrences(FRIDAY_NIGHT, ts(2026, 7, 1, 12))
    assert Window(ts(2026, 7, 3, 18), ts(2026, 7, 3, 21, 30), 1) in summer
    winter = occurrences(FRIDAY_NIGHT, ts(2026, 11, 4, 12))
    assert Window(ts(2026, 11, 6, 19), ts(2026, 11, 6, 22, 30), 1) in winter


def test_window_past_midnight_ends_the_next_day():
    late = weekly("nl", "5", "22:00", "02:00", "Europe/Amsterdam")  # Saturday night
    [w] = [w for w in occurrences(late, ts(2026, 11, 6, 12)) if w.start == ts(2026, 11, 7, 21)]
    assert w.end == ts(2026, 11, 8, 1)


def test_the_night_summer_time_ends():
    # Sunday 2026-10-25 the clocks go from 03:00 back to 02:00: 01:00 to 04:00 is 4 hours
    night = weekly("nl", "6", "01:00", "04:00", "Europe/Amsterdam")
    [w] = [w for w in occurrences(night, ts(2026, 10, 24, 12)) if w.start == ts(2026, 10, 24, 23)]
    assert w.end - w.start == 4 * 3600


def test_active_window_counts_the_lead():
    start = ts(2026, 11, 6, 19)  # Friday 20:00 Amsterdam
    lead = 10 * MIN
    assert active_window([FRIDAY_NIGHT], "nl", start - 11 * MIN, lead) is None
    assert active_window([FRIDAY_NIGHT], "nl", start - 10 * MIN, lead) is not None
    assert active_window([FRIDAY_NIGHT], "nl", start + 3 * 3600 + 29 * MIN, lead) is not None
    assert active_window([FRIDAY_NIGHT], "nl", start + 3 * 3600 + 30 * MIN, lead) is None
    assert active_window([FRIDAY_NIGHT], "ist", start, lead) is None  # not one of its servers
    off = weekly("nl", "4", "20:00", "23:30", "Europe/Amsterdam", enabled=False)
    assert active_window([off], "nl", start, lead) is None


def test_next_window():
    w = next_window([FRIDAY_NIGHT], "us", ts(2026, 11, 4, 12))
    assert w.start == ts(2026, 11, 6, 19)


@pytest.mark.parametrize(
    "args",
    [
        ("nl", "4", "8pm", "23:00", "UTC"),
        ("nl", "4", "20:00", "24:00", "UTC"),
        ("nl", "", "20:00", "23:00", "UTC"),
        ("nl", "7", "20:00", "23:00", "UTC"),
        ("", "4", "20:00", "23:00", "UTC"),
        ("nl", "4", "20:00", "23:00", "Mars/Olympus"),
    ],
)
def test_bad_schedules(args):
    with pytest.raises(BadSchedule):
        weekly(*args)


def test_describe():
    assert describe(FRIDAY_NIGHT) == "Fri 20:00 to 23:30 (Europe/Amsterdam)"
    assert describe(weekly("nl", "5,6", "18:00", "23:00", "UTC")).startswith("Weekends 18:00")


# ---------- the rule: decide() ----------

NOW = ts(2026, 11, 6, 21)
WINDOW = Window(NOW - 3600, NOW + 3600)


def test_in_a_window_it_runs_players_or_not():
    assert decide(OFF, WINDOW, NOW, IDLE) == decide(OFF, WINDOW, NOW, IDLE)
    d = decide(OFF, WINDOW, NOW, IDLE)
    assert d.on and d.reason == "scheduled" and d.stops_at == WINDOW.end
    # nobody since it came up hours ago, but the window is on
    assert decide(RUNNING, WINDOW, NOW, IDLE, ready_at=NOW - 3 * 3600).on


def test_a_boot_nobody_joins_stops_after_idle_minutes():
    ready = NOW - 14 * MIN
    d = decide(RUNNING, None, NOW, IDLE, ready_at=ready)
    assert d.on and d.reason == "idle" and d.stops_at == ready + IDLE
    assert not decide(RUNNING, None, NOW + MIN, IDLE, ready_at=ready).on


def test_idle_counts_from_the_last_player_leaving():
    ready, left = NOW - 2 * 3600, NOW - 10 * MIN
    assert decide(RUNNING, None, NOW, IDLE, ready_at=ready, last_human_at=left).on
    assert not decide(RUNNING, None, NOW + 5 * MIN, IDLE, ready_at=ready, last_human_at=left).on


def test_a_window_ending_with_players_on_keeps_it_up():
    d = decide(RUNNING, None, NOW, IDLE, ready_at=NOW - 3 * 3600, last_human_at=NOW)
    assert d.on and d.reason == "players on"


def test_a_window_ending_with_nobody_on_stops_it_right_away():
    d = decide(RUNNING, None, NOW, IDLE, ready_at=NOW - 3 * 3600, last_human_at=NOW - 2 * 3600)
    assert not d.on


def test_shut_down_by_hand_stays_off_until_the_window_ends():
    assert not decide(OFF, WINDOW, NOW, IDLE, hold_off_until=WINDOW.end).on
    assert decide(OFF, WINDOW, WINDOW.end - 1, IDLE, hold_off_until=WINDOW.end - 2).on


def test_a_booting_server_is_left_alone():
    assert decide(PROVISIONING, None, NOW, IDLE).on
    assert decide(BOOTING, None, NOW, IDLE).on
    assert not decide(OFF, None, NOW, IDLE).on
