# /// script
# requires-python = ">=3.13"
# dependencies = ["fastapi", "uvicorn", "psutil", "pillow"]
# ///
"""Small web UI to configure and control the IW4x LAN dedicated server."""

import asyncio
import base64
import hashlib
import hmac
import html
import io
import json
import os
import queue
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from functools import cache
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from PIL import Image
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
# login password for the web UI; empty = no login
UI_PASSWORD = os.environ.get("UI_PASSWORD", "")
# name players connect to (the VPS domain); empty = this machine's LAN address
JOIN_HOST = os.environ.get("JOIN_HOST", "")

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
# IW4x DLC maps that need textures from MW2's paid DLC packs (iw_dlc1_00.iwd / iw_dlc2_00.iwd),
# which IW4x doesn't ship: clients without them get "Couldn't load image" and freeze.
# mp_backlot: the dedicated server fails to load it ("Invalid trigger index") and drops to the lobby
BROKEN_MAPS = {"mp_crash_tropical", "mp_hardhat", "mp_backlot"}
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
                       "8": "akimbo", "9": "one in the chamber", "10": "AC-130 cannons", "11": "semtex only",
                       "12": "bomberman (C4 / claymores)", "13": "throwing knives", "14": "noob tubes",
                       "15": "gun game", "16": "gun game extended"}),
    "sv_funammo": ("Infinite ammo", "0", "magazine stays full, no reloading, for everyone (weapons.gsc)", ON_OFF),
    "sv_funlottery": ("AC-130 lottery", "0", "every spawn has this chance to come with an AC-130 cannon (weapons.gsc)",
                      {"0": "off", "3": "1 in 3", "6": "1 in 6", "10": "1 in 10"}),
    "sv_funrotate": ("AC-130 rotation", "0", "one player at a time holds the AC-130 cannon this long, or until they die, then it moves on (weapons.gsc)",
                     {"0": "off", "30": "30s each", "60": "60s each", "120": "2 min each"}),
    "sv_funpotato": ("Hot potato", "0", "one random player carries a bomb: get a kill to pass it on, or explode (weapons.gsc)",
                     {"0": "off", "15": "15s fuse", "20": "20s fuse", "30": "30s fuse"}),
    "sv_funairkill": ("Air support per kill", "0", "kills hand out a random air killstreak that stacks up: predator, harrier, choppers, AC-130 (weapons.gsc)",
                      {"0": "off", "1": "every kill", "2": "every 2 kills", "3": "every 3 kills"}),
    "sv_sdroulette": ("S&D round roulette", "0", "Search & Destroy: every round gets a random modifier (knife round, snipers, moon, ...), replacing Weapons (sdfun.gsc)", ON_OFF),
    "sv_sdclutch": ("S&D clutch mode", "0", "Search & Destroy: the last player alive on a team gets radar, endless ammo and extra speed (sdfun.gsc)", ON_OFF),
    "sv_sdhunted": ("S&D hunted carrier", "0", "Search & Destroy: the bomb carrier shows on the enemy minimap but runs faster (sdfun.gsc)", ON_OFF),
    "sv_sdrevive": ("S&D revive", "0", "Search & Destroy: stand on a dead teammate's green marker for 3s to bring them back, once per round (sdfun.gsc)", ON_OFF),
    "scr_game_hardpoints": ("Killstreaks", "1", "killstreak rewards", ON_OFF),
    "scr_game_perks": ("Perks", "1", "perks from classes", ON_OFF),
    "scr_game_allowkillcam": ("Killcam", "1", "replay of your death", ON_OFF),
    "scr_hardcore": ("Hardcore", "0", "low health, no HUD", ON_OFF),
    "scr_team_fftype": ("Friendly fire", "0", "what happens when you shoot a teammate",
                        {"0": "off", "1": "on", "2": "reflect", "3": "shared"}),
    "scr_player_maxhealth": ("Health", "100", "player health, 30 = one shot kills, 300 = tank", None),
    "scr_player_healthregentime": ("Health regen (s)", "5", "seconds before health comes back", None),
}
# cheat protected: the server ignores them from the config and rcon, so save_cfg also
# writes a copy as sv_fun_<name> and lobby.gsc applies it from the game script
CHEAT_DVARS = ("bg_fallDamageMinHeight", "bg_fallDamageMaxHeight")
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
        "Sticky situation": ("semtex only, refills every second, no killstreaks",
                             {"sv_funweapons": "11", "scr_game_hardpoints": "0"}),
        "Bomberman": ("knife plus C4 or claymores that refill, trap the map",
                      {"sv_funweapons": "12", "scr_game_hardpoints": "0"}),
        "Knife thrower": ("throwing knives only, floaty jumps for trickshots",
                          {"sv_funweapons": "13", "g_gravity": "500", "jump_height": "80", "scr_game_hardpoints": "0",
                           **NO_FALL_DAMAGE}),
        "Noob tube war": ("Thumpers only, endless grenades",
                          {"sv_funweapons": "14", "scr_game_hardpoints": "0"}),
        "Gun game": ("every kill gives the next weapon (melee kills only on the knife level), a melee death takes one back, a knife kill at the end wins (best in Free-for-all)",
                     {"sv_funweapons": "15", "scr_game_hardpoints": "0", "scr_game_perks": "0"}),
        "Gun game extended": ("gun game with a 45 level ladder: pistols to snipers, launchers, riot shield, knife, throwing knife last (only a knife throw kill wins)",
                              {"sv_funweapons": "16", "scr_game_hardpoints": "0", "scr_game_perks": "0"}),
        "Gunship war": ("everyone holds an AC-130 cannon, floaty jumps, blasts launch you",
                        {"sv_funweapons": "10", "g_knockback": "5000", "g_gravity": "400", "jump_height": "80",
                         "scr_game_hardpoints": "0", **NO_FALL_DAMAGE}),
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
        "Hot potato": ("one player carries a 20s bomb: get a kill or explode", {"sv_funpotato": "20"}),
        "Air raid": ("every kill hands out a random air killstreak, they stack up", {"sv_funairkill": "1"}),
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
        "S&D party": ("Search & Destroy with round roulette, clutch mode, hunted carrier and revives",
                      {"sv_sdroulette": "1", "sv_sdclutch": "1", "sv_sdhunted": "1", "sv_sdrevive": "1"}),
        "Chaos": ("friendly fire on, rockets launch you, moon gravity",
                  {"scr_team_fftype": "1", "g_knockback": "5000", "g_gravity": "200", "jump_height": "100",
                   **NO_FALL_DAMAGE}),
    },
}
# The server runs as a lobby (party) server, so map changes keep everyone connected. It only
# sits in the lobby at start: the UI then starts the saved map and mode, and every match
# that ends loads the next one itself (vote.gsc). The lobby never starts one by itself.
LOBBY_ARGS = ["+set", "party_enable", "1"]
# ends the match on "sv_tolobby 1" (End match): the scoreboard shows, then the next map loads
LOBBY_GSC = Path(__file__).resolve().parent / "lobby.gsc"
# weapon modes (knife only, snipers, ...) from the Fun panel's sv_funweapons
WEAPONS_GSC = Path(__file__).resolve().parent / "weapons.gsc"
# per-player actions from the Players table (kill, launch, give, ...) via sv_uicmd
PLAYERS_GSC = Path(__file__).resolve().parent / "players.gsc"
# Search & Destroy extras from the Fun panel (round roulette, clutch, hunted carrier, revive)
SD_GSC = Path(__file__).resolve().parent / "sdfun.gsc"
# in-game game type and map picks for everyone (!gt, !map, !menu); reads VOTE_LIST
VOTE_GSC = Path(__file__).resolve().parent / "vote.gsc"
VOTE_LIST = "scriptdata/vote.txt"  # in userraw, where IW4x's FileRead looks
PLAYER_ACTIONS = {"kill", "launch", "up", "give"}
# weapons the Players table can give: name -> weapon id
GIVE_WEAPONS = {
    "Intervention": "cheytac_mp", "Barrett .50cal": "barrett_mp", "ACR": "masada_mp", "M4A1": "m4_mp",
    "AK-47": "ak47_mp", "Vector": "kriss_mp", "UMP45": "ump45_mp", "AA-12": "aa12_mp", "SPAS-12": "spas12_mp",
    "M240": "m240_mp", "Desert Eagle": "deserteagle_mp", "Akimbo 1887s": "model1887_akimbo_mp",
    "RPG-7": "rpg_mp", "Javelin": "javelin_mp", "Riot shield": "riotshield_mp",
    # the guns of the air killstreaks as hand weapons (Fun "Air support per kill" gives the real killstreaks)
    "AC-130 cannon": "ac130_105mm_mp", "AC-130 40mm": "ac130_40mm_mp", "AC-130 25mm": "ac130_25mm_mp",
    "Predator missile": "remotemissile_projectile_mp", "Harrier cannon": "harrier_20mm_mp",
    "Chopper gunner minigun": "cobra_player_minigun_mp", "Attack heli gun": "cobra_20mm_mp",
    "Pave Low minigun": "pavelow_minigun_mp",
}
# Our own playlist file: the stock playlists set "rule party_minplayers 4" (re-applied on
# every return to the lobby), so with enough players the lobby starts the next playlist
# map by itself, and that list includes DLC maps that aren't installed.
LOBBY_PLAYLIST = "playlists_lobby.info"
# restart the game server when it runs but hasn't answered for this long (it can hang at start)
WATCHDOG_SECONDS = 90
# S&D round wins needed to win when the Game panel's Win limit is empty (the game's own default is 4)
SD_WINLIMIT = "12"
# the 16 original MW2 maps: the only ones the Game panel offers for S&D
STOCK_MAPS = ["mp_afghan", "mp_boneyard", "mp_brecourt", "mp_checkpoint", "mp_derail", "mp_estate",
              "mp_favela", "mp_highrise", "mp_invasion", "mp_nightshift", "mp_quarry", "mp_rundown",
              "mp_rust", "mp_subbase", "mp_terminal", "mp_underpass"]

