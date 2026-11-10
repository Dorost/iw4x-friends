"""Kill stats: every death on the fleet's servers with a person on at least one side, kept for
good. The game servers write them down as they happen (services/ui/app.py, Stats) and the
orchestrator takes them in every few seconds and once more before a server shuts down
(ingest). People are who play: a game identity (the IW4x guid) is new with every new install
of the game, so the fleet page links the identities of one person together (link, unlink).

What counts, as on the game's scoreboard: a kill is one of someone else on the other team (or
anyone, in free-for-all); every death counts, also by own hand, a fall or a team mate."""

import time
from collections import Counter, defaultdict

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from control.db import Kill, Match, Person, Player, Run
from control.telegram import esc

PAGE = 1000  # events asked of a server at a time
FREE_FOR_ALL = {"dm"}  # gametypes without teams: no team kills
PERIODS = {"last": None, "7d": 7, "30d": 30, "all": None}
NAME_WIDTH = 14  # in the group message's table

# ---------- names for the pages ----------

WEAPONS = {
    "m4": "M4A1", "famas": "FAMAS", "scar": "SCAR-H", "tavor": "TAR-21", "fal": "FAL",
    "m16": "M16A4", "masada": "ACR", "fn2000": "F2000", "ak47": "AK-47", "mp5k": "MP5K",
    "ump45": "UMP45", "kriss": "Vector", "p90": "P90", "uzi": "Mini-Uzi", "sa80": "L86 LSW",
    "rpd": "RPD", "mg4": "MG4", "aug": "AUG HBAR", "m240": "M240", "cheytac": "Intervention",
    "barrett": "Barrett .50cal", "wa2000": "WA2000", "m21": "M21 EBR", "pp2000": "PP2000",
    "glock": "G18", "beretta393": "M93 Raffica", "tmp": "TMP", "spas12": "SPAS-12",
    "aa12": "AA-12", "striker": "Striker", "ranger": "Ranger", "m1014": "M1014",
    "model1887": "Model 1887", "usp": "USP .45", "coltanaconda": ".44 Magnum", "beretta": "M9",
    "deserteagle": "Desert Eagle", "deserteaglegold": "Gold Desert Eagle", "at4": "AT4-HS",
    "m79": "Thumper", "rpg": "RPG-7", "javelin": "Javelin", "stinger": "Stinger",
    "riotshield": "Riot Shield", "gl": "Grenade launcher", "frag_grenade": "Frag",
    "frag_grenade_short": "Martyrdom", "semtex": "Semtex", "throwingknife": "Throwing knife",
    "claymore": "Claymore", "c4": "C4", "flash_grenade": "Flash", "concussion_grenade": "Stun",
    "ac130_105mm": "AC-130 105mm", "ac130_40mm": "AC-130 40mm", "ac130_25mm": "AC-130 25mm",
    "remotemissile_projectile": "Predator missile", "cobra_20mm": "Attack helicopter",
    "cobra_player_minigun": "Chopper gunner", "pavelow_minigun": "Pave Low",
    "harrier_20mm": "Harrier", "harrier_missile": "Harrier", "stealth_bomb": "Stealth bomber",
    "artillery": "Precision airstrike", "sentry_minigun": "Sentry gun", "nuke": "Tactical nuke",
    "destructible_car": "Car explosion", "barrel": "Barrel", "airdrop_marker": "Care package",
    "littlebird": "Care package", "none": "Nothing",
}  # fmt: skip
HIT_GROUPS = [  # body parts the game names, by group
    ("head", "Head", ("head", "helmet")),
    ("neck", "Neck", ("neck",)),
    ("torso", "Torso", ("torso_upper", "torso_lower")),
    ("arms", "Arms", ("arm", "hand")),
    ("legs", "Legs", ("leg", "foot")),
]


LONGEST_FIRST = sorted(WEAPONS, key=len, reverse=True)  # killstreaks have _ in their names


def weapon_of(weapon: str, means: str) -> str:
    """The weapon without attachments: "m4_reflex_silencer_mp" -> "m4"; a knife kill is a knife
    kill, whatever was in the hand (a riot shield's bash stays the shield's)."""
    base = weapon.removesuffix("_mp")
    if means == "MOD_MELEE" and not base.startswith("riotshield"):
        return "knife"
    if base in WEAPONS:
        return base
    for name in LONGEST_FIRST:
        if base.startswith(name + "_"):
            return name
    return base.split("_")[0] or "none"


