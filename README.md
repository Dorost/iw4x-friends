# IW4x LAN Server

Play Modern Warfare 2 ([IW4x](https://iw4x.io)) with friends: one script installs the game, one double-click runs the server.

## What players need

From whoever invites you:
- the setup files for your system: `setup-windows.ps1` + `install-maps.ps1` (Windows) or `setup-mac.sh` + `install-maps.sh` (Mac), in the same folder
- the **setup password**, or the files themselves: `mw.zip` and `mw2-iw4x-maps-bots.zip`

Zips in your **Downloads** folder (or the folder you run setup from) are found automatically. Otherwise the setup asks for the password and downloads them. Press Enter at the password prompt to paste a download link or the path to a zip instead (or drag the zip file into the window).

## Windows

1. Open **PowerShell** (Start menu → type "PowerShell") in the folder with the setup files, or `cd` there
2. Run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File setup-windows.ps1
   ```

3. Type the setup password when asked, then wait (~17 GB). If it stops, run the same command again, it continues where it left off
4. Click **Yes** if Windows asks to install DirectX, and **Allow** if the firewall asks about `iw4x.exe`
5. Start the game with the **IW4x** icon on your Desktop

Only need the custom maps and bots? Run `powershell -ExecutionPolicy Bypass -File install-maps.ps1` instead.

## Mac

1. Open **Terminal** (Spotlight → type "Terminal") and go to the folder with the setup files, e.g. `cd ~/Downloads`
2. Run:

   ```sh
   zsh setup-mac.sh
   ```

3. Type the setup password when asked, then wait (~17 GB). If it stops, run the same command again, it continues where it left off
4. If CrossOver opens, choose **Try Now**, then go back to Terminal and press Enter
5. Start the game with the **IW4x** icon on your Desktop

Only need the custom maps and bots? Run `bash install-maps.sh` instead.

## Joining a game

In the game, open **Server Browser → LAN**, or press `~` and type:

```
connect <server-ip>:28960
```

If the server has a password, type `password <password>` first.

**Max level and all unlocks:** at the main menu, press `~`, type `unlockstats` and press Enter, then restart the game. Progress is stored on each player's own computer, so everyone does this once on their machine.

**Ready-made classes:** ten agile classes (SMGs and light rifles, two M16 classes, a quickscope sniper, a Search & Destroy stealth class), most with silencer or red dot plus FMJ, see [`config/classes.cfg`](config/classes.cfg). Load them at the main menu: press `~` and type `exec classes.cfg`. Or press **F9** during a match (key bindings don't work in menus). They replace your custom class slots, so run `unlockstats` first.

## Server

Runs on any Mac or Windows PC with the game installed (see above). No GPU needed.

1. Get this repo: on GitHub **Code → Download ZIP** and unzip it (it's private, so you need access)
2. Double-click **Start Server** (`Start Server.command` on Mac, `Start Server.cmd` on Windows). On a Mac the first time: right-click → Open
3. The control page opens in your browser: press **Start**

In the control page you can pick maps and game modes, add bots, kick players and set a game password (**Settings → Save & apply**). To protect the control page itself, set `UI_PASSWORD=yourpassword` in the `.env` file and start it again.

The server needs the custom maps too: they come with the setup above. If the server runs from its own CrossOver bottle (for example `mw-server`), add them there:

```sh
bash scripts/install-maps.sh --bottle mw-server
```

### Download links

The setup scripts carry the `mw.zip` and maps pack links encrypted with the setup password. To set or change them, run `task links` (asks for both links and the password), then commit the updated scripts.

### Linux VPS (optional)

For a server on the internet, on an x86_64 VPS with a domain pointing to it:

```sh
git clone git@github.com:dorostanian/iw4x-lan-server.git   # private: needs a GitHub key with access
cd iw4x-lan-server
bash scripts/setup-linux.sh
docker compose up -d --build
```

Then open `https://<your-domain>`, log in with the password the setup printed, and press **Start**.