app = FastAPI()


# ---------- login ----------
# One password (UI_PASSWORD) on a login form, then a signed session cookie. The signing
# secret is session.key in the data dir (a volume in Docker); deleting it logs everyone out.

SESSION_KEY_FILE = DATA_DIR / "session.key"
SESSION_COOKIE = "iw4x_session"
SESSION_DAYS = 30
AUTH_OPEN = {"/login", "/api/auth/login"}  # work without a session


def session_key() -> bytes:
    if not SESSION_KEY_FILE.exists():
        SESSION_KEY_FILE.write_text(secrets.token_hex(32))
    return SESSION_KEY_FILE.read_text().strip().encode()


def session_cookie() -> str:
    expires = str(int(time.time()) + SESSION_DAYS * 86400)
    return expires + "." + hmac.new(session_key(), expires.encode(), hashlib.sha256).hexdigest()


def logged_in(request: Request) -> bool:
    expires, _, sig = request.cookies.get(SESSION_COOKIE, "").partition(".")
    good = hmac.new(session_key(), expires.encode(), hashlib.sha256).hexdigest()
    return expires.isdigit() and int(expires) > time.time() and hmac.compare_digest(sig, good)


def basic_auth_ok(request: Request) -> bool:
    """HTTP basic auth, for scripts like task stop (curl -u)."""
    try:
        given = base64.b64decode(request.headers.get("authorization", "").removeprefix("Basic ")).decode()
        return secrets.compare_digest(given.split(":", 1)[1].encode(), UI_PASSWORD.encode())
    except (ValueError, IndexError):
        return False


