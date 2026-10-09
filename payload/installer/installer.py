#!/usr/bin/env python3
"""Explicit INSTALLER-only copy/provision bridge; never infer a target mount."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import manifest
import provision

ISO_ROOT = Path("/run/install/repo")
TARGET_ROOT = Path("/mnt/sysroot")
LOCAL_SOURCE = "usr/share/pandora-linux/installer-source"


def mounted_iso():
    actual = subprocess.check_output(
        ["findmnt", "-rn", "--mountpoint", str(ISO_ROOT), "-o", "TARGET,FSTYPE"],
        text=True, timeout=30).strip()
    if actual != f"{ISO_ROOT} iso9660":
        raise ValueError("Expected the verified ISO9660 mount at /run/install/repo")


def checked_target(target):
    if target != TARGET_ROOT:
        raise ValueError("Only the installer target /mnt/sysroot is allowed")
    provision.guard(target)
    subprocess.run(["python3", str(Path(__file__).with_name("storage.py")),
                    "--target-root", str(target)], check=True, timeout=120)


def copy_payload(source, target, expected_hash):
    if source != ISO_ROOT / "payload":
        raise ValueError("Only the mounted ISO payload path is allowed")
    mounted_iso()
    checked_target(target)  # no destination writes before release/storage validation
    record = manifest.verify(source, expected_hash)
    provision.inputs(source)
    destination = provision.destination(target, LOCAL_SOURCE)
    if destination.exists():
        manifest.verify(destination, expected_hash)
    else:
        provision.mkdir_public(target, str(destination.parent.relative_to(target)))
        with tempfile.TemporaryDirectory(prefix=".pandora-source-", dir=destination.parent) as temporary:
            staging = Path(temporary) / "source"
            shutil.copytree(source, staging)
            # ISO extraction/copy must preserve the normalized closed inventory.
            manifest.verify(staging, expected_hash)
            os.rename(staging, destination)
    provision.atomic(target, "usr/share/pandora-linux/build-manifest.json",
                     (source / "manifest.json").read_bytes(), preserve=True)
    log = provision.destination(target, "var/log/pandora-linux")
    log.mkdir(parents=True, exist_ok=True, mode=0o700)
    log.chmod(0o700)
    subprocess.run(["chroot", str(target), "restorecon", "-RF",
                    "/usr/share/pandora-linux", "/var/log/pandora-linux"], check=True)
    print(f"PANDORA_PAYLOAD_COPY_OK files={len(record['files'])}")


def configure(source, target, expected_hash):
    if source != target / LOCAL_SOURCE:
        raise ValueError("Provision only from the copied target-local source")
    checked_target(target)
    manifest.verify(source, expected_hash)
    provision.inputs(source)
    # Check actual target mounts before any commands enter the target chroot.
    subprocess.run(["bash", str(source / "payload/installer/configure.sh"),
                    "--target-root", str(target), "--source-root", str(source),
                    "--resolver-from", "/etc/resolv.conf"], check=True)
    print("PANDORA_TARGET_PROVISION_OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("copy", "configure"))
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    # Imports must not add unmanifested __pycache__ files to the copied payload.
    try:
        if args.action == "copy":
            copy_payload(args.source_root, args.target_root, args.manifest_sha256)
        else:
            configure(args.source_root, args.target_root, args.manifest_sha256)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(f"Pandora installer phase failed: {error}")
