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

## Setup

```sh
git clone git@github.com:dorostanian/iw4x-lan-server.git
cd iw4x-lan-server
cp .env.example .env     # set IW4X_BOTTLE if your bottle is not called "mw"
task config              # copies server.cfg.example into the game's main/ folder
```

`IW4X_GAME_DIR` defaults to the MW2 folder inside the bottle. Set it in `.env` if your install lives elsewhere.

## Usage

| Command | What it does |
|---|---|
| `task ui` | Starts the web UI at http://localhost:8080 (also reachable from the LAN) |
| `task server` | Starts the dedicated server in the terminal, without the UI |
| `task stop` | Stops the dedicated server |
| `task config` | Installs the example config if the game has none |

Usually you only need `task ui`, then press **Start** in the page.

### Joining

Players on the same network can:

- open **Server Browser → LAN** in IW4x, or
- open the console (`~`) and run `connect <your-mac-ip>:28960`

The UI header shows the address to share.

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
│   └── install-config.sh
└── services/
    └── ui/
        ├── app.py         # FastAPI backend (uv inline script)
        └── index.html     # single page, Tailwind
```
