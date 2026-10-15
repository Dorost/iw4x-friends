# /// script
# requires-python = ">=3.13"
# dependencies = ["fastapi", "uvicorn", "psutil"]
# ///
"""Small web UI to configure and control the IW4x LAN dedicated server."""

import asyncio
import base64
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import zipfile
from functools import cache
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
# macOS: the server runs inside a CrossOver bottle (IW4X_BOTTLE is the older name of
# IW4X_SERVER_BOTTLE). Windows: it runs natively from the game folder.
# Linux: plain Wine (WINEPREFIX from the environment), game folder in game/ of the repo.
BOTTLE = os.environ.get("IW4X_SERVER_BOTTLE") or os.environ.get("IW4X_BOTTLE", "mw")
if IS_WINDOWS:
    DEFAULT_GAME_DIR = Path(r"C:\Games\Call of Duty Modern Warfare 2")
elif IS_LINUX:
    DEFAULT_GAME_DIR = Path(__file__).resolve().parent.parent.parent / "game"
else:
    DEFAULT_GAME_DIR = (Path.home() / "Library/Application Support/CrossOver/Bottles" / BOTTLE
                        / "drive_c/Program Files (x86)/Call of Duty Modern Warfare 2")
GAME_DIR = Path(os.environ.get("IW4X_SERVER_DIR", DEFAULT_GAME_DIR))
CFG = GAME_DIR / "main" / "server.cfg"
# server console log (a volume in Docker, so it survives rebuilds)
DATA_DIR = Path(os.environ.get("UI_DATA_DIR", Path(__file__).resolve().parent))
LOG = DATA_DIR / "server.log"
WINE = os.environ.get("WINE", "wine" if IS_LINUX else "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine")
PORT = int(os.environ.get("IW4X_PORT", "28960"))
UI_PORT = int(os.environ.get("UI_PORT", "8080"))
UI_HOST = os.environ.get("UI_HOST", "0.0.0.0")
UI_PASSWORD = os.environ.get("UI_PASSWORD", "")

