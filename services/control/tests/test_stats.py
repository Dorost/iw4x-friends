import pytest
from fakes import at, make, posts
from sqlalchemy import func, select

from control import stats
from control.db import Kill, Match, Player, Run, connect

NOW = int(at(2026, 11, 10, 20).timestamp())
NL = "10.66.0.11"
YASHAR, AMIN, SARA = "3e23598ed222419a", "1122334455667788", "99aa99aa99aa99aa"


def side(guid, name, team="allies", bot=False, ping=50):
    return {"guid": guid, "name": name, "team": team, "bot": bot, "ping": ping}


def bot(name, team="axis"):
    return side("bot" + name.lower(), name, team, bot=True, ping=0)


def kill(seq, victim, killer, weapon="m4_mp", means="MOD_RIFLE_BULLET", hit="torso_upper", match=1):
    return {
        "seq": seq,
        "type": "kill",
        "match": match,
        "at": NOW + seq,
        "victim": victim,
        "killer": killer,
        "weapon": weapon,
        "damage": 100,
        "means": means,
        "hit": hit,
    }


def match(seq, n=1, map_="mp_rust", gametype="war"):
    return {
        "seq": seq,
        "type": "match",
        "match": n,
        "at": NOW,
        "map": map_,
        "map_name": map_.removeprefix("mp_").title(),
        "gametype": gametype,
        "mode": gametype,
        "mode_name": {"war": "Team Deathmatch", "dm": "Free-for-all"}[gametype],
        "rule": "",
    }


@pytest.fixture
def db(tmp_path):
    return connect(tmp_path / "control.db")


def evening() -> list[dict]:
    y, a = side(YASHAR, "Yashar", "allies", ping=45), side(AMIN, "Amin", "axis", ping=80)
    return [
        match(1),
        kill(2, bot("Pedro"), y, "cheytac_fmj_mp", "MOD_HEAD_SHOT", "head"),
        kill(3, bot("Pedro"), y, "cheytac_mp", "MOD_RIFLE_BULLET", "left_leg_upper"),
        kill(4, y, a, "usp_tactical_mp", "MOD_MELEE", "torso_lower"),
        kill(5, a, bot("Jose", "allies"), "frag_grenade_mp", "MOD_GRENADE_SPLASH", "none"),
        kill(6, y, None, "none", "MOD_FALLING", "none"),  # a fall
        kill(7, side(AMIN, "Amin", "axis"), side(AMIN, "Amin", "axis"), "rpg_mp", "MOD_SUICIDE"),
        kill(8, side(SARA, "Sara", "allies"), y, "m4_mp"),  # a team mate
        {"seq": 9, "type": "end", "match": 1, "at": NOW + 600},
        match(10, 2, "mp_shipment", "dm"),
        kill(11, side(SARA, "Sara", "free"), side(YASHAR, "Yashar", "free"), match=2),  # FFA
    ]


def take(db, events, run_id=1, log="log1"):
    with db.begin() as s:
        return stats.ingest(s, "nl", run_id, log, events)


def test_kills_deaths_and_what_counts(db):
    assert take(db, evening()) == 8
    assert take(db, evening()) == 0  # asked again: nothing twice
    with db.begin() as s:
        rows = {r["name"]: r for r in stats.board(s, [])}
        assert s.scalar(select(func.count()).select_from(Match)) == 2
        assert s.scalar(select(Match.ended_at).where(Match.node_match == 1)) == NOW + 600
        fall = s.scalar(select(Kill).where(Kill.seq == 6))
        assert fall.killer_guid is None and fall.suicide and fall.killer_team == "world"
        assert s.scalar(select(Kill.team_kill).where(Kill.seq == 8))
        assert not s.scalar(select(Kill.team_kill).where(Kill.seq == 11))
        assert {p.guid for p in s.scalars(select(Player))} == {YASHAR, AMIN, SARA}  # no bots
    y, a, sara = rows["Yashar"], rows["Amin"], rows["Sara"]
    # 2 bots + Sara in FFA; not the team mate
    assert (y["kills"], y["deaths"], y["headshots"], y["matches"]) == (3, 2, 1, 2)
    assert (a["kills"], a["deaths"]) == (1, 2)  # killed by a bot, and by own rocket
    assert (sara["kills"], sara["deaths"]) == (0, 2)  # the team kill counts as her death
    assert y["kd"] == 1.5 and sara["kd"] == 0
    assert list(rows) == ["Yashar", "Amin", "Sara"]


