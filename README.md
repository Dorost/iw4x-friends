# IW4x: MW2 with friends

Play Modern Warfare 2 ([IW4x](https://iw4x.io)) with friends, on Windows, Mac or Linux:

1. **[Install the game](#install-the-game)**: one script sets up MW2 + IW4x, the custom maps and bots, and a Desktop icon
2. **[Join a game](#joining-a-game)**: on your LAN or over the internet
3. **[Host a server](#hosting-a-server)** (optional): a dedicated server with a web control page, on a Mac or Windows PC at home, or on a Linux VPS for internet play

## Install the game

From whoever invites you:
- the two setup files for your system, in the same folder: [`scripts/windows/`](scripts/windows) `setup.ps1` + `install-maps.ps1`, or [`scripts/mac/`](scripts/mac) `setup.sh` + `install-maps.sh`, or on Linux [`scripts/linux/setup-game.sh`](scripts/linux/setup-game.sh) + [`scripts/mac/install-maps.sh`](scripts/mac/install-maps.sh)
- the **setup password**, or the files themselves: `mw.zip` and `mw2-iw4x-maps-bots.zip`

Zips in your **Downloads** folder (or the folder you run setup from) are found automatically. Otherwise the setup asks for the password and downloads them. Press Enter at the password prompt to paste a download link or the path to a zip instead (or drag the zip file into the window).

### Windows

1. Open **PowerShell** (Start menu → type "PowerShell") in the folder with the setup files, or `cd` there
2. Run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```

3. Type the setup password when asked, then wait (~17 GB). If it stops, run the same command again, it continues where it left off
4. Click **Yes** if Windows asks to install DirectX, and **Allow** if the firewall asks about `iw4x.exe`
5. Start the game with the **IW4x** icon on your Desktop

Only need the custom maps and bots? Run `powershell -ExecutionPolicy Bypass -File install-maps.ps1` instead.

### Mac

1. Open **Terminal** (Spotlight → type "Terminal") and go to the folder with the setup files, e.g. `cd ~/Downloads`
2. Run:

   ```sh
   zsh setup.sh
   ```

3. Type the setup password when asked, then wait (~17 GB). If it stops, run the same command again, it continues where it left off
4. If CrossOver opens, choose **Try Now**, then go back to Terminal and press Enter
5. Start the game with the **IW4x** icon on your Desktop

Only need the custom maps and bots? Run `bash install-maps.sh` instead.

### Linux

On an x86_64 PC with a Vulkan graphics driver. The game runs in Wine with DXVK; no Steam needed.

1. Open a terminal in the folder with the setup files (or the repo), e.g. `cd ~/Downloads`
2. Run:

   ```sh
   bash setup-game.sh
   ```

3. Type your own password if it asks to install Wine, then the setup password, and wait (~17 GB). If it stops, run the same command again, it continues where it left off. Short on disk space? Download `mw.zip` to another drive and add `--zip /path/to/mw.zip`
4. Start the game with **IW4x** in your app menu

It installs into `~/Games/iw4x` (change it with `--dir`). Only need the custom maps and bots? Run `bash install-maps.sh --dir ~/Games/iw4x/game` instead.

## Joining a game

In the game, open **Server Browser → LAN** for a server on your network. For any server (LAN or internet), press `~` and type:

```
connect <server-ip-or-domain>:28960
```

If the server has a password, type `password <password>` first.

**Max level and all unlocks:** at the main menu, press `~`, type `unlockstats` and press Enter, then restart the game. Progress is stored on each player's own computer, so everyone does this once on their machine.

**Ready-made classes:** ten agile classes (SMGs and light rifles, two M16 classes, a quickscope sniper, a Search & Destroy stealth class), most with silencer or red dot plus FMJ, see [`config/classes.cfg`](config/classes.cfg). Load them at the main menu: press `~` and type `exec classes.cfg`. Or press **F9** during a match (key bindings don't work in menus). They replace your custom class slots, so run `unlockstats` first.

## Hosting a server

### On a Mac or Windows PC

Runs on any Mac or Windows PC with the game installed (see above). No GPU needed. Good for a LAN party; for internet play, forward UDP port 28960 on your router or use a VPS (below).

1. Get this repo: on GitHub **Code → Download ZIP** and unzip it
2. Double-click **Start Server** (`Start Server.command` on Mac, `Start Server.cmd` on Windows). On a Mac the first time: right-click → Open
3. The control page opens in your browser: press **Start**

Matches run back to back: when one ends, the scoreboard shows what is next and the next map and mode load right away, no lobby in between. Players see "Next up" at the start of each match, in its last minute and whenever it changes. In the control page, picking a map and mode sets the next match, **Start game** switches to it now and **End match** ends the running one early. In game, players can pick with `!map` and `!gt`, or vote: with no map picked, a vote starts 90 seconds before a timed match ends (game type first when none is picked, then 6 of the 16 original MW2 maps). Vote with **F1** to **F6**, `!1` to `!6` in chat, or Enter/F to step through. Search & Destroy offers only the 16 original maps and plays to 12 round wins unless you set another Win limit. Nobody gets disconnected in between. You can also add bots, kick players and set a game password. To protect the control page itself, set `UI_PASSWORD=yourpassword` in the `.env` file and start it again: the page then asks for that password.

The server needs the custom maps too: they come with the setup above. If the server runs from its own CrossOver bottle (for example `mw-server`), add them there:

```sh
bash scripts/mac/install-maps.sh --bottle mw-server
```

### On a Linux VPS (internet)

For a server on the internet, on an x86_64 VPS with a domain pointing to it:

```sh
git clone https://github.com/Dorost/iw4x-friends.git
cd iw4x-friends
bash scripts/linux/setup.sh
docker compose up -d --build
```

Then open `https://<your-domain>` and log in with the password from `UI_PASSWORD` in `.env` (setup asks for it). To change it, edit `.env` and run `docker compose up -d`.

### On Vultr, created by script

Creates the VPS (New York, high frequency 2 CPU / 4 GB), copies this repo, runs the setup and starts everything. No domain needed: the web UI gets `https://<ip>.sslip.io`. To use your own name instead, set `VPS_DOMAIN` and `CLOUDFLARE_DNS_TOKEN` in `.env`: `vps:up` then points the name at the VPS (DNS only) and players connect with `connect <your-name>`.

1. Put your Vultr API key in `.env`: `VULTR_API_KEY=...` (Vultr: Account → API, and allow your IP there)
2. Run `task vps:up`, type the setup password when asked. At the end it prints the web UI link and the `connect` address. Log in with `UI_PASSWORD` from your local `.env` (set it before `vps:up`; running `vps:up` again updates it)
3. Done playing: `task vps:down` destroys the VPS (billing stops, the game files go with it)

`task vps:status` shows the address again.

A second server next to it (e.g. Amsterdam): put `VPS_LABEL`, `VPS_REGION` and `VPS_DOMAIN` in front of each command, e.g. `VPS_LABEL=iw4x-nl VPS_REGION=ams VPS_DOMAIN=mw2-nl.example.com uv run scripts/tools/vultr.py up` (also `status`, `down`, `sync-iw4x`).

### Join and leave messages in Telegram

The server can post to a Telegram group when someone joins or leaves (bots don't count), with who is playing now:

> 🟢 **Amin** joined Dorost NL
> Playing (3): Amin, Bob, Yashar

Someone counts as gone after a minute away, so a map change, or a game crash or server restart they come back from, posts nothing. Leaves come without a notification sound.

1. In Telegram, message [@BotFather](https://t.me/BotFather): `/newbot`, pick a name. It answers with the bot's token
2. Add the bot to your group and send `/start@<bot name>` in it
3. Put the token in `.env`: `TELEGRAM_BOT_TOKEN=...`, then run `task telegram`: it lists the group with its chat id
4. Put that in `.env` too: `TELEGRAM_CHAT_ID=-100...`, then `task telegram` again sends a test message
5. Restart the web UI: on a Mac or Windows PC close its window and start it again, on Linux run `docker compose up -d` (restarts the game server)

On a VPS, put the two lines in the `.env` on the server (`~/iw4x/.env`). Several servers can post to the same group: each message names the server (`sv_hostname`). The web UI's log (`docker compose logs server`) shows whether the bot works.

### Map, mode and bots from Telegram

With the bot set up (above), a server on a VPS also has a Telegram mini app: a page that opens inside Telegram and shows each server's map, mode and players. Members of the group can change the map and mode there: pick a mode (the 8 stock modes, Gun Game or Gun Game Extended: Free-for-all with the Fun panel's preset of that name), then a map from its picture. **Start now** switches the running match, players stay connected; **Next match** loads it when the match ends. Leaving a gun game turns the weapons back to classes; other Fun settings stay as they are.

The bot button next to it sets the bots, as in the web UI: fill the match up to a number of players or add a number of bots on top, and their skill. It applies within seconds, also mid-match.

1. List the servers it shows, on each server, in `~/iw4x/.env`: `TELEGRAM_APP_SERVERS=mw2-nl.example.com mw2.example.com` (all with the same bot and group), then `docker compose up -d`
2. In Telegram, message @BotFather: `/mybots` → your bot → **Bot Settings** → **Configure Mini App** → **Enable Mini App**, and send it the address of one of them: `https://mw2-nl.example.com/tg/`

The bot's messages in the group then get a **🎮 Servers** button that opens it, and so does the bot's profile (**Open App**). `/servers` in the group (or to the bot) answers with the button too: the planner bot (below) handles it. Nobody needs the web UI password: Telegram signs who opened the app, and each server asks Telegram whether they are in the group. The map pictures are the loading screens from each server's own game files.

### Tonight? planner bot

The same Telegram bot also plans the nights, for friends in NL and California. It runs on one server only (NL), as the `bot` service of `docker-compose.yml`, and is the only program that reads the bot's messages (`services/bot`).

- 📣 `/play sat 20:00` (or `tomorrow 9pm`, `tonight`, `in 2h`, `21:30 ca`) posts a card with the time in both zones, **Sat 20:00 NL · 11:00 CA**, and **✅ In / 🤔 Maybe / ❌ Out** buttons. Once `BOT_MIN_PLAYERS` (3) are in it posts **🔥 Match on!** and pins the card (the bot has to be an admin to pin)
- ⏰ 30 and 5 minutes before, everyone who is in gets a DM with `connect mw2-nl.dorost.nl`; who never started the bot in private is mentioned in the group instead
- 🌍 `/tz` sets your zone (Amsterdam, Los Angeles, or `/tz Area/City`); without one it's `BOT_DEFAULT_TZ`. Times follow summer time in each zone
- 🗓 **📅 Plan** in the mini app: tap the hours you're usually free, per weekday, in your own zone. `/when` lists the best times for everyone this week, with a button to post one as a card
- 🟢 `/online` shows who is on each server
- 🔔 `/link <in-game name>` ties you to your name in the game, `/watch <name>` (or `@username` of someone who did `/link`) DMs you when they join a server, `/unwatch` stops it
- 🕹 `/servers` answers with the mini app buttons

The bot asks each server in `TELEGRAM_APP_SERVERS` who is playing (`/tg/api/state`) every 20 seconds, signed like the mini app as the bot itself, which is in the group: nothing to change on the game servers. Caddy sends `https://<domain>/bot/` to the bot, which serves the Plan page; the servers' mini app opens it.

To run it on a server, add to its `.env` (the `TELEGRAM_*` lines are already there):

```sh
COMPOSE_PROFILES=bot
BOT_DEFAULT_TZ=Europe/Amsterdam
BOT_MIN_PLAYERS=3
```

then `docker compose up -d --build`. Deploys from GitHub build it on that server. Its data is in the `bot-data` volume (`/data/bot.db`, SQLite; the bot creates and upgrades the tables when it starts).

#### Try it with a test bot first

A second bot from @BotFather (`/newbot`) and a test group, so the real group and bot stay untouched:

1. Add the test bot to a test group, send `/start@<test bot name>` there, and get its chat id: `TELEGRAM_BOT_TOKEN=<test token> TELEGRAM_CHAT_ID= uv run scripts/tools/telegram.py` (straight, so `.env` can't put the real token in)
2. In `.env` here: `BOT_DEV_TOKEN=<test token>`, `BOT_DEV_CHAT_ID=<test chat id>`
3. `task bot:dev`: the bot with its own `services/bot/dev.db` and fake game servers from `services/bot/dev-state.json` (edit the players there to try `/online` and friend alerts). It stops when `BOT_DEV_TOKEN` is the real bot's token
4. The Plan page in a browser, without Telegram: set `BOT_DEV_USER_ID=<your Telegram user id>` and open `http://localhost:8090/bot/`. Inside Telegram it needs HTTPS: point a tunnel (e.g. `cloudflared tunnel --url http://localhost:8090`) at it and give BotFather `https://<tunnel>/bot/` as the test bot's Mini App

`task bot:test` runs the tests (time parsing over summer time in both zones, cards and RSVPs, overlaps, reminders, access checks, a dry run against a fake Telegram), black and ruff.

### Updates from GitHub

The servers behind `mw2.dorost.nl` and `mw2-nl.dorost.nl` get their updates from GitHub. Every push builds the server image and starts its web UI as a test; on `main` the image goes to `ghcr.io/dorost/iw4x-friends:<commit>` and is deployed to the NL server, then the US one: [`scripts/deploy/deploy.sh`](scripts/deploy/deploy.sh) checks out the commit and, when `services/ui` changed, restarts the game server with the new image (players get disconnected and can rejoin right away). If the web UI or the game doesn't answer after that, it goes back to the previous version and leaves the US server alone. A file changed by hand on a server (`scp`, `vps:sync-ui`) stops the deploy: put the change in `main` instead.

To try a PR on a server before merging it: **Actions → ci → Run workflow**, pick the PR's branch and the server (`nl`, `us` or `both`). It builds that commit's image and deploys it like above; the server keeps it until the next push to `main` (or Run workflow on `main`) puts `main` back. The branch has to be in this repo (push a fork's PR to a branch here first) and have this workflow (merge `main` into it if it's older).

To set a server up for it, once, as root on the server:

```sh
cd ~/iw4x
git init -q && git remote add origin https://github.com/Dorost/iw4x-friends.git
git fetch -q origin main && git checkout -qf --detach origin/main
# the image running now, to go back to if the first deploy fails
docker tag "$(docker inspect -f '{{.Image}}' iw4x-server-1)" ghcr.io/dorost/iw4x-friends:pre-ci
echo IMAGE_TAG=pre-ci >> .env
```

Then add the server's deploy key (the public half of the `DEPLOY_SSH_KEY` secret of its environment in the repo settings, `nl` or `us`) to `~/.ssh/authorized_keys`, limited to the deploy script:

```
restrict,command="bash /root/iw4x/scripts/deploy/deploy.sh" ssh-ed25519 AAAA... iw4x deploy
```

A new server also gets an environment with its own `DEPLOY_SSH_KEY`, a deploy job in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) (a copy of `deploy-us`) and its host key (`/etc/ssh/ssh_host_ed25519_key.pub`) in [`scripts/deploy/known_hosts`](scripts/deploy/known_hosts).

## Repo layout

- `scripts/windows/`, `scripts/mac/`, `scripts/linux/`: setup and helper scripts per system
- `scripts/tools/`: maintenance (`task sync-config`, `task links`, `task telegram`)
- `scripts/deploy/`: deploys from GitHub Actions to the servers (see [Updates from GitHub](#updates-from-github))
- `config/`: shared game settings and classes, copied into the setup scripts by `task sync-config`
- `services/ui/`: the server's web control page
- `services/bot/`: the Tonight? planner bot (see [Tonight? planner bot](#tonight-planner-bot))
- `services/caddy/`: Caddy's config: HTTPS, the web UI and `/bot/`

The setup scripts carry the `mw.zip` and maps pack links encrypted with the setup password. To set or change them, run `task links` (asks for both links and the password), then commit the updated scripts.