def weapon_name(key: str) -> str:
    return "Knife" if key == "knife" else WEAPONS.get(key, key)


def hit_group(hit: str) -> str | None:
    """head, neck, torso, arms or legs; None for no body part (explosives, killstreaks, falls)."""
    for key, _, parts in HIT_GROUPS:
        if hit in parts or key in ("arms", "legs") and any(p in hit for p in parts):
            return key
    return None


def ratio(kills: int, deaths: int) -> float:
    return round(kills / deaths, 2) if deaths else float(kills)


# ---------- taking in ----------


def text(v, n: int = 64) -> str:
    return str(v if v is not None else "")[:n]


def number(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def ingest(db: Session, server: str, run_id: int | None, log: str, events: list[dict]) -> int:
    """Takes in a server's events (services/ui/app.py, Stats.events); one already in is
    skipped. How many kills were new."""
    new = 0
    for e in events:
        seq, kind = number(e.get("seq")), e.get("type")
        if seq is None:
            continue
        at = number(e.get("at")) or int(time.time())
        node_match = number(e.get("match"))
        if kind == "match" and node_match is not None:
            if not match_of(db, server, log, node_match):
                db.add(
                    Match(
                        server=server,
                        run_id=run_id,
                        log=log,
                        node_match=node_match,
                        map=text(e.get("map")),
                        map_name=text(e.get("map_name") or e.get("map")),
                        gametype=text(e.get("gametype"), 32),
                        mode=text(e.get("mode") or e.get("gametype"), 32),
                        mode_name=text(e.get("mode_name") or e.get("mode")),
                        rule=text(e.get("rule")),
                        started_at=at,
                    )
                )
                db.flush()
        elif kind == "end" and node_match is not None:
            if m := match_of(db, server, log, node_match):
                m.ended_at = at
        elif kind == "kill" and isinstance(e.get("victim"), dict):
            if db.scalar(
                select(Kill.id).where(Kill.server == server, Kill.log == log, Kill.seq == seq)
            ):
                continue
            match = match_of(db, server, log, node_match) if node_match is not None else None
            add_kill(db, server, run_id, log, seq, at, match, e)
            new += 1
    return new


def match_of(db: Session, server: str, log: str, node_match: int) -> Match | None:
    return db.scalar(
        select(Match).where(
            Match.server == server, Match.log == log, Match.node_match == node_match
        )
    )


def add_kill(db, server, run_id, log, seq, at, match: Match | None, e: dict) -> None:
    v, k = e["victim"], e.get("killer") if isinstance(e.get("killer"), dict) else None
    if k and not k.get("guid"):
        k = None
    suicide = k is None or k.get("guid") == v.get("guid")
    teams = k and v.get("team") == k.get("team") and v.get("team") in ("allies", "axis")
    team_kill = bool(not suicide and teams and (not match or match.gametype not in FREE_FOR_ALL))
    means = text(e.get("means"), 32)
    db.add(
        Kill(
            server=server,
            run_id=run_id,
            match_id=match.id if match else None,
            log=log,
            seq=seq,
            at=at,
            killer_guid=text(k.get("guid")).lower() if k else None,
            killer_name=text(k.get("name")) if k else "",
            killer_bot=bool(k and k.get("bot")),
            killer_team=text(k.get("team"), 16) if k else "world",
            killer_ping=number(k.get("ping")) if k else None,
            victim_guid=text(v.get("guid")).lower(),
            victim_name=text(v.get("name")),
            victim_bot=bool(v.get("bot")),
            victim_team=text(v.get("team"), 16),
            victim_ping=number(v.get("ping")),
            weapon=text(e.get("weapon")),
            means=means,
            hit=text(e.get("hit"), 32),
            damage=number(e.get("damage")) or 0,
            headshot=means == "MOD_HEAD_SHOT",
            suicide=suicide,
            team_kill=team_kill,
        )
    )
    for side in (v, k):
        if side and not side.get("bot") and side.get("guid"):
            seen(db, text(side["guid"]).lower(), text(side.get("name")), at)


def seen(db: Session, guid: str, name: str, at: int) -> None:
    """A game identity played: new ones are a person of their own until linked."""
    p = db.get(Player, guid)
    if p is None:
        person = Person(created_at=at)
        db.add(person)
        db.flush()
        db.add(Player(guid=guid, person_id=person.id, name=name, first_seen=at, last_seen=at))
        db.flush()
    elif at >= p.last_seen:
        p.last_seen, p.name = at, name or p.name


# ---------- people ----------


def people(db: Session) -> dict[str, int]:
    """guid -> person id."""
    return dict(db.execute(select(Player.guid, Player.person_id)).all())


def names(db: Session) -> dict[int, str]:
    """person id -> the name they last played with."""
    out, last = {}, {}
    for p in db.scalars(select(Player)):
        if p.last_seen >= last.get(p.person_id, -1):
            out[p.person_id], last[p.person_id] = p.name, p.last_seen
    return out


class NoSuchPlayer(LookupError):
    pass


def link(db: Session, guid: str, person_id: int) -> None:
    """This game identity belongs to that person (a person left with none goes)."""
    p = db.get(Player, guid)
    if not p or not db.get(Person, person_id):
        raise NoSuchPlayer(guid)
    old = p.person_id
    p.person_id, p.dismissed = person_id, False
    db.flush()
    if old != person_id and not db.scalar(select(Player.guid).where(Player.person_id == old)):
        db.execute(delete(Person).where(Person.id == old))


def unlink(db: Session, guid: str) -> None:
    """This game identity is someone of its own again."""
    p = db.get(Player, guid)
    if not p:
        raise NoSuchPlayer(guid)
    if db.scalar(select(func.count()).where(Player.person_id == p.person_id)) > 1:
        person = Person(created_at=int(time.time()))
        db.add(person)
        db.flush()
        p.person_id = person.id
    p.dismissed = True  # unlinked on purpose: not suggested again


def dismiss(db: Session, guid: str) -> None:
    p = db.get(Player, guid)
    if not p:
        raise NoSuchPlayer(guid)
    p.dismissed = True


def norm(name: str) -> str:
    return " ".join(name.lower().split())


def players_view(db: Session) -> dict:
    """The fleet page's Players: everyone with their game identities, and "same person?" for an
    identity that plays with a name someone else already had."""
    players = list(db.scalars(select(Player).order_by(Player.first_seen)))
    used: dict[str, set[str]] = defaultdict(set)  # guid -> names it played with
    for guid, name in db.execute(
        select(Kill.victim_guid, Kill.victim_name).where(~Kill.victim_bot).distinct()
    ).all():
        used[guid].add(name)
    for guid, name in db.execute(
        select(Kill.killer_guid, Kill.killer_name)
        .where(Kill.killer_guid.is_not(None), ~Kill.killer_bot)
        .distinct()
    ).all():
        used[guid].add(name)
    who = names(db)
    by_person: dict[int, list[Player]] = defaultdict(list)
    for p in players:
        by_person[p.person_id].append(p)
    suggestions = []
    for p in players:
        if p.dismissed:
            continue
        mine = {norm(n) for n in used[p.guid] | {p.name} if n.strip()}
        for q in players:  # the oldest identity of someone else with one of its names
            if q.first_seen > p.first_seen or q.person_id == p.person_id:
                continue
            if mine & {norm(n) for n in used[q.guid] | {q.name}}:
                suggestions.append(
                    {
                        "guid": p.guid,
                        "name": p.name,
                        "person": q.person_id,
                        "person_name": who.get(q.person_id, q.name),
                    }
                )
                break
    view = []
    for pid, ps in by_person.items():
        view.append(
            {
                "id": pid,
                "name": who.get(pid, ""),
                "last_seen": max(p.last_seen for p in ps),
                "players": [
                    {
                        "guid": p.guid,
                        "name": p.name,
                        "names": sorted(used[p.guid] | {p.name}, key=str.lower),
                        "first_seen": p.first_seen,
                        "last_seen": p.last_seen,
                    }
                    for p in ps
                ],
            }
        )
    view.sort(key=lambda x: -x["last_seen"])
    return {"people": view, "suggestions": suggestions}


# ---------- runs ----------


def new_run(db: Session, server: str, booted_at: int, by: str) -> int:
    run = Run(server=server, booted_at=booted_at, boot_by=by[:64])
    db.add(run)
    db.flush()
    return run.id


# ---------- what counts ----------


def counted_kill():
    """A kill on the scoreboard: of someone else, not a team mate."""
    return and_(Kill.killer_guid.is_not(None), ~Kill.suicide, ~Kill.team_kill)


def scope(server: str = "", period: str = "all", now: int | None = None, db=None):
    """The kills a page asks for: of one server or all, of a period: last (the latest run
    with kills), 7d, 30d or all."""
    where = []
    if server:
        where.append(Kill.server == server)
    days = PERIODS.get(period)
    if days:
        where.append(Kill.at >= (now or int(time.time())) - days * 86400)
    if period == "last" and db is not None:
        q = select(Kill.run_id).where(Kill.run_id.is_not(None), *where)
        last = db.scalar(q.order_by(Kill.at.desc()).limit(1))
        where.append(Kill.run_id == (last or -1))
    return where


def board(db: Session, where: list) -> list[dict]:
    """Per person: kills, deaths, K/D, headshots, matches; most kills first."""
    person = people(db)
    who = names(db)
    rows: dict[int, dict] = {}

    def row(pid: int) -> dict:
        return rows.setdefault(
            pid,
            {"id": pid, "name": who.get(pid, "?"), "kills": 0, "deaths": 0, "headshots": 0},
        )

    matches: dict[int, set] = defaultdict(set)
    q = select(Kill.killer_guid, Kill.match_id, func.count(), func.sum(Kill.headshot))
    q = q.where(counted_kill(), ~Kill.killer_bot, *where).group_by(Kill.killer_guid, Kill.match_id)
    for guid, match, n, hs in db.execute(q).all():
        if (pid := person.get(guid)) is not None:
            r = row(pid)
            r["kills"] += n
            r["headshots"] += hs or 0
            matches[pid].add(match)
    q = select(Kill.victim_guid, Kill.match_id, func.count()).where(~Kill.victim_bot, *where)
    for guid, match, n in db.execute(q.group_by(Kill.victim_guid, Kill.match_id)).all():
        if (pid := person.get(guid)) is not None:
            row(pid)["deaths"] += n
            matches[pid].add(match)
    for pid, r in rows.items():
        r["kd"] = ratio(r["kills"], r["deaths"])
        r["matches"] = len(matches[pid] - {None})
    return sorted(rows.values(), key=lambda r: (-r["kills"], -r["kd"], r["name"].lower()))


def report(db: Session, run_id: int, now: int) -> str:
    """For the group when a server shuts down: how long it ran, and everyone's kills, deaths and
    K/D of this run (bots and people alike), most kills first. "" when no person got a kill."""
    run = db.get(Run, run_id)
    where = [Kill.run_id == run_id]
    rows = [r for r in board(db, where) if r["kills"] or r["deaths"]]
    if not run or not any(r["kills"] for r in rows):
        return ""
    matches = db.scalar(select(func.count(func.distinct(Kill.match_id))).where(*where)) or 0
    minutes = max(0, now - (run.ready_at or run.booted_at)) // 60
    took = f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes} min"
    head = f"📊 {took}" + (f" · {matches} match{'es' if matches != 1 else ''}" if matches else "")
    width = min(NAME_WIDTH, max(len(r["name"]) for r in rows))
    lines = [f"{'':{width}}  {'K':>4}  {'D':>4}  {'K/D':>5}"]
    for r in rows:
        name = r["name"] if len(r["name"]) <= width else r["name"][: width - 1] + "…"
        lines.append(f"{name:<{width}}  {r['kills']:>4}  {r['deaths']:>4}  {r['kd']:>5.2f}")
    return head + "\n<pre>" + esc("\n".join(lines)) + "</pre>"