GAMETYPE_NAMES = {
    "war": "Team Deathmatch", "dm": "Free-for-all", "dom": "Domination",
    "sd": "Search & Destroy", "koth": "Headquarters", "sab": "Sabotage",
    "ctf": "Capture the Flag", "dd": "Demolition", "arena": "Arena",
    "oneflag": "One-Flag CTF", "gtnw": "Global Thermonuclear War",
    "conf": "Kill Confirmed", "gun": "Gun Game", "infect": "Infected", "vip": "VIP",
}
MAP_NAMES = {
    "mp_afghan": "Afghan", "mp_derail": "Derail", "mp_estate": "Estate",
    "mp_favela": "Favela", "mp_highrise": "Highrise", "mp_invasion": "Invasion",
    "mp_checkpoint": "Karachi", "mp_quarry": "Quarry", "mp_rundown": "Rundown",
    "mp_rust": "Rust", "mp_boneyard": "Scrapyard", "mp_nightshift": "Skidrow",
    "mp_subbase": "Sub Base", "mp_terminal": "Terminal", "mp_underpass": "Underpass",
    "mp_brecourt": "Wasteland", "mp_nuked": "Nuketown", "mp_shipment": "Shipment",
    "mp_shipment_long": "Shipment (long)", "mp_rust_long": "Rust (long)",
    "mp_killhouse": "Killhouse", "mp_backlot": "Backlot", "mp_bog_sh": "Bog",
    "mp_bloc": "Bloc", "mp_bloc_sh": "Bloc (short)", "mp_cargoship": "Wet Work",
    "mp_cargoship_sh": "Wet Work (short)", "mp_crash_snow": "Winter Crash",
    "mp_crash_tropical": "Crash Tropical", "mp_cross_fire": "Crossfire",
    "mp_citystreets": "District", "mp_convoy": "Ambush", "mp_countdown": "Countdown",
    "mp_farm": "Downpour", "mp_pipeline": "Pipeline", "mp_showdown": "Showdown",
    "mp_village": "Village", "mp_underground": "Underground", "mp_seatown": "Seatown",
    "mp_dome": "Dome", "mp_hardhat": "Hardhat", "mp_paris": "Resistance",
    "mp_plaza2": "Arkaden", "mp_alpha": "Lockdown", "mp_bravo": "Mission",
    "mp_carentan": "Chinatown", "mp_broadcast": "Broadcast", "mp_firingrange": "Firing Range",
    "mp_estate_tropical": "Estate Tropical", "mp_fav_tropical": "Favela Tropical",
    "mp_storm_spring": "Chemical Plant", "mp_dust2": "Dust II", "mp_bakaara": "Bakaara",
    "mp_bo2carrier": "Carrier (BO2)", "mp_bo2plaza": "Plaza (BO2)", "mp_creek": "Creek",
    "mp_summit": "Summit",
}
BOT_SKILLS = {
    "0": "Mixed", "1": "1 (easiest)", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6",
    "7": "7 (hardest)", "9": "Completely random",
}
# per-mode settings (scr_<mode>_<name>), set from the Game panel; empty = the mode's default
MODE_LIMITS = ["scorelimit", "timelimit", "roundlimit", "winlimit", "roundswitch", "numlives"]
ON_OFF = {"0": "off", "1": "on"}
# Physics and movement dvars from the Fun panel: dvar -> (label, game default, hint, choices or None).
# Applied right away on Save, also mid-match.
FUN_DVARS = {
    "g_gravity": ("Gravity", "800", "lower = floatier, 200 = moon", None),
    "jump_height": ("Jump height", "39", "higher = jump onto roofs", None),
    "g_speed": ("Move speed", "190", "player run speed", None),
    "g_knockback": ("Knockback", "1000", "push from damage and explosions", None),
    "bg_fallDamageMinHeight": ("Fall damage from", "128", "fall height where damage starts", None),
    "bg_fallDamageMaxHeight": ("Fall death at", "300", "fall height that kills", None),
    "jump_slowdownEnable": ("Jump slowdown", "1", "off = keep speed after landing (bunny hop)", ON_OFF),
    "player_sprintUnlimited": ("Unlimited sprint", "0", "sprint forever", ON_OFF),
}
# Match rule dvars from the Fun panel: dvar -> (label, game default, hint, choices or None).
# The game reads these when a match starts: they apply on the next Start game or map restart.
FUN_RULES = {
    "sv_funweapons": ("Weapons", "0", "everyone gets a random weapon of this kind on every spawn (weapons.gsc)",
                      {"0": "classes (normal)", "1": "knife only", "2": "snipers only", "3": "pistols only",
                       "4": "shotguns only", "5": "rockets (refill)", "6": "riot shields", "7": "roulette (any)",
                       "8": "akimbo", "9": "one in the chamber"}),
    "sv_funammo": ("Infinite ammo", "0", "magazines refill by themselves (weapons.gsc)", ON_OFF),
    "scr_game_hardpoints": ("Killstreaks", "1", "killstreak rewards", ON_OFF),
    "scr_game_perks": ("Perks", "1", "perks from classes", ON_OFF),
    "scr_game_allowkillcam": ("Killcam", "1", "replay of your death", ON_OFF),
    "scr_hardcore": ("Hardcore", "0", "low health, no HUD", ON_OFF),
    "scr_team_fftype": ("Friendly fire", "0", "what happens when you shoot a teammate",
                        {"0": "off", "1": "on", "2": "reflect", "3": "shared"}),
    "scr_player_maxhealth": ("Health", "100", "player health, 30 = one shot kills, 300 = tank", None),
    "scr_player_healthregentime": ("Health regen (s)", "5", "seconds before health comes back", None),
}
NO_FALL_DAMAGE = {"bg_fallDamageMinHeight": "9998", "bg_fallDamageMaxHeight": "9999"}
# One-click Fun setups, in groups: group -> name -> (hint, dvars that differ from the
# defaults). They only fill the fields; the numbers stay editable before Save.
FUN_PRESETS = {
    "Movement": {
        "Normal": ("stock MW2", {}),
        "Moon": ("low gravity, floaty high jumps, soft landings",
                 {"g_gravity": "150", "jump_height": "120", **NO_FALL_DAMAGE}),
        "Super jump": ("jump onto rooftops, never die from falling",
                       {"jump_height": "350", **NO_FALL_DAMAGE}),
        "Speed demon": ("run fast, sprint forever",
                        {"g_speed": "320", "player_sprintUnlimited": "1", "jump_slowdownEnable": "0"}),
        "Bunny hop": ("keep speed between jumps",
                      {"g_speed": "230", "jump_height": "60", "jump_slowdownEnable": "0", "player_sprintUnlimited": "1"}),
        "Parkour": ("fast, high jumps, no fall damage",
                    {"g_speed": "260", "jump_height": "110", "g_gravity": "650", "jump_slowdownEnable": "0",
                     "player_sprintUnlimited": "1", **NO_FALL_DAMAGE}),
        "Heavy metal": ("double gravity, slow, short jumps",
                        {"g_gravity": "1600", "jump_height": "22", "g_speed": "150"}),
        "Glass legs": ("any small drop hurts, a big one kills",
                       {"bg_fallDamageMinHeight": "40", "bg_fallDamageMaxHeight": "120"}),
    },
    "Weapons": {
        "Knife fight": ("knives only, fast and jumpy, no killstreaks",
                        {"sv_funweapons": "1", "g_speed": "240", "jump_height": "60", "scr_game_hardpoints": "0",
                         "player_sprintUnlimited": "1"}),
        "Ninja": ("knives only, silent leaps across the map, no killcam",
                  {"sv_funweapons": "1", "g_gravity": "400", "jump_height": "150", "g_speed": "260",
                   "scr_game_allowkillcam": "0", "scr_game_hardpoints": "0", **NO_FALL_DAMAGE}),
        "Sniper duel": ("snipers only, one shot, no killstreaks",
                        {"sv_funweapons": "2", "scr_player_maxhealth": "30", "scr_game_hardpoints": "0"}),
        "Trickshot": ("snipers, floaty jumps, keep speed after landing: spin and quickscope",
                      {"sv_funweapons": "2", "g_gravity": "500", "jump_height": "100", "g_speed": "230",
                       "jump_slowdownEnable": "0", "scr_game_hardpoints": "0", **NO_FALL_DAMAGE}),
        "Pistol whip": ("pistols only, extra health", {"sv_funweapons": "3", "scr_player_maxhealth": "150"}),
        "Shotgun rush": ("shotguns only, fast, sprint forever",
                         {"sv_funweapons": "4", "g_speed": "250", "player_sprintUnlimited": "1", "jump_slowdownEnable": "0"}),
        "Akimbo madness": ("two guns at once, endless ammo, run fast",
                           {"sv_funweapons": "8", "sv_funammo": "1", "g_speed": "220", "player_sprintUnlimited": "1"}),
        "One in the chamber": ("Deagle with one bullet, every kill gives one more, one shot kills",
                               {"sv_funweapons": "9", "scr_player_maxhealth": "30", "scr_game_hardpoints": "0",
                                "scr_game_perks": "0"}),
        "Shield bash": ("riot shields only, melee to kill", {"sv_funweapons": "6", "scr_game_hardpoints": "0"}),
    },
    "Party": {
        "Rocket ride": ("explosions launch players across the map",
                        {"g_knockback": "6000", "g_gravity": "500", **NO_FALL_DAMAGE}),
        "Rocket arena": ("rockets that refill, explosions launch you, no fall damage",
                         {"sv_funweapons": "5", "g_knockback": "4000", "g_gravity": "500", "jump_height": "80",
                          "scr_game_hardpoints": "0", **NO_FALL_DAMAGE}),
        "Space snipers": ("snipers on the moon",
                          {"sv_funweapons": "2", "g_gravity": "100", "jump_height": "200", **NO_FALL_DAMAGE}),
        "Roulette": ("random weapon every spawn", {"sv_funweapons": "7"}),
        "Spray and pray": ("random weapon every spawn, ammo never runs out",
                           {"sv_funweapons": "7", "sv_funammo": "1"}),
        "Old school": ("CoD classic: no killstreaks, no perks, high jumps, no fall damage",
                       {"scr_game_hardpoints": "0", "scr_game_perks": "0", "jump_height": "64", **NO_FALL_DAMAGE}),
        "One shot": ("every hit kills, no regen",
                     {"scr_player_maxhealth": "30", "scr_player_healthregentime": "0"}),
        "Tanks": ("triple health, fast regen, slow walk",
                  {"scr_player_maxhealth": "300", "scr_player_healthregentime": "2", "g_speed": "160"}),
        "Juggernauts": ("huge health, endless ammo, slow and heavy, no knockback",
                        {"scr_player_maxhealth": "500", "sv_funammo": "1", "g_speed": "140", "g_gravity": "1200",
                         "g_knockback": "0"}),
        "Glass cannons": ("hardcore, friendly fire reflects, killcam off",
                          {"scr_hardcore": "1", "scr_team_fftype": "2", "scr_game_allowkillcam": "0"}),
        "Chaos": ("friendly fire on, rockets launch you, moon gravity",
                  {"scr_team_fftype": "1", "g_knockback": "5000", "g_gravity": "200", "jump_height": "100",
                   **NO_FALL_DAMAGE}),
    },
}
# The server always runs as a lobby (party) server: players wait in the lobby and the UI
# picks the map and mode and starts each match. The lobby never starts one by itself.
LOBBY_ARGS = ["+set", "party_enable", "1"]
# ends the match on "sv_tolobby 1", sending everyone back to the lobby
LOBBY_GSC = Path(__file__).resolve().parent / "lobby.gsc"
# weapon modes (knife only, snipers, ...) from the Fun panel's sv_funweapons
WEAPONS_GSC = Path(__file__).resolve().parent / "weapons.gsc"
# per-player actions from the Players table (wallhack, radar, kill, ...) via sv_uicmd
PLAYERS_GSC = Path(__file__).resolve().parent / "players.gsc"
PLAYER_ACTIONS = {"esp", "radar", "kill", "launch", "up", "give"}
# weapons the Players table can give: name -> weapon id
GIVE_WEAPONS = {
    "Intervention": "cheytac_mp", "Barrett .50cal": "barrett_mp", "ACR": "masada_mp", "M4A1": "m4_mp",
    "AK-47": "ak47_mp", "Vector": "kriss_mp", "UMP45": "ump45_mp", "AA-12": "aa12_mp", "SPAS-12": "spas12_mp",
    "M240": "m240_mp", "Desert Eagle": "deserteagle_mp", "Akimbo 1887s": "model1887_akimbo_mp",
    "RPG-7": "rpg_mp", "Javelin": "javelin_mp", "Riot shield": "riotshield_mp",
}
# Our own playlist file: the stock playlists set "rule party_minplayers 4" (re-applied on
# every return to the lobby), so with enough players the lobby starts the next playlist
# map by itself, and that list includes DLC maps that aren't installed.
LOBBY_PLAYLIST = "playlists_lobby.info"
# Waiting room: instead of idling in the lobby (where IW4x has no voice chat), players wait
# in a no-limits match on this map and mode until the host presses Start game
HANGOUT_MAP, HANGOUT_MODE = "mp_rust", "dm"
# restart the game server when it runs but hasn't answered for this long (it can hang at start)
WATCHDOG_SECONDS = 90
STOCK_MAPS = ["mp_afghan", "mp_boneyard", "mp_brecourt", "mp_checkpoint", "mp_derail", "mp_estate",
              "mp_favela", "mp_highrise", "mp_invasion", "mp_nightshift", "mp_quarry", "mp_rundown",
              "mp_rust", "mp_subbase", "mp_terminal", "mp_underpass"]

