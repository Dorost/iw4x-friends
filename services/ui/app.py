# /// script
# requires-python = ">=3.13"
# dependencies = ["fastapi", "uvicorn", "pillow"]
# ///
"""Small web UI to configure and control the IW4x LAN dedicated server."""

import io
import os
import re
import socket
import struct
import subprocess
import threading
import time
import zipfile
from functools import cache
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from PIL import Image
from pydantic import BaseModel

BOTTLE = os.environ.get("IW4X_BOTTLE", "mw")
GAME_DIR = Path(os.environ.get(
    "IW4X_GAME_DIR",
    Path.home() / "Library/Application Support/CrossOver/Bottles" / BOTTLE
    / "drive_c/Program Files (x86)/Call of Duty Modern Warfare 2",
))
CFG = GAME_DIR / "main" / "server.cfg"
LOG = Path(__file__).resolve().parent / "server.log"
THUMBS = Path(__file__).resolve().parent / "thumbs"
WINE = os.environ.get("WINE", "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine")
PORT = int(os.environ.get("IW4X_PORT", "28960"))
UI_PORT = int(os.environ.get("UI_PORT", "8080"))
MATCH = "iw4x.exe -dedicated"

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

app = FastAPI()


def installed_maps() -> list[dict]:
    names = {
        p.stem for p in (GAME_DIR / "zone").rglob("mp_*.ff")
        if not p.stem.endswith(("_load", "_shaders"))
    }
    custom = {
        d.name for d in (GAME_DIR / "usermaps").glob("mp_*") if (d / f"{d.name}.ff").exists()
    }
    maps = [
        {"id": n, "name": MAP_NAMES.get(n, n), "custom": n in custom and n not in names,
         "image": n in image_index()}
        for n in names | custom
    ]
    return sorted(maps, key=lambda m: m["name"])


@cache
def gametypes() -> dict[str, str]:
    """Stock modes plus any gametype script found in iwd archives or userraw."""
    ids = set(GAMETYPE_NAMES)
    pattern = re.compile(r"maps/mp/gametypes/([a-z0-9]+)\.gsc$", re.I)
    for iwd in [*GAME_DIR.glob("main/**/*.iwd"), *GAME_DIR.glob("userraw/*.iwd")]:
        try:
            ids |= {m[1].lower() for n in zipfile.ZipFile(iwd).namelist() if (m := pattern.search(n))}
        except zipfile.BadZipFile:
            continue
    ids |= {p.stem.lower() for p in GAME_DIR.glob("userraw/maps/mp/gametypes/*.gsc") if not p.stem.startswith("_")}
    names = {g: GAMETYPE_NAMES.get(g, g) for g in ids}
    return dict(sorted(names.items(), key=lambda kv: kv[1]))


# ---------- map images ----------

@cache
def image_index() -> dict[str, tuple[Path, str]]:
    """Map id -> (iwd, member) of its largest preview/loadscreen image."""
    best: dict[str, tuple[int, Path, str]] = {}
    for iwd in [*GAME_DIR.glob("main/**/*.iwd"), *GAME_DIR.glob("usermaps/*/*.iwd")]:
        try:
            z = zipfile.ZipFile(iwd)
        except zipfile.BadZipFile:
            continue
        for name in z.namelist():
            m = re.match(r"images/(?:loadscreen|preview)_(mp_\w+)\.iwi$", name)
            if not m:
                continue
            with z.open(name) as f:
                w, h = struct.unpack_from("<2H", f.read(14), 10)
            if w >= 64 and w * h > best.get(m[1], (0,))[0]:
                best[m[1]] = (w * h, iwd, name)
    return {k: (v[1], v[2]) for k, v in best.items()}


