# IW4x LAN Server

Play Modern Warfare 2 ([IW4x](https://iw4x.io)) on your local network: set up the game on Macs (through CrossOver) and Windows PCs with one script, and run a dedicated server you manage from a web UI.

![stack](https://img.shields.io/badge/python-3.13-3776ab) ![stack](https://img.shields.io/badge/FastAPI-uv-009688) ![stack](https://img.shields.io/badge/macOS-CrossOver-6e4aff) ![stack](https://img.shields.io/badge/Windows-native-0078d4)

## Contents

- [Features](#features)
- [Install the game on a new machine](#install-the-game-on-a-new-machine) (Mac / Windows)
- [Run the server](#run-the-server)
- [Passwords](#passwords)
- [Join a game](#join-a-game)
- [Shared game settings](#shared-game-settings)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Project layout](#project-layout)

## Features

**Web UI for the dedicated server**
- **Start / stop / restart**, and **Save & apply**: settings take effect with a map change, players stay connected
- **Settings**: server name, game password, rcon password, mode, max players, score/time limits, LAN only
- **Map rotation picker** with loading-screen images from the game files, including custom maps from `usermaps/`
- **Game modes** detected from the installed files, including the IW4x extras (Gun Game, Infected, Kill Confirmed, VIP) and modes added by mods
- **Bots** (Bot Warfare mod): fill count, counting mode, skill
- **Live**: current map/mode, players and bots with kick, change map now
- **Console**: server output plus an rcon command box
- Optional **login** for the UI

**Setup scripts for players**
- One standalone file per platform, copy it to a friend's machine and run it
- Downloads the game package, installs it, gives each machine its own player identity, and applies settings that run smoothly (lowest graphics, no FPS drops when hit)
- Safe to re-run after an interruption

## Install the game on a new machine

Both scripts use the same prepared game package (`mw.zip`, ~16 GB, from Google Drive), work as single files without the rest of this repo, and can be re-run any time: every step skips what is already done and an interrupted download resumes.

### Mac

```sh
zsh setup-mac.sh
```

1. Installs **Rosetta 2** and **CrossOver** if missing (from Homebrew if available, otherwise from CodeWeavers)
2. Finds `mw.zip` on the Mac or downloads it, then installs it as the CrossOver bottle `mw`
3. Removes the copied player identity (`guid.dat`) and profile (`players/`), so this Mac doesn't collide with others on a server
4. Configures the bottle: Graphics **Auto**, **MSync** on, DLSS off, High Resolution Mode off
5. Sets fullscreen at the Mac's "looks like" resolution and installs the [shared game settings](#shared-game-settings)
6. Puts an **IW4x** launcher on the Desktop and offers to start the game

| Option | Effect |
|---|---|
| `--bottle <name>` | Install under another bottle name (default `mw`) |
| `--force` | Replace an existing bottle with that name (the old one is renamed to a backup, not deleted) |
| `--zip <path>` | Use this `mw.zip` (otherwise it looks in `~/Downloads`, the Bottles folder and the current folder) |
| `--keep-zip` | Keep `mw.zip` after installing (a zip the script didn't download is never deleted) |

Needs about 36 GB free disk space, or 20 GB if `mw.zip` is already there. A bottle the script didn't create is never touched without `--force`, and configuration runs only once, so a re-run never resets your identity or settings.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File setup-windows.ps1
```

No CrossOver needed, the game runs natively.

1. Finds `mw.zip` or downloads it, then extracts **only the game folder** to `C:\Games\Call of Duty Modern Warfare 2`
2. Installs the **DirectX 9 runtime** if missing: IW4x needs `d3dx9_43.dll`, which Windows 10/11 don't ship (Windows asks for permission)
3. Removes the copied profile (`players\`), sets fullscreen at the screen's resolution and installs the [shared game settings](#shared-game-settings)
4. Creates an **IW4x** shortcut on the Desktop and offers to start the game

Options: `-InstallDir <path>`, `-Zip <path>`, `-KeepZip`, `-Force`, same meaning as on the Mac. Allow `iw4x.exe` through Windows Firewall when asked.

### Google Drive "Quota exceeded"

Drive limits how often a shared file can be downloaded per day, and a 16 GB file hits that limit quickly. The scripts detect it and stop with a message. Either wait (it usually resets within 24 hours), or open the Drive link in a browser while logged in, save `mw.zip` to your Downloads folder and run the script again: it picks the file up.

## Run the server

### Requirements

- The game installed (see above), on macOS in a CrossOver bottle, on Windows natively
- [uv](https://docs.astral.sh/uv/) and [go-task](https://taskfile.dev):

  ```sh
  brew install uv go-task                 # macOS
  winget install astral-sh.uv Task.Task   # Windows
  ```

The dedicated server doesn't render anything, so it needs **no GPU**: about one CPU core and 400 MB of RAM.

### Setup

```sh
git clone git@github.com:dorostanian/iw4x-lan-server.git
cd iw4x-lan-server
cp .env.example .env     # adjust the settings below
task config              # installs server.cfg.example as the server config (skips if one exists)
```

| Setting in `.env` | Used by | Default |
|---|---|---|
| `IW4X_SERVER_BOTTLE` | macOS: bottle the server runs in (web UI, `task server`) | `mw` |
| `IW4X_GAME_BOTTLE` | macOS: bottle you play from (`task game`) | `mw` |
| `IW4X_SERVER_DIR` / `IW4X_GAME_DIR` | MW2 folder of the server / game. On Windows these are the only ones that matter | inside the bottle; Windows: `C:\Games\Call of Duty Modern Warfare 2` |
| `IW4X_PORT` | server port (UDP) | `28960` |
| `UI_PORT` | web UI port | `8080` |
| `UI_PASSWORD` | web UI login, see [Passwords](#passwords) | empty = no login |

**On a Mac you also play on, run the server in its own bottle.** Programs in one bottle share a single `wineserver`, and under load (getting hit, explosions) game and server wait on each other, which shows up as stutter. Create a second bottle, copy the server files into it and point the server at it:

```sh
zsh scripts/setup-mac.sh --bottle mw-server
# copy usermaps/, userraw/ and main/server.cfg from the mw bottle's game folder into mw-server's
# then in .env:  IW4X_SERVER_BOTTLE=mw-server   IW4X_GAME_BOTTLE=mw
```

### Commands

Every task works on macOS and Windows.

| Command | What it does |
|---|---|
| `task ui` | Web UI at http://localhost:8080, also reachable from the LAN. Usually all you need: press **Start** in the page |
| `task server` | Dedicated server in the terminal, without the UI (refuses to start a second one) |
| `task stop` | Stops the dedicated server |
| `task game` | Starts the game with the shared settings, skipping the launcher's update check |
| `task game:update` | Same, but lets the launcher update IW4x first |
| `task game:kill` | Stops a stuck launcher or game, leaving the server running |
| `task setup` | Runs this platform's setup script (options after `--`, e.g. `task setup -- --force`) |
| `task sync-config` | Copies `config/client.cfg` into both setup scripts |
| `task config` | Installs the example server config if there is none |

**Mac Desktop shortcuts (optional):** small `.command` files make this one double-click. For example `IW4x.command` containing `exec ~/workspace/iw4x-lan-server/scripts/start-game.sh`, and `IW4x Server UI.command` that runs `cd ~/workspace/iw4x-lan-server && task ui` and opens http://localhost:8080. Make them executable with `chmod +x`.

### Using the web UI

- **Settings** → change values → **Save & apply**: reloads the config and starts the new rotation with a map change. Players stay connected. **Save** alone applies at the next map change.
- **Restart** (top bar) restarts the server process and **disconnects everyone**. Use it only if the server hangs.
- **Map rotation**: click a map to add or remove it, **▶** on a map plays it now. Filter by name, rotation or custom maps.
- **Players**: kick players and bots (tagged **bot**).
- **Bots**: "Fill to" keeps the server at that many players (players + bots) or that many bots; applies from the next map.
- **Console**: server output, and any rcon command (`say hello`, `fast_restart`, `map mp_rust`, ...).

## Passwords

| What | Where to set it | Effect |
|---|---|---|
| **Game password** | Web UI → Settings → **Game password**, then **Save & apply** | Players must enter it to join. Players already on the server stay |
| **Web UI login** | `.env`: `UI_PASSWORD=yourpassword`, then restart the UI | The browser asks for a login (any username, this password) before the page or any action |
| **Rcon password** | Web UI → Settings → **Rcon password** (default `changeme`) | Lets anyone with it control the server directly, bypassing the UI. Change it if others are on your network |

Joining a server with a game password, in the game console (`~`):

```
password yourpassword
connect <server-ip>:28960
```

## Join a game

- **Server Browser → LAN** in IW4x, or
- console (`~`): `connect <server-ip>:28960`. The web UI header shows the address to share.

Everyone needs the same IW4x version, and the same custom maps (`usermaps/<mapname>/` in the game folder) to play those maps.

## Shared game settings

`config/client.cfg` is the one place for the game settings every player gets:

- **Lowest graphics**: lowest textures, no shadows, AA, anisotropic filtering, glow, specular, water, sun, decals, ragdolls
- **No hitches**: shaders prepared at map load
- **No FPS drops when hit**: damage audio filter (EQ/reverb), blood and damage overlays, scripted vision effects off. Under CrossOver the damage EQ alone dropped FPS to ~10 every time you got hit

How it's applied:

- Each launcher (Desktop shortcut, `task game`) starts the game with `+exec client_tweaks.cfg`, a copy of this file in the game's `main/` folder. That reapplies it on **every start**, including settings the game itself never saves to its config.
- `task game` copies the current `config/client.cfg` into the game before starting, so edits apply to your own game right away.
- The setup scripts carry their own copy, since they must work as single files. After editing `config/client.cfg`, run `task sync-config`. CI fails if a setup script is out of sync.

## Troubleshooting

### IW4x won't open

The IW4x shortcut that comes with the game starts `iw4x-launcher.exe`, which checks GitHub for updates first. Under CrossOver that check can hang: the launcher burns CPU without a window and the game never appears. Start it without the check:

```sh
task game
```

Without this repo (Mac):

```sh
cd ~/Library/Application\ Support/CrossOver/Bottles/mw/drive_c/Program\ Files\ \(x86\)/Call\ of\ Duty\ Modern\ Warfare\ 2
/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine --bottle mw --cx-app iw4x-launcher.exe \
  --arch x86 --skip-remote --no-self-update --no-shortcuts --no-connect-protocol \
  --game-args "+exec client_tweaks.cfg"
```

With the update check skipped you get no IW4x updates: run `task game:update` now and then.

Still not opening:

1. **Stuck processes**: `task game:kill`, then try again
2. **Wrong client**: use `iw4x.exe` (classic, x86). `IW4x (mm)` is a separate client that can't join this server and has no `connect` command
3. **Logs**: `cache/launcher_*.log` and `iw4x_*.log` in the game folder

### Window is small or not fullscreen

Quit the game and set in `players/iw4x_config.cfg`:

```
seta r_fullscreen "1"
seta r_noborder "0"
seta r_mode "1512x982"
seta vid_xpos "0"
seta vid_ypos "0"
```

Use your screen's resolution for `r_mode` (on a Mac the "looks like" resolution). The game rewrites this file when it exits, so edit it with the game closed.

### Black screen, stutter or low FPS (Mac)

`iw4x.exe` is a 32-bit DirectX 9 program, which limits what CrossOver can do with it:

| CrossOver Graphics setting | Result with IW4x |
|---|---|
| **Auto** | Works (Wine's DirectX 9 to OpenGL translation). Use this |
| D3DMetal | Not used for this 32-bit game, falls back to the same OpenGL path |
| DXVK | **Black screen** (fails to build the game's shaders) |
| DXMT | DirectX 10/11 only, doesn't apply |

Also keep **MSync** on and **High Resolution Mode** off (it renders at 4x the pixels). For stutter when getting hit, make sure the [shared game settings](#shared-game-settings) are loaded (start through `task game` or the setup's Desktop launcher), and on a Mac that also hosts, run the server in its own bottle.

The in-game FPS counter (`cg_drawFPS 1` in the console) tells graphics problems (FPS drops) from network problems (FPS steady, players jump around).

### Two players kick each other off

Both have the same player identity, usually because a bottle or game folder was copied. Delete the identity file on one of them with the game closed; IW4x creates a new one:

- Mac: `drive_c/users/crossover/AppData/Local/iw4x/guid.dat` inside the bottle
- Windows: `%LOCALAPPDATA%\iw4x\guid.dat`

The setup scripts already take care of this.

## How it works

- The server is `iw4x.exe -dedicated`, on macOS launched through CrossOver's `wine` in the server bottle, on Windows run directly.
- Settings are written to `main/server.cfg` in the server's game folder, which the server runs at startup.
- Live actions (status, kick, map change, apply) go over **rcon** (UDP). IW4x ignores rcon commands that arrive less than 500 ms apart, so the UI spaces them out.
- Map images are read from the `.iwd` archives (IWI textures in RGB, DXT1 or DXT5), converted to JPEG and cached in `services/ui/thumbs/`.
- Stopping the server only targets real server processes, never shells or the game.

## Project layout

```
.
├── Taskfile.yml           # every task runs on macOS and Windows
├── .env.example
├── server.cfg.example
├── config/
│   └── client.cfg         # shared game settings (the one place to edit them)
├── scripts/
│   ├── setup-mac.sh       # new Mac: CrossOver + bottle + config
│   ├── setup-windows.ps1  # new Windows PC: game folder + DirectX + config
│   ├── sync-config.py     # copies config/client.cfg into both setup scripts
│   ├── env.sh             # shared defaults (macOS)
│   ├── start-server.sh
│   ├── start-game.sh      # game with shared settings, optional update check
│   ├── kill-game.sh       # stop stuck game processes
│   ├── install-config.sh
│   └── windows/           # PowerShell versions of the helper scripts
├── services/
│   └── ui/
│       ├── app.py         # FastAPI backend (uv inline script)
│       └── index.html     # single page, Tailwind
└── .github/workflows/
    └── check.yml          # config sync, lint and script parse checks
```