@app.middleware("http")
async def require_password(request: Request, call_next):
    """With UI_PASSWORD set, everything but the login form needs a session."""
    if request.url.path.startswith("/tg/"):
        # the Telegram mini app: Telegram's signature instead of the password (telegram_user),
        # and its page on another server calls this one (TELEGRAM_APP_SERVERS)
        response = Response(status_code=204) if request.method == "OPTIONS" else await call_next(request)
        response.headers.update(TG_CORS)
        return response
    if UI_PASSWORD and request.url.path not in AUTH_OPEN and not logged_in(request) and not basic_auth_ok(request):
        if request.url.path == "/":
            return RedirectResponse("/login")
        return Response(status_code=401)
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
        {"id": n, "name": MAP_NAMES.get(n, n), "custom": n in custom and n not in names, "stock": n in STOCK_MAPS}
        for n in (names | custom) - BROKEN_MAPS
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
    bots_skill: str


def clean(s: str) -> str:
    return s.replace('"', "").replace("\n", "").strip()


def fun_value(key: str, raw: str) -> str:
    """A Fun field's value: a number (or one of its choices); empty = the game's default."""
    _, default, _, choices = {**FUN_DVARS, **FUN_RULES}[key]
    val = clean(raw) or default
    if not re.fullmatch(r"-?\d+(\.\d+)?", val) or (choices and val not in choices):
        raise HTTPException(400, f"{key}: invalid value")
    if key in CHEAT_DVARS and float(val) < 1:  # the game rejects these below 1
        raise HTTPException(400, f"{FUN_DVARS[key][0]}: 1 or more (9999 = no fall damage)")
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
    })
    save_cfg(v)


def save_cfg(v: dict[str, str]) -> None:
    # always a lobby server: an old "party_enable 0" would end the lobby on "exec server.cfg"
    v["party_enable"] = "1"
    for key in ("sv_mapRotation", "lobby_playlist", "sv_hangout_enabled", "sv_vote_enabled"):  # left over from older versions
        v.pop(key, None)
    for key in CHEAT_DVARS:
        if key in v:
            v[f"sv_fun_{key}"] = v[key]
    v.setdefault("scr_sd_winlimit", SD_WINLIMIT)  # empty S&D Win limit = ours, not the game's 4
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
    for src in (LOBBY_GSC, WEAPONS_GSC, PLAYERS_GSC, SD_GSC, VOTE_GSC):
        dest = GAME_DIR / "userraw" / "scripts" / "mp" / src.name
        if GAME_DIR.exists() and (not dest.exists() or dest.read_bytes() != src.read_bytes()):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
    if GAME_DIR.exists():
        # maps and modes for vote.gsc: map<TAB>id<TAB>name, mode<TAB>id<TAB>name
        lines = [f"map\t{m['id']}\t{m['name']}" for m in installed_maps()]
        lines += [f"mode\t{g}\t{name}" for g, name in gametypes().items()]
        dest = GAME_DIR / "userraw" / VOTE_LIST
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(("\n".join(lines) + "\n").encode())


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
    if CFG.exists() and "scr_sd_winlimit" not in (v := read_cfg()):
        save_cfg(v)  # a server.cfg from before the S&D Win limit default gets it
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
    if not status.lstrip().startswith("map:") and "Server is not running" not in status:
        # no answer in time, e.g. while the server restarts an S&D round: ask once more
        status = rcon("status")
    for line in status.splitlines():
        m = row.match(line)
        if m:
            players.append({
                "num": int(m[1]), "score": m[2], "ping": m[3], "guid": m[4],
                "name": strip_colors(m[5]), "address": m[7], "bot": m[4].startswith("bot"),
            })
    in_game = status.lstrip().startswith("map:")
    # neither: no usable answer, so not known whether a match runs (never taken as the lobby)
    lobby = "Server is not running" in status
    if not in_game and not lobby:
        print(f"rcon status: no usable answer ({status.strip()[:60]!r}), lobby or match unknown", flush=True)
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
        "lobby": lobby,
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


lobby_started = False  # the match after this lobby visit has been started
starting_match = threading.Event()  # Start game is passing through the lobby: don't start one here too
last_alive = time.monotonic()  # last time the game server answered (watchdog)
# a map load can report "lobby" for a moment: the lobby counts once it lasts this long
LOBBY_CONFIRM_SECONDS = 15
lobby_since = 0.0  # when the server started reporting the lobby; 0 = it doesn't


def set_playlist(mode: str) -> bool:
    """Switches the lobby to the mode's playlist and reads it back: a match takes its mode from
    the playlist, and a busy server (e.g. right after start) can drop the rcon command."""
    index = lobby_playlist(mode)
    for _ in range(3):
        if f'"playlist" is: "{index}^7"' in rcon("playlist"):
            return True
        rcon(f"playlist {index}")
        time.sleep(1)  # switching playlist re-picks the lobby map: let it settle
    return f'"playlist" is: "{index}^7"' in rcon("playlist")


def start_from_lobby() -> bool:
    """Lobby -> match on the map and mode saved in server.cfg (at server start, or when a
    match fell back to the lobby). False when the lobby didn't take the mode's playlist."""
    if not set_playlist(read_cfg().get("g_gametype", "war")):
        return False
    rcon("exec server.cfg")
    rcon("xpartygo")
    return True


