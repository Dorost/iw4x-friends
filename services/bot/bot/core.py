"""The bot: commands, buttons, reminders and friend alerts. Telegram comes in as a Client, the
clock as now(), so tests drive it with a fake of each."""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from bot import planner
from bot.config import ZONES, Settings
from bot.db import Plan, Rsvp, Slot, User, Watch
from bot.planner import esc
from bot.servers import Joins, fetch_states, short
from bot.telegram import Client, TelegramError
from bot.when import BadTime, both_zones, parse_when, valid_zone

log = logging.getLogger("bot")

COMMANDS = [
    ("play", "Plan a match: /play sat 20:00"),
    ("when", "Best times for everyone this week"),
    ("online", "Who is on the servers now"),
    ("tz", "Your time zone"),
    ("watch", "DM me when a friend joins: /watch name"),
    ("unwatch", "Stop a friend alert"),
    ("link", "Your in-game name: /link name"),
    ("servers", "Map, mode and bots of the servers"),
    ("help", "What I can do"),
]
HELP = (
    "🎮 <b>Tonight?</b> plans our MW2 nights\n\n"
    "📣 /play <code>sat 20:00</code> · <code>tomorrow 9pm</code> · <code>tonight</code>\n"
    "🗓 /when best times this week (mark yours in 📅 Plan)\n"
    "🟢 /online who is playing now\n"
    "🌍 /tz your time zone\n"
    "🔔 /watch <code>name</code> DM when a friend joins · /unwatch\n"
    "🏷 /link <code>in-game name</code>\n"
    "🕹 /servers map, mode and bots"
)
COMMAND_MAX_AGE = 120  # older messages are left over from before a restart
MEMBER_CACHE = (600, 60)  # seconds to trust "in the group" and "not in the group"
ALERT_COOLDOWN = 1800  # one DM per watcher and friend per half hour
TZ_PICKS = [
    ("🇳🇱 Amsterdam", ZONES["NL"]),
    ("🇺🇸 Eastern", ZONES["ET"]),
    ("🇺🇸 Pacific", ZONES["PT"]),
]


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'


def aka(ingame: str, tg_name: str | None) -> str:
    """ " (Telegram name)" after an in-game name, when it says something new."""
    return f" ({esc(tg_name)})" if tg_name and tg_name.lower() != ingame.lower() else ""