def iwi_to_image(data: bytes) -> Image.Image:
    fmt = data[8]
    w, h = struct.unpack_from("<2H", data, 10)
    # mipmaps are stored smallest first, so the full-size image is at the end
    if fmt == 0x2:
        return Image.frombytes("RGB", (w, h), data[-w * h * 3:], "raw", "BGR")
    if fmt == 0x1:
        return Image.frombytes("RGBA", (w, h), data[-w * h * 4:], "raw", "BGRA").convert("RGB")
    if fmt == 0xB:
        return Image.frombytes("RGBA", (w, h), data[-w * h // 2:], "bcn", 1).convert("RGB")
    if fmt in (0xC, 0xD):
        return Image.frombytes("RGBA", (w, h), data[-w * h:], "bcn", fmt - 0xA).convert("RGB")
    raise ValueError(f"unsupported iwi format {fmt:#x}")


def map_thumb(map_id: str) -> Path | None:
    out = THUMBS / f"{map_id}.jpg"
    if out.exists():
        return out
    src = image_index().get(map_id)
    if not src:
        return None
    img = iwi_to_image(zipfile.ZipFile(src[0]).read(src[1]))
    THUMBS.mkdir(exist_ok=True)
    img.resize((480, 270), Image.LANCZOS).save(out, "JPEG", quality=82)
    return out


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
    tokens = v.get("sv_mapRotation", "").split()
    maps = [tokens[i + 1] for i in range(len(tokens) - 1) if tokens[i] == "map"]
    return {
        "hostname": v.get("sv_hostname", ""),
        "password": v.get("g_password", ""),
        "rcon_password": v.get("rcon_password", ""),
        "maxclients": int(v.get("sv_maxclients", "18")),
        "lan_only": v.get("sv_lanOnly", "1") == "1",
        "gametype": gt,
        "scorelimit": v.get(f"scr_{gt}_scorelimit", ""),
        "timelimit": v.get(f"scr_{gt}_timelimit", ""),
        "maps": maps,
        "bots_fill": int(v.get("bots_manage_fill", "0")),
        "bots_fill_mode": v.get("bots_manage_fill_mode", "0"),
        "bots_skill": v.get("bots_skill", "0"),
    }


class Config(BaseModel):
    hostname: str
    password: str
    rcon_password: str
    maxclients: int
    lan_only: bool
    gametype: str
    scorelimit: str
    timelimit: str
    maps: list[str]
    bots_fill: int
    bots_fill_mode: str
    bots_skill: str


def clean(s: str) -> str:
    return s.replace('"', "").replace("\n", "").strip()


def write_cfg(c: Config) -> None:
    valid = {m["id"] for m in installed_maps()}
    if c.gametype not in gametypes():
        raise HTTPException(400, "unknown gametype")
    maps = [m for m in c.maps if m in valid]
    if not maps:
        raise HTTPException(400, "pick at least one map")
    if c.bots_skill not in BOT_SKILLS or c.bots_fill_mode not in ("0", "1"):
        raise HTTPException(400, "invalid bot settings")
    v = read_cfg()
    v.update({
        "sv_hostname": clean(c.hostname),
        "sv_lanOnly": "1" if c.lan_only else "0",
        "sv_maxclients": str(max(1, min(c.maxclients, 18))),
        "party_maxplayers": str(max(1, min(c.maxclients, 18))),
        "g_password": clean(c.password),
        "rcon_password": clean(c.rcon_password),
        "g_gametype": c.gametype,
        "sv_mapRotation": f"gametype {c.gametype} " + " ".join(f"map {m}" for m in maps),
        "bots_manage_fill": str(max(0, min(c.bots_fill, 17))),
        "bots_manage_fill_mode": c.bots_fill_mode,
        "bots_skill": c.bots_skill,
    })
    for key, val in ((f"scr_{c.gametype}_scorelimit", c.scorelimit),
                     (f"scr_{c.gametype}_timelimit", c.timelimit)):
        if clean(val):
            v[key] = clean(val)
        else:
            v.pop(key, None)
    lines = ["// IW4x LAN dedicated server (edited by server-ui)"]
    lines += [f'set {k} "{val}"' for k, val in v.items()]
    CFG.write_text("\n".join(lines) + "\n")


# ---------- process control ----------

def server_pids() -> list[int]:
    out = subprocess.run(["pgrep", "-f", MATCH], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def start_server() -> None:
    if server_pids():
        return
    subprocess.Popen(
        [WINE, "--bottle", BOTTLE, "--cx-app", "iw4x.exe", "-dedicated",
         "+set", "net_port", str(PORT), "+exec", "server.cfg", "+map_rotate"],
        cwd=GAME_DIR, stdout=LOG.open("w"), stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )


def stop_server() -> None:
    subprocess.run(["pkill", "-f", MATCH])
    for _ in range(30):
        if not server_pids():
            return
        time.sleep(0.5)
    subprocess.run(["pkill", "-9", "-f", MATCH])
    time.sleep(1)


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
    for line in rcon("status").splitlines():
        m = row.match(line)
        if m:
            players.append({
                "num": int(m[1]), "score": m[2], "ping": m[3], "guid": m[4],
                "name": strip_colors(m[5]), "address": m[7], "bot": m[4].startswith("bot"),
            })
    return {
        "hostname": strip_colors(kv.get("sv_hostname", "")),
        "map": kv.get("mapname", ""),
        "gametype": kv.get("g_gametype", ""),
        "version": kv.get("shortversion", ""),
        "players": players,
    }


def lan_ip() -> str:
    for iface in ("en0", "en1"):
        ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True).stdout.strip()
        if ip:
            return ip
    return "127.0.0.1"


# ---------- API ----------

@app.get("/api/state")
def state():
    return {
        "running": bool(server_pids()),
        "live": live_status(),
        "address": f"{lan_ip()}:{PORT}",
        "config": config_view(),
        "maps": installed_maps(),
        "gametypes": gametypes(),
        "bot_skills": BOT_SKILLS,
    }


@app.post("/api/config")
def save_config(c: Config):
    write_cfg(c)
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
    return {"ok": True}


@app.post("/api/apply")
def apply_config():
    """Reload server.cfg and start the new rotation via a map change, which keeps players connected."""
    if not live_status():
        start_server()
        return {"ok": True, "started": True}
    rcon("exec server.cfg")
    rcon('sv_mapRotationCurrent ""')
    rcon("map_rotate")
    return {"ok": True, "started": False}


class Kick(BaseModel):
    num: int


@app.post("/api/kick")
def kick(k: Kick):
    return {"output": rcon(f"clientkick {k.num}")}


class MapChange(BaseModel):
    map: str
    gametype: str


@app.post("/api/map")
def change_map(m: MapChange):
    if m.gametype not in gametypes() or m.map not in {x["id"] for x in installed_maps()}:
        raise HTTPException(400, "invalid map or gametype")
    rcon(f"g_gametype {m.gametype}")
    return {"output": rcon(f"map {m.map}")}


class Command(BaseModel):
    cmd: str


@app.post("/api/rcon")
def raw_rcon(c: Command):
    return {"output": rcon(c.cmd)}


@app.get("/api/log")
def log():
    if not LOG.exists():
        return {"lines": ["(no log yet: start the server from this page to capture its console)"]}
    return {"lines": LOG.read_text(errors="replace").splitlines()[-300:]}


@app.get("/api/mapimg/{map_id}")
def map_image(map_id: str):
    if not re.fullmatch(r"mp_\w+", map_id):
        raise HTTPException(400)
    path = map_thumb(map_id)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "index.html").read_text()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=UI_PORT)
