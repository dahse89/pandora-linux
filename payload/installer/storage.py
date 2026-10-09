#!/usr/bin/env python3
"""Read-only, fail-closed check of an explicitly mounted Pandora target.

Pandora uses one Btrfs device on an active LUKS2 mapping. No disk is
opened for writing. Never infer the installer target from its own root.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


class StorageError(ValueError):
    pass


def output(*args):
    return subprocess.check_output(args, text=True, timeout=30)


def mount_at(target):
    data = json.loads(output("findmnt", "--json", "--mountpoint", target,
                             "-o", "TARGET,SOURCE,FSTYPE,OPTIONS,FSROOT,UUID"))
    mounts = data["filesystems"]
    if len(mounts) != 1 or mounts[0]["target"] != target:
        raise StorageError(f"Expected exactly one mount at {target}")
    return mounts[0]


def block_number(source):
    # findmnt adds [/subvolume] to the block-device source on Btrfs.
    device = source.split("[", 1)[0]
    info = os.stat(device)
    if not stat.S_ISBLK(info.st_mode):
        raise StorageError(f"Not a block device: {device}")
    return f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"


def validate(root, home, blocks, device_number):
    """Validate real findmnt/lsblk data; device_number is from stat(st_rdev).

    Btrfs findmnt MAJ:MIN is a *filesystem* pseudo-device, not the block
    device MAJ:MIN. Matching those directly would reject valid Btrfs.
    """
    for mount in (root, home):
        if mount.get("fstype") != "btrfs":
            raise StorageError("Root and home must both be Btrfs")
        options = dict(item.split("=", 1) if "=" in item else (item, "")
                       for item in mount.get("options", "").split(","))
        subvol = mount.get("fsroot")
        if (not subvol or subvol == "/" or options.get("subvol") != subvol
                or not options.get("subvolid", "").isdigit()
                or int(options["subvolid"]) <= 5):
            raise StorageError("Missing/non-subvolume root or home mount")
    rpath, hpath = root["fsroot"], home["fsroot"]
    if (rpath == hpath or hpath.startswith(rpath.rstrip("/") + "/")
            or rpath.startswith(hpath.rstrip("/") + "/")):
        raise StorageError("Root and home must be separate, non-nested subvolumes")
    if (not root.get("uuid") or root["uuid"] != home.get("uuid")
            or root["source"].split("[", 1)[0] != home["source"].split("[", 1)[0]):
        raise StorageError("Root and home must share the same encrypted Btrfs device")
    nodes, parents = {}, {}

    def visit(node, parent=None):
        key = node["maj:min"]
        nodes[key] = node
        if parent is not None:
            parents.setdefault(key, set()).add(parent)
        for child in node.get("children", []):
            visit(child, key)

    for node in blocks["blockdevices"]:
        visit(node)
    device = nodes.get(device_number)
    if not device or device.get("fstype") != "btrfs" or device.get("type") != "crypt":
        raise StorageError("Btrfs must be directly on an active encrypted mapping")
    ancestry = parents.get(device_number, set())
    if len(ancestry) != 1:
        raise StorageError("Ambiguous/missing encryption parent")
    parent = nodes[next(iter(ancestry))]
    if parent.get("fstype") != "crypto_LUKS" or str(parent.get("fsver")) != "2":
        raise StorageError("The actual Btrfs parent must be LUKS2")
    return parent["path"]


def verify(target_root):
    if not target_root.startswith("/") or os.path.realpath(target_root) != target_root:
        raise StorageError("--target-root must be an absolute canonical path")
    target = Path(target_root)
    if not target.is_dir() or (target / "home").is_symlink():
        raise StorageError("Missing target or symlinked target home")
    root = mount_at(str(target))
    home = mount_at(str(target / "home"))
    if root.get("fstype") != "btrfs" or home.get("fstype") != "btrfs":
        raise StorageError("Root and home must both be Btrfs")
    number = block_number(root["source"])
    if block_number(home["source"]) != number:
        raise StorageError("Root/home use different block devices")
    blocks = json.loads(output("lsblk", "--json", "-o",
                              "NAME,PATH,TYPE,FSTYPE,FSVER,MAJ:MIN,PKNAME"))
    luks = validate(root, home, blocks, number)
    ids = []
    for path, mount in ((str(target), root), (str(target / "home"), home)):
        data = output("btrfs", "subvolume", "show", path)
        match = re.search(r"^\s*Subvolume ID:\s*(\d+)\s*$", data, re.MULTILINE)
        expected = re.search(r"(?:^|,)subvolid=(\d+)(?:,|$)", mount["options"])
        if not match or not expected or match[1] != expected[1]:
            raise StorageError("Mount is not the actual Btrfs subvolume root")
        ids.append(match[1])
    if ids[0] == ids[1]:
        raise StorageError("Root/home have the same subvolume ID")
    data = output("btrfs", "filesystem", "show", "--raw", str(target))
    total = re.search(r"Total devices\s+(\d+)", data)
    devices = re.findall(r"\bdevid\s+\d+.*\bpath\s+(\S+)\s*$", data, re.MULTILINE)
    if not total or total[1] != "1" or len(devices) != 1 or block_number(devices[0]) != number:
        raise StorageError("Pandora requires exactly one fully accounted Btrfs device")
    header = output("cryptsetup", "luksDump", luks)
    if not re.search(r"^Version:\s+2\s*$", header, re.MULTILINE):
        raise StorageError("Actual encryption header is not LUKS2")
    return {"target_root": target_root, "filesystem": "btrfs", "luks_version": 2,
            "root_subvolume": root["fsroot"], "home_subvolume": home["fsroot"],
            "root_subvolume_id": int(ids[0]), "home_subvolume_id": int(ids[1])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.target_root), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        sys.exit(f"Pandora storage check failed: {error}")
