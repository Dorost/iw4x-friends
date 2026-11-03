# The fleet: a bastion and game servers on demand

Our servers don't run all the time. A small always-on VM, the **bastion** (`https://mw2.dorost.nl`), creates a game server when it's wanted and destroys it afterwards, by a schedule or by a button on the fleet page or in the Telegram mini app.

```
                          players: connect mw2-nl.dorost.nl (UDP 28960)
                                         │
 Telegram ── mini app, messages ──┐      ▼
 browser ─── fleet page ──────────┤   ┌──────────────┐   ┌──────────────┐   ┌───────────────────┐   ┌──────────────┐
 GitHub Actions ── deploy (SSH) ──┤   │ NL  (Vultr)  │   │ US  (Vultr)  │   │ Istanbul (Zenlayer)│   │ Milan (Vultr)│
                                  ▼   │ game server  │   │ game server  │   │ game server        │   │ game server  │
                ┌──────────────────┐  │ its own disk │   │ its own disk │   │ its own disk       │   │ its own disk │
                │ bastion (Vultr)  │  └──────┬───────┘   └──────┬───────┘   └─────────┬─────────┘   └──────┬───────┘
                │ control plane    │◄────────┴──── WireGuard ───┴─────────────────────┴─────────────────────┘
                │ planner bot      │   (each server's web UI and SSH: only through here)
                │ Caddy (HTTPS)    │
                └──────────────────┘
```

- **The bastion** runs the control plane ([`services/control`](../services/control)), the planner bot ([`services/bot`](../services/bot)) and Caddy, from [`bastion/docker-compose.yml`](bastion/docker-compose.yml). Its own disk keeps the schedules, the bot's database and the HTTPS certificates, so a rebuilt bastion carries on where the old one was.
- **A game server** is a VM made from plain Ubuntu at every boot, the same way each time ([`node/bootstrap.sh`](node/bootstrap.sh)). What has to last is on the server's own disk, which outlives the VM: the game files (17 GB, downloaded on its first boot only), `server.cfg` and the web UI's presets. Shutting down destroys the VM and keeps the disk, so nothing is billed for the VM while it's off.
- **WireGuard** connects the bastion with the servers. A server's web UI and SSH listen only on it; to the internet a server only opens the game port.
- **Domains:** players connect to `mw2-nl.dorost.nl`, `mw2-us.dorost.nl`, `mw2-ist.dorost.nl` and `mw2-milan.dorost.nl`. While a server runs, its domain points at its VM, otherwise at the bastion.
- **Telegram:** the mini app (`https://mw2.dorost.nl/tg/`) shows every server, boots and shuts them down, and changes map, mode and bots. The bastion posts joins and leaves, who booted a server, and when it is up or shut down. A server booted outside a schedule window comes with the warning that it goes offline 15 minutes after it's up if nobody joins. The game servers never get the bot token.
- **Fleet page** (`https://mw2.dorost.nl`, `UI_PASSWORD`): every server with boot and shut down, the schedules, what happened, and each running server's own control page at `/s/<server>/`.

The servers are listed in [`fleet.toml`](fleet.toml): region, plan, domain, disk size. A new server is one more block there with a free WireGuard address.

## When a server runs

