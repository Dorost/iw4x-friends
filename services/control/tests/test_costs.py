"""What the fleet costs: the clouds' billing answers (shaped like the real ones, 2026-11) turned
into charges per server."""

import json

import httpx
import pytest
from fakes import FLEET, at

from control.config import load_fleet
from control.costs import (
    BadMonth,
    Balance,
    Charge,
    Costs,
    FakeBilling,
    Fetched,
    VultrBilling,
    ZenlayerBilling,
    assemble,
    zenlayer_charges,
)
from control.providers.vultr import Vultr
from control.providers.zenlayer import Zenlayer

NOW = at(2026, 11, 4, 18).timestamp()


def vm_line(ip, label, units, total):
    return {"description": f"{ip} (4096 MB) [{label}]", "product": "Vultr Cloud Compute",
            "units": units, "unit_type": "hours", "total": total}  # fmt: skip


PENDING = [
    {"description": "45.76.38.119 (1024 MB) [iw4x-bastion]", "product": "Vultr Cloud Compute",
     "units": 25, "unit_type": "hours", "unit_price": 0.0074, "total": 0.19},
    {"description": "40 GB HDD Block Storage (Amsterdam)  (iw4x-bastion)",
     "product": "Block Storage", "units": 25, "unit_type": "hours", "total": 0.04},
    {"description": "40 GB HDD Block Storage (Amsterdam)  (iw4x-fleet-nl)",
     "product": "Block Storage", "units": 25, "unit_type": "hours", "total": 0.04},
    {"description": "40 GB NVMe Block Storage (Milan)  (iw4x-fleet-milan)",
     "product": "Block Storage", "units": 24, "unit_type": "hours", "total": 0.15},
    vm_line("45.32.234.26", "iw4x-fleet-nl", 1, 0.04),
    vm_line("108.61.166.235", "iw4x-fleet-nl", 2, 0.07),
    vm_line("144.202.3.91", "iw4x", 68, 2.43),
    {"description": 'Snapshot "iw4x-us mw2.dorost.nl 2026-10-17" 24 GB',
     "product": "Compute Snapshot", "units": 68, "unit_type": "hours", "total": 0.12},
]  # fmt: skip
OCTOBER = [
    {"description": "Backup Service for 104.207.128.7", "product": "Automatic Backup",
     "units": 21, "unit_type": "hours", "total": 0.29},
    vm_line("104.207.128.7", "", 21, 1.41) | {"description": "104.207.128.7 (4096 MB)"},
]  # fmt: skip


class VultrBillingFake:
    def __init__(self):
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        self.paths.append(f"{path}?{request.url.query.decode()}")
        if path == "/billing/pending-charges":
            return httpx.Response(200, json={"pending_charges": PENDING})
        if path == "/billing/invoices":
            invoices = [{"id": 30829410, "date": "2026-11-01T02:00:00+00:00", "amount": 30.03}]
            return httpx.Response(200, json={"billing_invoices": invoices, "meta": {}})
        if path == "/billing/invoices/30829410/items":
            if "cursor=" not in str(request.url):
                meta = {"total": 2, "links": {"next": "bmV4dA==", "prev": ""}}
                return httpx.Response(200, json={"invoice_items": OCTOBER[:1], "meta": meta})
            meta = {"total": 2, "links": {"next": "", "prev": ""}}
            return httpx.Response(200, json={"invoice_items": OCTOBER[1:], "meta": meta})
        if path == "/account":
            return httpx.Response(200, json={"account": {"balance": -219.97, "pending_charges": 6}})
        return httpx.Response(404, json={"error": "no"})


def vultr_billing(fake) -> VultrBilling:
    v = Vultr("key", httpx.AsyncClient(transport=httpx.MockTransport(fake)), 0)
    return VultrBilling(v, clock=lambda: NOW)


@pytest.mark.anyio
async def test_vultr_this_month_comes_from_the_pending_charges():
    charges = await vultr_billing(VultrBillingFake()).charges("2026-11")
    assert charges[0] == Charge("iw4x-bastion", "vm", 0.19, 25, PENDING[0]["description"])
    assert [(c.label, c.kind) for c in charges[1:4]] == [
        ("iw4x-bastion", "disk"),
        ("iw4x-fleet-nl", "disk"),
        ("iw4x-fleet-milan", "disk"),
    ]
    assert charges[-1].kind == "snapshot" and charges[-1].label == ""


@pytest.mark.anyio
async def test_vultr_an_earlier_month_comes_from_its_invoice():
    fake = VultrBillingFake()
    b = vultr_billing(fake)
    assert await b.months() == ["2026-10"]  # the invoice of Nov 1st is October's
    charges = await b.charges("2026-10")
    assert [(c.label, c.kind, c.amount) for c in charges] == [
        ("", "backup", 0.29),
        ("", "vm", 1.41),  # "104.207.128.7 (4096 MB)": a VM without a name
    ]
    assert any("cursor=bmV4dA%3D%3D" in p for p in fake.paths)  # the second page
    assert await b.charges("2026-09") == []