def test_the_shutdown_report(db):
    with db.begin() as s:
        run = stats.new_run(s, "nl", NOW - 3600, "test")
        s.get(Run, run).ready_at = NOW - 2 * 3600 - 14 * 60
    take(db, evening(), run_id=run)
    with db.begin() as s:
        text = stats.report(s, run, NOW)
    assert text.startswith("📊 2h 14m · 2 matches\n<pre>")
    lines = text.removesuffix("</pre>").replace("<pre>", "").split("\n")[1:]
    assert lines[0].split() == ["K", "D", "K/D"]
    assert lines[1].split() == ["Yashar", "3", "2", "1.50"]
    assert lines[2].split() == ["Amin", "1", "2", "0.50"]
    assert lines[3].split() == ["Sara", "0", "2", "0.00"]
    with db.begin() as s:  # nobody got a kill: nothing to post
        empty = stats.new_run(s, "nl", NOW, "test")
    take(db, [kill(50, side(YASHAR, "Yashar"), bot("Pedro"))], run_id=empty)
    with db.begin() as s:
        assert stats.report(s, empty, NOW) == ""


def test_one_person_on_two_installs(db):
    take(db, evening())
    new = "77777777deadbeef"  # Yashar on a new laptop
    take(db, [match(20, 3), kill(21, bot("Pedro"), side(new, "Yashar"), match=3)])
    with db.begin() as s:
        view = stats.players_view(s)
        assert len(view["people"]) == 4
        (sug,) = view["suggestions"]
        assert sug["guid"] == new and sug["person_name"] == "Yashar"
        stats.link(s, new, sug["person"])
    with db.begin() as s:
        assert stats.players_view(s)["suggestions"] == []
        rows = {r["name"]: r for r in stats.board(s, [])}
        assert rows["Yashar"]["kills"] == 4 and rows["Yashar"]["matches"] == 3
        assert len(stats.players_view(s)["people"]) == 3  # the empty person went
        stats.unlink(s, new)
    with db.begin() as s:
        view = stats.players_view(s)
        assert len(view["people"]) == 4 and view["suggestions"] == []  # not suggested again
        assert [r["kills"] for r in stats.board(s, []) if r["name"] == "Yashar"] == [3, 1]


def test_a_players_page(db):
    take(db, evening())
    with db.begin() as s:
        pid = s.get(Player, YASHAR).person_id
        amin = s.get(Player, AMIN).person_id
        v = stats.person_view(s, pid, [], {"nl": "Netherlands"})
    assert (v["kills"], v["deaths"], v["headshots"], v["matches"]) == (3, 2, 1, 2)
    assert v["vs_bots"] == {"kills": 2, "deaths": 0}
    assert v["vs_humans"] == {"kills": 1, "deaths": 1}
    assert v["nemesis"] == [
        {"kind": "person", "id": amin, "name": "Amin", "count": 1},
        {"kind": "self", "name": "The world", "count": 1},
    ]
    assert v["victims"][0] == {"kind": "bot", "name": "Pedro", "count": 2}
    assert v["weapons"] == [{"name": "Intervention", "count": 2}, {"name": "M4A1", "count": 1}]
    hits = {h["key"]: h["count"] for h in v["hits"]}
    assert hits == {"head": 1, "neck": 0, "torso": 1, "arms": 0, "legs": 1}
    assert v["maps"][0] == {"name": "Rust", "kills": 2, "deaths": 2, "kd": 1.0}
    assert {m["name"] for m in v["modes"]} == {"Team Deathmatch", "Free-for-all"}
    assert v["servers"] == [{"name": "Netherlands", "kills": 3, "deaths": 2, "kd": 1.5, "ping": 46}]


def test_scopes(db):
    take(db, evening(), run_id=1)
    take(db, [match(30, 9), kill(31, bot("Pedro"), side(AMIN, "Amin"), match=9)], run_id=2)
    with db.begin() as s:
        last = {r["name"]: r["kills"] for r in stats.board(s, stats.scope("", "last", NOW, s))}
        assert last == {"Amin": 1}
        assert stats.board(s, stats.scope("us", "all", NOW, s)) == []
        week = stats.scope("nl", "7d", NOW + 8 * 86400, s)
        assert stats.board(s, week) == []


