"""What the fleet costs, from the clouds' own billing: a month's charges per game server, for the
bastion, and for anything else on the accounts. The fleet page (/costs) shows all of it and what
is left on each account; the mini app only the fleet's servers and the bastion.

Vultr     /v2/billing/pending-charges   this month so far: a line per VM run, disk or snapshot
          /v2/billing/invoices/<id>/items   an earlier month (its invoice comes on the 1st)
          /v2/account                   the credit left
Zenlayer  zbc DescribeBillDetail        a month: a line per resource and order
          zbc DescribeTransactionHistory  the hourly deductions behind those lines. They split
                                        a VM's line into the VM and its system disk, and its
                                        public IP's into the IP and the bandwidth
          zbc DescribeCustomerBalance   the prepaid balance left

A charge goes to a server by the name of its VM or disk (iw4x-fleet-<server>, iw4x-bastion).
Zenlayer names a VM's public IP on its own (EIP-<region>-1): it goes with the VM of its order.
Both clouds bill in US dollars."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

from control.config import BASTION_LABEL, Fleet
from control.providers.vultr import Vultr
from control.providers.zenlayer import Zenlayer

log = logging.getLogger("control.costs")

FLEET_PREFIX = "iw4x-fleet-"
FRESH = 10 * 60  # this month's figures are fetched again after this long
FRESH_PAST = 6 * 3600  # an earlier month's barely change
RETRY = 60  # after a cloud didn't answer
MONTHS_SHOWN = 12
KINDS = {  # in the order shown
    "vm": "VM",
    "disk": "Disk",
    "ip": "Public IP",
    "bandwidth": "Bandwidth",
    "snapshot": "Snapshot",
    "backup": "Backups",
    "other": "Other",
}
TITLES = {"vultr": "Vultr", "zenlayer": "Zenlayer"}
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class Charge:
    label: str  # the name of the VM or disk at the cloud, "" when the line has none
    kind: str  # a key of KINDS
    amount: float  # US dollars
    hours: float = 0  # how long a VM ran (vm only)
    what: str = ""  # the cloud's own words, for a charge outside the fleet


@dataclass(frozen=True)
class Balance:
    label: str  # "Credit left", "Owed", "Prepaid balance"
    amount: float


class Billing(Protocol):
    name: str

    async def charges(self, month: str) -> list[Charge]:
        """month: "2026-11"."""
        ...

    async def months(self) -> list[str]:
        """Earlier months it has bills for."""
        ...

    async def balance(self) -> Balance: ...


def this_month(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m")


def month_start(month: str) -> datetime:
    return datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=UTC)


def next_month(month: str) -> datetime:
    return (month_start(month) + timedelta(days=32)).replace(day=1)


# ---------- Vultr ----------

# the name is at the end: "45.76.38.119 (1024 MB) [iw4x-bastion]" for a VM (an old one may have
# none: "104.207.128.7 (4096 MB)"), "40 GB HDD Block Storage (Amsterdam)  (iw4x-fleet-nl)" for a
# disk
VULTR_NAME = re.compile(r"\[([^\]]+)\]\s*$")
VULTR_DISK_NAME = re.compile(r"\(([^()]+)\)\s*$")


def vultr_kind(product: str) -> str:
    p = product.lower()
    if "block storage" in p:
        return "disk"
    if "snapshot" in p:
        return "snapshot"
    if "backup" in p:
        return "backup"
    if "bandwidth" in p:
        return "bandwidth"
    if re.search(r"\bip\b", p):  # Reserved IP
        return "ip"
    if "compute" in p or "instance" in p or "metal" in p:
        return "vm"
    return "other"


def vultr_charge(line: dict) -> Charge:
    what = line.get("description") or ""
    kind = vultr_kind(line.get("product") or "")
    m = (VULTR_DISK_NAME if kind == "disk" else VULTR_NAME).search(what)
    label = m.group(1).strip() if m else ""
    hours = float(line.get("units") or 0) if line.get("unit_type") == "hours" else 0
    return Charge(label, kind, float(line.get("total") or 0), hours if kind == "vm" else 0, what)


class VultrBilling:
    name = "vultr"

    def __init__(self, vultr: Vultr, clock=time.time):
        self.vultr, self.clock = vultr, clock

    async def invoices(self) -> dict[str, list[int]]:
        """The invoices of each earlier month: the one dated the 1st is for the month before."""
        out: dict[str, list[int]] = {}
        page = await self.vultr.call("GET", "/billing/invoices?per_page=100")
        for invoice in page.get("billing_invoices", []):
            month = (datetime.fromisoformat(invoice["date"]) - timedelta(days=1)).strftime("%Y-%m")
            out.setdefault(month, []).append(invoice["id"])
        return out

    async def months(self) -> list[str]:
        return list(await self.invoices())

    async def charges(self, month: str) -> list[Charge]:
        if month == this_month(self.clock()):
            lines = (await self.vultr.call("GET", "/billing/pending-charges"))["pending_charges"]
        else:
            lines = []
            for invoice_id in (await self.invoices()).get(month, []):
                lines += await self.items(invoice_id)
        return [vultr_charge(x) for x in lines]

    async def items(self, invoice_id: int) -> list[dict]:
        out, cursor = [], ""
        while True:
            path = f"/billing/invoices/{invoice_id}/items?per_page=500"
            page = await self.vultr.call(
                "GET", path + (f"&cursor={quote(cursor)}" if cursor else "")
            )
            out += page.get("invoice_items", [])
            cursor = ((page.get("meta") or {}).get("links") or {}).get("next") or ""
            if not cursor:
                return out

    async def balance(self) -> Balance:
        account = (await self.vultr.call("GET", "/account"))["account"]
        balance = float(account.get("balance") or 0)  # below zero: credit
        return Balance("Credit left", -balance) if balance <= 0 else Balance("Owed", balance)


# ---------- Zenlayer ----------

# "Product: ZEC Elastic IP - ZEC Bandwidth//\nType: europe-east-1(Istanbul)/... - hourly billing"
DEDUCTION = re.compile(r"Product:\s*(.+?)\s+-\s+(.+?)\s*//")
ZENLAYER_PARTS = {
    "ZEC Instance": "vm",
    "ZEC Disk": "disk",  # a VM's system disk, or a data disk
    "ZEC Elastic IP": "ip",
    "ZEC Bandwidth": "bandwidth",
}
ZENLAYER_PRODUCTS = {"Elastic Compute": "vm", "ZEC Disk": "disk", "ZEC Elastic IP": "ip"}


def hours_between(start: str | None, end: str | None) -> float:
    try:
        a = datetime.fromisoformat((start or "").replace("Z", "+00:00"))
        b = datetime.fromisoformat((end or "").replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, (b - a).total_seconds() / 3600)


def zenlayer_charges(lines: list[dict], deductions: list[dict]) -> list[Charge]:
    """A month's bill lines, each split by the deductions of its order into its parts."""
    # an order's VM and disk carry the fleet's name, its public IP doesn't
    names: dict[str, str] = {}
    for x in lines:
        if (x.get("label") or "").startswith("iw4x-"):
            names.setdefault(x.get("orderSn"), x["label"])
    # (order, product) -> part -> dollars: ("181…", "ZEC Elastic IP") -> {"ZEC Bandwidth": .66, …}
    parts: dict[tuple, dict[str, float]] = {}
    for d in deductions:
        m = DEDUCTION.match(d.get("description") or "")
        if m:
            share = parts.setdefault((d.get("orderSn"), m.group(1)), {})
            share[m.group(2)] = share.get(m.group(2), 0) + float(d.get("amount") or 0)
    out = []
    for x in lines:
        label = names.get(x.get("orderSn")) or x.get("label") or ""
        product = x.get("productSubitem") or ""
        amount = float(x.get("amount") or 0)
        hours = hours_between(x.get("startTime"), x.get("endTime"))
        what = f"{product} {x.get('label') or ''}".strip()
        split = parts.get((x.get("orderSn"), product)) or {}
        whole = sum(split.values())
        if whole <= 0:  # no deductions to go by: the line as it is
            kind = ZENLAYER_PRODUCTS.get(product, "other")
            out.append(Charge(label, kind, amount, hours if kind == "vm" else 0, what))
            continue
        for part, dollars in split.items():
            kind = ZENLAYER_PARTS.get(part, "other")
            share = amount * dollars / whole
            out.append(Charge(label, kind, share, hours if kind == "vm" else 0, what))
    return out


