# IW4x LAN Server

Run a Modern Warfare 2 (IW4x) dedicated server on a Mac with CrossOver, and manage it from a small web UI on your local network.

![stack](https://img.shields.io/badge/python-3.13-3776ab) ![stack](https://img.shields.io/badge/FastAPI-uv-009688) ![stack](https://img.shields.io/badge/CrossOver-macOS-6e4aff)

## Features

- **Start / stop / restart** the dedicated server
- **Save & apply** settings with a map change, so players stay connected
- **Settings**: server name, passwords, game mode, max players, score/time limits
- **Map rotation picker** with loading-screen images extracted from the game files, plus custom maps from `usermaps/`
- **Game modes** detected from the installed files, including the IW4x extras (Gun Game, Infected, Kill Confirmed, VIP) and modes added by mods
- **Bots** (Bot Warfare mod): fill count, counting mode, skill
- **Live**: current map/mode, player list with kick, change map now
- **Console**: server output plus an rcon command box

## Requirements

- macOS with [CrossOver](https://www.codeweavers.com/crossover)
- A CrossOver bottle with MW2 and the [IW4x](https://iw4x.io) client installed
- [uv](https://docs.astral.sh/uv/) and [go-task](https://taskfile.dev)

```sh
brew install uv go-task
```

## New Mac: install the game

`scripts/setup-mac.sh` sets up a Mac from scratch, so friends can play too. It's a single standalone file: copy it over (AirDrop works) and run:

```sh
zsh setup-mac.sh
```

What it does:

1. Installs **Rosetta 2** and **CrossOver** if missing. CrossOver comes from Homebrew if available, otherwise from CodeWeavers directly.
2. Downloads the prepared `mw` bottle (`mw.zip`, ~16 GB) from Google Drive. If interrupted, re-run and it resumes.
3. Installs it into CrossOver's `Bottles` folder.
4. Configures it:
   - removes the copied player identity (`guid.dat`) and profile (`players/`), so this Mac gets its own and doesn't collide with others on a server
   - CrossOver bottle: Graphics **Auto**, **MSync** on, DLSS off, High Resolution Mode off
   - fullscreen at the Mac's native "looks like" resolution
   - lowest graphics preset (textures, shadows, effects, AA off) with shader preloading, which avoids hitches when shooting starts
   - damage audio filter (EQ/reverb) and scripted damage effects off. Under CrossOver the EQ made FPS drop to ~10 every time you got hit
5. Puts an **IW4x** launcher on the Desktop that skips the update check that can hang, and offers to start the game.

| Option | Effect |
|---|---|
| `--bottle <name>` | Install under another bottle name (default `mw`), e.g. to test next to an existing one |
| `--force` | Replace an existing bottle with that name (the old one is renamed to a backup, not deleted) |
| `--zip <path>` | Use an already downloaded `mw.zip` |
| `--keep-zip` | Keep `mw.zip` after installing |

**Safe to re-run.** If the script stops (network drop, Ctrl+C, reboot), run it again and it continues:

- CrossOver is skipped if installed; its download resumes if interrupted
- an existing complete `mw.zip` in `~/Downloads`, the Bottles folder or the current folder is reused; a partial one resumes
- a bottle installed by an earlier run is kept and setup continues from there. A bottle the script didn't create is never touched without `--force`
- configuration runs once, so a re-run never resets your identity or graphics settings

**Google Drive "Quota exceeded".** Drive limits how often a shared file can be downloaded per day, and a 16 GB file hits that limit quickly. The script detects this and stops with a message. Either wait (it usually resets within 24 hours), or open the Drive link in a browser while logged in, save `mw.zip` to `~/Downloads` and re-run.

Needs about 36 GB free disk space, or 20 GB if `mw.zip` is already downloaded. From the repo you can also run `task setup` (options after `--`, for example `task setup -- --force`).

## Server setup

```sh
git clone git@github.com:dorostanian/iw4x-lan-server.git
cd iw4x-lan-server
cp .env.example .env     # set the bottle names, see below
task config              # copies server.cfg.example into the game's main/ folder
```

| Setting | Used by | Default |
|---|---|---|
| `IW4X_SERVER_BOTTLE` | dedicated server, web UI, `task server` | `mw` |
| `IW4X_GAME_BOTTLE` | `task game`, `task game:update` | `mw` |
| `IW4X_SERVER_DIR` / `IW4X_GAME_DIR` | override the MW2 folder inside those bottles | standard path |

**Run the server in its own bottle** if you also play on the same Mac. Two Windows programs in one bottle share a single `wineserver`, and under load (getting hit, explosions) the game and server wait on each other, which shows up as stutter. Create a second bottle (for example `zsh scripts/setup-mac.sh --bottle mw-server`), copy `usermaps/`, `userraw/` and `main/server.cfg` into it, and set `IW4X_SERVER_BOTTLE=mw-server`.

## Usage

| Command | What it does |
|---|---|
| `task ui` | Starts the web UI at http://localhost:8080 (also reachable from the LAN) |
| `task server` | Starts the dedicated server in the terminal, without the UI |
| `task stop` | Stops the dedicated server |
| `task config` | Installs the example config if the game has none |
| `task game` | Starts the IW4x game, skipping the launcher's update check |
| `task game:update` | Runs the IW4x launcher normally, with the update check |
| `task game:kill` | Stops a stuck launcher or game, leaving the server running |

Usually you only need `task ui`, then press **Start** in the page.

### Joining

Players on the same network can:

- open **Server Browser → LAN** in IW4x, or
- open the console (`~`) and run `connect <your-mac-ip>:28960`

The UI header shows the address to share.

## IW4x won't open?

The IW4x shortcut starts `iw4x-launcher.exe`, which checks GitHub for updates before starting the game. Under CrossOver that check can hang: the launcher burns CPU with no window, and the game never appears.

**Fix: start it without the update check**

```sh
task game
```

That runs the launcher with flags that skip the remote check and start the classic x86 client right away:

```
iw4x-launcher.exe --arch x86 --skip-remote --no-self-update --no-shortcuts --no-connect-protocol
```

Without this repo, run it straight from the bottle:

```sh
cd ~/Library/Application\ Support/CrossOver/Bottles/mw/drive_c/Program\ Files\ \(x86\)/Call\ of\ Duty\ Modern\ Warfare\ 2
/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine --bottle mw --cx-app iw4x-launcher.exe \
  --arch x86 --skip-remote --no-self-update --no-shortcuts --no-connect-protocol
```

With `--skip-remote` you get no IW4x updates. Run `task game:update` now and then to update, and fall back to `task game` if it hangs.

**Still not opening? Check these:**

1. **Stuck instances.** Stop leftover launcher and game processes, then try again:
   ```sh
   task game:kill
   ```
   This leaves the dedicated server running. `task stop` stops only the server.
2. **Wrong client.** Use `iw4x.exe` (classic, x86). `IW4x (mm)` is a separate client that can't join this server and has no `connect` command.
3. **Window is tiny or off-screen.** Quit the game and set these in `players/iw4x_config.cfg`:
   ```
   seta r_fullscreen "1"
   seta r_noborder "0"
   seta r_mode "1512x982"
   seta vid_xpos "0"
   seta vid_ypos "0"
   ```
   Use your Mac's "looks like" resolution for `r_mode`. The game rewrites this file when it exits, so edit it with the game closed.
4. **Black screen, crash or stutter.** In CrossOver, open the bottle → Advanced Settings and set **Graphics: Auto**. Some backends (D3DMetal, for example) can stutter or fail with this DirectX 9 game. Keep **High Resolution Mode** off and **MSync** on.
5. **Logs.** The launcher logs to `cache/launcher_*.log` and the game to `iw4x_*.log` in the game folder. Check the newest one for errors.

## How it works

- The server is `iw4x.exe -dedicated`, launched through CrossOver's `wine` in the configured bottle.
- Settings are written to `main/server.cfg` in the game folder, which the server runs at startup.
- Live actions (status, kick, map change, apply) go over **rcon** (UDP). IW4x ignores rcon commands that arrive less than 500 ms apart, so the UI spaces them out.
- Map images are read from the `.iwd` archives (IWI textures in RGB, DXT1 or DXT5), converted to JPEG and cached in `services/ui/thumbs/`.

## Tips

- **Each player needs a unique identity.** If you copy a bottle to another Mac, delete `drive_c/users/crossover/AppData/Local/iw4x/guid.dat` there. Otherwise the server sees both as the same player and kicks one.
- **Custom maps** go in `usermaps/<mapname>/` in the game folder. Every player needs the same files.
- **Change `rcon_password`** from `changeme` if other people are on your network.
- The web UI has no login and is reachable from your whole LAN.

## Project layout

```
.
├── Taskfile.yml
├── .env.example
├── server.cfg.example
├── scripts/
│   ├── env.sh             # shared defaults
│   ├── start-server.sh
│   ├── start-game.sh      # game client, optional update check
│   ├── setup-mac.sh       # new Mac: CrossOver + bottle + config
│   ├── kill-game.sh       # stop stuck client processes
│   └── install-config.sh
└── services/
    └── ui/
        ├── app.py         # FastAPI backend (uv inline script)
        └── index.html     # single page, Tailwind
```
