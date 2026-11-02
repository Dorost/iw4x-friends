from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot.when import BadTime, both_zones, parse_when, valid_zone

NL, CA = "Europe/Amsterdam", "America/Los_Angeles"
AMS, LA = ZoneInfo(NL), ZoneInfo(CA)


def local(t: datetime, z: ZoneInfo) -> str:
    return t.astimezone(z).strftime("%a %Y-%m-%d %H:%M")


# Wednesday 4 Nov 2026, 12:00 in Amsterdam (both zones on winter time)
NOW = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "tz", "want", "zone"),
    [
        ("sat 20:00", NL, "Sat 2026-11-07 20:00", AMS),
        ("saturday 8pm", NL, "Sat 2026-11-07 20:00", AMS),
        ("Sat 20.30", NL, "Sat 2026-11-07 20:30", AMS),
        ("tomorrow 21:00", NL, "Thu 2026-11-05 21:00", AMS),
        ("tomorrow 9pm", CA, "Thu 2026-11-05 21:00", LA),
        ("tonight", NL, "Wed 2026-11-04 21:00", AMS),
        ("20:00", NL, "Wed 2026-11-04 20:00", AMS),
        ("11:00", NL, "Thu 2026-11-05 11:00", AMS),  # already past today: tomorrow
        ("wed 10:00", NL, "Wed 2026-11-11 10:00", AMS),  # today but past: next week
        ("sat 11:00 ca", NL, "Sat 2026-11-07 11:00", LA),  # zone word wins over the sender's
        ("fri 12am", CA, "Fri 2026-11-06 00:00", LA),
        ("sat at 8 pm", CA, "Sat 2026-11-07 20:00", LA),
    ],
)
def test_parse(text, tz, want, zone):
    assert local(parse_when(text, tz, NOW), zone) == want


def test_in_hours_and_minutes():
    assert parse_when("in 2h", NL, NOW) == NOW + timedelta(hours=2)
    assert parse_when("in 30 min", CA, NOW) == NOW + timedelta(minutes=30)


@pytest.mark.parametrize("text", ["", "soon", "25:00", "13pm", "today 09:00", "sat 20:61"])
def test_bad(text):
    with pytest.raises(BadTime):
        parse_when(text, NL, NOW)


def test_same_card_both_zones_winter():
    t = parse_when("sat 20:00", NL, NOW)
    assert both_zones(t, bold=False) == "Sat 20:00 NL · 11:00 CA"


def test_dst_gap_week_between_eu_and_us_changes():
    # EU leaves summer time on 25 Oct 2026, the US on 1 Nov: that week NL is 8 hours ahead
    now = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
    t = parse_when("sat 20:00", NL, now)
    assert t == datetime(2026, 10, 31, 19, 0, tzinfo=UTC)
    assert both_zones(t, bold=False) == "Sat 20:00 NL · 12:00 CA"
    # a week later both are on winter time: 9 hours
    t = parse_when("sat 20:00", NL, now + timedelta(days=7))
    assert both_zones(t, bold=False) == "Sat 20:00 NL · 11:00 CA"


def test_next_week_keeps_wall_clock_over_dst():
    # Sunday 25 Oct 2026 22:00 in Amsterdam, after the change; "sun 20:00" is next Sunday 20:00
    now = datetime(2026, 10, 25, 21, 0, tzinfo=UTC)
    t = parse_when("sun 20:00", NL, now)
    assert local(t, AMS) == "Sun 2026-11-01 20:00"


def test_spring_forward_gap_is_still_a_real_time():
    # 29 Mar 2026: Amsterdam skips 02:00 to 03:00
    now = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
    t = parse_when("sun 02:30", NL, now)
    assert local(t, AMS) == "Sun 2026-03-29 03:30"


def test_california_evening_is_next_day_in_nl():
    t = parse_when("fri 19:00", CA, NOW)
    assert both_zones(t, bold=False) == "Sat 04:00 NL · Fri 19:00 CA"


def test_valid_zone():
    assert valid_zone("europe/london") == "Europe/London"
    assert valid_zone("Mars/Base") is None