# ---------- Telegram: who joins and leaves ----------
# With TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID set (README: "Join and leave messages in
# Telegram"), the poll loop posts to a Telegram group when a player joins or leaves the
# server; bots are left out. A player counts as gone after LEAVE_SECONDS away while the
# server answers, so a map change, or a game crash or server restart they come back
# from, posts nothing.

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_ON = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT)
TELEGRAM_API = "https://api.telegram.org"
LEAVE_SECONDS = 60
# who is on, so that a restart of the web UI (a deploy) doesn't post them all again
PRESENCE_FILE = DATA_DIR / "presence.json"
PRESENCE_MAX_AGE = 600  # older than this when the web UI starts: not used


def humans_now(st: dict | None) -> dict[str, str] | None:
    """guid -> name of the players (not bots) on the server. None when that isn't known:
    no answer, or a lobby with people in it (IW4x can't list them)."""
    if st is None:
        return None
    if not st["running"]:
        return {}
    live = st["live"]
    if live and live["in_game"]:
        return {p["guid"]: p["name"] for p in live["players"] if not p["bot"] and p["ping"] != "ZMBI"}
    if live and live["lobby"] and live["lobby_count"] == 0:
        return {}
    return None


class Presence:
    """Turns the poll loop's player lists into joins and leaves."""

    def __init__(self, path: Path):
        self.path = path
        self.players: dict[str, str] = {}  # guid -> name: joined and not left yet
        self.away: dict[str, float] = {}  # guid -> seconds missing while the server answered
        self.known = False  # False: the next player list is taken as is, nothing posted
        self.last = 0.0
        self.saved = 0.0
        try:
            saved = json.loads(path.read_text())
            if time.time() - saved["time"] < PRESENCE_MAX_AGE:
                self.players, self.known = dict(saved["players"]), True
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def update(self, humans: dict[str, str] | None, now: float) -> tuple[list[str], list[str]]:
        """Names that joined and that left since the last call (now: time.monotonic())."""
        dt = min(now - self.last, 10.0) if self.last else 0.0
        self.last = now
        if humans is None:
            return [], []
        if not self.known:  # the web UI started with players already on: no news
            self.players, self.known = dict(humans), True
            self.save()
            return [], []
        before = dict(self.players)
        joined = [name for guid, name in humans.items() if guid not in self.players]
        left = []
        for guid in [g for g in self.players if g not in humans]:
            self.away[guid] = self.away.get(guid, 0.0) + dt
            if self.away[guid] >= LEAVE_SECONDS:
                del self.away[guid]
                left.append(self.players.pop(guid))
        for guid in humans:
            self.away.pop(guid, None)
        self.players.update(humans)  # also takes new names
        if self.players != before or time.time() - self.saved > 60:
            self.save()
        return joined, left

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"time": time.time(), "players": self.players}))
            tmp.replace(self.path)
            self.saved = time.time()
        except OSError as e:
            print(f"telegram: can't save {self.path}: {e}", flush=True)


def presence_message(server: str, joined: list[str], left: list[str], playing: list[str]) -> str:
    def bold(names: list[str]) -> str:
        return ", ".join(f"<b>{html.escape(n)}</b>" for n in names)

    lines = []
    if joined:
        lines.append(f"🟢 {bold(joined)} joined {html.escape(server)}")
    if left:
        lines.append(f"🔴 {bold(left)} left {html.escape(server)}")
    playing = sorted(playing, key=str.lower)
    lines.append(f"Playing ({len(playing)}): {html.escape(', '.join(playing))}" if playing else "Nobody playing now")
    return "\n".join(lines)


presence = Presence(PRESENCE_FILE)
telegram_outbox: queue.Queue[tuple[str, bool]] = queue.Queue()
server_name = ""  # sv_hostname, kept for when the server doesn't answer


def report_presence(st: dict | None) -> None:
    global server_name
    if st and st["live"] and st["live"]["hostname"]:
        server_name = st["live"]["hostname"]
    joined, left = presence.update(humans_now(st), time.monotonic())
    if joined or left:
        print(f"players: joined {joined}, left {left}", flush=True)
        text = presence_message(server_name or JOIN_HOST or "the server", joined, left,
                                list(presence.players.values()))
        telegram_outbox.put((text, not joined))  # only leaves: no notification sound


def telegram(method: str, wait: float = 20, **params) -> dict:
    """Calls the Telegram Bot API. A failure comes back as {"ok": False, "description": ...}."""
    req = urllib.request.Request(f"{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/{method}",
                                 data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=wait) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # Telegram says why in the body
        try:
            return json.load(e)
        except ValueError:
            return {"ok": False, "error_code": e.code, "description": str(e)}
    except (OSError, ValueError) as e:
        return {"ok": False, "description": str(e)}


def telegram_loop() -> None:
    """Sends the queued messages in order, trying again while Telegram can't be reached."""
    global TELEGRAM_CHAT
    me = telegram("getMe")
    if me.get("ok"):
        print(f"telegram: posting joins and leaves as @{me['result']['username']} to {TELEGRAM_CHAT}", flush=True)
    else:
        print(f"telegram: bot not usable ({me.get('description')}), check TELEGRAM_BOT_TOKEN", flush=True)
    while True:
        text, silent = telegram_outbox.get()
        for attempt in range(6):
            extra = {"reply_markup": button} if (button := app_button()) else {}
            r = telegram("sendMessage", chat_id=TELEGRAM_CHAT, text=text, parse_mode="HTML",
                         disable_notification=silent, **extra)
            if r.get("ok"):
                break
            params = r.get("parameters") or {}
            if params.get("migrate_to_chat_id"):  # the group became a supergroup, with a new id
                TELEGRAM_CHAT = str(params["migrate_to_chat_id"])
                print(f"telegram: the group has a new id, set TELEGRAM_CHAT_ID={TELEGRAM_CHAT} in .env", flush=True)
                continue
            print(f"telegram: message not sent: {r.get('description')}", flush=True)
            code = r.get("error_code", 0)
            if 400 <= code < 500 and code != 429:
                break  # e.g. a wrong chat id: sending it again won't help
            time.sleep(params.get("retry_after") or 5 * 2**attempt)


