"""The bastion's WireGuard interface (wg0, set up by deploy/bastion/bootstrap.sh): the game
servers' web UIs and SSH are only reachable through it. The interface belongs to the host; this
adds and removes the peer of each running server (`wg set`, the container has NET_ADMIN), and
puts them all back after a restart of the host or the container."""

import asyncio
import logging

log = logging.getLogger("control.wg")


class WireGuard:
    def __init__(self, interface: str = "wg0"):
        self.interface = interface

    async def wg(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "wg",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode:
            raise RuntimeError(f"wg {args[0]}: {err.decode().strip()}")
        return out.decode().strip()

    async def public_key(self) -> str:
        return await self.wg("show", self.interface, "public-key")

    async def sync(self, peers: dict[str, str]) -> None:
        """Exactly these peers: public key -> address."""
        current = set((await self.wg("show", self.interface, "peers")).split())
        for public in current - set(peers):
            await self.wg("set", self.interface, "peer", public, "remove")
            log.info("removed peer %s", public[:8])
        for public, ip in peers.items():
            if public not in current:
                await self.wg("set", self.interface, "peer", public, "allowed-ips", f"{ip}/32")
                log.info("added peer %s for %s", public[:8], ip)


class FakeWireGuard:
    def __init__(self) -> None:
        self.peers: dict[str, str] = {}

    async def public_key(self) -> str:
        return "BASTION/fake/public/key/AAAAAAAAAAAAAAAAAAAAAAA="

    async def sync(self, peers: dict[str, str]) -> None:
        self.peers = dict(peers)