- **In a schedule window** it runs, players or not. It boots 10 minutes before the window starts (`LEAD_MINUTES`), so it's ready on time.
- **Outside a window** it runs until nobody has played on it for 15 minutes (`IDLE_MINUTES`; bots don't count). That counts from when it came up: a boot nobody joins stops after 15 minutes. A window that ends with players on keeps going until 15 minutes after the last one left.
- **Shut down by hand** during a window, it stays off until that window ends. Booting it by hand again lifts that.

A boot takes about 5 minutes (VM, Docker, the server image). The first boot of a server also downloads the game onto its disk, 15 to 30 minutes. A scheduled boot that fails is tried again 10 minutes later, 3 times per window. Schedules are set on the fleet page; the Telegram mini app only boots and shuts down.

## Deploys

Every push to `main` builds the images (`ghcr.io/dorost/iw4x-friends:<commit>` for the game servers, `:control-<commit>` and `:bot-<commit>` for the bastion) and deploys the commit to the bastion ([`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)). GitHub connects with a key that can only run [`bastion/deploy.sh`](bastion/deploy.sh), and sends the settings along. The script restarts what changed, and goes back to the previous commit if the control plane or the bot doesn't answer.

The game servers follow by themselves. The next boot starts on the new commit. A running server moves to it once nobody has played for 2 minutes ([`node/update.sh`](node/update.sh): when `services/ui` didn't change, nothing restarts). The fleet page has **Update now** for when that can't wait.

**Actions → ci → Run workflow** on a branch (a PR's) deploys that branch to the bastion, and with it the servers; the next push to `main` puts `main` back.

## Secrets and settings

All in the GitHub environment **`bastion`** (Settings → Environments). The deploy writes them to `/opt/iw4x/deploy/bastion/.env` on the bastion (readable by root only), from where the control plane and the bot get theirs. Changing one there and running the deploy again (Actions → ci → Run workflow on `main`) applies it.

| Secret | What |
| --- | --- |
| `UI_PASSWORD` | the fleet page's password |
| `TELEGRAM_BOT_TOKEN` | the bot (@BotFather) |
| `VULTR_API_KEY` | creates and destroys the bastion and the NL, US and Milan servers (Vultr: Account → API) |
| `CLOUDFLARE_DNS_TOKEN` | points the domains at the VMs (Cloudflare: API Tokens → "Edit zone DNS" for `dorost.nl`) |
| `MW_SETUP_PASSWORD` | the setup password: a server's first boot decrypts the game's download links with it |
| `GAME_JOIN_PASSWORD` | the password players type to join (`password <password>`), set on every server at every boot. A server can be opened to everyone instead (🔒/🌐 on the fleet page and in the mini app); that choice is kept for its next boots. Without the secret, each server keeps the one set in its own control page |
| `ZENLAYER_ACCESS_KEY_ID`, `ZENLAYER_ACCESS_KEY_PASSWORD` | Istanbul (Zenlayer console: Access Keys). Without them, Istanbul doesn't show up |
| `DEPLOY_SSH_KEY` | the SSH key GitHub deploys with; the bastion lets it run `bastion/deploy.sh` and nothing else |
| `BASTION_SSH_HOST_KEY` | the bastion's own SSH host key. Every new bastion gets it, so the deploy can check it's talking to the bastion |

| Variable | What |
| --- | --- |
| `TELEGRAM_CHAT_ID` | the group (`task telegram` finds it) |
| `ADMIN_SSH_KEYS` | public SSH keys, one per line, let into the bastion and the servers |
| `BOT_DEFAULT_TZ`, `BOT_MIN_PLAYERS` | the planner bot (optional) |
| `IDLE_MINUTES`, `LEAD_MINUTES` | see [When a server runs](#when-a-server-runs) (optional, 15 and 10) |

Nothing else is secret, so it's in the repo: [`fleet.toml`](fleet.toml). The bastion makes the rest itself and never hands them out. That covers a new WireGuard key and a new web UI password for each server on every boot, the SSH key it reaches the servers with, and the fleet page's session key. A server gets the setup password only while the game still has to be downloaded.

## Setting it up from scratch

Everything is created by GitHub Actions; what you do by hand is put the secrets in GitHub, once.

1. **Make the environment and its secrets.** In the repo: Settings → Environments → New environment `bastion`, then add the secrets and variables from the tables above. The two SSH keys are new key pairs made for this, nothing else uses them; either `task fleet:keys` makes both and stores them (needs `gh`, logged in as a repo admin), or make each with `ssh-keygen -t ed25519 -N "" -f key` and paste the content of `key` (the private half) as the secret.
2. **Let GitHub use the Vultr API key.** Vultr only takes API calls from the addresses allowed under Account → API → Access Control, and GitHub's runners have changing addresses: allow all IPv4 (`0.0.0.0/0`). The bastion also calls from its own address.
3. **Merge to `main`.** The `ci` workflow builds and pushes the images. Its deploy step finds no bastion yet and skips, while `mw2.dorost.nl` still leads to another machine (or fails, if the name leads nowhere: the old servers already gone).
4. **Actions → bastion → Run workflow** (on `main`). It waits for that commit's images, then creates the bastion's disk and VM (`vc2-1c-1gb` in Amsterdam) and points `mw2.dorost.nl` at it. The new VM sets itself up from plain Ubuntu ([`bastion/bootstrap.sh`](bastion/bootstrap.sh)): Docker, WireGuard, the firewall, its disk. The workflow then deploys to it. About 10 minutes in all. From then on every push to `main` deploys by itself.
5. **Telegram:** in @BotFather, `/mybots` → the bot → Bot Settings → Configure Mini App: set the URL to `https://mw2.dorost.nl/tg/`. This one Telegram only lets you do there.
6. **Boot each server once** from the fleet page or the mini app: the first boot downloads the game onto its disk.

For Istanbul, the bastion makes what Zenlayer needs itself on its first boot there: a VPC `iw4x-fleet` (`172.30.0.0/16`) with a subnet in Istanbul, and a security group with the game port open. Only check that `plan` in `fleet.toml` is an Istanbul instance type in stock: `task fleet:zenlayer-types` (with the two Zenlayer keys in your local `.env`).

**Rebuilding the bastion:** Run workflow on `bastion` with **rebuild** replaces the VM with a fresh one made the same way. Its disk stays, and with it the schedules, the bot's database and the HTTPS certificates. A bastion deleted together with its disk is made new from scratch by a plain Run workflow.

**Replacing a secret:** change it in the environment, then Actions → ci → Run workflow on `main` deploys it. New SSH keys (`task fleet:keys --force`) also need a rebuild, as the bastion has the old ones.

## The old servers

The always-on VPSes from before (Vultr labels `iw4x` and `iw4x-nl`) can be destroyed whenever: nothing here uses them. The old NL server runs the planner bot, and Telegram lets only one program read the bot's messages. So destroy it, or at least stop its bot, before the bastion starts its own (step 4). The planner bot's data (plans, free hours) is in that server's `bot-data` volume; copy `bot.db` to `/srv/iw4x/bot/` on the bastion to keep it. Then delete the GitHub environments `nl` and `us`.

## Running it

- **SSH:** `ssh root@mw2.dorost.nl` for the bastion, `ssh -J root@mw2.dorost.nl root@10.66.0.11` for a running server (`.12` US, `.13` Istanbul, `.14` Milan), with a key from `ADMIN_SSH_KEYS`.
- **Logs:** on the bastion, `cd /opt/iw4x && docker compose -f deploy/bastion/docker-compose.yml logs control` (or `bot`, `caddy`). On a server, `/var/log/iw4x-bootstrap.log` for its setup and `cd /opt/iw4x && docker compose -f deploy/node/docker-compose.yml logs` for the game server. A failed boot keeps its VM for 10 minutes, so there's time to look.
- **Trying the control plane:** `task control:dev` runs the fleet page on `http://localhost:8070` (password `dev`) with pretend clouds and servers. Nothing is created and nothing goes to Telegram. `task control:test` runs its tests.
- **Costs:** the bastion is Vultr's `vc2-1c-1gb` ($5/month). A game server is `vhf-2c-4gb`, $0.033 per hour while it runs; Milan has no such plan and is `voc-c-2c-4gb-50s-amd`, $0.055 per hour. Each disk is billed every month, running or not (Vultr NVMe block storage for the game servers, HDD for the bastion; Zenlayer's data disk for Istanbul). A disk made before the switch to NVMe stays HDD: the bastion finds it by its label and keeps using it.
