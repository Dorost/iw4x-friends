# IW4x: MW2 with friends

Play Modern Warfare 2 ([IW4x](https://iw4x.io)) with friends, on Windows or Mac:

1. **[Install the game](#install-the-game)**: one script sets up MW2 + IW4x, the custom maps and bots, and a Desktop icon
2. **[Join a game](#joining-a-game)**: on your LAN or over the internet
3. **[Host a server](#hosting-a-server)** (optional): a dedicated server with a web control page, on a Mac or Windows PC at home, or on a Linux VPS for internet play

## Install the game

From whoever invites you:
- the two setup files for your system, in the same folder: [`scripts/windows/`](scripts/windows) `setup.ps1` + `install-maps.ps1`, or [`scripts/mac/`](scripts/mac) `setup.sh` + `install-maps.sh`
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

The server runs as a lobby, like vanilla MW2: players join the lobby and wait there. In the control page you pick the map and mode and press **Start game** to take everyone into the match, and **Back to lobby** to end it early. When a match ends, everyone goes back to the lobby; no map starts on its own. Nobody gets disconnected in between. You can also add bots, kick players and set a game password. To protect the control page itself, set `UI_PASSWORD=yourpassword` in the `.env` file and start it again.

The server needs the custom maps too: they come with the setup above. If the server runs from its own CrossOver bottle (for example `mw-server`), add them there:

```sh
bash scripts/mac/install-maps.sh --bottle mw-server
```

### On a Linux VPS (internet)

For a server on the internet, on an x86_64 VPS with a domain pointing to it:

```sh
git clone https://github.com/dorostanian/iw4x-friends.git
cd iw4x-friends
bash scripts/linux/setup.sh
docker compose up -d --build
```

Then open `https://<your-domain>`, log in with the password the setup printed, and press **Start**.

### On Vultr, created by script

Creates the VPS (New York, high frequency 2 CPU / 4 GB), copies this repo, runs the setup and starts everything. No domain needed: the web UI gets `https://<ip>.sslip.io`. To use your own name instead, set `VPS_DOMAIN` and `CLOUDFLARE_DNS_TOKEN` in `.env`: `vps:up` then points the name at the VPS (DNS only) and players connect with `connect <your-name>`.

1. Put your Vultr API key in `.env`: `VULTR_API_KEY=...` (Vultr: Account → API, and allow your IP there)
2. Run `task vps:up`, type the setup password when asked. At the end it prints the web UI link, its password and the `connect` address
3. Done playing: `task vps:down` destroys the VPS (billing stops, the game files go with it)

`task vps:status` shows the address again.

## Repo layout

- `scripts/windows/`, `scripts/mac/`, `scripts/linux/`: setup and helper scripts per system
- `scripts/tools/`: maintenance (`task sync-config`, `task links`)
- `config/`: shared game settings and classes, copied into the setup scripts by `task sync-config`
- `services/ui/`: the server's web control page

The setup scripts carry the `mw.zip` and maps pack links encrypted with the setup password. To set or change them, run `task links` (asks for both links and the password), then commit the updated scripts.
