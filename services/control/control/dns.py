"""Cloudflare DNS: a server's domain follows its VM (DNS only: the game needs plain UDP, which
Cloudflare's proxy doesn't pass). A short TTL, so players reach a new VM within a minute."""

import httpx

from control.providers import CloudError

API = "https://api.cloudflare.com/client/v4"
TTL = 60


class Cloudflare:
    def __init__(self, token: str, http: httpx.AsyncClient | None = None):
        self.http = http or httpx.AsyncClient(timeout=30)
        self.headers = {"Authorization": f"Bearer {token}"}
        self.zones: dict[str, str] = {}

    async def call(self, method: str, path: str, body: dict | None = None):
        try:
            r = await self.http.request(method, API + path, json=body, headers=self.headers)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise CloudError(f"Cloudflare not reachable: {type(e).__name__}") from None
        if not data.get("success"):
            errors = "; ".join(e.get("message", "") for e in data.get("errors", []))
            raise CloudError(f"Cloudflare {method} {path.split('?')[0]}: {errors}", r.status_code)
        return data["result"]

    async def zone_id(self, name: str) -> str:
        """The zone is the longest suffix of the name that Cloudflare knows."""
        labels = name.split(".")
        for i in range(len(labels) - 1):
            suffix = ".".join(labels[i:])
            if suffix in self.zones:
                return self.zones[suffix]
            found = await self.call("GET", f"/zones?name={suffix}")
            if found:
                self.zones[suffix] = found[0]["id"]
                return found[0]["id"]
        raise CloudError(f"no Cloudflare zone for {name} (check CLOUDFLARE_DNS_TOKEN)")

    async def point(self, name: str, ip: str) -> None:
        zone = await self.zone_id(name)
        record = {"type": "A", "name": name, "content": ip, "ttl": TTL, "proxied": False}
        existing = await self.call("GET", f"/zones/{zone}/dns_records?type=A&name={name}")
        if existing and existing[0]["content"] == ip and existing[0]["ttl"] == TTL:
            return
        if existing:
            await self.call("PATCH", f"/zones/{zone}/dns_records/{existing[0]['id']}", record)
        else:
            await self.call("POST", f"/zones/{zone}/dns_records", record)

    async def close(self) -> None:
        await self.http.aclose()


class FakeDns:
    def __init__(self) -> None:
        self.records: dict[str, str] = {}

    async def point(self, name: str, ip: str) -> None:
        self.records[name] = ip

    async def close(self) -> None:
        pass
