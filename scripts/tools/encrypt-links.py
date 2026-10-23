# /// script
# requires-python = ">=3.13"
# dependencies = ["cryptography"]
# ///
"""Encrypt the mw.zip and maps pack download links into the setup scripts.

Asks for both links and a password, then writes the encrypted links into every
setup script. When no zip is found locally, the scripts ask players for that
password and download from the decrypted links.

Format is openssl's, so the scripts decrypt with:
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -a -A

  uv run scripts/tools/encrypt-links.py
"""

import base64
import getpass
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent.parent
ITERATIONS = 200_000
# script -> the line holding the encrypted links
TARGETS = {
    "mac/setup.sh": re.compile(r'^LINKS_ENC=".*"$', re.MULTILINE),
    "linux/setup.sh": re.compile(r'^LINKS_ENC=".*"$', re.MULTILINE),
    "linux/setup-game.sh": re.compile(r'^LINKS_ENC=".*"$', re.MULTILINE),
    "mac/install-maps.sh": re.compile(r'^LINKS_ENC=".*"$', re.MULTILINE),
    "windows/setup.ps1": re.compile(r'^\$LinksEnc = ".*"$', re.MULTILINE),
    "windows/install-maps.ps1": re.compile(r'^\$LinksEnc = ".*"$', re.MULTILINE),
}


def encrypt(text: str, password: str) -> str:
    salt = os.urandom(8)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48, salt=salt, iterations=ITERATIONS)
    key_iv = kdf.derive(password.encode())
    padder = padding.PKCS7(128).padder()
    data = padder.update(text.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key_iv[:32]), modes.CBC(key_iv[32:])).encryptor()
    return base64.b64encode(b"Salted__" + salt + encryptor.update(data) + encryptor.finalize()).decode()


def main() -> int:
    game = input("mw.zip download link: ").strip()
    maps = input("maps pack download link: ").strip()
    if not game.startswith("http") or not maps.startswith("http"):
        print("both links must start with http")
        return 1
    password = getpass.getpass("password: ")
    if not password or password != getpass.getpass("password again: "):
        print("passwords empty or not the same")
        return 1

    blob = encrypt(f"game={game}\nmaps={maps}\n", password)
    for name, line in TARGETS.items():
        path = ROOT / "scripts" / name
        text = path.read_text()
        if not line.search(text):
            print(f"{name}: encrypted links line not found")
            return 1
        value = f'"{blob}"'
        path.write_text(line.sub(lambda m, v=value: m.group(0).split('"', 1)[0] + v, text, count=1))
    print("updated: " + ", ".join(TARGETS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