app = FastAPI()


@app.middleware("http")
async def require_password(request: Request, call_next):
    """HTTP basic auth when UI_PASSWORD is set (any username)."""
    if UI_PASSWORD:
        auth = request.headers.get("authorization", "")
        try:
            given = base64.b64decode(auth.removeprefix("Basic ")).decode().split(":", 1)[1]
        except (ValueError, IndexError):
            given = ""
        if not secrets.compare_digest(given.encode(), UI_PASSWORD.encode()):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="IW4x Server"'})
    return await call_next(request)


def installed_maps() -> list[dict]:
    names = {
        p.stem for p in (GAME_DIR / "zone").rglob("mp_*.ff")
        if not p.stem.endswith(("_load", "_shaders"))
    }
    custom = {
        d.name for d in (GAME_DIR / "usermaps").glob("mp_*") if (d / f"{d.name}.ff").exists()
    }
    maps = [
        {"id": n, "name": MAP_NAMES.get(n, n), "custom": n in custom and n not in names}
        for n in names | custom
    ]
    return sorted(maps, key=lambda m: m["name"])


@cache
def gametypes() -> dict[str, str]:
    """Stock modes plus any gametype script found in iwd archives or userraw."""
    ids = set(GAMETYPE_NAMES)
    pattern = re.compile(r"maps/mp/gametypes/([a-z0-9]+)\.gsc$", re.IGNORECASE)
    for iwd in [*GAME_DIR.glob("main/**/*.iwd"), *GAME_DIR.glob("userraw/*.iwd")]:
        try:
            ids |= {m[1].lower() for n in zipfile.ZipFile(iwd).namelist() if (m := pattern.search(n))}
        except zipfile.BadZipFile:
            continue
    ids |= {p.stem.lower() for p in GAME_DIR.glob("userraw/maps/mp/gametypes/*.gsc") if not p.stem.startswith("_")}
    names = {g: GAMETYPE_NAMES.get(g, g) for g in ids}
    return dict(sorted(names.items(), key=lambda kv: kv[1]))


