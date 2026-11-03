#!/usr/bin/env bash
# Mounts this VM's data disk, the one that outlives the VM (Vultr block storage, a Zenlayer data
# disk), at $1. The first time the disk is blank and gets formatted with the label iw4x-data;
# after that it is found by that label. A disk that holds anything else (a filesystem without
# the label, partitions) is never formatted. Waits up to 10 minutes for the disk to show up:
# the bastion attaches it once the VM runs.
#
#   bash deploy/common/mount-data.sh /srv/iw4x

set -euo pipefail

MNT=${1:?usage: mount-data.sh <mount point>}
LABEL=iw4x-data

if mountpoint -q "$MNT"; then
  echo "    $MNT already mounted"
  exit 0
fi

# the disk the system runs from, never a candidate
root_disk=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" | head -1)

blank_disk() {
  local dev size
  for dev in $(lsblk -dnpo NAME,TYPE | awk '$2 == "disk" {print $1}'); do
    [[ "$(basename "$dev")" == "$root_disk" ]] && continue
    size=$(lsblk -dnbo SIZE "$dev")
    (( size >= 10 * 1024 ** 3 )) || continue                 # not a config drive
    (( $(lsblk -no NAME "$dev" | wc -l) == 1 )) || continue   # has partitions
    blkid -p "$dev" >/dev/null 2>&1 && continue                # has a filesystem or other signature
    echo "$dev"
    return 0
  done
  return 1
}

dev=""
for (( i = 0; i < 120; i++ )); do
  udevadm settle 2>/dev/null || true
  if [[ -e "/dev/disk/by-label/$LABEL" ]]; then
    dev=$(readlink -f "/dev/disk/by-label/$LABEL")
    echo "    found the data disk: $dev"
    break
  fi
  if dev=$(blank_disk); then
    echo "    a blank disk: $dev, formatting it (first boot of this server)"
    mkfs.ext4 -q -m 0 -L "$LABEL" "$dev"
    break
  fi
  sleep 5
done
[[ -n "$dev" ]] || { echo "    no data disk showed up in 10 minutes" >&2; exit 1; }

mkdir -p "$MNT"
grep -q "LABEL=$LABEL " /etc/fstab ||
  echo "LABEL=$LABEL $MNT ext4 defaults,nofail,x-systemd.device-timeout=30s 0 2" >> /etc/fstab
mount "$dev" "$MNT"
echo "    mounted at $MNT ($(df -h "$MNT" | awk 'NR == 2 {print $4}') free)"
