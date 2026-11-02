# /// script
# requires-python = ">=3.11"
# ///
"""Sets up the Telegram join and leave messages (README: "Join and leave messages in
Telegram"). Run it with task telegram, which reads .env:

- TELEGRAM_CHAT_ID empty: lists the groups the bot was added to, with their chat ids
- TELEGRAM_CHAT_ID set: sends a test message to that group
"""

import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def call(method: str, **params) -> dict:
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        if e.code == 409:  # a server answering /servers reads the bot's messages: only one may
            sys.exit("A server reads this bot's messages (it answers /servers), so this can't list the groups."
                     " Send /servers in the group instead: the server's log (docker compose logs server)"
                     " shows the chat id of a group that isn't TELEGRAM_CHAT_ID.")
        sys.exit(f"Telegram: {json.load(e).get('description', e)}")
    except OSError as e:
        sys.exit(f"Telegram not reachable: {e}")


if not TOKEN:
    sys.exit("Put the bot's token in .env: TELEGRAM_BOT_TOKEN=... (Telegram: @BotFather -> /newbot)")
bot = call("getMe")["username"]

if CHAT:
    call("sendMessage", chat_id=CHAT, text="✅ Test from the IW4x server: joins and leaves show up here")
    print(f"Sent a test message to {CHAT} as @{bot}. Restart the web UI (Linux: docker compose up -d) to start.")
    sys.exit()

# Telegram keeps a bot's updates for 24 hours: being added to a group, a /start@bot in it
chats, moved = {}, set()
for u in call("getUpdates"):
    for kind in ("message", "my_chat_member"):
        update = u.get(kind, {})
        if update.get("chat", {}).get("type") in ("group", "supergroup"):
            chats[update["chat"]["id"]] = update["chat"].get("title", "")
        if "migrate_to_chat_id" in update:  # the group became a supergroup, with a new id
            moved.add(update["chat"]["id"])
chats = {i: t for i, t in chats.items() if i not in moved}
if not chats:
    sys.exit(f"@{bot} hasn't seen a group yet. Add it to the group, send /start@{bot} there,"
             " then run this again.")
print(f"Groups @{bot} is in, put one in .env:")
for chat_id, title in chats.items():
    print(f"  TELEGRAM_CHAT_ID={chat_id}   ({title})")
print("Then run task telegram again for a test message.")