@pytest.mark.anyio
async def test_vultr_balance_below_zero_is_credit():
    assert await vultr_billing(VultrBillingFake()).balance() == Balance("Credit left", 219.97)


# Istanbul's first run (order 1), its data disk (order 2), as Zenlayer bills them
BILL = [
    {"resourceId": "vm-1", "label": "iw4x-fleet-ist", "productSubitem": "Elastic Compute",
     "orderSn": "o-1", "amount": 0.08, "startTime": "2026-11-03T19:49:03Z",
     "endTime": "2026-11-03T21:19:41Z"},
    {"resourceId": "eip-1", "label": "EIP-europe-east-1-1", "productSubitem": "ZEC Elastic IP",
     "orderSn": "o-1", "amount": 0.28, "startTime": "2026-11-03T19:49:02Z",
     "endTime": "2026-11-03T21:19:41Z"},
    {"resourceId": "disk-1", "label": "iw4x-fleet-ist", "productSubitem": "ZEC Disk",
     "orderSn": "o-2", "amount": 0.09, "startTime": "2026-11-03T19:25:16Z",
     "endTime": "2026-11-04T18:00:00Z"},
]  # fmt: skip


def deduction(order, product, part, amount):
    return {"transactionType": "DEDUCTION", "orderSn": order, "amount": amount,
            "description": f"Product: {product} - {part}//\nType: europe-east-1(Istanbul)/x"
                           " - hourly billing"}  # fmt: skip


DEDUCTIONS = [
    deduction("o-1", "ZEC Elastic IP", "ZEC Bandwidth", 0.20),
    deduction("o-1", "ZEC Elastic IP", "ZEC Bandwidth", 0.06),
    deduction("o-1", "ZEC Elastic IP", "ZEC Elastic IP", 0.02),
    deduction("o-1", "Elastic Compute", "ZEC Instance", 0.06),
    deduction("o-1", "Elastic Compute", "ZEC Disk", 0.02),
    deduction("o-2", "ZEC Disk", "ZEC Disk", 0.09),
]


def test_zenlayer_splits_each_line_by_its_deductions():
    charges = zenlayer_charges(BILL, DEDUCTIONS)
    assert [(c.label, c.kind, round(c.amount, 2), round(c.hours, 1)) for c in charges] == [
        ("iw4x-fleet-ist", "vm", 0.06, 1.5),
        ("iw4x-fleet-ist", "disk", 0.02, 0),  # its system disk
        ("iw4x-fleet-ist", "bandwidth", 0.26, 0),  # the public IP goes with its VM's order
        ("iw4x-fleet-ist", "ip", 0.02, 0),
        ("iw4x-fleet-ist", "disk", 0.09, 0),  # the data disk
    ]
    assert round(sum(c.amount for c in charges), 2) == 0.45


def test_zenlayer_line_without_deductions_stays_whole():
    charges = zenlayer_charges(BILL, [])
    assert [(c.label, c.kind, c.amount) for c in charges] == [
        ("iw4x-fleet-ist", "vm", 0.08),
        ("iw4x-fleet-ist", "ip", 0.28),
        ("iw4x-fleet-ist", "disk", 0.09),
    ]


class ZenlayerBillingFake:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/zbc"
        assert request.headers["x-zc-service"] == "zbc"
        assert request.headers["x-zc-version"] == "2024-08-09"
        action, body = request.headers["x-zc-action"], json.loads(request.content)
        self.calls.append((action, body))
        if action == "DescribeBillDetail":
            data = BILL if body["billMonthly"] == 202611 else []
            return self.ok({"dataSet": data, "totalCount": len(data)})
        if action == "DescribeTransactionHistory":
            return self.ok({"dataSet": DEDUCTIONS, "totalCount": len(DEDUCTIONS)})
        if action == "DescribeCustomerBalance":
            return self.ok({"cashBalance": 9.03, "purchasingPower": 9.03})
        return httpx.Response(400, json={"code": "UNKNOWN", "message": action})

    @staticmethod
    def ok(response: dict) -> httpx.Response:
        return httpx.Response(200, json={"requestId": "r", "response": response})


def zenlayer_billing(fake) -> ZenlayerBilling:
    z = Zenlayer("key-id", "secret", httpx.AsyncClient(transport=httpx.MockTransport(fake)), 0)
    return ZenlayerBilling(z)


@pytest.mark.anyio
async def test_zenlayer_billing_asks_for_the_month_and_its_deductions():
    fake = ZenlayerBillingFake()
    b = zenlayer_billing(fake)
    charges = await b.charges("2026-11")
    assert round(sum(c.amount for c in charges), 2) == 0.45
    (_, bill), (_, history) = fake.calls
    assert bill["billMonthly"] == 202611
    assert history["transactionType"] == ["DEDUCTION"]
    assert (history["startTime"], history["endTime"]) == (
        "2026-11-01T00:00:00Z",
        "2026-12-02T00:00:00Z",  # a day into December: the month's last hours
    )
    assert await b.charges("2026-10") == []
    assert await b.balance() == Balance("Prepaid balance", 9.03)


