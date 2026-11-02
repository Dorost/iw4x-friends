"""The bot's web side, under /bot (Caddy sends /bot/* here): the Plan mini app page and its API.
Same login as the servers' mini app: Telegram signs who opened it (initData), and only members
of the group get in."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import delete, distinct, func, select

from bot import planner
from bot.config import ZONES
from bot.core import Bot
from bot.db import Slot, User
from bot.servers import BadInitData, verify_init_data
from bot.telegram import TelegramError
from bot.when import valid_zone

PAGE = Path(__file__).with_name("plan.html")


class Slots(BaseModel):
    slots: list[tuple[int, int]]  # (weekday 0 = Monday, hour) in the user's zone


class Tz(BaseModel):
    tz: str


def routes(app: FastAPI, get_bot) -> None:
    async def user_of(request: Request) -> dict:
        bot: Bot = get_bot()
        header = request.headers.get("authorization", "")
        if not header.startswith("tma ") and bot.s.dev_user_id:  # task bot:dev in a browser
            with bot.db.begin() as db:
                if not db.get(User, bot.s.dev_user_id):
                    bot.save_user(db, {"id": bot.s.dev_user_id, "first_name": "Dev"})
            return {"id": bot.s.dev_user_id}
        else:
            if not header.startswith("tma "):
                raise HTTPException(401, "open this from Telegram")
            try:
                user = verify_init_data(bot.s.token, header[4:])
            except BadInitData as e:
                raise HTTPException(401, str(e)) from None
            try:
                member = await bot.is_member(user["id"])
            except TelegramError:
                raise HTTPException(503, "Telegram can't be reached, try again") from None
            if not member:
                raise HTTPException(403, "only for members of the group")
        with bot.db.begin() as db:
            bot.save_user(db, user)
        return user

    def view(bot: Bot, uid: int) -> dict:
        free, names = bot.free_hours()
        with bot.db.begin() as db:
            me = db.get(User, uid)
            tz = bot.tz_of(me)
            mine = sorted(
                [s.weekday, s.hour] for s in db.scalars(select(Slot).where(Slot.user_id == uid))
            )
            others = db.scalar(
                select(func.count(distinct(Slot.user_id))).where(Slot.user_id != uid)
            )
        best = [
            {
                "start": int(w.start.timestamp()),
                "hours": w.hours,
                "people": sorted((names.get(u, "?") for u in w.people), key=str.lower),
            }
            for w in planner.best_windows(free)
        ]
        return {
            "name": names.get(uid, ""),
            "tz": tz,
            "zones": ZONES,
            "slots": mine,
            "heat": planner.heat(free, tz, skip=uid),
            "others": others,
            "best": best,
            "now": int(datetime.now(UTC).timestamp()),
        }

    @app.get("/bot/", response_class=HTMLResponse)
    def page():
        return PAGE.read_text()

    @app.get("/bot/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/bot/api/me")
    async def me(request: Request):
        user = await user_of(request)
        return view(get_bot(), user["id"])

    @app.put("/bot/api/slots")
    async def put_slots(body: Slots, request: Request):
        user = await user_of(request)
        bot: Bot = get_bot()
        marks = {(d, h) for d, h in body.slots if 0 <= d <= 6 and 0 <= h <= 23}
        with bot.db.begin() as db:
            db.execute(delete(Slot).where(Slot.user_id == user["id"]))
            db.add_all(Slot(user_id=user["id"], weekday=d, hour=h) for d, h in marks)
        return view(bot, user["id"])

    @app.put("/bot/api/tz")
    async def put_tz(body: Tz, request: Request):
        user = await user_of(request)
        name = valid_zone(body.tz)
        if not name:
            raise HTTPException(400, "unknown time zone")
        bot: Bot = get_bot()
        await bot.set_tz(user["id"], name)
        return view(bot, user["id"])
