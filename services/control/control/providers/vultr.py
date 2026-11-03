"""Vultr (api.vultr.com/v2): VMs from Ubuntu 24.04 with a user-data script, block storage as the
disk that outlives them. Vultr bills a halted VM like a running one, so a VM is destroyed when
its server stops."""

import asyncio
import base64

import httpx

from control.providers import ACTIVE, FAILED, GONE, PENDING, CloudError, Instance, Machine

API = "https://api.vultr.com/v2"
OS_NAME = "Ubuntu 24.04 LTS x64"
TAG = "iw4x-fleet"


class Vultr:
    name = "vultr"

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None, poll: float = 5):
        self.http = http or httpx.AsyncClient(timeout=30)
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.poll = poll
        self._os_id: int | None = None

    async def call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = await self.http.request(method, API + path, json=body, headers=self.headers)
        except httpx.HTTPError as e:
            raise CloudError(f"Vultr not reachable: {type(e).__name__}") from None
        if r.status_code >= 400:
            try:
                detail = r.json().get("error") or r.text
            except ValueError:
                detail = r.text
            raise CloudError(
                f"Vultr {method} {path.split('?')[0]}: {r.status_code} {detail}", r.status_code
            )
        return r.json() if r.content else {}

    async def os_id(self) -> int:
        if self._os_id is None:
            found = [
                o["id"]
                for o in (await self.call("GET", "/os?per_page=500"))["os"]
                if o["name"] == OS_NAME
            ]
            if not found:
                raise CloudError(f"Vultr has no {OS_NAME} image")
            self._os_id = found[0]
        return self._os_id

    # ---------- disk ----------

    async def ensure_volume(self, m: Machine) -> str:
        blocks = (await self.call("GET", "/blocks?per_page=500"))["blocks"]
        mine = [b for b in blocks if b["label"] == m.label and b["region"] == m.region]
        if mine:
            return mine[0]["id"]
        block = (
            await self.call(
                "POST",
                "/blocks",
                {
                    "region": m.region,
                    "size_gb": m.volume_gb,
                    "label": m.label,
                    "block_type": m.options.get("block_type", "storage_opt"),
                },
            )
        )["block"]
        for _ in range(60):
            if (await self.call("GET", f"/blocks/{block['id']}"))["block"]["status"] == "active":
                return block["id"]
            await asyncio.sleep(self.poll)
        raise CloudError(f"Vultr disk {m.label} didn't become ready")

    async def attach_volume(self, volume_id: str, instance_id: str) -> None:
        block = (await self.call("GET", f"/blocks/{volume_id}"))["block"]
        if block.get("attached_to_instance") == instance_id:
            return
        if block.get("attached_to_instance"):
            raise CloudError(
                f"the disk is attached to another VM ({block['attached_to_instance']})"
            )
        await self.call(
            "POST", f"/blocks/{volume_id}/attach", {"instance_id": instance_id, "live": True}
        )
        for _ in range(60):
            block = (await self.call("GET", f"/blocks/{volume_id}"))["block"]
            if block.get("attached_to_instance") == instance_id:
                return
            await asyncio.sleep(self.poll)
        raise CloudError("the disk didn't attach")

    async def detach_volume(self, volume_id: str, instance_id: str) -> None:
        block = (await self.call("GET", f"/blocks/{volume_id}"))["block"]
        if block.get("attached_to_instance") != instance_id:
            return
        await self.call("POST", f"/blocks/{volume_id}/detach", {"live": True})
        for _ in range(60):
            if not (await self.call("GET", f"/blocks/{volume_id}"))["block"].get(
                "attached_to_instance"
            ):
                return
            await asyncio.sleep(self.poll)
        raise CloudError("the disk didn't detach")

    # ---------- VM ----------

    async def create_instance(self, m: Machine, user_data: str) -> str:
        avail = (await self.call("GET", f"/regions/{m.region}/availability"))["available_plans"]
        if m.plan not in avail:
            raise CloudError(f"Vultr has no {m.plan} left in {m.region} right now")
        body = {
            "region": m.region,
            "plan": m.plan,
            "os_id": await self.os_id(),
            "label": m.label,
            "hostname": m.label,
            "user_data": base64.b64encode(user_data.encode()).decode(),
            "backups": "disabled",
            "enable_ipv6": False,
            "tags": [TAG],
        }
        return (await self.call("POST", "/instances", body))["instance"]["id"]

    async def get_instance(self, instance_id: str) -> Instance:
        try:
            inst = (await self.call("GET", f"/instances/{instance_id}"))["instance"]
        except CloudError as e:
            if e.status == 404:
                return Instance(instance_id, GONE)
            raise
        ip = inst.get("main_ip") if inst.get("main_ip") not in (None, "", "0.0.0.0") else None
        if inst.get("status") == "suspended":
            return Instance(instance_id, FAILED, ip)
        # server_status goes "locked" (installing) -> "installingbooting" -> "ok": only then can
        # a disk be attached
        ready = (
            inst.get("status") == "active"
            and inst.get("power_status") == "running"
            and inst.get("server_status") == "ok"
            and ip
        )
        return Instance(instance_id, ACTIVE if ready else PENDING, ip)

    async def find_instances(self, label: str) -> list[str]:
        return [i["id"] for i in (await self.call("GET", f"/instances?label={label}"))["instances"]]

    async def destroy_instance(self, instance_id: str, volume_id: str | None) -> None:
        if volume_id:  # Vultr keeps a block when its VM goes, but never take the chance
            await self.detach_volume(volume_id, instance_id)
        try:
            await self.call("DELETE", f"/instances/{instance_id}")
        except CloudError as e:
            if e.status != 404:
                raise

    async def close(self) -> None:
        await self.http.aclose()