bot_app = {"checked": 0.0, "button": None}


def app_button() -> dict | None:
    """A button under the bot's messages that opens the mini app, once BotFather has it as the
    bot's main Mini App. Asks Telegram again after 10 minutes, so setting it up needs no restart."""
    if not bot_app["checked"] or time.monotonic() - bot_app["checked"] > 600:
        me = telegram("getMe")
        if me.get("ok"):
            bot = me["result"]
            bot_app["checked"] = time.monotonic()
            bot_app["button"] = {"inline_keyboard": [[
                {"text": "🎮 Servers", "url": f"https://t.me/{bot['username']}?startapp"}]]} if bot.get("has_main_web_app") else None
    return bot_app["button"]


# ---------- Telegram mini app: map, mode and bots from the group ----------
# tg.html, served at /tg/, opens inside Telegram (README: "Map, mode and bots from Telegram"). It shows
# the map, mode and players of each server in TELEGRAM_APP_SERVERS and lets members of the
# TELEGRAM_CHAT_ID group change map, mode and bots. Telegram signs who opened it (initData) with the
# bot token, which every server has, so the page calls each server's /tg/api itself: no web UI
# password involved, and a server only takes changes from people in the group.

TELEGRAM_APP_SERVERS = [
    s if s.startswith("http") else f"https://{s}"
    for s in os.environ.get("TELEGRAM_APP_SERVERS", "").replace(",", " ").split()
]
APP_MODES = {g: GAMETYPE_NAMES[g] for g in ("war", "dm", "dom", "sd", "koth", "sab", "ctf", "dd")}
# the gun games: Free-for-all with the Fun panel's preset of that name
GUN_GAMES = {"gungame": ("Gun Game", "Gun game"), "gungame_ext": ("Gun Game Extended", "Gun game extended")}
APP_MODES |= {mode: name for mode, (name, _) in GUN_GAMES.items()}
GUN_GAME_PRESETS = {mode: FUN_PRESETS["Weapons"][preset][1] for mode, (_, preset) in GUN_GAMES.items()}
GUN_GAME_WEAPONS = {dvars["sv_funweapons"]: mode for mode, dvars in GUN_GAME_PRESETS.items()}
NO_GUN_GAME = {key: FUN_RULES[key][1] for key in GUN_GAME_PRESETS["gungame"]}  # the game's defaults
INIT_DATA_MAX_AGE = 86400  # an app left open longer has to be opened again
TG_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Authorization, Content-Type",
           "Access-Control-Allow-Methods": "GET, POST", "Access-Control-Max-Age": "86400"}
THUMBS = DATA_DIR / "thumbs"
members: dict[int, tuple[float, bool]] = {}  # Telegram user id -> (when asked, in the group)
# sv_funweapons of the running match: read from server.cfg when a new map or mode shows up,
# right after vote.gsc or Start game ran exec server.cfg for it
match_weapons: dict = {"match": None, "value": "0"}


def track_match(st: dict | None) -> None:
    live = st and st["live"]
    if live and live["in_game"] and (live["map"], live["gametype"]) != match_weapons["match"]:
        match_weapons.update(match=(live["map"], live["gametype"]), value=read_cfg().get("sv_funweapons", "0"))


def in_group(user_id: int) -> bool:
    hit = members.get(user_id)
    if hit and time.monotonic() - hit[0] < (600 if hit[1] else 60):
        return hit[1]
    r = telegram("getChatMember", chat_id=TELEGRAM_CHAT, user_id=user_id)
    if not r.get("ok") and r.get("error_code") != 400:  # 400: not a member
        raise HTTPException(503, "Telegram can't be reached, try again")
    m = r.get("result") or {}
    ok = m.get("status") in ("creator", "administrator", "member") or bool(m.get("is_member"))
    members[user_id] = (time.monotonic(), ok)
    return ok


def telegram_user(request: Request) -> dict:
    """The Telegram user who opened the mini app, from the initData Telegram signed for this
    bot (header Authorization: tma <initData>), if they are in the group.
    On a server of the fleet (deploy/fleet.toml) the bastion serves the mini app: it checks the
    Telegram login itself and calls here with this server's web UI password, naming the user in
    X-Telegram-User (for the log). Such a server has no bot token."""
    if UI_PASSWORD and basic_auth_ok(request):
        try:
            user = json.loads(request.headers.get("x-telegram-user") or "{}")
        except ValueError:
            user = {}
        return user if isinstance(user, dict) else {}
    if not TELEGRAM_ON:
        raise HTTPException(503, "Telegram is not set up on this server")
    header = request.headers.get("authorization", "")
    if not header.startswith("tma "):
        raise HTTPException(401, "open this from Telegram")
    fields = dict(urllib.parse.parse_qsl(header[4:], keep_blank_values=True))
    signed = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()) if k != "hash")
    key = hmac.new(b"WebAppData", TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(key, signed.encode(), hashlib.sha256).hexdigest(), fields.get("hash", "")):
        raise HTTPException(401, "not signed by Telegram for this bot")
    if time.time() - int(fields.get("auth_date") or 0) > INIT_DATA_MAX_AGE:
        raise HTTPException(401, "open the app again from Telegram")
    user = json.loads(fields.get("user") or "{}")
    if not user.get("id") or not in_group(user["id"]):
        raise HTTPException(403, "only for members of the group")
    return user


