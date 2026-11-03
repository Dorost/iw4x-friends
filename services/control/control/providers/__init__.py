"""Clouds the fleet's VMs run on. Each one creates a VM from a user-data script, keeps a disk per
server between runs and destroys the VM again. The disk is only ever detached, never deleted."""

from dataclasses import dataclass
from typing import Protocol

# an instance as the orchestrator sees it
PENDING, ACTIVE, FAILED, GONE = "pending", "active", "failed", "gone"


class CloudError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status  # the HTTP status the cloud answered with, 0 when none


@dataclass(frozen=True)
class Instance:
    id: str
    status: str  # PENDING, ACTIVE, FAILED or GONE
    ip: str | None = None


@dataclass(frozen=True)
class Machine:
    """What to create: the catalog's server or the bastion, in the provider's own terms."""

    label: str  # name of the VM and of its disk
    region: str  # Vultr region / Zenlayer zone
    plan: str  # Vultr plan / Zenlayer instance type
    volume_gb: int
    options: dict


class Provider(Protocol):
    name: str

    async def ensure_volume(self, m: Machine) -> str:
        """The id of the machine's disk, created (empty) when it has none yet."""
        ...

    async def create_instance(self, m: Machine, user_data: str) -> str: ...

    async def get_instance(self, instance_id: str) -> Instance: ...

    async def attach_volume(self, volume_id: str, instance_id: str) -> None: ...

    async def detach_volume(self, volume_id: str, instance_id: str) -> None:
        """Returns once the disk is detached; CloudError when it isn't."""
        ...

    async def destroy_instance(self, instance_id: str, volume_id: str | None) -> None:
        """volume_id: the disk that must survive (detached before)."""
        ...

    async def close(self) -> None: ...
