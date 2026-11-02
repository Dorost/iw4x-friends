from datetime import UTC, datetime, timedelta

from bot.planner import best_windows, due_reminder, free_hours, heat, render_card

NL, CA = "Europe/Amsterdam", "America/Los_Angeles"
START = datetime(2026, 11, 7, 19, 0, tzinfo=UTC)  # Sat 20:00 NL, 11:00 CA


def test_card_shows_both_zones_and_people():
    text = render_card(
        START,
        [("bob", "in"), ("Amin", "in"), ("Sara", "maybe"), ("Kim", "out")],
        START - timedelta(hours=3),
        3,
    )
    assert "<b>Sat 20:00</b> NL · <b>11:00</b> CA" in text
    assert "✅ In (2): <b>Amin</b>, <b>bob</b>" in text
    assert "🤔 Maybe (1): Sara" in text
    assert "❌ Out (1): Kim" in text
    assert "need <b>1</b> more" in text


def test_card_match_on_and_started():
    people = [("A", "in"), ("B", "in"), ("C", "in")]
    assert "match on" in render_card(START, people, START - timedelta(hours=1), 3)
    assert "🏁 started" in render_card(START, people, START + timedelta(minutes=1), 3)


def test_reminders_30_then_5():
    sent: set[int] = set()
    assert due_reminder(START, sent, START - timedelta(minutes=45)) is None
    assert due_reminder(START, sent, START - timedelta(minutes=30)) == 30
    sent.add(30)
    assert due_reminder(START, sent, START - timedelta(minutes=20)) is None
    assert due_reminder(START, sent, START - timedelta(minutes=5)) == 5
    sent.add(5)
    assert due_reminder(START, sent, START - timedelta(minutes=1)) is None


def test_reminders_after_downtime_skip_the_stale_one():
    # the bot was down until 3 minutes before: only the 5 minute one, and none long after
    assert due_reminder(START, set(), START - timedelta(minutes=3)) == 5
    assert due_reminder(START, set(), START + timedelta(minutes=10)) is None


def test_overlap_nl_and_ca():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)  # Monday
    slots = {
        1: (NL, {(5, h) for h in range(18, 23)}),  # Sat 18:00 to 23:00 NL
        2: (CA, {(5, h) for h in range(9, 14)}),  # Sat 09:00 to 14:00 CA = 18:00 to 23:00 NL
        3: (CA, {(5, 11), (5, 12)}),  # Sat 11:00 to 13:00 CA = 20:00 to 22:00 NL
    }
    free = free_hours(slots, now)
    best = best_windows(free)
    assert best[0].start == datetime(2026, 11, 7, 19, 0, tzinfo=UTC)
    assert best[0].hours == 2 and best[0].people == {1, 2, 3}
    assert best[1].people == {1, 2} and best[1].hours == 2  # 18:00 to 20:00 NL first, sooner
    assert best[1].start == datetime(2026, 11, 7, 17, 0, tzinfo=UTC)


def test_overlap_follows_dst_week():
    # week of 26 Oct 2026: NL already on winter time, CA not yet, 8 hours apart
    now = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    slots = {1: (NL, {(5, 20)}), 2: (CA, {(5, 12)})}
    best = best_windows(free_hours(slots, now))
    assert len(best) == 1 and best[0].start == datetime(2026, 10, 31, 19, 0, tzinfo=UTC)
    # the next week the same local hours don't meet anymore (9 hours apart)
    assert best_windows(free_hours(slots, now + timedelta(days=7))) == []


def test_only_future_hours():
    now = datetime(2026, 11, 7, 19, 30, tzinfo=UTC)  # Sat 20:30 NL
    free = free_hours({1: (NL, {(5, 20), (5, 21)}), 2: (NL, {(5, 20), (5, 21)})}, now)
    # the hour that started is gone, the same one next Saturday is in the week
    assert sorted(free) == [
        datetime(2026, 11, 7, 20, 0, tzinfo=UTC),
        datetime(2026, 11, 14, 19, 0, tzinfo=UTC),
    ]


def test_heat_in_viewer_zone_without_viewer():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    free = free_hours({1: (NL, {(5, 20)}), 2: (CA, {(5, 11)})}, now)
    assert heat(free, CA, skip=2) == {"5-11": 1}
    assert heat(free, NL, skip=1) == {"5-20": 1}