# ---------- server.cfg ----------

def read_cfg() -> dict[str, str]:
    values = {}
    if CFG.exists():
        for line in CFG.read_text().splitlines():
            m = re.match(r'\s*seta?\s+(\S+)\s+"(.*)"', line)
            if m:
                values[m.group(1)] = m.group(2)
    return values


def config_view() -> dict:
    v = read_cfg()
    gt = v.get("g_gametype", "war")
    return {
        "hostname": v.get("sv_hostname", ""),
        "password": v.get("g_password", ""),
        "rcon_password": v.get("rcon_password", ""),
        "maxclients": int(v.get("sv_maxclients", "18")),
        "lan_only": v.get("sv_lanOnly", "1") == "1",
        "fun": {k: v.get(k, d[1]) for k, d in {**FUN_DVARS, **FUN_RULES}.items()},
        "gametype": gt,
        **{k: v.get(f"scr_{gt}_{k}", "") for k in MODE_LIMITS},
        "map": v.get("ui_mapname", ""),
        "bots_fill": int(v.get("bots_manage_fill", "0")),
        "bots_fill_mode": v.get("bots_manage_fill_mode", "0"),
        "bots_skill": v.get("bots_skill", "0"),
        "voice": v.get("sv_voice", "0") == "1",  # off on dedicated servers unless set
        "alltalk": v.get("sv_alltalk", "0") == "1",
        "deadchat": v.get("g_deadChat", "0") == "1",
        "hangout": v.get("sv_hangout_enabled", "1") == "1",
    }


class Config(BaseModel):
    hostname: str
    password: str
    rcon_password: str
    maxclients: int
    lan_only: bool
    fun: dict[str, str] = {}
    bots_fill: int
    bots_fill_mode: str
    voice: bool = True
    alltalk: bool = False
    deadchat: bool = False
    hangout: bool = True
    bots_skill: str


def clean(s: str) -> str:
    return s.replace('"', "").replace("\n", "").strip()


def fun_value(key: str, raw: str) -> str:
    """A Fun field's value: a number (or one of its choices); empty = the game's default."""
    _, default, _, choices = {**FUN_DVARS, **FUN_RULES}[key]
    val = clean(raw) or default
    if not re.fullmatch(r"-?\d+(\.\d+)?", val) or (choices and val not in choices):
        raise HTTPException(400, f"{key}: invalid value")
    return val


def write_cfg(c: Config) -> None:
    if c.bots_skill not in BOT_SKILLS or c.bots_fill_mode not in ("0", "1"):
        raise HTTPException(400, "invalid bot settings")
    v = read_cfg()
    for key in {**FUN_DVARS, **FUN_RULES}:
        v[key] = fun_value(key, c.fun.get(key, ""))
    v.update({
        "sv_hostname": clean(c.hostname),
        "sv_lanOnly": "1" if c.lan_only else "0",
        "sv_maxclients": str(max(1, min(c.maxclients, 18))),
        "party_maxplayers": str(max(1, min(c.maxclients, 18))),
        "g_password": clean(c.password),
        "rcon_password": clean(c.rcon_password),
        "bots_manage_fill": str(max(0, min(c.bots_fill, 17))),
        "bots_manage_fill_mode": c.bots_fill_mode,
        "bots_skill": c.bots_skill,
        "bots_manage_fill_kick": "1",                  # remove bots when players join or the number goes down
        "bots_main_waitForHostTime": "0",              # a dedicated server has no host: don't wait 10 s for one
        "sv_voice": "1" if c.voice else "0",          # voice chat on/off
        "sv_alltalk": "1" if c.alltalk else "0",      # 1: everyone hears everyone, 0: own team only
        "g_deadChat": "1" if c.deadchat else "0",     # dead players can talk to the living
        "sv_hangout_enabled": "1" if c.hangout else "0",  # wait in a match instead of the lobby
    })
    save_cfg(v)


