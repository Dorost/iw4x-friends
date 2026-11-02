"""A dry run of the bot against a fake Telegram: a /play card, RSVPs, match on, reminders,
/when, /online and a friend alert. Run with -s to see what the bot would post."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fake import GROUP, make_bot, msg, press

from bot.db import Plan

NOW = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)  # Wed 12:00 NL, 03:00 CA
AMIN, SARA, JOE, KIM = 11, 12, 13, 14


def show(tg, start=0):
    for method, p in tg.calls[start:]:
        if method in ("sendMessage", "editMessageText", "pinChatMessage", "answerCallbackQuery"):
            body = p.get("text", "")
            print(f"--- {method} to {p.get('chat_id', '')}\n{body}")
    return len(tg.calls)


@pytest.mark.anyio
async def test_play_rsvp_match_on_and_reminders(tmp_path):
    bot, tg, clock, sessions = make_bot(tmp_path, NOW, members={AMIN, SARA, JOE, KIM}, no_dm={KIM})
    for uid, name in [(AMIN, "Amin"), (SARA, "Sara"), (JOE, "Joe"), (KIM, "Kim")]:
        await bot.handle(msg("/start", uid, name, private=uid != KIM))  # Kim never DMs the bot
    tg.calls.clear()

    await bot.handle(msg("/tz", JOE, "Joe"))
    await bot.handle(press("tz:America/Los_Angeles", JOE, "Joe"))
    await bot.handle(msg("/play sat 20:00", AMIN, "Amin"))
    card = tg.sent(GROUP)[-1]
    assert (
        "<b>Sat 20:00</b> NL · <b>14:00</b> ET · <b>11:00</b> PT" in card
        and "✅ In (1): <b>Amin</b>" in card
    )

    await bot.handle(press("rsvp:1:in", SARA, "Sara"))
    await bot.handle(press("rsvp:1:maybe", JOE, "Joe"))
    await bot.handle(press("rsvp:1:in", KIM, "Kim"))
    edits = [p["text"] for m, p in tg.calls if m == "editMessageText"]
    assert "✅ In (3): <b>Amin</b>, <b>Kim</b>, <b>Sara</b>" in edits[-1]
    assert "🤔 Maybe (1): Joe" in edits[-1]
    match_on = [t for t in tg.sent(GROUP) if "Match on" in t]
    assert len(match_on) == 1 and "connect mw2-nl.dorost.nl" in match_on[0]
    # the group's pinned message stays: no pin, unpin or delete, edits only on the card
    touch = {"pinChatMessage", "unpinChatMessage", "unpinAllChatMessages", "deleteMessage"}
    assert not touch & set(tg.methods())
    with sessions.begin() as db:
        card_id = db.get(Plan, 1).message_id
    assert card_id and {p["message_id"] for m, p in tg.calls if m == "editMessageText"} == {card_id}
    await bot.handle(press("rsvp:1:in", JOE, "Joe"))  # a 4th: no second announcement
    assert len([t for t in tg.sent(GROUP) if "Match on" in t]) == 1
    n = show(tg)

    with sessions.begin() as db:
        starts = datetime.fromtimestamp(db.get(Plan, 1).starts_at, UTC)
    clock.t = starts - timedelta(minutes=31)
    await bot.tick()
    assert not any("to go" in t for t in tg.sent())
    clock.t = starts - timedelta(minutes=29)
    await bot.tick()
    await bot.tick()  # once only
    for uid in (AMIN, SARA, JOE):
        assert [t for t in tg.sent(uid) if "30 min" in t], uid
    group_reminders = [t for t in tg.sent(GROUP) if "30 min" in t]
    assert len(group_reminders) == 1 and 'tg://user?id=14">Kim' in group_reminders[0]
    clock.t = starts - timedelta(minutes=4)
    await bot.tick()
    assert [t for t in tg.sent(AMIN) if "5 min" in t]
    show(tg, n)


@pytest.mark.anyio
async def test_when_suggests_overlap(tmp_path):
    bot, tg, _, sessions = make_bot(
        tmp_path, datetime(2026, 11, 2, 12, 0, tzinfo=UTC), members={AMIN, JOE}
    )
    from bot.db import Slot, User

    with sessions.begin() as db:
        db.add_all(
            [
                User(id=AMIN, name="Amin", dm=True),
                User(id=JOE, name="Joe", tz="America/Los_Angeles", dm=True),
            ]
        )
        db.add_all(Slot(user_id=AMIN, weekday=5, hour=h) for h in (19, 20, 21, 22))
        db.add_all(Slot(user_id=JOE, weekday=5, hour=h) for h in (11, 12))
    await bot.handle(msg("/when", AMIN, "Amin"))
    text = tg.sent(GROUP)[-1]
    print(text)
    assert (
        "🥇 <b>Sat 20:00</b> to 22:00 NL · <b>Sat 14:00</b> to 16:00 ET"
        " · <b>Sat 11:00</b> to 13:00 PT"
    ) in text
    buttons = tg.calls[-1][1]["reply_markup"]["inline_keyboard"][0]
    await bot.handle(press(buttons[0]["callback_data"], JOE, "Joe"))
    assert "<b>Sat 20:00</b> NL · <b>14:00</b> ET · <b>11:00</b> PT" in tg.sent(GROUP)[-1]


@pytest.mark.anyio
async def test_online_and_friend_alert(tmp_path):
    state = tmp_path / "state.json"

    def servers(nl_players, status="match"):
        state.write_text(
            json.dumps(
                {
                    "mw2-nl.dorost.nl": {
                        "status": status,
                        "map_name": "Favela",
                        "mode_name": "Team Deathmatch",
                        "players": nl_players,
                        "bots": 2,
                        "address": "mw2-nl.dorost.nl",
                    },
                    "mw2.dorost.nl": {"status": "lobby", "players": []},
                }
            )
        )

    bot, tg, _, _ = make_bot(tmp_path, NOW, members={AMIN, SARA}, fake_state=state)
    servers(["Amin"])
    await bot.handle(msg("/start", SARA, "Sara", private=True))
    await bot.handle(msg("/link Amin", AMIN, "Amin"))
    await bot.handle(msg("/watch @amin", SARA, "Sara"))  # by Telegram name: the linked in-game one
    assert "Watching: <b>amin</b>" in tg.sent(GROUP)[-1]
    await bot.handle(msg("/online", SARA, "Sara"))
    online = tg.sent(GROUP)[-1]
    print(online)
    assert "🟢 <b>mw2-nl</b> · Favela · Team Deathmatch" in online and "<b>Amin</b> +2 🤖" in online
    assert "⚪ <b>mw2</b> · between matches" in online

    await bot.watch_servers()  # first look: Amin already on, no alert
    assert not tg.sent(SARA)[1:]
    servers([])
    await bot.watch_servers()
    servers([], status="lobby")  # map change: nobody counts as gone
    await bot.watch_servers()
    bot.joins.seen["https://mw2-nl.dorost.nl"].clear()  # Amin gone a while
    servers(["Amin", "Zed"])
    await bot.watch_servers()
    alerts = [t for t in tg.sent(SARA) if "just joined" in t]
    print(alerts)
    assert len(alerts) == 1 and "🟢 <b>Amin</b> just joined <b>mw2-nl</b>" in alerts[0]
    bot.joins.seen["https://mw2-nl.dorost.nl"].clear()
    await bot.watch_servers()  # again within half an hour: no second DM
    assert len([t for t in tg.sent(SARA) if "just joined" in t]) == 1


@pytest.mark.anyio
async def test_tz_picker_and_zone_words(tmp_path):
    bot, tg, _, _ = make_bot(tmp_path, NOW, members={JOE})
    await bot.handle(msg("/tz", JOE, "Joe", private=True))
    _, p = tg.calls[-1]
    buttons = [b["text"] for b in p["reply_markup"]["inline_keyboard"][0]]
    assert buttons == ["🇳🇱 Amsterdam", "🇺🇸 Eastern", "🇺🇸 Pacific"]
    await bot.handle(msg("/tz eastern", JOE, "Joe", private=True))
    assert "America/New_York" in tg.sent(JOE)[-1]
    await bot.handle(msg("/tz pt", JOE, "Joe", private=True))
    assert "America/Los_Angeles" in tg.sent(JOE)[-1]