FLEET_TOML = load_fleet(FLEET)


def test_charges_per_server_then_the_bastion_then_the_rest():
    vultr = [
        Charge("iw4x-bastion", "vm", 0.19, 25),
        Charge("iw4x-bastion", "disk", 0.04),
        Charge("iw4x-fleet-nl", "vm", 0.04, 1),
        Charge("iw4x-fleet-nl", "vm", 0.07, 2),
        Charge("iw4x-fleet-nl", "disk", 0.04),
        Charge("iw4x", "vm", 2.43, 68, "144.202.3.91 (4096 MB) [iw4x]"),
        Charge("", "snapshot", 0.12, 0, 'Snapshot "old" 24 GB'),
        Charge("iw4x-fleet-milan", "disk", 0.15),
    ]
    view = assemble(
        FLEET_TOML,
        "2026-11",
        {"vultr": Fetched(NOW, vultr, []), "zenlayer": Fetched(NOW - 60, [
            Charge("iw4x-fleet-ist", "bandwidth", 0.66), Charge("iw4x-fleet-ist", "vm", 0.14, 3.7),
        ], [])},
    )  # fmt: skip
    assert [g["key"] for g in view["groups"]] == ["nl", "us", "ist", "bastion", "milan", "other"]
    nl, us, ist, bastion, milan, other = view["groups"]
    assert nl["total"] == 0.15
    assert nl["items"] == [
        {"kind": "vm", "name": "VM", "amount": 0.11, "hours": 3.0, "runs": 2},
        {"kind": "disk", "name": "Disk", "amount": 0.04, "hours": 0.0, "runs": 0},
    ]
    assert us["total"] == 0 and us["items"] == []  # nothing this month, still listed
    assert [i["kind"] for i in ist["items"]] == ["vm", "bandwidth"]
    assert bastion["total"] == 0.23
    assert milan["title"] == "Milan" and milan["note"] == "no longer in the fleet"
    assert [i["name"] for i in other["items"]] == ["VM iw4x", 'Snapshot "old" 24 GB']
    assert view["providers"] == [
        {"name": "vultr", "title": "Vultr", "total": 3.08, "error": ""},
        {"name": "zenlayer", "title": "Zenlayer", "total": 0.8, "error": ""},
    ]
    assert view["total"] == 3.88
    assert view["updated_at"] == int(NOW - 60)


def test_without_a_zenlayer_key_istanbul_isnt_listed():
    view = assemble(FLEET_TOML, "2026-11", {"vultr": Fetched(NOW, [], [])})
    assert [g["key"] for g in view["groups"]] == ["nl", "us", "bastion"]


class Flaky(FakeBilling):
    def __init__(self):
        super().__init__(
            "vultr", [Charge("iw4x-fleet-nl", "disk", 0.04)], Balance("Credit left", 5)
        )
        self.calls = 0
        self.down = False

    async def charges(self, month):
        self.calls += 1
        if self.down:
            raise RuntimeError("Vultr not reachable: ConnectError")
        return await super().charges(month)


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


@pytest.mark.anyio
async def test_figures_are_kept_a_while_and_survive_a_cloud_outage():
    billing, clock = Flaky(), Clock()
    costs = Costs(FLEET_TOML, [billing], clock)
    assert (await costs.view())["total"] == 0.04
    await costs.view()
    assert billing.calls == 1  # fresh for 10 minutes
    clock.t += 11 * 60
    billing.down = True
    view = await costs.view()
    assert view["total"] == 0.04  # the last figures stay
    assert view["providers"][0]["error"] == "Vultr not reachable: ConnectError"
    assert billing.calls == 2
    clock.t += 30
    await costs.view()
    assert billing.calls == 2  # tried again only after a minute
    clock.t += 31
    billing.down = False
    assert (await costs.view())["providers"][0]["error"] == ""
    assert billing.calls == 3


@pytest.mark.anyio
async def test_months_and_balances():
    costs = Costs(FLEET_TOML, [Flaky()], Clock())
    view = await costs.view()
    assert view["month"] == "2026-11" and view["current"]
    assert view["months"] == ["2026-11", "2026-10"]
    assert "balances" not in view
    view = await costs.view("2026-10", balances=True)
    assert not view["current"]
    assert view["balances"] == [
        {"provider": "vultr", "title": "Vultr", "label": "Credit left", "amount": 5, "error": ""}
    ]
    for bad in ("2026-12", "2026-13", "november", "2026-1"):
        with pytest.raises(BadMonth):
            await costs.view(bad)
