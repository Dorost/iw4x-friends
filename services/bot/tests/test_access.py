import time
from datetime import UTC, datetime

import pytest
from fake import BOT_TOKEN, GROUP, make_bot, msg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.servers import BadInitData, sign_init_data, verify_init_data
from bot.web import routes

NOW = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)
AMIN, STRANGER = 11, 99


def test_init_data_roundtrip_and_tamper():
    raw = sign_init_data(BOT_TOKEN, {"id": AMIN, "first_name": "Amin"})
    assert verify_init_data(BOT_TOKEN, raw)["id"] == AMIN
    with pytest.raises(BadInitData):
        verify_init_data("654321:other-bot", raw)  # signed for another bot
    with pytest.raises(BadInitData):
        verify_init_data(BOT_TOKEN, raw.replace("Amin", "Evil"))
    old = sign_init_data(BOT_TOKEN, {"id": AMIN}, auth_date=int(time.time()) - 2 * 86400)
    with pytest.raises(BadInitData):
        verify_init_data(BOT_TOKEN, old)


@pytest.fixture
def api(tmp_path):
    bot, tg, _, _ = make_bot(tmp_path, NOW, members={AMIN})
    app = FastAPI()
    routes(app, lambda: bot)
    return TestClient(app), bot, tg


def auth(user_id: int, token: str = BOT_TOKEN) -> dict:
    return {"Authorization": "tma " + sign_init_data(token, {"id": user_id, "first_name": "X"})}


def test_api_needs_telegram_and_the_group(api):
    client, _, _ = api
    assert client.get("/bot/api/me").status_code == 401
    assert client.get("/bot/api/me", headers=auth(AMIN, "1:wrong")).status_code == 401
    assert client.get("/bot/api/me", headers=auth(STRANGER)).status_code == 403
    r = client.get("/bot/api/me", headers=auth(AMIN))
    assert r.status_code == 200 and r.json()["tz"] == "Europe/Amsterdam"


def test_api_saves_slots_and_zone(api):
    client, _, _ = api
    r = client.put("/bot/api/slots", json={"slots": [[5, 20], [5, 21], [9, 1]]}, headers=auth(AMIN))
    assert r.json()["slots"] == [[5, 20], [5, 21]]  # weekday 9 dropped
    r = client.put("/bot/api/tz", json={"tz": "america/los_angeles"}, headers=auth(AMIN))
    assert r.json()["tz"] == "America/Los_Angeles"
    assert (
        client.put("/bot/api/tz", json={"tz": "Nope/Zone"}, headers=auth(AMIN)).status_code == 400
    )


def test_dev_user_only_when_set(tmp_path):
    bot, _, _, _ = make_bot(tmp_path, NOW, dev_user_id=7)
    app = FastAPI()
    routes(app, lambda: bot)
    assert TestClient(app).get("/bot/api/me").status_code == 200


@pytest.mark.anyio
async def test_commands_only_in_our_group_and_from_members_in_private(tmp_path):
    bot, tg, _, _ = make_bot(tmp_path, NOW, members={AMIN})
    other_group = {"id": -555, "type": "supergroup", "title": "elsewhere"}
    await bot.handle(msg("/help", AMIN, "Amin", chat=other_group))
    assert tg.sent() == []
    await bot.handle(msg("/help", STRANGER, "Eve", private=True))
    assert tg.sent(STRANGER) == ["🔒 Only for members of our group."]
    await bot.handle(msg("/help", AMIN, "Amin", private=True))
    assert "Tonight?" in tg.sent(AMIN)[0]
    await bot.handle(msg("/help", STRANGER, "Eve"))  # in the group itself: anyone there
    assert "Tonight?" in tg.sent(GROUP)[0]
    await bot.handle(msg("/help@some_other_bot", AMIN, "Amin"))
    assert len(tg.sent(GROUP)) == 1


def test_page_is_served(api):
    client, _, _ = api
    r = client.get("/bot/")
    assert r.status_code == 200 and "Plan" in r.text
