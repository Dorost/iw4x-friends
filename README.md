# IW4x LAN Server

Play Modern Warfare 2 ([IW4x](https://iw4x.io)) with friends: set up the game on Macs (through CrossOver) and Windows PCs with one script, and run a dedicated server you manage from a web UI, at home or on a Linux VPS.

![stack](https://img.shields.io/badge/python-3.13-3776ab) ![stack](https://img.shields.io/badge/FastAPI-uv-009688) ![stack](https://img.shields.io/badge/macOS-CrossOver-6e4aff) ![stack](https://img.shields.io/badge/Windows-native-0078d4) ![stack](https://img.shields.io/badge/Linux-Docker%20%2B%20Wine-2496ed)

## Quick start

**Mac player**: open Terminal (Spotlight → "Terminal"), paste this and press Enter:

```sh
zsh -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-mac.sh)"
```

**Windows player**: open PowerShell (Start menu → "PowerShell"), paste this and press Enter:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-windows.ps1)))
```

Both install everything (on the Mac including CrossOver), put an **IW4x** icon on the Desktop and start the game. Join with **Server Browser → LAN**, or press `~` and type `connect <server-ip>:28960`.

**Server host (Mac or Windows)**: on [GitHub](https://github.com/dorostanian/iw4x-lan-server) click **Code → Download ZIP**, unzip it, and double-click **Start Server** (`Start Server.command` on Mac, `Start Server.cmd` on Windows). It sets everything up on first run and opens the web UI, where you press **Start**. The game must be installed on that machine first (see above).

Nothing else to install: no git, no go-task. The rest of this README is details.

## Contents

- [Features](#features)
- [For Mac players](#for-mac-players)
- [For Windows players](#for-windows-players)
- [Running the server](#running-the-server) (Mac, Windows, Linux VPS)
- [Shared game settings](#shared-game-settings)
- [How it works](#how-it-works)
- [Project layout](#project-layout)

## Features

**Setup scripts for players**
- One standalone file per platform: copy it to a friend's machine and run it
- Downloads the game package, installs it, gives each machine its own player identity, and applies settings that run smoothly (lowest graphics, no FPS drops when hit)
- Safe to re-run after an interruption

**Web UI for the dedicated server**
- **Start / stop / restart**, and **Save & apply**: settings take effect with a map change, players stay connected
- **Settings**: server name, game password, rcon password, mode, max players, score/time limits, LAN only
- **Map rotation picker** with loading-screen images from the game files, including custom maps from `usermaps/`
- **Game modes** detected from the installed files, including the IW4x extras (Gun Game, Infected, Kill Confirmed, VIP) and modes added by mods
- **Bots** (Bot Warfare mod): fill count, counting mode, skill
- **Live**: current map/mode, players and bots with kick, change map now
- **Console**: server output plus an rcon command box
- Optional **login** for the UI

---

## For Mac players

### Install

In Terminal:

```sh
zsh -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-mac.sh)"
```

Or download [`setup-mac.sh`](https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-mac.sh) and run `zsh setup-mac.sh`. Options go at the end: `zsh -c "$(curl -fsSL ...)" setup --force`.

1. Installs **Rosetta 2** and **CrossOver** if missing (from Homebrew if available, otherwise from CodeWeavers). On first install it opens CrossOver once: choose "Try Now" or register
2. Finds the game package `mw.zip` (~16 GB) on the Mac or downloads it, then installs it as the CrossOver bottle `mw`
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

Needs about 36 GB free disk space, or 20 GB if `mw.zip` is already there.

**Safe to re-run.** If it stops (network drop, Ctrl+C, reboot), run the same command again: every step skips what is done and the download resumes. A bottle the script didn't create is never touched without `--force`, and configuration runs only once, so a re-run never resets your identity or settings.

**Google Drive "Quota exceeded".** Drive limits how often a shared file can be downloaded per day, and a 16 GB file hits that limit quickly. The script detects it and stops with a message. Either wait (it usually resets within 24 hours), or open the Drive link from the message in a browser while logged in, save `mw.zip` to `~/Downloads` and run the script again: it picks the file up.

### Play

1. Double-click **IW4x** on the Desktop (first time: right-click → Open if macOS blocks it)
2. Join: **Server Browser → LAN**, or press `~` and type `connect <server-ip>:28960`
3. If the server has a game password, type `password <password>` in the console before `connect`

### Troubleshooting (Mac)

**IW4x won't open.** The IW4x shortcut that comes with the game starts `iw4x-launcher.exe`, which checks GitHub for updates first. Under CrossOver that check can hang: the launcher burns CPU without a window and the game never appears. The setup's Desktop launcher skips that check. To start it by hand:

```sh
cd ~/Library/Application\ Support/CrossOver/Bottles/mw/drive_c/Program\ Files\ \(x86\)/Call\ of\ Duty\ Modern\ Warfare\ 2
/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine --bottle mw --cx-app iw4x-launcher.exe \
  --arch x86 --skip-remote --no-self-update --no-shortcuts --no-connect-protocol \
  --game-args "+exec client_tweaks.cfg"
