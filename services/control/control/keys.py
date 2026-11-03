"""Keys the control plane makes itself, so they never pass through GitHub: a WireGuard key pair
per boot, an SSH key for reaching the game servers, the web UI session secret."""

import base64
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


def wireguard_pair() -> tuple[str, str]:
    """(private, public), base64 as wg(8) writes them."""
    key = X25519PrivateKey.generate()
    raw = serialization.Encoding.Raw
    private = key.private_bytes(raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(raw, serialization.PublicFormat.Raw)
    return base64.b64encode(private).decode(), base64.b64encode(public).decode()


def token() -> str:
    """A game server's web UI password for one run: URL safe, nothing .env would mangle."""
    return secrets.token_urlsafe(32)


def ssh_key(path: Path) -> str:
    """The control plane's SSH key (made once, in the data dir); returns the public line."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
        path.write_bytes(pem)
        path.chmod(0o600)
    key = serialization.load_ssh_private_key(path.read_bytes(), password=None)
    public = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    return public.decode() + " iw4x-control"


def public_of(private_openssh: str, comment: str) -> str:
    """The public line of an OpenSSH private key (for the deploy key and the bastion host key)."""
    key = serialization.load_ssh_private_key(private_openssh.strip().encode() + b"\n", None)
    public = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    return f"{public.decode()} {comment}".strip()


def secret_file(path: Path) -> bytes:
    """A random secret kept in a file (made the first time)."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()