def save_cfg(v: dict[str, str]) -> None:
    # always a lobby server: an old "party_enable 0" would end the lobby on "exec server.cfg"
    v["party_enable"] = "1"
    for key in ("sv_mapRotation", "lobby_playlist"):  # left over from rotation / playlist mode
        v.pop(key, None)
    lines = ["// IW4x LAN dedicated server (edited by server-ui)"]
    lines += [f'set {k} "{val}"' for k, val in v.items()]
    CFG.write_text("\n".join(lines) + "\n")


# ---------- process control ----------

def server_procs() -> list[psutil.Process]:
    """The dedicated server (and on macOS its wine wrapper); never shells that merely mention it.
    Under Wine the server's command line starts with its Windows path (C:\\... or Z:\\...)."""
    found = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if "iw4x.exe" not in cmd or "-dedicated" not in cmd:
            continue
        if IS_WINDOWS:
            real = (proc.info["name"] or "").lower() == "iw4x.exe"
        else:
            # Linux: "wine iw4x.exe ..." until Wine rewrites it to the Windows path,
            # or (Debian's Wine 8) to the bare "iw4x.exe ..."
            real = (bool(re.match(r"[A-Z]:\\", cmd)) or "winewrapper" in cmd
                    or (IS_LINUX and Path(proc.info["cmdline"][0]).name.startswith(("wine", "iw4x.exe"))))
        if real:
            found.append(proc)
    return found


def server_pids() -> list[int]:
    return [p.pid for p in server_procs()]


def install_lobby_gsc() -> None:
    """The server loads custom scripts on every map load, so this also reaches a running server."""
    for src in (LOBBY_GSC, WEAPONS_GSC, PLAYERS_GSC):
        dest = GAME_DIR / "userraw" / "scripts" / "mp" / src.name
        if GAME_DIR.exists() and (not dest.exists() or dest.read_bytes() != src.read_bytes()):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())


def install_lobby_playlist() -> bool:
    """Writes userraw/playlists_lobby.info: the stock gametype definitions plus one playlist
    per mode, whose rules never let the lobby start a match itself (needs 18 players and a
    27 hour countdown). The UI starts matches with xpartygo, which skips both.
    Clients take the mode name in the lobby and on the loading screen from the playlist
    entry, hence a playlist per mode. The server reads this file once, at start."""
    stock = GAME_DIR / "main" / "iw4x" / "x86" / "playlists_default.info"
    if not stock.exists():
        return False
    data = stock.read_bytes()
    gametypes_only = data[:m.start()] if (m := re.search(rb"^playlist ", data, re.MULTILINE)) else data
    # playlist gametype ids differ from the scripts they run (tdm -> war, ffa -> dm, hq -> koth):
    # the first definition per script is the plain mode, then come hc_ / die_ variants
    playlist_ids: dict[str, str] = {}
    for gid, script in re.findall(rb"^gametype (\w+).*?^script (\w+)", gametypes_only, re.MULTILINE | re.DOTALL):
        playlist_ids.setdefault(script.decode(), gid.decode())
    maxplayers = read_cfg().get("party_maxplayers", "18")
    playlists = []
    for i, mode in enumerate((g for g in gametypes() if g in playlist_ids), 1):
        playlists += [
            f"playlist {i}",
            f'name english "Lobby {mode}"',
            "rule party_minplayers 18",
            f"rule party_maxplayers {maxplayers}",
            "rule party_matchedplayercount 1",
            "rule party_gameStartTimerLength 99999",
            "",
            *(f"{map_id},{playlist_ids[mode]},1" for map_id in STOCK_MAPS),
            "",
        ]
    dest = GAME_DIR / "userraw" / LOBBY_PLAYLIST
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(gametypes_only + "\n".join(playlists).encode())
    return True


def lobby_playlist(mode: str) -> str:
    """Index of the lobby playlist for this mode (0-based, for the playlist command).
    A mode with no playlist definition (a custom gametype) uses Team Deathmatch's.
    Read back from the file, which is what the running server loaded."""
    try:
        text = (GAME_DIR / "userraw" / LOBBY_PLAYLIST).read_text(errors="replace")
    except OSError:
        return "0"
    lobby_modes = re.findall(r'^name english "Lobby (\w+)"', text, re.MULTILINE)
    for m in (mode, "war"):
        if m in lobby_modes:
            return str(lobby_modes.index(m))
    return "0"


def start_server() -> None:
    global last_alive
    if server_pids():
        return
    last_alive = time.monotonic()
    install_lobby_gsc()
    args = ["-dedicated", "+set", "net_port", str(PORT), "+exec", "server.cfg"]
    args += LOBBY_ARGS
    if install_lobby_playlist():
        args += ["+set", "playlistFilename", LOBBY_PLAYLIST,
                 "+playlist", lobby_playlist(read_cfg().get("g_gametype", "war"))]
    else:
        args += ["+playlist", "0"]
    if IS_WINDOWS:
        cmd = [str(GAME_DIR / "iw4x.exe"), *args]
        detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    elif IS_LINUX:
        cmd = [WINE, "iw4x.exe", *args]
        detach = {"start_new_session": True}
    else:
        cmd = [WINE, "--bottle", BOTTLE, "--cx-app", "iw4x.exe", *args]
        detach = {"start_new_session": True}
    subprocess.Popen(cmd, cwd=GAME_DIR, stdout=LOG.open("w"), stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, **detach)


