import base64
import json

import httpx
import pytest
from fakes import FLEET

from control.config import load_fleet
from control.providers import ACTIVE, GONE, PENDING, CloudError, Instance, Machine
from control.providers.vultr import Vultr
from control.providers.zenlayer import Zenlayer, sign

MACHINE = Machine("iw4x-fleet-nl", "ams", "vhf-2c-4gb", 40, {})
IST = Machine(
    "iw4x-fleet-ist",
    "europe-east-1a",
    "z2a.cpu.2",
    40,
    {"bandwidth_mbps": 50, "system_disk_gb": 60, "subnet_id": "sub-1", "security_group_id": "sg-1"},
)


def test_zenlayer_signature_matches_the_docs_example():
    # "Signature Algorithm v2" in Zenlayer's API docs
    body = b'{"pageSize":10,"pageNum":1,"zoneId":"HKG-A"}'
    header = sign("0D9UtpyKYcHxms5v", "Gu5t9xGARNpq86cd98joQYCN3", body, 1673361177)
    assert header == (
        "ZC2-HMAC-SHA256 Credential=0D9UtpyKYcHxms5v, SignedHeaders=content-type;host, "
        "Signature=efb356c32e55c781e10dc676da59462c22596d82e91c57803666243379555b2f"
    )


class ZenlayerFake:
    """Answers like Zenlayer's API, from a few disks and instances."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.disk = {"diskId": "d-1", "diskName": "iw4x-fleet-ist", "diskStatus": "IN_USE",
                     "instanceId": "i-1"}  # fmt: skip
        self.detach_works = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        action = request.headers["x-zc-action"]
        body = json.loads(request.content)
        assert request.headers["authorization"].startswith("ZC2-HMAC-SHA256 Credential=key-id,")
        assert request.headers["x-zc-version"] == "2025-09-01"
        self.calls.append((action, body))
        if action == "DescribeDisks":
            return self.ok({"dataSet": [self.disk]})
        if action == "DetachDisks":
            if self.detach_works:
                self.disk = {**self.disk, "diskStatus": "AVAILABLE", "instanceId": None}
            return self.ok({"failedDiskIds": [] if self.detach_works else ["d-1"]})
        if action == "DescribeInstances":
            return self.ok({"dataSet": [{"instanceId": "i-1", "status": "RUNNING",
                                         "publicIpAddresses": ["203.0.113.7"]}]})  # fmt: skip
        if action == "DescribeImages":
            images = [
                {"imageId": "ubuntu2204_x", "imageName": "Ubuntu 22.04"},
                {"imageId": "ubuntu2404_x", "imageName": "Ubuntu 24.04"},
            ]
            return self.ok({"dataSet": images})
        if action == "CreateZecInstances":
            return self.ok({"instanceIdSet": ["i-2"]})
        if action == "ReleaseInstances":
            return self.ok({"instanceIds": []})
        return httpx.Response(400, json={"code": "UNKNOWN", "message": action})

    @staticmethod
    def ok(response: dict) -> httpx.Response:
        return httpx.Response(
            200, json={"requestId": "r", "response": {"requestId": "r", **response}}
        )


def zenlayer(fake) -> Zenlayer:
    return Zenlayer("key-id", "secret", httpx.AsyncClient(transport=httpx.MockTransport(fake)), 0)


@pytest.mark.anyio
async def test_zenlayer_detaches_the_disk_before_releasing_the_vm():
    fake = ZenlayerFake()
    await zenlayer(fake).destroy_instance("i-1", "d-1")
    actions = [a for a, _ in fake.calls]
    assert actions.index("DetachDisks") < actions.index("ReleaseInstances")
    assert dict(fake.calls)["DetachDisks"]["instanceCheckFlag"] is False


@pytest.mark.anyio
async def test_zenlayer_never_releases_with_the_disk_attached():
    fake = ZenlayerFake()
    fake.detach_works = False
    with pytest.raises(CloudError):
        await zenlayer(fake).destroy_instance("i-1", "d-1")
    assert "ReleaseInstances" not in [a for a, _ in fake.calls]


@pytest.mark.anyio
async def test_zenlayer_create_and_get():
    fake = ZenlayerFake()
    z = zenlayer(fake)
    assert await z.create_instance(IST, "#!/bin/bash\necho hi\n") == "i-2"
    params = dict(fake.calls)["CreateZecInstances"]
    assert params["imageId"] == "ubuntu2404_x" and params["zoneId"] == "europe-east-1a"
    assert params["subnetId"] == "sub-1" and params["systemDisk"] == {"diskSize": 60}
    assert base64.b64decode(params["userData"]).decode().startswith("#!/bin/bash")
    assert params["password"] and params["bandwidth"] == 50
    inst = await z.get_instance("i-1")
    assert inst.status == ACTIVE and inst.ip == "203.0.113.7"


@pytest.mark.anyio
async def test_zenlayer_error_answer():
    z = zenlayer(lambda r: httpx.Response(400, json={"code": "INVALID_ZONE", "message": "nope"}))
    with pytest.raises(CloudError, match="INVALID_ZONE"):
        await z.call("DescribeZones")


class VultrFake:
    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.blocks = [
            {"id": "b-old", "label": "iw4x-fleet-nl", "region": "ewr", "status": "active"}
        ]
        self.attached: str | None = None
        ip = "203.0.113.5"
        self.vms = {  # as Vultr shows a new VM: installing, booting, ready
            "vm-1": {"status": "pending", "power_status": "stopped", "server_status": "none",
                     "main_ip": "0.0.0.0"},
            "vm-2": {"status": "active", "power_status": "running", "server_status": "locked",
                     "main_ip": ip},
            "vm-3": {"status": "active", "power_status": "running", "server_status": "ok",
                     "main_ip": ip},
        }  # fmt: skip

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/v2")
        self.calls.append((request.method, path, body))
        assert request.headers["authorization"] == "Bearer key"
        if path == "/blocks" and request.method == "GET":
            return httpx.Response(200, json={"blocks": self.blocks})
        if path == "/blocks" and request.method == "POST":
            self.blocks.append({"id": "b-new", **body, "status": "active"})
            return httpx.Response(201, json={"block": {"id": "b-new"}})
        if path.startswith("/blocks/") and path.endswith("/detach"):
            self.attached = None
            return httpx.Response(204)
        if path.startswith("/blocks/"):
            return httpx.Response(
                200, json={"block": {"status": "active", "attached_to_instance": self.attached}}
            )
        if path == "/regions/ams/availability":
            return httpx.Response(200, json={"available_plans": ["vhf-2c-4gb"]})
        if path == "/os":
            return httpx.Response(200, json={"os": [{"id": 2284, "name": "Ubuntu 24.04 LTS x64"}]})
        if path == "/instances" and request.method == "POST":
            return httpx.Response(202, json={"instance": {"id": "vm-1"}})
        if path.rsplit("/", 1)[-1] in self.vms and request.method == "GET":
            return httpx.Response(200, json={"instance": self.vms[path.rsplit("/", 1)[-1]]})
        if path.startswith("/instances/") and request.method == "GET":
            return httpx.Response(404, json={"error": "not found"})
        if path.startswith("/instances/") and request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(500)


def vultr(fake) -> Vultr:
    return Vultr("key", httpx.AsyncClient(transport=httpx.MockTransport(fake)), 0)


@pytest.mark.anyio
async def test_vultr_disk_is_found_by_label_and_region_or_made():
    fake = VultrFake()
    v = vultr(fake)
    assert await v.ensure_volume(MACHINE) == "b-new"  # the one there is in another region
    created = [b for m, p, b in fake.calls if m == "POST" and p == "/blocks"][0]
    assert created == {
        "region": "ams",
        "size_gb": 40,
        "label": "iw4x-fleet-nl",
        "block_type": "storage_opt",
    }
    assert await v.ensure_volume(MACHINE) == "b-new"
    assert len([1 for m, p, _ in fake.calls if m == "POST" and p == "/blocks"]) == 1


@pytest.mark.anyio
async def test_vultr_disk_type_comes_from_the_fleet():
    fake = VultrFake()
    nvme = Machine("iw4x-fleet-nl", "ams", "vhf-2c-4gb", 40, {"block_type": "high_perf"})
    await vultr(fake).ensure_volume(nvme)
    created = [b for m, p, b in fake.calls if m == "POST" and p == "/blocks"][0]
    assert created["block_type"] == "high_perf"
    fleet = load_fleet(FLEET)
    assert {
        s.options.get("block_type") for s in fleet.servers.values() if s.provider == "vultr"
    } == {"high_perf"}


def test_vultr_polls_every_two_seconds():
    assert Vultr("key").poll == 2


@pytest.mark.anyio
async def test_vultr_create_get_destroy():
    fake = VultrFake()
    v = vultr(fake)
    assert await v.create_instance(MACHINE, "#!/bin/bash\n") == "vm-1"
    body = [b for m, p, b in fake.calls if m == "POST" and p == "/instances"][0]
    assert (
        body["label"] == "iw4x-fleet-nl"
        and body["os_id"] == 2284
        and body["tags"] == ["iw4x-fleet"]
    )
    assert base64.b64decode(body["user_data"]) == b"#!/bin/bash\n"
    assert (await v.get_instance("vm-1")).status == PENDING
    assert (await v.get_instance("vm-2")).status == PENDING  # "locked" while installing
    assert (await v.get_instance("vm-3")) == Instance("vm-3", ACTIVE, "203.0.113.5")
    assert (await v.get_instance("vm-9")).status == GONE
    fake.attached = "vm-1"
    await v.destroy_instance("vm-1", "b-old")
    order = [(m, p) for m, p, _ in fake.calls]
    assert order.index(("POST", "/blocks/b-old/detach")) < order.index(
        ("DELETE", "/instances/vm-1")
    )


class NetworkFake:
    """Zenlayer's VPC and subnet calls, starting from the VPCs and subnets given."""

    def __init__(self, vpcs=(), subnets=()):
        self.vpcs, self.subnets = list(vpcs), list(subnets)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        action, body = request.headers["x-zc-action"], json.loads(request.content)
        self.calls.append((action, body))
        if action == "DescribeSubnets":  # name: a fuzzy filter, as Zenlayer's
            found = [s for s in self.subnets if body["name"] in s["name"]]
            return ZenlayerFake.ok({"dataSet": found})
        if action == "DescribeVpcs":
            return ZenlayerFake.ok({"dataSet": [v for v in self.vpcs if body["name"] in v["name"]]})
        if action == "CreateVpc":
            self.vpcs.append({"vpcId": "vpc-new", "name": body["name"]})
            return ZenlayerFake.ok({"vpcId": "vpc-new"})
        if action == "CreateSubnet":
            return ZenlayerFake.ok({"subnetId": "sub-new"})
        return httpx.Response(400, json={"code": "UNKNOWN", "message": action})

    def made(self) -> list[str]:
        return [a for a, _ in self.calls if a.startswith("Create")]


