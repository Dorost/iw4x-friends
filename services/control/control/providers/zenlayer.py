"""Zenlayer Elastic Compute (console.zenlayer.com/api/v2/zec), for the Istanbul server: a VM with
a public IP from a user-data script, a data disk that outlives it.

Releasing a VM also releases the detachable disks still attached to it (dependResource), so the
disk is detached, and checked to be, before a VM is released."""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import string
import time

import httpx

from control.providers import ACTIVE, FAILED, GONE, PENDING, CloudError, Instance, Machine

HOST = "console.zenlayer.com"
VERSION = "2025-09-01"  # of the zec service, as in Zenlayer's own SDK
ALGORITHM = "ZC2-HMAC-SHA256"
CONTENT_TYPE = "application/json; charset=utf-8"
SECURITY_GROUP = "iw4x-fleet"
# the network the fleet makes for its VMs, the first time it needs one (no console step): a global
# VPC with a subnet per region. Clear of WireGuard's 10.66.0.0/24
VPC = "iw4x-fleet"
VPC_CIDR = "172.30.0.0/16"
# the game (UDP), ping; SSH only answers over WireGuard (ufw on the VM) but stays reachable for
# Zenlayer's console tools
RULES = [
    {"direction": "ingress", "policy": "accept", "priority": 1, "ipProtocol": "udp",
     "portRange": "28960", "cidrIp": "0.0.0.0/0", "desc": "game"},
    {"direction": "ingress", "policy": "accept", "priority": 1, "ipProtocol": "icmp",
     "portRange": "-1", "cidrIp": "0.0.0.0/0", "desc": "ping"},
    {"direction": "ingress", "policy": "accept", "priority": 1, "ipProtocol": "tcp",
     "portRange": "22", "cidrIp": "0.0.0.0/0", "desc": "ssh"},
    {"direction": "egress", "policy": "accept", "priority": 1, "ipProtocol": "all",
     "portRange": "-1", "cidrIp": "0.0.0.0/0", "desc": "out"},
]  # fmt: skip
STATUS = {
    "RUNNING": ACTIVE,
    "CREATE_FAILED": FAILED,
    "RELEASING": GONE,
    "RECYCLE": GONE,
}


def sign(key_id: str, key_password: str, body: bytes, timestamp: int) -> str:
    """The Authorization header of Zenlayer's signature v2 (docs: "Signature Algorithm v2")."""
    canonical = "\n".join(
        [
            "POST",
            "/",
            "",
            f"content-type:{CONTENT_TYPE}\nhost:{HOST}\n",
            "content-type;host",
            hashlib.sha256(body).hexdigest(),
        ]
    )
    to_sign = f"{ALGORITHM}\n{timestamp}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    signature = hmac.new(key_password.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    return (
        f"{ALGORITHM} Credential={key_id}, SignedHeaders=content-type;host, Signature={signature}"
    )


def random_password() -> str:
    """For the VM's root login, which is never used (SSH keys only), but Zenlayer wants one."""
    alphabet = string.ascii_letters + string.digits
    return "Ix-" + "".join(secrets.choice(alphabet) for _ in range(24)) + "9a"