def stop_server() -> None:
    for force in (False, True):
        procs = server_procs()
        if not procs:
            return
        for proc in procs:
            try:
                proc.kill() if force else proc.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(procs, timeout=15)


# ---------- network queries ----------

def udp(msg: str, timeout: float = 1.0) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    s.sendto(b"\xff\xff\xff\xff" + msg.encode() + b"\n", ("127.0.0.1", PORT))
    parts = []
    try:
        while True:
            data = s.recv(65535)[4:].decode(errors="replace")
            parts.append(data.split("\n", 1)[1] if "\n" in data else "")
            s.settimeout(0.3)
    except OSError:
        pass
    finally:
        s.close()
    return "".join(parts)


# IW4x drops rcon requests that arrive within rcon_timeout (500 ms) of the previous one
rcon_lock = threading.Lock()
last_rcon = 0.0


def rcon(cmd: str) -> str:
    global last_rcon
    with rcon_lock:
        time.sleep(max(0.0, last_rcon + 0.6 - time.monotonic()))
        try:
            return udp(f'rcon {read_cfg().get("rcon_password", "")} {cmd}')
        finally:
            last_rcon = time.monotonic()


def strip_colors(s: str) -> str:
    return re.sub(r"\^\d", "", s)


def live_status() -> dict | None:
    raw = udp("getstatus", 0.7)
    if not raw:
        return None
    info = raw.split("\n", 1)[0].split("\\")[1:]
    kv = dict(zip(info[::2], info[1::2]))
    players = []
    row = re.compile(r"^\s*(\d+)\s+(-?\d+)\s+(\S+)\s+(\S+)\s+(.*?)\s+(\d+)\s+(\S+)\s+(-?\d+)\s+(\d+)\s*$")
    status = rcon("status")  # "map: ..." during a match, "Server is not running." in the lobby
    for line in status.splitlines():
        m = row.match(line)
        if m:
            players.append({
                "num": int(m[1]), "score": m[2], "ping": m[3], "guid": m[4],
                "name": strip_colors(m[5]), "address": m[7], "bot": m[4].startswith("bot"),
            })
    in_game = status.lstrip().startswith("map:")
    if in_game and players:
        # who has wallhack / radar on (players.gsc): "3:e 5:er "
        m = re.search(r'"sv_uistate" is: "(.*?)\^7"', rcon("sv_uistate"))
        flags = dict(f.split(":", 1) for f in (m[1].split() if m else []) if ":" in f)
        for p in players:
            p["esp"] = "e" in flags.get(str(p["num"]), "")
            p["radar"] = "r" in flags.get(str(p["num"]), "")
    lobby_count = 0
    if not in_game:
        # IW4x can't list lobby members, but getinfo counts them
        info = udp("getinfo", 0.7).split("\\")[1:]
        lobby_count = int(dict(zip(info[::2], info[1::2])).get("clients", "0").strip() or 0)
    return {
        "hostname": strip_colors(kv.get("sv_hostname", "")),
        "map": kv.get("mapname", ""),
        "gametype": kv.get("g_gametype", ""),
        "version": kv.get("shortversion", ""),
        "in_game": in_game,
        "players": players,
        "lobby_count": lobby_count,
    }