def test_weapon_names():
    assert stats.weapon_of("m4_reflex_silencer_mp", "MOD_RIFLE_BULLET") == "m4"
    assert stats.weapon_of("ac130_105mm_mp", "MOD_PROJECTILE_SPLASH") == "ac130_105mm"
    assert stats.weapon_of("frag_grenade_short_mp", "MOD_GRENADE_SPLASH") == "frag_grenade_short"
    assert stats.weapon_of("usp_mp", "MOD_MELEE") == "knife"
    assert stats.weapon_of("riotshield_mp", "MOD_MELEE") == "riotshield"
    assert stats.weapon_of("gl_ak47_mp", "MOD_GRENADE") == "gl"
    assert stats.weapon_name("cheytac") == "Intervention"
    assert stats.hit_group("right_hand") == "arms" and stats.hit_group("left_foot") == "legs"
    assert stats.hit_group("helmet") == "head" and stats.hit_group("none") is None


# ---------- with the orchestrator ----------


@pytest.fixture
def fleet(tmp_path):
    orch, cloud, clock = make(tmp_path, at(2026, 11, 10, 20))

    async def bastion_ip():
        return "198.51.100.1"

    orch.bastion_ip = bastion_ip
    return orch, clock


async def up(orch):
    orch.nodes.up.add(NL)
    await orch.boot_now("nl", "test")
    await orch.tasks["nl"]


@pytest.mark.anyio
async def test_kills_come_in_while_it_runs_and_the_group_gets_them_at_shutdown(fleet):
    orch, clock = fleet
    await up(orch)
    run_id = orch.row("nl").run_id
    assert run_id
    for e in evening()[:4]:
        orch.nodes.add_event(NL, **{k: v for k, v in e.items() if k != "seq"})
    await orch.poll_servers()
    with orch.db.begin() as s:
        assert s.scalar(select(func.count()).select_from(Kill).where(Kill.run_id == run_id)) == 3
    assert orch.row("nl").stats_seq == 4
    for e in evening()[4:]:
        orch.nodes.add_event(NL, **{k: v for k, v in e.items() if k != "seq"})
    posts(orch)
    clock.advance(30)
    await orch.shutdown_now("nl", "test")
    await orch.tasks["nl"]
    (msg,) = posts(orch)
    assert msg.startswith("⚪ <b>NL</b> shut down (by test)\n\n📊 30 min · 2 matches")
    assert "Yashar     3     2   1.50" in msg
    row = orch.row("nl")
    assert row.run_id is None and row.stats_seq == 11
    with orch.db.begin() as s:
        assert s.get(Run, run_id).stopped_at == orch.now()


@pytest.mark.anyio
async def test_a_new_stats_file_on_the_server_is_taken_from_its_start(fleet):
    orch, _ = fleet
    await up(orch)
    for e in evening()[:3]:
        orch.nodes.add_event(NL, **{k: v for k, v in e.items() if k != "seq"})
    await orch.pull_stats("nl")
    orch.nodes.stats[NL], orch.nodes.stats_log[NL] = [], "new-disk"
    orch.nodes.add_event(NL, **match(0, 1))
    orch.nodes.add_event(NL, **{k: v for k, v in kill(0, bot("Jose"), side(SARA, "Sara")).items()})
    await orch.pull_stats("nl")
    row = orch.row("nl")
    assert (row.stats_log, row.stats_seq) == ("new-disk", 2)
    with orch.db.begin() as s:
        assert s.scalar(select(func.count()).select_from(Kill)) == 3


@pytest.mark.anyio
async def test_a_server_up_from_before_the_stats_gets_a_run(fleet):
    orch, _ = fleet
    await up(orch)
    orch.update("nl", run_id=None)
    orch.nodes.add_event(NL, **match(0))
    assert await orch.pull_stats("nl")
    run_id = orch.row("nl").run_id
    with orch.db.begin() as s:
        assert s.get(Run, run_id).ready_at == orch.row("nl").ready_at