class ZenlayerBilling:
    name = "zenlayer"

    def __init__(self, zenlayer: Zenlayer):
        self.zl = zenlayer

    async def pages(self, action: str, **params) -> list[dict]:
        out, page = [], 1
        while True:
            r = await self.zl.billing(action, pageSize=1000, pageNum=page, **params)
            found = r.get("dataSet") or []
            out += found
            if not found or len(out) >= int(r.get("totalCount") or 0):
                return out
            page += 1

    async def months(self) -> list[str]:
        return []  # Zenlayer has no list of its bills: the months come from Vultr

    async def charges(self, month: str) -> list[Charge]:
        lines = await self.pages("DescribeBillDetail", billMonthly=int(month.replace("-", "")))
        if not lines:
            return []
        # a month's last hours are deducted early the next month
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        deductions = await self.pages(
            "DescribeTransactionHistory",
            transactionType=["DEDUCTION"],
            startTime=month_start(month).strftime(fmt),
            endTime=(next_month(month) + timedelta(days=1)).strftime(fmt),
        )
        return zenlayer_charges(lines, deductions)

    async def balance(self) -> Balance:
        r = await self.zl.billing("DescribeCustomerBalance")
        return Balance("Prepaid balance", float(r.get("cashBalance") or 0))


# ---------- made up, for task control:dev ----------