def lan_ip() -> str:
    """Address of the interface that routes outward (no packet is actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def show_pick() -> None:
    """Lobby: shows the picked map and mode (saved in server.cfg) to everyone in the lobby.
    Rcon runs one command per request, so these go one by one."""
    global pick_shown
    v = read_cfg()
    if v.get("ui_mapname") and v.get("ui_gametype"):
        # switching playlist (= mode) makes the lobby pick a random map from it: switch only
        # when the mode changed, let that settle, and show the pick again on the next poll
        index = lobby_playlist(v["ui_gametype"])
        if f'"playlist" is: "{index}^7"' not in rcon("playlist"):
            rcon(f"playlist {index}")
            time.sleep(1)
            pick_shown = False
        rcon(f"ui_mapname {v['ui_mapname']}")
        rcon(f"ui_gametype {v['ui_gametype']}")
        rcon("xupdatepartystate")


# a match ending makes the lobby show a random playlist map: show the pick again once per lobby visit
pick_shown = False
hangout_active = False  # the running match is the waiting room
starting_match = threading.Event()  # Start game is passing through the lobby: no waiting room
last_alive = time.monotonic()  # last time the game server answered (watchdog)


def hangout_msg() -> str:
    v = read_cfg()
    names = {m["id"]: m["name"] for m in installed_maps()}
    mode = gametypes().get(v.get("ui_gametype", ""), v.get("ui_gametype", "?"))
    return clean(f"Next: {names.get(v.get('ui_mapname', ''), v.get('ui_mapname', '?'))} - {mode}")


def start_hangout(from_match: bool = False) -> None:
    """Lobby -> waiting room match: no time or score limit, no bots, banner from lobby.gsc.
    from_match: switch the running match straight to the waiting room map, no lobby in between."""
    global hangout_active
    if not from_match:
        rcon(f"playlist {lobby_playlist(HANGOUT_MODE)}")
        time.sleep(1)  # switching playlist re-picks the lobby map: let it settle
    for cmd in (f"ui_mapname {HANGOUT_MAP}", f"ui_gametype {HANGOUT_MODE}", f"g_gametype {HANGOUT_MODE}",
                f"set scr_{HANGOUT_MODE}_timelimit 0", f"set scr_{HANGOUT_MODE}_scorelimit 0",
                "set bots_manage_fill 0", "set sv_hangout 1", f'set sv_hangout_msg "{hangout_msg()}"',
                f"map {HANGOUT_MAP}" if from_match else "xpartygo"):
        rcon(cmd)
    hangout_active = True


# ---------- live updates ----------
# One background thread queries the server for every open page and pushes changes to
# them (SSE), instead of each page polling: rcon allows only one request per 500 ms.

POLL_SECONDS = 2.0
poked = threading.Event()  # set after an action: poll right away instead of waiting
snapshot_lock = threading.Lock()
snapshot: dict = {"version": 0, "data": None}


def changed() -> None:
    poked.set()


def poll_loop() -> None:
    while True:
        poked.clear()
        try:
            data = {"state": state(), "log": log()["lines"]}
        except Exception as e:  # keep pushing: one failed query must not stop live updates
            data = {"error": str(e)}
        if server_pids() and time.monotonic() - last_alive > WATCHDOG_SECONDS:
            print(f"game server not answering for {WATCHDOG_SECONDS} s, restarting it", flush=True)
            stop_server()
            start_server()
        with snapshot_lock:
            if data != snapshot["data"]:
                snapshot["data"] = data
                snapshot["version"] += 1
        poked.wait(POLL_SECONDS)


@app.get("/api/events")
async def events(request: Request):
    async def stream():
        seen, idle = 0, 0.0
        while not await request.is_disconnected():
            with snapshot_lock:
                version, data = snapshot["version"], snapshot["data"]
            if version != seen and data is not None:
                seen, idle = version, 0.0
                yield f"data: {json.dumps(data)}\n\n"
            elif idle >= 15:  # keeps proxies from closing a quiet stream
                idle = 0.0
                yield ": ping\n\n"
            await asyncio.sleep(0.25)
            idle += 0.25

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- API ----------

@app.get("/api/state")
def state():
    global pick_shown, hangout_active, last_alive
    live = live_status()
    if live:
        last_alive = time.monotonic()
    if live and not live["in_game"]:
        hangout_active = False
        if not pick_shown and not starting_match.is_set():
            pick_shown = True  # before show_pick, which can ask for one more showing
            if read_cfg().get("sv_hangout_enabled", "1") == "1":
                start_hangout()
            else:
                show_pick()
    else:
        pick_shown = False
    return {
        "running": bool(server_pids()),
        "live": live and {**live, "hangout": live["in_game"] and hangout_active},
        "address": f"{lan_ip()}:{PORT}",
        "config": config_view(),
        "maps": installed_maps(),
        "gametypes": gametypes(),
        "bot_skills": BOT_SKILLS,
        "give_weapons": GIVE_WEAPONS,
        "fun_dvars": FUN_DVARS,
        "fun_rules": FUN_RULES,
        "fun_presets": {**FUN_PRESETS, "Custom": custom_presets()},
    }


# ---------- custom Fun presets ----------
# Saved from the Fun panel, in the data dir (a volume in Docker, so they survive rebuilds):
# name -> (hint, dvars that differ from the defaults), the same shape as FUN_PRESETS.

PRESETS_FILE = DATA_DIR / "presets.json"


def custom_presets() -> dict[str, tuple[str, dict[str, str]]]:
    try:
        return json.loads(PRESETS_FILE.read_text())
    except (OSError, ValueError):
        return {}


class CustomPreset(BaseModel):
    name: str
    fun: dict[str, str]


@app.post("/api/presets")
def save_preset(p: CustomPreset):
    """Saves the Fun fields as a preset; an existing custom preset with that name is overwritten."""
    name = clean(p.name)
    if not 0 < len(name) <= 24:
        raise HTTPException(400, "preset name: 1 to 24 characters")
    if any(name in group for group in FUN_PRESETS.values()):
        raise HTTPException(400, f"{name} is a built-in preset, pick another name")
    changes = {}
    for key, (_, default, *_) in {**FUN_DVARS, **FUN_RULES}.items():
        if (val := fun_value(key, p.fun.get(key, ""))) != default:
            changes[key] = val
    presets = custom_presets()
    presets[name] = ("your preset", changes)
    PRESETS_FILE.write_text(json.dumps(presets, indent=1))
    return {"presets": presets}


@app.delete("/api/presets/{name}")
def delete_preset(name: str):
    presets = custom_presets()
    presets.pop(name, None)
    PRESETS_FILE.write_text(json.dumps(presets, indent=1))
    return {"presets": presets}


@app.post("/api/config")
def save_config(c: Config):
    write_cfg(c)
    if live_status():
        rcon("exec server.cfg")
    changed()
    return {"ok": True}


@app.post("/api/server/{action}")
def server_action(action: str):
    if action == "start":
        start_server()
    elif action == "stop":
        stop_server()
    elif action == "restart":
        stop_server()
        start_server()
    else:
        raise HTTPException(404)
    changed()
    return {"ok": True}


class PlayerAction(BaseModel):
    num: int
    action: str
    weapon: str = ""


@app.post("/api/player")
def player_action(a: PlayerAction):
    """Runs a Players table action in the match through players.gsc."""
    if a.action not in PLAYER_ACTIONS or (a.action == "give" and a.weapon not in GIVE_WEAPONS.values()):
        raise HTTPException(400, "invalid action")
    live = live_status()
    if not live or not live["in_game"]:
        raise HTTPException(409, "no match running")
    rcon(f'set sv_uicmd "{a.action} {a.num} {a.weapon}"')
    changed()
    return {"ok": True}


class Kick(BaseModel):
    num: int


@app.post("/api/kick")
def kick(k: Kick):
    output = rcon(f"clientkick {k.num}")
    changed()
    return {"output": output}


class Pick(BaseModel):
    map: str
    gametype: str


def save_pick(p: Pick) -> dict[str, str]:
    if p.gametype not in gametypes() or p.map not in {m["id"] for m in installed_maps()}:
        raise HTTPException(400, "invalid map or gametype")
    v = read_cfg()
    v.update({"g_gametype": p.gametype, "ui_gametype": p.gametype, "ui_mapname": p.map})
    return v


@app.post("/api/select")
def select(p: Pick):
    """Saves the picked map and mode and shows them in the lobby, so players see what's next."""
    save_cfg(save_pick(p))
    live = live_status()
    if live and not live["in_game"]:
        show_pick()
    elif live and hangout_active:
        rcon(f'set sv_hangout_msg "{hangout_msg()}"')
    changed()
    return {"ok": True}