NO_SUBNET = Machine("iw4x-fleet-ist", "europe-east-1a", "z2a.cpu.2", 40, {})


@pytest.mark.anyio
async def test_zenlayer_uses_the_fleets_subnet_when_there_is_one():
    subnets = [
        {"subnetId": "sub-1", "name": "iw4x-fleet-europe-east-1"},
        {"subnetId": "sub-x", "name": "iw4x-fleet-europe-east-1-old"},
    ]
    fake = NetworkFake(subnets=subnets)
    assert await zenlayer(fake).subnet_id(NO_SUBNET) == "sub-1"
    assert fake.made() == []


@pytest.mark.anyio
async def test_zenlayer_makes_the_vpc_and_the_subnet_the_first_time():
    fake = NetworkFake(vpcs=[{"vpcId": "vpc-other", "name": "iw4x-fleet-test"}])
    assert await zenlayer(fake).subnet_id(NO_SUBNET) == "sub-new"
    assert fake.made() == ["CreateVpc", "CreateSubnet"]
    calls = dict(fake.calls)
    assert calls["CreateVpc"] == {"name": "iw4x-fleet", "cidrBlock": "172.30.0.0/16", "mtu": 1500}
    assert calls["CreateSubnet"] == {"vpcId": "vpc-new", "name": "iw4x-fleet-europe-east-1",
                                     "regionId": "europe-east-1", "stackType": "IPv4",
                                     "cidrBlock": "172.30.1.0/24"}  # fmt: skip


@pytest.mark.anyio
async def test_zenlayer_adds_a_subnet_to_the_fleets_vpc():
    fake = NetworkFake(vpcs=[{"vpcId": "vpc-1", "name": "iw4x-fleet"}])
    assert await zenlayer(fake).subnet_id(NO_SUBNET) == "sub-new"
    assert fake.made() == ["CreateSubnet"] and dict(fake.calls)["CreateSubnet"]["vpcId"] == "vpc-1"