class FakeBilling:
    def __init__(self, name: str, charges: list[Charge], balance: Balance):
        self.name, self._charges, self._balance = name, charges, balance

    async def charges(self, month: str) -> list[Charge]:
        return self._charges

    async def months(self) -> list[str]:
        return ["2026-10"]

    async def balance(self) -> Balance:
        return self._balance


def fake_billings() -> list[FakeBilling]:
    return [
        FakeBilling(
            "vultr",
            [
                Charge("iw4x-bastion", "vm", 2.31, 310),
                Charge("iw4x-bastion", "disk", 0.46),
                Charge("iw4x-fleet-nl", "vm", 0.82, 23),
                Charge("iw4x-fleet-nl", "disk", 0.46),
                Charge("iw4x-fleet-us", "vm", 0.11, 3),
                Charge("iw4x-fleet-us", "disk", 0.46),
                Charge("iw4x", "vm", 2.43, 68, "144.202.3.91 (4096 MB) [iw4x]"),
            ],
            Balance("Credit left", 219.97),
        ),
        FakeBilling(
            "zenlayer",
            [
                Charge("iw4x-fleet-ist", "vm", 0.41, 9),
                Charge("iw4x-fleet-ist", "disk", 1.42),
                Charge("iw4x-fleet-ist", "ip", 0.07),
                Charge("iw4x-fleet-ist", "bandwidth", 1.61),
            ],
            Balance("Prepaid balance", 9.03),
        ),
    ]


# ---------- the view ----------


class BadMonth(ValueError):
    pass


@dataclass
class Fetched:
    at: float
    charges: list[Charge]
    months: list[str]
    error: str = ""


class Costs:
    def __init__(self, fleet: Fleet, billings: list[Billing], clock=time.time):
        self.fleet, self.billings, self.clock = fleet, billings, clock
        self.fetched: dict[tuple[str, str], Fetched] = {}  # (cloud, month)
        self.balances: dict[str, tuple[float, Balance | None, str]] = {}  # cloud -> at, it, error
        self.locks: dict[tuple[str, str], asyncio.Lock] = {}

    def month(self, month: str) -> str:
        current = this_month(self.clock())
        if not month:
            return current
        if not MONTH.match(month) or month > current:
            raise BadMonth(f"no such month: {month}")
        return month

    async def fetch(self, b: Billing, month: str) -> Fetched:
        """One cloud's charges of a month, from the cache while they are fresh. When the cloud
        doesn't answer, the last ones it gave stay (with the error)."""
        key = (b.name, month)
        async with self.locks.setdefault(key, asyncio.Lock()):
            now = self.clock()
            last = self.fetched.get(key)
            fresh = FRESH if month == this_month(now) else FRESH_PAST
            if last and now - last.at < (RETRY if last.error else fresh):
                return last
            try:
                charges, months = await asyncio.gather(b.charges(month), b.months())
                got = Fetched(now, charges, months)
            except Exception as e:  # noqa: BLE001  any cloud trouble: show what's known
                log.warning("%s billing: %s", b.name, e)
                error = str(e) or type(e).__name__
                got = Fetched(now, last.charges if last else [], last.months if last else [], error)
            self.fetched[key] = got
            return got

    async def balance(self, b: Billing) -> tuple[Balance | None, str]:
        now = self.clock()
        last = self.balances.get(b.name)
        if last and now - last[0] < (RETRY if last[2] else FRESH):
            return last[1], last[2]
        try:
            got = (now, await b.balance(), "")
        except Exception as e:  # noqa: BLE001
            log.warning("%s balance: %s", b.name, e)
            got = (now, last[1] if last else None, str(e) or type(e).__name__)
        self.balances[b.name] = got
        return got[1], got[2]

    async def view(self, month: str = "", balances: bool = False, fleet_only: bool = False) -> dict:
        """balances: what is left on each account. fleet_only: only the fleet's servers and the
        bastion, nothing else on the accounts (in the totals neither)."""
        month = self.month(month)
        fetched = await asyncio.gather(*(self.fetch(b, month) for b in self.billings))
        by_cloud = {b.name: f for b, f in zip(self.billings, fetched, strict=True)}
        out = assemble(self.fleet, month, by_cloud, fleet_only)
        months = {this_month(self.clock())} | {m for f in fetched for m in f.months}
        out["months"] = sorted(months, reverse=True)[:MONTHS_SHOWN]
        out["current"] = month == this_month(self.clock())
        if balances:
            got = await asyncio.gather(*(self.balance(b) for b in self.billings))
            out["balances"] = [
                {
                    "provider": b.name,
                    "title": TITLES.get(b.name, b.name),
                    "label": bal.label if bal else "",
                    "amount": round(bal.amount, 2) if bal else None,
                    "error": error,
                }
                for b, (bal, error) in zip(self.billings, got, strict=True)
            ]
        return out


