"""A pretend cloud for task control:dev and the tests: VMs come up after a few polls, disks are
remembered, nothing costs money."""

import itertools

from control.providers import ACTIVE, GONE, PENDING, CloudError, Instance, Machine


class FakeCloud:
    def __init__(self, name: str = "fake", boot_polls: int = 2):
        self.name = name
        self.boot_polls = boot_polls
        self.ids = itertools.count(1)
        self.volumes: dict[str, str] = {}  # label -> id
        self.attached: dict[str, str] = {}  # volume -> instance
        self.instances: dict[str, dict] = {}  # id -> {label, polls, user_data, gone}
        self.calls: list[tuple[str, str]] = []
        self.fail_create = False

    async def ensure_volume(self, m: Machine) -> str:
        self.calls.append(("ensure_volume", m.label))
        if m.label not in self.volumes:
            self.volumes[m.label] = f"vol-{next(self.ids)}"
        return self.volumes[m.label]

    async def create_instance(self, m: Machine, user_data: str) -> str:
        self.calls.append(("create_instance", m.label))
        if self.fail_create:
            raise CloudError("no capacity (fake)")
        instance_id = f"vm-{next(self.ids)}"
        self.instances[instance_id] = {"label": m.label, "polls": 0, "user_data": user_data}
        return instance_id

    async def get_instance(self, instance_id: str) -> Instance:
        inst = self.instances.get(instance_id)
        if not inst or inst.get("gone"):
            return Instance(instance_id, GONE)
        inst["polls"] += 1
        if inst["polls"] <= self.boot_polls:
            return Instance(instance_id, PENDING)
        return Instance(instance_id, ACTIVE, f"192.0.2.{int(instance_id.split('-')[1]) % 250}")

    async def attach_volume(self, volume_id: str, instance_id: str) -> None:
        self.calls.append(("attach_volume", volume_id))
        if self.attached.get(volume_id) not in (None, instance_id):
            raise CloudError("attached elsewhere")
        self.attached[volume_id] = instance_id

    async def detach_volume(self, volume_id: str, instance_id: str) -> None:
        self.calls.append(("detach_volume", volume_id))
        if self.attached.get(volume_id) == instance_id:
            del self.attached[volume_id]

    async def destroy_instance(self, instance_id: str, volume_id: str | None) -> None:
        self.calls.append(("destroy_instance", instance_id))
        if volume_id:
            await self.detach_volume(volume_id, instance_id)
        if volume_id in self.attached:
            raise CloudError("disk still attached")
        if instance_id in self.instances:
            self.instances[instance_id]["gone"] = True

    def running(self) -> list[str]:
        return [i for i, v in self.instances.items() if not v.get("gone")]

    async def close(self) -> None:
        pass