class Zenlayer:
    name = "zenlayer"

    def __init__(
        self,
        key_id: str,
        key_password: str,
        http: httpx.AsyncClient | None = None,
        poll: float = 5,
        clock=time.time,
    ):
        self.key_id, self.key_password = key_id, key_password
        self.http = http or httpx.AsyncClient(timeout=30)
        self.poll, self.clock = poll, clock

    async def call(self, action: str, **params) -> dict:
        body = json.dumps(params, separators=(",", ":")).encode()
        timestamp = int(self.clock())
        headers = {
            "Content-Type": CONTENT_TYPE,
            "Host": HOST,
            "X-ZC-Action": action,
            "X-ZC-Version": VERSION,
            "X-ZC-Service": "zec",
            "X-ZC-Timestamp": str(timestamp),
            "X-ZC-Signature-Method": ALGORITHM,
            "Authorization": sign(self.key_id, self.key_password, body, timestamp),
        }
        try:
            r = await self.http.post(f"https://{HOST}/api/v2/zec", content=body, headers=headers)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise CloudError(f"Zenlayer not reachable: {type(e).__name__}") from None
        if r.status_code >= 400 or "code" in data and "response" not in data:
            raise CloudError(
                f"Zenlayer {action}: {data.get('code', r.status_code)} {data.get('message', '')}",
                r.status_code,
            )
        return data.get("response", {})

    # ---------- what a VM needs ----------

    async def image_id(self, m: Machine) -> str:
        if m.options.get("image_id"):
            return m.options["image_id"]
        images = (await self.call("DescribeImages", zoneId=m.region, imageName="Ubuntu"))["dataSet"]
        for image in images:
            text = f"{image.get('imageId', '')} {image.get('imageName', '')}".lower()
            if "24.04" in text or "2404" in text:
                return image["imageId"]
        raise CloudError(f"no Ubuntu 24.04 image in {m.region}, set image_id in fleet.toml")

    async def subnet_id(self, m: Machine) -> str:
        """The fleet's subnet in the zone's region: subnet_id from fleet.toml, else the one named
        iw4x-fleet-<region>, else made (with the iw4x-fleet VPC, when there is none either)."""
        if m.options.get("subnet_id"):
            return m.options["subnet_id"]
        region = m.region[:-1]  # zone europe-east-1a is in region europe-east-1
        name = f"{VPC}-{region}"
        subnets = (await self.call("DescribeSubnets", regionId=region, name=name, pageSize=100))[
            "dataSet"
        ]
        mine = [s for s in subnets if s.get("name") == name]
        if mine:
            return mine[0]["subnetId"]
        vpcs = (await self.call("DescribeVpcs", name=VPC, pageSize=100))["dataSet"]
        vpcs = [v for v in vpcs if v.get("name") == VPC]
        vpc_id = (
            vpcs[0]["vpcId"]
            if vpcs
            else (await self.call("CreateVpc", name=VPC, cidrBlock=VPC_CIDR, mtu=1500))["vpcId"]
        )
        cidr = m.options.get("subnet_cidr", "172.30.1.0/24")
        for _ in range(24):  # a new VPC can take a moment before it takes subnets
            try:
                return (
                    await self.call(
                        "CreateSubnet",
                        vpcId=vpc_id,
                        name=name,
                        regionId=region,
                        stackType="IPv4",
                        cidrBlock=cidr,
                    )
                )["subnetId"]
            except CloudError as e:
                last = e
                await asyncio.sleep(self.poll)
        raise CloudError(f"Zenlayer didn't make the subnet {name}: {last}")

    async def security_group_id(self, m: Machine) -> str:
        if m.options.get("security_group_id"):
            return m.options["security_group_id"]
        found = (await self.call("DescribeSecurityGroups", securityGroupName=SECURITY_GROUP))[
            "dataSet"
        ]
        found = [g for g in found if g.get("securityGroupName") == SECURITY_GROUP]
        if found:
            return found[0]["securityGroupId"]
        return (
            await self.call(
                "CreateSecurityGroup", securityGroupName=SECURITY_GROUP, ruleInfos=RULES
            )
        )["securityGroupId"]

    # ---------- disk ----------

    async def disk(self, disk_id: str) -> dict | None:
        found = (await self.call("DescribeDisks", diskIds=[disk_id]))["dataSet"]
        return found[0] if found else None

    async def ensure_volume(self, m: Machine) -> str:
        found = (await self.call("DescribeDisks", diskName=m.label, zoneId=m.region))["dataSet"]
        found = [
            d
            for d in found
            if d.get("diskName") == m.label and d.get("diskStatus") not in ("DELETING", "RECYCLED")
        ]
        if found:
            return found[0]["diskId"]
        disk_id = (
            await self.call(
                "CreateDisks",
                zoneId=m.region,
                diskSize=m.volume_gb,
                diskName=m.label,
                diskAmount=1,
            )
        )["diskIds"][0]
        await self._disk_until(disk_id, "AVAILABLE")
        return disk_id

    async def _disk_until(self, disk_id: str, status: str) -> dict:
        for _ in range(60):
            d = await self.disk(disk_id)
            if d and d.get("diskStatus") == status:
                return d
            if d and d.get("diskStatus") == "FAILED":
                raise CloudError(f"Zenlayer disk {disk_id} failed")
            await asyncio.sleep(self.poll)
        raise CloudError(f"Zenlayer disk {disk_id} isn't {status}")

    async def attach_volume(self, volume_id: str, instance_id: str) -> None:
        d = await self.disk(volume_id)
        if d and d.get("instanceId") == instance_id and d.get("diskStatus") == "IN_USE":
            return
        r = await self.call("AttachDisks", diskIds=[volume_id], instanceId=instance_id)
        if r.get("failedDiskIds"):
            raise CloudError("Zenlayer didn't attach the disk")
        await self._disk_until(volume_id, "IN_USE")

    async def detach_volume(self, volume_id: str, instance_id: str) -> None:
        d = await self.disk(volume_id)
        if not d or not d.get("instanceId"):
            return
        r = await self.call("DetachDisks", diskIds=[volume_id], instanceCheckFlag=False)
        if r.get("failedDiskIds"):
            raise CloudError("Zenlayer didn't detach the disk")
        await self._disk_until(volume_id, "AVAILABLE")

    # ---------- VM ----------

    async def create_instance(self, m: Machine, user_data: str) -> str:
        o = m.options
        params = {
            "zoneId": m.region,
            "imageId": await self.image_id(m),
            "instanceType": m.plan,
            "instanceCount": 1,
            "instanceName": m.label,
            "subnetId": await self.subnet_id(m),
            "securityGroupId": await self.security_group_id(m),
            "password": random_password(),
            "timeZone": "UTC",
            "systemDisk": {"diskSize": int(o.get("system_disk_gb", 60))},
            "internetChargeType": o.get("internet_charge", "ByBandwidth"),
            "bandwidth": int(o.get("bandwidth_mbps", 50)),
            "networkLineType": o.get("network_line", "PremiumBGP"),
            "userData": base64.b64encode(user_data.encode()).decode(),
        }
        ids = (await self.call("CreateZecInstances", **params))["instanceIdSet"]
        if not ids:
            raise CloudError("Zenlayer created no VM")
        return ids[0]

    async def get_instance(self, instance_id: str) -> Instance:
        found = (await self.call("DescribeInstances", instanceIds=[instance_id]))["dataSet"]
        if not found:
            return Instance(instance_id, GONE)
        inst = found[0]
        ips = inst.get("publicIpAddresses") or []
        status = STATUS.get(inst.get("status", ""), PENDING)
        if status == ACTIVE and not ips:
            status = PENDING
        return Instance(instance_id, status, ips[0] if ips else None)

    async def destroy_instance(self, instance_id: str, volume_id: str | None) -> None:
        if volume_id:
            await self.detach_volume(volume_id, instance_id)
            d = await self.disk(volume_id)
            if d and d.get("instanceId") == instance_id:
                raise CloudError("the disk is still attached, not releasing the VM")
        if (await self.get_instance(instance_id)).status == GONE:
            return
        # dependResource also releases the VM's public IP, which is billed on its own
        await self.call("ReleaseInstances", instanceIds=[instance_id], dependResource=True)

    async def instance_types(self, zone: str) -> list[dict]:
        return (await self.call("DescribeZoneInstanceConfigInfos", zoneId=zone))[
            "instanceTypeQuotaSet"
        ]

    async def close(self) -> None:
        await self.http.aclose()