def tg_mode(gametype: str, weapons: str) -> tuple[str, str]:
    """(mode id, name) as the app shows them: the gun games are modes of their own."""
    if gametype == "dm" and weapons in GUN_GAME_WEAPONS:
        return GUN_GAME_WEAPONS[weapons], APP_MODES[GUN_GAME_WEAPONS[weapons]]
    name = GAMETYPE_NAMES.get(gametype, gametype)
    if weapons != "0":  # a Fun panel weapons rule, e.g. "Team Deathmatch · snipers only"
        name += " · " + FUN_RULES["sv_funweapons"][3].get(weapons, f"weapons {weapons}")
    return gametype, name


@app.get("/tg/", response_class=HTMLResponse)
def tg_page():
    servers = TELEGRAM_APP_SERVERS or [""]  # empty: only this server
    # the Plan page of the planner bot (services/bot), behind the first server's /bot/
    return ((Path(__file__).parent / "tg.html").read_text().replace('["__SERVERS__"]', json.dumps(servers))
            .replace('"__PLAN__"', json.dumps(f"{servers[0]}/bot/")))


@app.get("/tg/api/state")
def tg_state(request: Request):
    telegram_user(request)
    with snapshot_lock:
        st = (snapshot["data"] or {}).get("state")
    live = st and st["live"]
    status = ("starting" if not st else "offline" if not st["running"] else "no answer" if not live
              else "match" if live["in_game"] else "lobby" if live["lobby"] else "no answer")
    mode, mode_name = "", ""
    if status == "match":
        weapons = (match_weapons["value"] if match_weapons["match"] == (live["map"], live["gametype"])
                   else read_cfg().get("sv_funweapons", "0"))  # until the poll loop sees the new match
        mode, mode_name = tg_mode(live["gametype"], weapons)
    players = live["players"] if status == "match" else []
    # people, not bots; not a slot that is leaving (ZMBI) or one without a name yet
    humans = [p for p in players if not p["bot"] and p["ping"] != "ZMBI" and p["name"].strip()]
    return {
        "name": (live and live["hostname"]) or server_name or JOIN_HOST or "IW4x",
        "address": st["address"] if st else "",
        "status": status,
        "map": live["map"] if status == "match" else "",
        "map_name": MAP_NAMES.get(live["map"], live["map"]) if status == "match" else "",
        "mode": mode,
        "mode_name": mode_name,
        "players": sorted((p["name"] for p in humans), key=str.lower),
        # guid -> name: the fleet's bastion tells joins and leaves apart by guid, not by name
        "humans": {p["guid"]: p["name"] for p in humans},
        # the players for the mini app's list, to kick from (no addresses)
        "roster": sorted(({k: p[k] for k in ("num", "guid", "name", "score", "ping")} for p in humans),
                         key=lambda p: p["name"].lower()),
        "bots": sum(p["bot"] for p in players),
        "lobby_count": live["lobby_count"] if status == "lobby" else 0,
        "maps": [{k: m[k] for k in ("id", "name", "stock")} for m in (st["maps"] if st else [])],
        "modes": [{"id": k, "name": v} for k, v in APP_MODES.items()],
        "bot_settings": tg_bot_settings((st or {}).get("config") or config_view()),
        "bot_skills": [{"id": k, "name": BOT_SKILL_NAMES.get(k, k)} for k in BOT_SKILLS],
    }


BOT_SKILL_NAMES = {"0": "Mixed", "9": "Random"}  # short names for BOT_SKILLS, the rest are 1 to 7


def tg_bot_settings(c: dict) -> dict:
    return {"fill": c["bots_fill"], "add": c["bots_fill_mode"] == "1", "skill": c["bots_skill"]}


class Bots(BaseModel):
    fill: int  # players to fill up to, or bots to add
    add: bool  # True: add that many bots on top of the players
    skill: str


class JoinPassword(BaseModel):
    password: str


@app.post("/api/join-password")
def set_join_password(j: JoinPassword):
    """The join password ("" = open to everyone), saved to server.cfg (the next match reads it
    again) and set right away for new joins; nobody playing gets kicked. The fleet's bastion
    calls it (deploy/README.md: GAME_JOIN_PASSWORD)."""
    v = read_cfg()
    v["g_password"] = clean(j.password)
    save_cfg(v)
    if server_pids():
        rcon(f'set g_password "{v["g_password"]}"')
    changed()
    print(f"join password {'set' if v['g_password'] else 'removed: open to everyone'}", flush=True)
    return {"ok": True}


class TgKick(BaseModel):
    num: int
    guid: str  # who the kick is for: the slot may have changed hands since the list was shown


@app.post("/tg/api/kick")
def tg_kick(k: TgKick, request: Request):
    """Kicks a player from the mini app's list, if that slot still holds them."""
    user = telegram_user(request)
    live = live_status()
    if not live or not live["in_game"]:
        raise HTTPException(409, "no match running")
    player = next((p for p in live["players"] if p["num"] == k.num and p["guid"] == k.guid), None)
    if not player:
        raise HTTPException(409, "they already left")
    rcon(f"clientkick {k.num}")
    changed()
    print(f"telegram app: {user.get('id')} {user.get('first_name')!r}: kicked {player['name']!r}", flush=True)
    return {"ok": True, "name": player["name"]}


@app.post("/tg/api/bots")
def tg_bots(b: Bots, request: Request):
    """The web UI's bot settings: saved to server.cfg, and set right away on a running
    server, where the bot mod applies them within seconds."""
    user = telegram_user(request)
    if not 0 <= b.fill <= 17 or b.skill not in BOT_SKILLS:
        raise HTTPException(400, "invalid bot settings")
    bots = {"bots_manage_fill": str(b.fill), "bots_manage_fill_mode": "1" if b.add else "0", "bots_skill": b.skill}
    v = read_cfg()
    v.update(bots, bots_manage_fill_kick="1", bots_main_waitForHostTime="0")  # as write_cfg
    save_cfg(v)
    if server_pids():
        for key, val in bots.items():
            rcon(f"set {key} {val}")
    changed()
    print(f"telegram app: {user.get('id')} {user.get('first_name')!r}: bots {bots}", flush=True)
    return {"ok": True}