class Bot:
    def __init__(
        self,
        settings: Settings,
        tg: Client,
        sessions: sessionmaker[Session],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        http: httpx.AsyncClient | None = None,
    ):
        self.s, self.tg, self.db, self.now = settings, tg, sessions, now
        self.http = http or httpx.AsyncClient()
        self.chat_id = settings.chat_id
        self.username = ""
        self.has_app = False
        self.members: dict[int, tuple[float, bool]] = {}
        self.joins = Joins()
        self.alerted: dict[tuple[int, str], float] = {}
        self.cards: dict[int, str] = {}  # plan id -> the card text Telegram shows

    # ---------- helpers ----------

    async def setup(self) -> None:
        me = await self.tg.call("getMe")
        self.username, self.has_app = me["username"], bool(me.get("has_main_web_app"))
        await self.tg.call(
            "setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS]
        )
        log.info("bot @%s for chat %s", self.username, self.chat_id)

    def app_link(self, start: str = "") -> str:
        return f"https://t.me/{self.username}?startapp{'=' + start if start else ''}"

    async def send(self, chat_id: int | str, text: str, **extra) -> dict | None:
        try:
            return await self.tg.call(
                "sendMessage",
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                link_preview_options={"is_disabled": True},
                **extra,
            )
        except TelegramError as e:
            if migrate := e.parameters.get("migrate_to_chat_id"):
                log.warning("the group has a new id, set TELEGRAM_CHAT_ID=%s", migrate)
                if str(chat_id) == self.chat_id:
                    self.chat_id = str(migrate)
                    return await self.send(self.chat_id, text, **extra)
            log.warning("not sent to %s: %s", chat_id, e.description)
            return None

    async def dm(self, user_id: int, text: str, **extra) -> bool:
        """A private message; False (and the user marked as unreachable) when Telegram refuses."""
        if await self.send(user_id, text, **extra):
            return True
        with self.db.begin() as db:
            if user := db.get(User, user_id):
                user.dm = False
        return False

    async def is_member(self, user_id: int) -> bool:
        hit = self.members.get(user_id)
        if hit and time.monotonic() - hit[0] < MEMBER_CACHE[0 if hit[1] else 1]:
            return hit[1]
        try:
            m = await self.tg.call("getChatMember", chat_id=self.chat_id, user_id=user_id)
            ok = m.get("status") in ("creator", "administrator", "member") or bool(
                m.get("is_member")
            )
        except TelegramError as e:
            if e.code != 400:  # 400: not in the group
                raise
            ok = False
        self.members[user_id] = (time.monotonic(), ok)
        return ok

    def save_user(self, db: Session, frm: dict, private: bool = False) -> User:
        user = db.get(User, frm["id"])
        name = (frm.get("first_name") or frm.get("username") or "?")[:64]
        if not user:
            user = User(id=frm["id"], name=name, dm=False)
            db.add(user)
        user.name, user.username = name, frm.get("username")
        if private:
            user.dm = True
        return user

    def tz_of(self, user: User | None) -> str:
        return (user and user.tz) or self.s.default_tz

    # ---------- updates ----------

    async def handle(self, update: dict) -> None:
        if msg := update.get("message"):
            await self.on_message(msg)
        elif cb := update.get("callback_query"):
            await self.on_callback(cb)

    async def allowed(self, chat: dict, frm: dict) -> bool:
        """The group, and private chats with members of the group."""
        if chat.get("type") == "private":
            return await self.is_member(frm["id"])
        if str(chat.get("id")) == self.chat_id:
            return True
        log.info(
            "ignored a message from another group %r, chat id %s", chat.get("title"), chat.get("id")
        )
        return False

    async def on_message(self, m: dict) -> None:
        text, frm, chat = m.get("text") or "", m.get("from") or {}, m.get("chat") or {}
        if not text.startswith("/") or not frm or frm.get("is_bot"):
            return
        if time.time() - m.get("date", time.time()) > COMMAND_MAX_AGE:
            return
        head, _, arg = text.partition(" ")
        name, _, to = head[1:].partition("@")
        if to and to.lower() != self.username.lower():
            return  # for another bot
        handler = getattr(self, f"cmd_{name.lower()}", None)
        if not handler:
            return
        if not await self.allowed(chat, frm):
            if chat.get("type") == "private":
                await self.send(chat["id"], "🔒 Only for members of our group.")
            return
        private = chat.get("type") == "private"
        with self.db.begin() as db:
            self.save_user(db, frm, private)
        await handler(m, arg.strip(), private)

    async def reply(self, m: dict, text: str, **extra) -> dict | None:
        return await self.send(
            m["chat"]["id"],
            text,
            reply_parameters={"message_id": m["message_id"], "allow_sending_without_reply": True},
            **extra,
        )

    # ---------- commands ----------

    async def cmd_start(self, m: dict, arg: str, private: bool) -> None:
        await self.reply(m, ("👋 Hi! I can DM you now.\n\n" if private else "") + HELP)

    async def cmd_help(self, m: dict, arg: str, private: bool) -> None:
        await self.reply(m, HELP)

    async def cmd_servers(self, m: dict, arg: str, private: bool) -> None:
        if not self.has_app:  # BotFather may have it by now
            me = await self.tg.call("getMe")
            self.has_app = bool(me.get("has_main_web_app"))
        if not self.has_app:
            await self.reply(m, "🕹 The mini app isn't set up in BotFather yet.")
            return
        await self.reply(
            m,
            "🕹 <b>Servers</b>: map, mode, players and bots",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "🎮 Servers", "url": self.app_link()},
                        {"text": "📅 Plan", "url": self.app_link("plan")},
                    ]
                ]
            },
        )

    async def cmd_play(self, m: dict, arg: str, private: bool) -> None:
        frm = m["from"]
        with self.db.begin() as db:
            tz = self.tz_of(db.get(User, frm["id"]))
        try:
            when = parse_when(arg or "tonight", tz, self.now())
        except BadTime:
            await self.reply(
                m,
                "🤔 When? Try <code>/play sat 20:00</code>, <code>/play tomorrow 9pm</code>, "
                "<code>/play 21:30 ca</code> or <code>/play in 2h</code>",
            )
            return
        await self.create_plan(frm["id"], when)
        if private:
            await self.reply(m, f"📣 Posted in the group: {both_zones(when)}")

    async def cmd_tz(self, m: dict, arg: str, private: bool) -> None:
        uid = m["from"]["id"]
        if arg:
            name = valid_zone(arg)
            if not name:
                await self.reply(
                    m, "🌍 Unknown zone. Try <code>/tz eastern</code> or <code>/tz pacific</code>"
                )
                return
            await self.set_tz(uid, name)
            await self.reply(m, f"🌍 Your zone: <b>{esc(name)}</b>")
            return
        with self.db.begin() as db:
            tz = self.tz_of(db.get(User, uid))
        buttons = [{"text": t, "callback_data": f"tz:{z}"} for t, z in TZ_PICKS]
        await self.reply(
            m,
            f"🌍 Your zone: <b>{esc(tz)}</b>\nPick one, or send <code>/tz Area/City</code>",
            reply_markup={
                "inline_keyboard": [buttons, [{"text": "🌐 Other", "callback_data": "tz:other"}]]
            },
        )

    async def set_tz(self, user_id: int, name: str) -> None:
        with self.db.begin() as db:
            db.get(User, user_id).tz = name

    async def cmd_when(self, m: dict, arg: str, private: bool) -> None:
        free, names = self.free_hours()
        best = planner.best_windows(free)
        plan_btn = [[{"text": "📅 Mark my times", "url": self.app_link("plan")}]]
        if not best:
            await self.reply(
                m,
                "🗓 No overlap yet. Mark the hours you're usually free in 📅 <b>Plan</b>.",
                reply_markup={"inline_keyboard": plan_btn},
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = ["🗓 <b>Best times this week</b>"]
        lines += [f"{medals[i]} {planner.window_text(w, names)}" for i, w in enumerate(best)]
        buttons = [
            {
                "text": f"📣 {medals[i]} {both_zones(w.start, bold=False).split(' · ')[0]}",
                "callback_data": f"plan:{int(w.start.timestamp())}",
            }
            for i, w in enumerate(best)
        ]
        await self.reply(
            m, "\n".join(lines), reply_markup={"inline_keyboard": [buttons] + plan_btn}
        )

    def free_hours(self) -> tuple[dict, dict[int, str]]:
        with self.db.begin() as db:
            users = {u.id: u for u in db.scalars(select(User))}
            slots: dict[int, tuple[str, set]] = {}
            for s in db.scalars(select(Slot)):
                slots.setdefault(s.user_id, (self.tz_of(users.get(s.user_id)), set()))[1].add(
                    (s.weekday, s.hour)
                )
            names = {u.id: u.name for u in users.values()}
        return planner.free_hours(slots, self.now()), names

    async def cmd_online(self, m: dict, arg: str, private: bool) -> None:
        states = await self.states()
        if not states:
            await self.reply(m, "🛰 No servers to ask.")
            return
        with self.db.begin() as db:
            linked = {u.ingame.lower(): u.name for u in db.scalars(select(User)) if u.ingame}
        lines = []
        for base, st in states.items():
            if not st:
                lines.append(f"🔴 <b>{esc(short(base))}</b> · unreachable")
                continue
            players = st.get("players") or []
            if st.get("status") != "match":
                status = {"lobby": "between matches", "offline": "server off"}.get(
                    st.get("status"), st.get("status") or "?"
                )
                lines.append(f"⚪ <b>{esc(short(base))}</b> · {esc(status)}")
                continue
            dot = "🟢" if players else "⚪"
            lines.append(
                f"{dot} <b>{esc(short(base))}</b> · {esc(st.get('map_name', ''))} · "
                f"{esc(st.get('mode_name', ''))}"
            )
            who = [f"<b>{esc(p)}</b>" + aka(p, linked.get(p.lower())) for p in players]
            bots = f" +{st['bots']} 🤖" if st.get("bots") else ""
            lines.append(f"    👥 {', '.join(who) if who else 'nobody'}{bots}")
        await self.reply(m, "\n".join(lines))

    async def cmd_link(self, m: dict, arg: str, private: bool) -> None:
        uid = m["from"]["id"]
        with self.db.begin() as db:
            user = db.get(User, uid)
            if arg:
                user.ingame = arg[:64]
            name = user.ingame
        if name:
            await self.reply(m, f"🏷 You play as <b>{esc(name)}</b>")
        else:
            await self.reply(m, "🏷 Tell me your in-game name: <code>/link YourName</code>")

    async def cmd_watch(self, m: dict, arg: str, private: bool) -> None:
        uid = m["from"]["id"]
        with self.db.begin() as db:
            if arg:
                name = self.resolve(db, arg)
                db.merge(Watch(user_id=uid, name=name.lower()))
            names = sorted(w.name for w in db.scalars(select(Watch).where(Watch.user_id == uid)))
            dm = db.get(User, uid).dm
        if not names:
            await self.reply(m, "🔔 Who? <code>/watch name</code> and I DM you when they join.")
            return
        text = "🔔 Watching: " + ", ".join(f"<b>{esc(n)}</b>" for n in names)
        extra = {}
        if not dm:
            text += "\n👉 Start me in private once so I can DM you."
            extra["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "💬 Start", "url": f"https://t.me/{self.username}?start=watch"}]
                ]
            }
        await self.reply(m, text, **extra)

    def resolve(self, db: Session, arg: str) -> str:
        """An in-game name; @username or a first name of someone who did /link works too."""
        key = arg.lstrip("@").lower()
        for u in db.scalars(select(User).where(User.ingame.is_not(None))):
            if key in ((u.username or "").lower(), u.name.lower()):
                return u.ingame
        return arg.lstrip("@")[:64]

    async def cmd_unwatch(self, m: dict, arg: str, private: bool) -> None:
        uid = m["from"]["id"]
        with self.db.begin() as db:
            if arg.lower() in ("", "all"):
                db.execute(delete(Watch).where(Watch.user_id == uid))
                text = "🔕 No more friend alerts."
            else:
                name = self.resolve(db, arg).lower()
                db.execute(delete(Watch).where(Watch.user_id == uid, Watch.name == name))
                text = f"🔕 Not watching <b>{esc(name)}</b> anymore."
        await self.reply(m, text)

    # ---------- buttons ----------

    async def on_callback(self, cb: dict) -> None:
        frm, data = cb.get("from") or {}, cb.get("data") or ""
        msg = cb.get("message") or {}
        if not await self.allowed(msg.get("chat") or {"type": "private"}, frm):
            await self.answer(cb, "🔒 Only for members of our group.")
            return
        with self.db.begin() as db:
            self.save_user(db, frm)
        kind, _, rest = data.partition(":")
        if kind == "rsvp":
            plan_id, _, status = rest.partition(":")
            await self.on_rsvp(cb, int(plan_id), status)
        elif kind == "tz":
            if rest == "other":
                await self.answer(cb, "Send /tz Area/City, like /tz Europe/London", alert=True)
            elif valid_zone(rest):
                await self.set_tz(frm["id"], rest)
                await self.answer(cb, f"🌍 {rest}")
        elif kind == "plan":
            await self.on_plan_button(cb, int(rest))
        else:
            await self.answer(cb, "")

    async def answer(self, cb: dict, text: str, alert: bool = False) -> None:
        try:
            await self.tg.call(
                "answerCallbackQuery", callback_query_id=cb["id"], text=text, show_alert=alert
            )
        except TelegramError as e:
            log.info("callback not answered: %s", e.description)

    async def on_rsvp(self, cb: dict, plan_id: int, status: str) -> None:
        if status not in planner.STATUSES:
            return
        with self.db.begin() as db:
            plan = db.get(Plan, plan_id)
            over = bool(plan) and plan.starts_at < self.now().timestamp() - 3600
            if plan and not over:
                db.merge(
                    Rsvp(
                        plan_id=plan_id,
                        user_id=cb["from"]["id"],
                        status=status,
                        at=int(time.time()),
                    )
                )
        if not plan or over:
            await self.answer(cb, "🏁 That one is over." if plan else "This plan is gone.")
            return
        await self.answer(cb, planner.STATUSES[status])
        await self.refresh_card(plan_id)
        await self.check_match_on(plan_id)

    async def on_plan_button(self, cb: dict, ts: int) -> None:
        when = datetime.fromtimestamp(ts, UTC)
        if when <= self.now():
            await self.answer(cb, "That time has passed, try /when again.")
            return
        await self.answer(cb, "📣 Posted")
        await self.create_plan(cb["from"]["id"], when)

    async def create_plan(self, user_id: int, when: datetime) -> int:
        """Posts a card in the group, with its creator in."""
        with self.db.begin() as db:
            plan = Plan(
                chat_id=int(self.chat_id),
                starts_at=int(when.timestamp()),
                created_by=user_id,
                match_on=False,
                reminded_30=False,
                reminded_5=False,
            )
            db.add(plan)
            db.flush()
            db.add(Rsvp(plan_id=plan.id, user_id=user_id, status="in", at=int(time.time())))
            plan_id = plan.id
        text, _ = self.card(plan_id)
        sent = await self.send(self.chat_id, text, reply_markup=planner.rsvp_keyboard(plan_id))
        if sent:
            with self.db.begin() as db:
                db.get(Plan, plan_id).message_id = sent["message_id"]
        await self.check_match_on(plan_id)
        return plan_id

    # ---------- plans ----------

    def card(self, plan_id: int) -> tuple[str, Plan]:
        with self.db.begin() as db:
            plan = db.get(Plan, plan_id)
            rows = db.execute(
                select(User.name, Rsvp.status).join(User).where(Rsvp.plan_id == plan_id)
            ).all()
            by = db.get(User, plan.created_by)
            text = planner.render_card(
                datetime.fromtimestamp(plan.starts_at, UTC),
                [(n, s) for n, s in rows],
                self.now(),
                self.s.min_players,
                by.name if by else "",
                self.s.default_tz,
            )
        return text, plan

    async def refresh_card(self, plan_id: int) -> None:
        text, plan = self.card(plan_id)
        if not plan.message_id or self.cards.get(plan_id) == text:
            return
        self.cards[plan_id] = text
        try:
            await self.tg.call(
                "editMessageText",
                chat_id=plan.chat_id,
                message_id=plan.message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=planner.rsvp_keyboard(plan_id),
            )
        except TelegramError as e:
            if "not modified" not in e.description:
                log.info("card %s not updated: %s", plan_id, e.description)

    def ins(self, db: Session, plan_id: int) -> list[User]:
        return list(
            db.scalars(select(User).join(Rsvp).where(Rsvp.plan_id == plan_id, Rsvp.status == "in"))
        )

    async def check_match_on(self, plan_id: int) -> None:
        with self.db.begin() as db:
            plan = db.get(Plan, plan_id)
            names = [u.name for u in self.ins(db, plan_id)]
            if plan.match_on or len(names) < self.s.min_players:
                return
            plan.match_on = True
            starts, message_id = datetime.fromtimestamp(plan.starts_at, UTC), plan.message_id
        await self.send(
            self.chat_id,
            planner.match_on_text(starts, names, self.s.connect_host),
            **({"reply_parameters": {"message_id": message_id}} if message_id else {}),
        )  # no pin: the group's own pinned message stays the pinned one

    async def tick(self) -> None:
        """Reminders 30 and 5 minutes before, to everyone who is in."""
        now = self.now()
        with self.db.begin() as db:
            plans = list(db.scalars(select(Plan).where(Plan.starts_at > now.timestamp() - 600)))
            due = []
            for p in plans:
                sent = {30} if p.reminded_30 else set()
                sent |= {5} if p.reminded_5 else set()
                starts = datetime.fromtimestamp(p.starts_at, UTC)
                minutes = planner.due_reminder(starts, sent, now)
                if minutes is None:
                    continue
                # both flags: a 5 minute reminder means the 30 one is not coming anymore
                p.reminded_5 = minutes == 5 or p.reminded_5
                p.reminded_30 = True
                people = [(u.id, u.name, u.dm) for u in self.ins(db, p.id)]
                due.append((starts, minutes, people))
        for p in plans:  # "in 2h", then "started"
            await self.refresh_card(p.id)
        for starts, minutes, people in due:
            text = planner.reminder_text(minutes, starts, self.s.connect_host)
            missed = []
            for uid, name, dm in people:
                if not (dm and await self.dm(uid, text)):
                    missed.append(mention(uid, name))
            if missed:
                await self.send(self.chat_id, f"{text}\n👥 {', '.join(missed)}")

    # ---------- servers and friend alerts ----------

    async def states(self) -> dict[str, dict | None]:
        return await fetch_states(
            self.s.servers,
            self.s.token,
            self.s.bot_id,
            self.http,
            self.s.fake_state,
            self.s.states_url,
        )

    async def watch_servers(self) -> None:
        states = await self.states()
        now = time.monotonic()
        for base, st in states.items():
            for name in self.joins.update(base, st, now):
                await self.alert(base, st, name, now)

    async def alert(self, base: str, st: dict, name: str, now: float) -> None:
        with self.db.begin() as db:
            watchers = [
                (u.id, u.ingame, u.dm)
                for u in db.scalars(select(User).join(Watch).where(Watch.name == name.lower()))
            ]
            owner = db.scalar(select(User).where(User.ingame.ilike(name)))
        who = f"<b>{esc(name)}</b>" + aka(name, owner.name if owner else None)
        where = " · ".join(x for x in (st.get("map_name"), st.get("mode_name")) if x)
        address = st.get("address") or short(base)
        text = (
            f"🟢 {who} just joined <b>{esc(short(base))}</b>"
            + (f" · {esc(where)}" if where else "")
            + f"\n🎯 <code>connect {esc(address)}</code>"
        )
        for uid, ingame, dm in watchers:
            if (ingame or "").lower() == name.lower() or not dm:
                continue
            if now - self.alerted.get((uid, name.lower()), -ALERT_COOLDOWN) < ALERT_COOLDOWN:
                continue
            if await self.dm(uid, text):
                self.alerted[(uid, name.lower())] = now

    # ---------- loops ----------

    async def poll_updates(self) -> None:
        offset, conflict = 0, False
        while True:
            try:
                updates = await self.tg.call(
                    "getUpdates",
                    wait=70,
                    offset=offset,
                    timeout=50,
                    allowed_updates=["message", "callback_query"],
                )
            except TelegramError as e:
                if e.code == 409 and not conflict:
                    log.warning(
                        "another program reads this bot's updates (an old game server "
                        "with the /servers reader?). Only one can."
                    )
                conflict = e.code == 409
                await asyncio.sleep(10 if e.code else 3)
                continue
            conflict = False
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    await self.handle(update)
                except Exception:  # one odd update must not stop the bot
                    log.exception("update %s", update.get("update_id"))

    async def every(self, seconds: float, job: Callable) -> None:
        while True:
            try:
                await job()
            except Exception:
                log.exception("%s", job.__name__)
            await asyncio.sleep(seconds)