def assemble(
    fleet: Fleet, month: str, fetched: dict[str, Fetched], fleet_only: bool = False
) -> dict:
    """The charges per server (in the fleet's order), the bastion, servers no longer in the
    fleet, and what isn't the fleet's ("other"). fleet_only: the servers and the bastion only."""
    groups: dict[str, dict] = {}
    totals = dict.fromkeys(fetched, 0.0)  # per cloud, of the charges shown

    def group(key: str, title: str, note: str = "") -> dict:
        return groups.setdefault(key, {"key": key, "title": title, "note": note, "items": {}})

    for name, spec in fleet.servers.items():
        if spec.provider in fetched:
            group(name, spec.title)
    if fleet.bastion.provider in fetched:
        group("bastion", "Bastion", "the fleet page, mini app and bot: always on")
    for cloud, f in fetched.items():
        for c in f.charges:
            name = c.label.removeprefix(FLEET_PREFIX) if c.label.startswith(FLEET_PREFIX) else ""
            if c.label == BASTION_LABEL:
                g = group("bastion", "Bastion", "the fleet page, mini app and bot: always on")
            elif name in fleet.servers:
                g = group(name, fleet.servers[name].title)
            elif fleet_only:
                continue
            elif name:
                g = group(name, name.title(), "no longer in the fleet")
            else:
                g = group("other", "Other", "on the accounts, but not the fleet's")
            totals[cloud] += c.amount
            if g["key"] == "other":
                key = (c.kind, c.label or c.what)
                shown = f"{KINDS[c.kind]} {c.label}" if c.label else c.what or KINDS[c.kind]
            else:
                key, shown = (c.kind, ""), KINDS[c.kind]
            item = g["items"].setdefault(
                key, {"kind": c.kind, "name": shown, "amount": 0.0, "hours": 0.0, "runs": 0}
            )
            item["amount"] += c.amount
            if c.kind == "vm" and c.hours:
                item["hours"] += c.hours
                item["runs"] += 1
    order = list(KINDS)
    out_groups = []
    # the fleet's servers, the bastion, servers no longer in the fleet, other
    rank = {name: i for i, name in enumerate([*fleet.servers, "bastion"])}
    ranked = sorted(
        groups.values(), key=lambda g: rank.get(g["key"], 99 if g["key"] == "other" else 50)
    )
    for g in ranked:
        items = sorted(g["items"].values(), key=lambda i: (order.index(i["kind"]), -i["amount"]))
        for i in items:
            i["amount"] = round(i["amount"], 2)
            i["hours"] = round(i["hours"], 1)
        total = round(sum(i["amount"] for i in items), 2)
        if g["key"] in fleet.servers or g["key"] == "bastion" or total:
            out_groups.append({**g, "items": items, "total": total})
    providers = [
        {
            "name": name,
            "title": TITLES.get(name, name),
            "total": round(totals[name], 2),
            "error": f.error,
        }
        for name, f in fetched.items()
    ]
    return {
        "month": month,
        "updated_at": int(min((f.at for f in fetched.values()), default=0)),
        "total": round(sum(p["total"] for p in providers), 2),
        "providers": providers,
        "groups": out_groups,
    }


def for_providers(fleet: Fleet, providers: dict, fake: bool = False) -> Costs:
    """The billing of each cloud the bastion has a key for (made-up figures with pretend clouds)."""
    if fake:
        return Costs(fleet, fake_billings())
    billings: list[Billing] = []
    for p in providers.values():
        if isinstance(p, Vultr):
            billings.append(VultrBilling(p))
        elif isinstance(p, Zenlayer):
            billings.append(ZenlayerBilling(p))
    return Costs(fleet, billings)