@app.post("/tg/api/restart")
def tg_restart(request: Request):
    """Fast restart of the running match: same map and mode, scores reset, everyone stays. Unlike
    the web UI's Fast restart, it leaves the mode's limits as they are."""
    user = telegram_user(request)
    live = live_status()
    if not live or not live["in_game"]:
        raise HTTPException(409, "no match running")
    rcon("fast_restart")
    changed()
    print(f"telegram app: {user.get('id')} {user.get('first_name')!r}: fast restart on {live['map']}", flush=True)
    return {"ok": True}


class Play(BaseModel):
    map: str
    mode: str
    now: bool  # False: the next match


@app.post("/tg/api/play")
def tg_play(p: Play, request: Request):
    user = telegram_user(request)
    if p.mode not in APP_MODES:
        raise HTTPException(400, "unknown mode")
    gametype = "dm" if p.mode in GUN_GAMES else p.mode
    maps = {m["id"]: m for m in installed_maps()}
    if p.map not in maps or (gametype == "sd" and not maps[p.map]["stock"]):
        raise HTTPException(400, "that map isn't available in this mode")
    v = read_cfg()
    if p.mode in GUN_GAMES:
        v.update(GUN_GAME_PRESETS[p.mode])
    elif v.get("sv_funweapons") in GUN_GAME_WEAPONS:  # out of gun game: classes again
        v.update(NO_GUN_GAME)
    save_cfg(v)  # read again by Start game; the end of a match runs exec server.cfg
    if p.now:
        # the mode's limits as they are (Start game resets the empty ones)
        start_game(Game(map=p.map, gametype=gametype, **{k: v.get(f"scr_{gametype}_{k}", "") for k in MODE_LIMITS}))
        match_weapons.update(match=(p.map, gametype), value=v.get("sv_funweapons", "0"))
    else:
        select(Pick(map=p.map, gametype=gametype))
    print(f"telegram app: {user.get('id')} {user.get('first_name')!r}: {p.map} {p.mode} {'now' if p.now else 'next'}",
          flush=True)
    return {"ok": True}


def iwi_image(raw: bytes) -> Image.Image:
    """Decodes an IW4 .iwi image (version 8 or 9): uncompressed BGR, DXT1 or DXT5."""
    if raw[:3] != b"IWi" or len(raw) < 32:
        raise ValueError("not an iwi image")
    fmt, width, height = raw[8], *struct.unpack("<HH", raw[10:14])
    if fmt == 2:
        size = width * height * 3
        return Image.frombytes("RGB", (width, height), raw[-size:], "raw", "BGR")
    if fmt in (11, 13):  # mipmaps go smallest first: the full image is at the end
        size = width * height // (2 if fmt == 11 else 1)
        dds = struct.pack("<4s7I44s2I4s5I5I", b"DDS ", 124, 0x81007, height, width, size, 0, 1, b"\0" * 44,
                          32, 4, b"DXT1" if fmt == 11 else b"DXT5", 0, 0, 0, 0, 0, 0x1000, 0, 0, 0, 0)
        return Image.open(io.BytesIO(dds + raw[-size:])).convert("RGB")
    raise ValueError(f"iwi format {fmt}")


@cache
def loadscreens() -> dict[str, tuple[Path, str]]:
    """map -> (archive, file) of its loading screen image in the game files."""
    found = {}
    archives = [*sorted(GAME_DIR.glob("main/*.iwd")), *sorted(GAME_DIR.glob("main/iw4x/**/*.iwd")),
                *sorted(GAME_DIR.glob("usermaps/*/*.iwd"))]
    for iwd in archives:
        try:
            for info in zipfile.ZipFile(iwd).infolist():
                if (m := re.fullmatch(r"images/loadscreen_(mp_\w+)\.iwi", info.filename, re.IGNORECASE)) \
                        and info.file_size > 1024:  # not an empty placeholder
                    found[m[1].lower()] = (iwd, info.filename)
        except (zipfile.BadZipFile, OSError):
            continue
    return found