class Game(Pick):
    scorelimit: str = ""
    timelimit: str = ""
    roundlimit: str = ""
    winlimit: str = ""
    roundswitch: str = ""
    numlives: str = ""


@app.post("/api/game")
def start_game(g: Game):
    """Lobby -> match on the chosen map and mode. Everyone in the lobby goes along, still connected."""
    global pick_shown
    v = save_pick(g)
    live = live_status()
    if not live:
        raise HTTPException(409, "server not running")
    if live["in_game"] and not hangout_active:
        raise HTTPException(409, "a match is running: send everyone to the lobby first")
    starting_match.set()  # keeps the waiting room from starting again in the lobby
    try:
        return start_match(g, v, live)
    finally:
        # the match takes a while to load and the server reports "lobby" meanwhile: no
        # waiting room until it's seen in a match again (that resets pick_shown)
        pick_shown = True
        starting_match.clear()


def start_match(g: Game, v: dict[str, str], live: dict) -> dict:
    global hangout_active
    if live["in_game"]:  # waiting room: end it, everyone goes to the lobby, then start
        rcon("sv_tolobby 1")
        for _ in range(60):
            time.sleep(1)
            if (now := live_status()) and not now["in_game"]:
                break
        else:
            raise HTTPException(504, "the waiting room did not end, try again")
        hangout_active = False
    rcon("set sv_hangout 0")
    for limit in MODE_LIMITS:
        key, val = f"scr_{g.gametype}_{limit}", getattr(g, limit)
        if clean(val):
            v[key] = clean(val)
        else:
            v.pop(key, None)
            rcon(f"reset {key}")  # back to the mode's default
    save_cfg(v)
    rcon(f"playlist {lobby_playlist(g.gametype)}")
    time.sleep(1)  # switching playlist re-picks the lobby map: let it settle, then set ours
    rcon("exec server.cfg")
    output = rcon("xpartygo")
    changed()
    return {"output": output}


@app.post("/api/lobby")
def to_lobby():
    """Match -> lobby: lobby.gsc ends the match, players stay connected and wait in the lobby.
    With the waiting room on, the match switches straight to it instead (no scoreboard or lobby)."""
    global pick_shown, hangout_active
    live = live_status()
    if not live or not live["in_game"]:
        raise HTTPException(409, "no match running")
    if read_cfg().get("sv_hangout_enabled", "1") != "1":
        output = rcon("sv_tolobby 1")
        changed()
        return {"output": output}
    starting_match.set()  # the map load can show as "lobby": don't start the waiting room twice
    try:
        start_hangout(from_match=True)
        time.sleep(5)  # the old match still answers for a moment
        for _ in range(40):
            if (now := live_status()) and now["in_game"]:
                hangout_active = True  # the poll loop clears it while the map loads
                break
            time.sleep(1)
    finally:
        # if the switch fell back to the lobby, the next poll starts the waiting room from there
        pick_shown = False
        starting_match.clear()
    changed()
    return {"output": ""}


MATCH_COMMANDS = {
    "fast_restart": "fast_restart",  # restart the match on the same map, no reload
    "map_restart": "map_restart",  # reload the map, then restart the match
}


@app.post("/api/match/{action}")
def match_action(action: str):
    """Restart the running match; players stay connected."""
    if action not in MATCH_COMMANDS:
        raise HTTPException(404)
    live = live_status()
    if not live or not live["in_game"]:
        raise HTTPException(409, "no match running")
    output = rcon(MATCH_COMMANDS[action])
    changed()
    return {"output": output}


class Command(BaseModel):
    cmd: str


@app.post("/api/rcon")
def raw_rcon(c: Command):
    output = rcon(c.cmd)
    changed()
    return {"output": output}


@app.get("/api/log")
def log():
    if not LOG.exists():
        return {"lines": ["(no log yet: start the server from this page to capture its console)"]}
    return {"lines": LOG.read_text(errors="replace").splitlines()[-300:]}


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "index.html").read_text()


if __name__ == "__main__":
    install_lobby_gsc()
    if os.environ.get("AUTOSTART") == "1":
        start_server()
    threading.Thread(target=poll_loop, daemon=True).start()
    # an open live-update stream would otherwise keep the server from shutting down
    uvicorn.run(app, host=UI_HOST, port=UI_PORT, timeout_graceful_shutdown=2)
