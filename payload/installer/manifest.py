#!/usr/bin/env python3
"""File hashes and normalized permissions, shared by the ISO builder and installer."""
import hashlib
import json
from pathlib import Path
import stat


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inventory(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Payload must be a real directory")
    result = {}
    for path in sorted(directory.rglob("*")):
        name = path.relative_to(directory).as_posix()
        if name == "manifest.json":
            continue
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode) and mode == 0o755:
            result[name] = {"type": "directory", "mode": mode}
        elif stat.S_ISREG(info.st_mode) and mode in (0o644, 0o755):
            result[name] = {"type": "file", "mode": mode, "size_bytes": info.st_size,
                            "sha256": digest(path)}
        else:
            raise ValueError(f"Unsafe payload type/permissions: {name}")
    return result


def verify(directory, expected_hash):
    manifest = directory / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file() or digest(manifest) != expected_hash:
        raise ValueError("Payload manifest hash mismatch")
    record = json.loads(manifest.read_text())
    if record.get("schema_version") != 1 or record.get("kind") != "pandora-linux-payload":
        raise ValueError("Unsupported payload manifest")
    if not record.get("files") or inventory(directory) != record["files"]:
        raise ValueError("Payload file inventory/hash/mode mismatch")
    return record