@app.get("/tg/thumb/{map_id}.jpg")
def tg_thumb(map_id: str):
    """A map's loading screen as a small JPEG, made once from the game files."""
    path = THUMBS / f"{map_id}.jpg"
    if not path.exists():
        if not re.fullmatch(r"mp_\w+", map_id) or not (src := loadscreens().get(map_id)):
            raise HTTPException(404)
        try:
            image = iwi_image(zipfile.ZipFile(src[0]).read(src[1])).resize((480, 270), Image.Resampling.LANCZOS)
        except (ValueError, OSError, zipfile.BadZipFile) as e:
            print(f"thumbnail of {map_id}: {e}", flush=True)
            raise HTTPException(404) from None
        THUMBS.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        image.save(tmp, "JPEG", quality=80)
        tmp.replace(path)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


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
            st = state()
            data = {"state": st, "log": log()["lines"]}
            track_match(st)
        except Exception as e:  # noqa: BLE001  keep pushing: one failed query must not stop live updates
            st, data = None, {"error": str(e)}
        if TELEGRAM_ON:
            try:
                report_presence(st)
            except Exception as e:  # noqa: BLE001  nor a failure here
                print(f"telegram: {e!r}", flush=True)
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
    global lobby_started, last_alive, lobby_since
    live = live_status()
    if live:
        last_alive = time.monotonic()
    lobby_since = (lobby_since or time.monotonic()) if live and live["lobby"] else 0.0
    if live and live["lobby"]:
        if (not lobby_started and not starting_match.is_set()
                and time.monotonic() - lobby_since >= LOBBY_CONFIRM_SECONDS):
            print(f"in the lobby for {time.monotonic() - lobby_since:.0f} s: starting the match", flush=True)
            lobby_started = start_from_lobby()  # not started: try again on the next poll
    elif not live or live["in_game"]:  # an unknown answer changes nothing
        lobby_started = False
    return {
        "running": bool(server_pids()),
        "live": live,
        # no ":port" with a name on the default port: "connect mw2.example.com"
        "address": JOIN_HOST if JOIN_HOST and PORT == 28960 else f"{JOIN_HOST or lan_ip()}:{PORT}",
        "config": config_view(),
        "maps": installed_maps(),
        "gametypes": gametypes(),
        "bot_skills": BOT_SKILLS,
        "auth": bool(UI_PASSWORD),
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
    """Saves the picked map and mode as the next match: vote.gsc announces it and loads it
    when the running match ends (the lobby at server start uses the saved ones)."""
    save_cfg(save_pick(p))
    live = live_status()
    if live and live["in_game"]:
        rcon(f"set sv_vote_map {p.map}")
        rcon(f"set sv_vote_mode {p.gametype}")
    changed()
    return {"ok": True}


class Limits(BaseModel):
    scorelimit: str = ""
    timelimit: str = ""
    roundlimit: str = ""
    winlimit: str = ""
    roundswitch: str = ""
    numlives: str = ""


class Game(Pick, Limits):
    pass


@app.post("/api/game")
def start_game(g: Game):
    """Lobby or a running match -> match on the chosen map and mode.
    Everyone goes along, still connected."""
    global lobby_started
    v = save_pick(g)
    live = live_status()
    if not live:
        raise HTTPException(409, "server not running")
    if not live["in_game"] and not live["lobby"]:
        raise HTTPException(503, "the server didn't answer, try again")
    starting_match.set()  # keeps the poll loop from starting another match from the lobby
    try:
        return start_match(g, v, live)
    finally:
        # the match takes a while to load and the server reports "lobby" meanwhile: no
        # start from the lobby until it's seen in a match again (that resets lobby_started)
        lobby_started = True
        starting_match.clear()


def save_limits(gametype: str, limits: Limits, v: dict[str, str]) -> None:
    """Saves the mode's limits to server.cfg; the caller runs exec server.cfg to apply them."""
    if clean(limits.roundlimit) and not clean(limits.winlimit):
        # the mode's default win limit (S&D: 12) would end the match before the rounds are played
        limits = limits.model_copy(update={"winlimit": "0"})
    for limit in MODE_LIMITS:
        key, val = f"scr_{gametype}_{limit}", getattr(limits, limit)
        if clean(val):
            v[key] = clean(val)
        else:
            v.pop(key, None)
            rcon(f"reset {key}")  # back to the mode's default
    save_cfg(v)


def start_match(g: Game, v: dict[str, str], live: dict) -> dict:
    save_limits(g.gametype, g, v)
    if live["in_game"]:  # switch the map straight to the new match, no scoreboard or lobby
        rcon("exec server.cfg")
        rcon("set sv_vote_map none")  # in-game picks for the next match are used up
        rcon("set sv_vote_mode none")
        output = rcon(f"map {g.map}")
        time.sleep(5)  # the old match still answers for a moment
        for _ in range(40):
            if (now := live_status()) and now["in_game"]:
                break
            time.sleep(1)
        changed()
        return {"output": output}
    if not set_playlist(g.gametype):
        raise HTTPException(503, "the server didn't switch to that mode, try again")
    rcon("exec server.cfg")
    output = rcon("xpartygo")
    changed()
    return {"output": output}


@app.post("/api/lobby")
def end_match():
    """Ends the match through lobby.gsc: the scoreboard shows, then the next map loads (vote.gsc)."""
    live = live_status()
    if not live or not live["in_game"]:
        raise HTTPException(409, "no match running")
    output = rcon("sv_tolobby 1")
    changed()
    return {"output": output}


MATCH_COMMANDS = {
    "fast_restart": "fast_restart",  # restart the match on the same map, no reload
    "map_restart": "map_restart",  # reload the map, then restart the match
}


@app.post("/api/match/{action}")
def match_action(action: str, limits: Limits):
    """Restart the running match with the form's limits (rounds, side switch, ...); players stay connected."""
    if action not in MATCH_COMMANDS:
        raise HTTPException(404)
    live = live_status()
    if not live or not live["in_game"]:
        raise HTTPException(409, "no match running")
    if live["gametype"] in gametypes():
        save_limits(live["gametype"], limits, read_cfg())
        rcon("exec server.cfg")
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


class Login(BaseModel):
    password: str


@app.post("/api/auth/login")
def login(c: Login, request: Request, response: Response):
    if not secrets.compare_digest(c.password.encode(), UI_PASSWORD.encode()):
        time.sleep(1)  # slows down guessing
        raise HTTPException(401, "wrong password")
    # Secure only over HTTPS (Caddy on the VPS), so plain http on the LAN still works
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(SESSION_COOKIE, session_cookie(), max_age=SESSION_DAYS * 86400,
                        httponly=True, secure=https, samesite="strict")
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (Path(__file__).parent / "login.html").read_text()


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "index.html").read_text()


if __name__ == "__main__":
    install_lobby_gsc()
    if os.environ.get("AUTOSTART") == "1":
        start_server()
    if TELEGRAM_ON:
        threading.Thread(target=telegram_loop, daemon=True).start()
    elif TELEGRAM_TOKEN or TELEGRAM_CHAT:
        print("telegram: set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID for join and leave messages", flush=True)
    threading.Thread(target=poll_loop, daemon=True).start()
    # an open live-update stream would otherwise keep the server from shutting down
    uvicorn.run(app, host=UI_HOST, port=UI_PORT, timeout_graceful_shutdown=2)