# ---------- one person ----------


def top(counter: Counter, n: int = 5) -> list[tuple]:
    return sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]


def person_view(db: Session, person_id: int, where: list, titles: dict[str, str]) -> dict:
    """Everything the mini app's player page shows, for one person, in a scope."""
    if not db.get(Person, person_id):
        raise NoSuchPlayer(str(person_id))
    person = people(db)
    who = names(db)
    guids = [g for g, pid in person.items() if pid == person_id]
    kills = list(
        db.scalars(select(Kill).where(Kill.killer_guid.in_(guids), counted_kill(), *where))
    )
    deaths = list(db.scalars(select(Kill).where(Kill.victim_guid.in_(guids), *where)))
    match_ids = {k.match_id for k in kills + deaths if k.match_id}
    matches = (
        {m.id: m for m in db.scalars(select(Match).where(Match.id.in_(match_ids)))}
        if match_ids
        else {}
    )

    def other(guid: str | None, name: str, bot: bool) -> tuple:
        """Who was on the other side: a person (by id), a bot (by name) or the world."""
        if guid is None:
            return ("world", "The world")
        if bot:
            return ("bot", name)
        pid = person.get(guid)
        return ("person", pid) if pid is not None else ("bot", name)

    def label(key: tuple) -> dict:
        kind, v = key
        if kind == "person":
            return {"kind": "person", "id": v, "name": who.get(v, "?")}
        return {"kind": kind, "name": v}

    victims, killers = Counter(), Counter()
    for k in kills:
        victims[other(k.victim_guid, k.victim_name, k.victim_bot)] += 1
    for d in deaths:
        if d.suicide:
            killers[("self", "Own hand" if d.killer_guid else "The world")] += 1
        else:
            killers[other(d.killer_guid, d.killer_name, d.killer_bot)] += 1
    weapons = Counter(weapon_of(k.weapon, k.means) for k in kills)
    hits = Counter(hit_group(k.hit) for k in kills)
    per_map: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_mode: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_server: dict[str, list] = defaultdict(lambda: [0, 0, []])
    for rows, i in ((kills, 0), (deaths, 1)):
        for k in rows:
            if (m := matches.get(k.match_id)) and m.map:  # a match the server saw no map of
                per_map[m.map_name or m.map][i] += 1
                per_mode[m.mode_name or m.mode][i] += 1
            per_server[k.server][i] += 1
            ping = k.killer_ping if i == 0 else k.victim_ping
            if ping is not None and 0 < ping < 999:
                per_server[k.server][2].append(ping)
    vs_humans = [
        sum(1 for k in kills if not k.victim_bot),
        sum(1 for d in deaths if not d.suicide and not d.killer_bot),
    ]
    vs_bots = [
        sum(1 for k in kills if k.victim_bot),
        sum(1 for d in deaths if not d.suicide and d.killer_bot),
    ]
    body = sum(n for g, n in hits.items() if g)

    def kd_rows(d: dict) -> list[dict]:
        out = [
            {"name": k, "kills": v[0], "deaths": v[1], "kd": ratio(v[0], v[1])}
            for k, v in d.items()
        ]
        return sorted(out, key=lambda r: (-(r["kills"] + r["deaths"]), r["name"]))

    return {
        "id": person_id,
        "name": who.get(person_id, "?"),
        "kills": len(kills),
        "deaths": len(deaths),
        "kd": ratio(len(kills), len(deaths)),
        "headshots": sum(k.headshot for k in kills),
        "matches": len(match_ids),
        "suicides": sum(d.suicide for d in deaths),
        "vs_humans": {"kills": vs_humans[0], "deaths": vs_humans[1]},
        "vs_bots": {"kills": vs_bots[0], "deaths": vs_bots[1]},
        "nemesis": [{**label(key), "count": n} for key, n in top(killers)],
        "victims": [{**label(key), "count": n} for key, n in top(victims)],
        "weapons": [{"name": weapon_name(w), "count": n} for w, n in top(weapons)],
        "hits": [{"key": key, "name": name, "count": hits[key]} for key, name, _ in HIT_GROUPS],
        "hits_total": body,
        "no_body_part": hits[None],
        "maps": kd_rows(per_map),
        "modes": kd_rows(per_mode),
        "servers": sorted(
            (
                {
                    "name": titles.get(s, s),
                    "kills": v[0],
                    "deaths": v[1],
                    "kd": ratio(v[0], v[1]),
                    "ping": round(sum(v[2]) / len(v[2])) if v[2] else None,
                }
                for s, v in per_server.items()
            ),
            key=lambda r: -(r["kills"] + r["deaths"]),
        ),
    }


def span(db: Session, where: list) -> dict | None:
    """When the first and the last kill of a scope were (unix seconds), or None."""
    first, last = db.execute(select(func.min(Kill.at), func.max(Kill.at)).where(*where)).one()
    return None if first is None else {"from": first, "to": last}