```

With the update check skipped you get no IW4x updates: from the repo, run `task game:update` now and then. Still not opening:

1. **Stuck processes**: `task game:kill` (from the repo), or quit CrossOver, then try again
2. **Wrong client**: use `iw4x.exe` (classic, x86). `IW4x (mm)` is a separate client that can't join this server and has no `connect` command
3. **Logs**: `cache/launcher_*.log` and `iw4x_*.log` in the game folder

**Black screen, stutter or low FPS.** `iw4x.exe` is a 32-bit DirectX 9 program, which limits what CrossOver can do with it:

| CrossOver Graphics setting | Result with IW4x |
|---|---|
| **Auto** | Works (Wine's DirectX 9 to OpenGL translation). Use this |
| D3DMetal | Not used for this 32-bit game, falls back to the same OpenGL path |
| DXVK | **Black screen** (fails to build the game's shaders) |
| DXMT | DirectX 10/11 only, doesn't apply |

Keep **MSync** on and **High Resolution Mode** off (it renders at 4x the pixels). For stutter when getting hit, make sure the [shared game settings](#shared-game-settings) are loaded by starting through the Desktop launcher. The FPS counter (`cg_drawFPS 1` in the console) tells graphics problems (FPS drops) from network problems (FPS steady, players jump around).

**Window is small or not fullscreen.** Quit the game and set in `players/iw4x_config.cfg` (inside the bottle's game folder):

```
seta r_fullscreen "1"
seta r_noborder "0"
seta r_mode "1512x982"
seta vid_xpos "0"
seta vid_ypos "0"
```

Use your Mac's "looks like" resolution for `r_mode`. The game rewrites this file when it exits, so edit it with the game closed.

**Two players kick each other off.** Both have the same player identity, usually because a bottle was copied. With the game closed, delete `drive_c/users/crossover/AppData/Local/iw4x/guid.dat` inside the bottle on one of them; IW4x creates a new one. The setup script already does this.

---

## For Windows players

No CrossOver needed: the game runs natively.

### Install

1. **Open PowerShell**: Start menu → type "PowerShell" → **Windows PowerShell**. No admin needed
2. **Paste this and press Enter**:

   ```powershell
   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-windows.ps1)))
   ```

   With options: `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-windows.ps1))) -InstallDir "D:\Games\MW2"`

Or download [`setup-windows.ps1`](https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-windows.ps1) and run `powershell -ExecutionPolicy Bypass -File setup-windows.ps1` (Windows blocks unsigned script files by default; the flag only applies to this run).

What it does:

1. Finds the game package `mw.zip` (~16 GB) or downloads it, then extracts **only the game folder** to `C:\Games\Call of Duty Modern Warfare 2`
2. Installs the **DirectX 9 runtime** if missing: IW4x needs `d3dx9_43.dll`, which Windows 10/11 don't ship. Windows asks for permission, click **Yes**
3. Removes the copied profile (`players\`), sets fullscreen at the screen's resolution and installs the [shared game settings](#shared-game-settings)
4. Creates an **IW4x** shortcut on the Desktop and offers to start the game

| Option | Effect |
|---|---|
| `-InstallDir <path>` | Install somewhere else, e.g. `-InstallDir "D:\Games\MW2"` |
| `-Force` | Replace an existing install (the old folder is renamed to a backup, not deleted) |
| `-Zip <path>` | Use this `mw.zip` (otherwise it looks in Downloads and the current folder) |
| `-KeepZip` | Keep `mw.zip` after installing |

Needs about 36 GB free on the install drive. **Safe to re-run** like the Mac script, and the same [Google Drive "Quota exceeded"](#install) advice applies: download `mw.zip` in a browser to `Downloads` and run the script again.

### Play

1. Double-click **IW4x** on the Desktop
2. If Windows Firewall asks about `iw4x.exe`, click **Allow** (private networks)
3. Join: **Server Browser → LAN**, or press `~` and type `connect <server-ip>:28960`. With a game password, type `password <password>` first

### Troubleshooting (Windows)

- **Game doesn't start / missing DLL**: install the DirectX 9 runtime from [Microsoft](https://download.microsoft.com/download/1/7/1/1718CCC4-6315-4D8E-9543-8E28A4E18C4C/dxwebsetup.exe) and try again
- **Can't see or join the server**: make sure `iw4x.exe` is allowed in Windows Firewall, and that both machines are on the same network (guest Wi-Fi often blocks devices from seeing each other)
- **Two players kick each other off**: with the game closed, delete `%LOCALAPPDATA%\iw4x\guid.dat` on one of them; IW4x creates a new identity
- **Window is small or not fullscreen**: same settings as on the Mac, in `C:\Games\Call of Duty Modern Warfare 2\players\iw4x_config.cfg`, with your screen resolution for `r_mode`
- **Logs**: `cache\launcher_*.log` and `iw4x_*.log` in the game folder

---

## Running the server

The dedicated server doesn't render anything, so it needs **no GPU**: about one CPU core and 400 MB of RAM. Run it on a Mac, a Windows PC or a Linux VPS.

### On a Mac or Windows PC

1. Install the game on that machine (see the player sections above)
2. Get this repo: on [GitHub](https://github.com/dorostanian/iw4x-lan-server) **Code → Download ZIP** and unzip it (or `git clone https://github.com/dorostanian/iw4x-lan-server.git`)
3. Double-click **Start Server**: `Start Server.command` on Mac (first time: right-click → Open, since it's downloaded), `Start Server.cmd` on Windows

On first run it installs [uv](https://docs.astral.sh/uv/) (runs the web UI's Python), creates `.env` from `.env.example` and installs `server.cfg.example` as the server config. Then it opens the web UI at http://localhost:8080: press **Start**. Closing its window stops the UI, not the game server.

[go-task](https://taskfile.dev) is optional: with it (`brew install go-task`, `winget install Task.Task`) the [commands](#commands) below are available as shortcuts.

**On a Mac you also play on, run the server in its own bottle.** Programs in one bottle share a single `wineserver`, and under load (getting hit, explosions) game and server wait on each other, which shows up as stutter. Create a second bottle, copy the server files into it and point the server at it:

```sh
zsh scripts/setup-mac.sh --bottle mw-server
# copy usermaps/, userraw/ and main/server.cfg from the mw bottle's game folder into mw-server's
# then in .env:  IW4X_SERVER_BOTTLE=mw-server   IW4X_GAME_BOTTLE=mw
```

On Windows that isn't needed. Allow `iw4x.exe` (and Python, for the UI) through Windows Firewall when asked.

**Desktop shortcut (optional):** drag `Start Server.command` to the Dock (Mac), or right-click `Start Server.cmd` → Send to → Desktop (Windows).

### On a Linux VPS

IW4x only ships Windows binaries, so on Linux the dedicated server runs under Wine, in Docker together with the web UI. Caddy serves the UI over HTTPS on your domain.

**VPS size:** x86_64 (no ARM), 1 to 2 vCPU, 2 GB RAM, about 40 GB disk during setup (20 GB after). The server mainly uses one core, so a fast core matters more than many. No GPU.

**Before you start:** point a DNS A record (e.g. `iw4x.example.com`) at the VPS's public IP.

```sh
git clone https://github.com/dorostanian/iw4x-lan-server.git
cd iw4x-lan-server
bash scripts/setup-linux.sh        # Docker, game files, public server.cfg, .env, firewall
docker compose up -d --build       # server + web UI + Caddy
```

With [go-task](https://taskfile.dev) installed, the same is `task setup` and `task up`.

`task setup` (`scripts/setup-linux.sh`, safe to re-run):

1. Installs Docker and unzip if missing
2. Downloads `mw.zip` (resumes if interrupted) and extracts only the game folder into `game/`
3. Installs `server.cfg` with `sv_lanOnly 0` (public) and a **random rcon password**: rcon goes over the public game port, so `changeme` would let anyone control the server
4. Asks for the UI domain and generates a `UI_PASSWORD` if empty. Both are required, `task up` refuses to start without them
5. Opens `28960/udp`, `80/tcp` and `443/tcp` in ufw. Open them in your provider's firewall too

Then open `https://<your-domain>`, log in and press **Start**. Players join with `connect <vps-ip>:28960`.

| Command | What it does |
|---|---|
| `docker compose up -d --build` (`task up`) | Builds and starts everything in the background, restarts on reboot |
| `docker compose down` (`task down`) | Stops everything |
| Web UI **Stop** (`task stop`) | Stops only the dedicated server |
| `docker compose logs -f` | Logs of the UI and Caddy |

**Performance setup:**

- **Host networking**: no Docker NAT on the game's UDP traffic, so no extra latency and the server sees real player addresses (kick, status)
- **`WINEDEBUG=-all`**: Wine's debug logging costs CPU on every call
- **32-bit Wine prefix built into the image**: what `iw4x.exe` needs, and starts fast
- **Crash dialog off**: a crashed server exits instead of hanging on an invisible window, so **Start** works again
- The UI listens on `127.0.0.1` only. From outside it's reachable only through Caddy (HTTPS + login)

### Settings (`.env`)

| Setting | Used by | Default |
|---|---|---|
| `IW4X_SERVER_BOTTLE` | macOS: bottle the server runs in (web UI, `task server`) | `mw` |
| `IW4X_GAME_BOTTLE` | macOS: bottle you play from (`task game`) | `mw` |
| `IW4X_SERVER_DIR` / `IW4X_GAME_DIR` | MW2 folder of the server / game. On Windows these are the only ones that matter | inside the bottle; Windows: `C:\Games\Call of Duty Modern Warfare 2` |
| `IW4X_PORT` | server port (UDP) | `28960` |
| `UI_PORT` | web UI port | `8080` |
| `UI_PASSWORD` | web UI login, see [Passwords](#passwords) | empty = no login (required on Linux) |
| `DOMAIN` | Linux: domain the web UI is served on over HTTPS | none |

### Commands

Optional shortcuts if you have [go-task](https://taskfile.dev). Everything works without them: **Start Server** for the UI, the Desktop **IW4x** icon for the game.

| Command | What it does |
|---|---|
| `task ui` | Web UI at http://localhost:8080, also reachable from the LAN. Usually all you need: press **Start** in the page |
| `task server` | Dedicated server in the terminal, without the UI (refuses to start a second one) |
| `task stop` | Stops the dedicated server |
| `task game` | Starts the game with the shared settings, skipping the launcher's update check |
| `task game:update` | Same, but lets the launcher update IW4x first |
| `task game:kill` | Stops a stuck launcher or game, leaving the server running |
| `task setup` | Runs this platform's setup script (options after `--`, e.g. `task setup -- --force`) |
| `task sync-config` | Copies `config/client.cfg` into the setup scripts |
| `task config` | Installs the example server config if there is none |
| `task up` / `task down` | Linux: start / stop the Docker stack |

### Using the web UI

- **Settings** → change values → **Save & apply**: reloads the config and starts the new rotation with a map change. Players stay connected. **Save** alone applies at the next map change.
- **Restart** (top bar) restarts the server process and **disconnects everyone**. Use it only if the server hangs.
- **Map rotation**: click a map to add or remove it, **▶** on a map plays it now. Filter by name, rotation or custom maps.
- **Players**: kick players and bots (tagged **bot**).
- **Bots**: "Fill to" keeps the server at that many players (players + bots) or that many bots; applies from the next map.
- **Console**: server output, and any rcon command (`say hello`, `fast_restart`, `map mp_rust`, ...).

Custom maps go in `usermaps/<mapname>/` in the server's game folder; every player needs the same files to play them.

### Passwords

| What | Where to set it | Effect |
|---|---|---|
| **Game password** | Web UI → Settings → **Game password**, then **Save & apply** | Players must enter it to join (`password <pw>` in the console before `connect`). Players already on the server stay |
| **Web UI login** | `.env`: `UI_PASSWORD=yourpassword`, then restart the UI | The browser asks for a login (any username, this password) before the page or any action |
| **Rcon password** | Web UI → Settings → **Rcon password** (default `changeme`) | Lets anyone with it control the server directly, bypassing the UI. Change it if others are on your network |

---

## Shared game settings

`config/client.cfg` is the one place for the game settings every player gets, on Mac and Windows:

- **Lowest graphics**: lowest textures, no shadows, AA, anisotropic filtering, glow, specular, water, sun, decals, ragdolls
- **No hitches**: shaders prepared at map load
- **No FPS drops when hit**: damage audio filter (EQ/reverb), blood and damage overlays, scripted vision effects off. Under CrossOver the damage EQ alone dropped FPS to ~10 every time you got hit

How it's applied:

- Each launcher (Desktop shortcut, `task game`) starts the game with `+exec client_tweaks.cfg`, a copy of this file in the game's `main/` folder. That reapplies it on **every start**, including settings the game itself never saves to its config.
- `task game` copies the current `config/client.cfg` into the game before starting, so edits apply to your own game right away.
- The setup scripts carry their own copy, since they must work as single files. After editing `config/client.cfg`, run `task sync-config`. CI fails if a setup script is out of sync.

## How it works

- The server is `iw4x.exe -dedicated`: on macOS launched through CrossOver's `wine` in the server bottle, on Windows run directly, on Linux through Wine inside Docker (with a virtual X display, since the server opens a console window).
- Settings are written to `main/server.cfg` in the server's game folder, which the server runs at startup.
- Live actions (status, kick, map change, apply) go over **rcon** (UDP). IW4x ignores rcon commands that arrive less than 500 ms apart, so the UI spaces them out.
- Map images are read from the `.iwd` archives (IWI textures in RGB, DXT1 or DXT5), converted to JPEG and cached in `services/ui/thumbs/`.
- Stopping the server only targets real server processes, never shells or the game.

## Project layout

```
.
├── Start Server.command   # macOS: double-click to start the web UI
├── Start Server.cmd       # Windows: double-click to start the web UI
├── Taskfile.yml           # optional shortcuts; every task runs on macOS and Windows; up/down on Linux
├── docker-compose.yml     # Linux: server + web UI + Caddy
├── .env.example
├── server.cfg.example
├── config/
│   └── client.cfg         # shared game settings (the one place to edit them)
├── scripts/
│   ├── setup-mac.sh       # new Mac: CrossOver + bottle + config
│   ├── setup-windows.ps1  # new Windows PC: game folder + DirectX + config
│   ├── setup-linux.sh     # Linux VPS: Docker + game folder + public config
│   ├── sync-config.py     # copies config/client.cfg into the setup scripts
│   ├── env.sh             # shared defaults (macOS)
│   ├── start-server.sh
│   ├── start-game.sh      # game with shared settings, optional update check
│   ├── kill-game.sh       # stop stuck game processes
│   ├── install-config.sh
│   └── windows/           # PowerShell versions of the helper scripts (start-ui.ps1 behind Start Server.cmd)
├── services/
│   └── ui/
│       ├── Dockerfile     # Linux: Wine + Xvfb + web UI
│       ├── app.py         # FastAPI backend (uv inline script)
│       └── index.html     # single page, Tailwind
└── .github/workflows/
    └── check.yml          # config sync, lint and script parse checks
```
