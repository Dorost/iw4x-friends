# IW4x LAN Server

Play Modern Warfare 2 ([IW4x](https://iw4x.io)) with friends: one command installs the game, one double-click runs the server.

## Windows

1. Open **PowerShell** (Start menu → type "PowerShell")
2. Paste this and press Enter:

   ```powershell
   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-windows.ps1)))
   ```

3. Wait for the download (~17 GB, game plus custom maps and bots). If it stops, run the same command again, it continues where it left off
4. Click **Yes** if Windows asks to install DirectX, and **Allow** if the firewall asks about `iw4x.exe`
5. Start the game with the **IW4x** icon on your Desktop

Already have the game and only need the custom maps and bots? Run this instead:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.ps1)))
```

## Mac

1. Open **Terminal** (Spotlight → type "Terminal")
2. Paste this and press Enter:

   ```sh
   zsh -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-mac.sh)"
   ```

3. Wait for the download (~17 GB, game plus custom maps and bots). If it stops, run the same command again, it continues where it left off
4. If CrossOver opens, choose **Try Now**, then go back to Terminal and press Enter
5. Start the game with the **IW4x** icon on your Desktop

Already have the game and only need the custom maps and bots? Run this instead:

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.sh)"
```

## Joining a game

In the game, open **Server Browser → LAN**, or press `~` and type:

```
connect <server-ip>:28960
```

If the server has a password, type `password <password>` first.

**Max level and all unlocks:** at the main menu, press `~`, type `unlockstats` and press Enter, then restart the game. Progress is stored on each player's own computer, so everyone does this once on their machine.

**Ready-made classes:** after `unlockstats`, load ten agile classes (SMGs and light rifles, a quickscope sniper, a Search & Destroy stealth class), see [`config/classes.cfg`](config/classes.cfg). Put the file in the game's `main` folder (`task game` does this), then at the main menu press `~` and type `exec classes.cfg`. They replace your custom class slots.

## Server

Runs on any Mac or Windows PC with the game installed (see above). No GPU needed.

1. On this page click **Code → Download ZIP** and unzip it
2. Double-click **Start Server** (`Start Server.command` on Mac, `Start Server.cmd` on Windows). On a Mac the first time: right-click → Open
3. The control page opens in your browser: press **Start**

In the control page you can pick maps and game modes, add bots, kick players and set a game password (**Settings → Save & apply**). To protect the control page itself, set `UI_PASSWORD=yourpassword` in the `.env` file and start it again.

The server needs the custom maps too: they come with the setup above. If the server runs from its own CrossOver bottle (for example `mw-server`), add them there:

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.sh)" install-maps --bottle mw-server
```

### Linux VPS (optional)

For a server on the internet, on an x86_64 VPS with a domain pointing to it:

```sh
git clone https://github.com/dorostanian/iw4x-lan-server.git
cd iw4x-lan-server
bash scripts/setup-linux.sh
docker compose up -d --build
```

Then open `https://<your-domain>`, log in with the password the setup printed, and press **Start**.
