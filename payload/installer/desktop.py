#!/usr/bin/env python3
"""Install system files and user defaults from payload/files without replacing personal files."""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
import tarfile
import tempfile

import provision

SHELL = "/bin/zsh"


def users(passwd, settings):
    limits = []
    for key in ("UID_MIN", "UID_MAX"):
        match = re.search(rf"^\s*{key}\s+(\d+)", settings, re.MULTILINE)
        if not match:
            raise ValueError(f"Missing login.defs {key}")
        limits.append(int(match[1]))
    if limits[0] > limits[1]:
        raise ValueError("Invalid UID limits")
    result = []
    for line in passwd.splitlines():
        name, _, uid, gid, _, home, shell = line.split(":")
        if not limits[0] <= int(uid) <= limits[1]:
            continue
        if int(uid) == 0 or name in {"root", "sddm", "gdm", "greeter", "nobody"} or shell in {
                "/sbin/nologin", "/usr/sbin/nologin", "/bin/false", "/usr/bin/false"}:
            continue
        if not home.startswith("/home/") or posixpath.normpath(home) != home:
            raise ValueError("Regular user home must be canonical and below /home")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*\$?", name):
            raise ValueError("Unsupported regular user name")
        result.append((name, int(uid), int(gid), home))
    if not result or len({u[3] for u in result}) != len(result):
        raise ValueError("Require regular users with distinct home directories")
    return result


def copy_missing(root, relative, data, uid, gid):
    """No overwrite/chown of an existing personal file, including a symlink."""
    path = root / relative
    if path.exists() or path.is_symlink():
        print(f"Preserved existing default: /{relative}")
        return False
    provision.destination(root, relative)  # reject symlinked parent directories
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o755)
        os.chown(parent, uid, gid)
    # Atomic exclusive publication; never replace a file created in the meantime.
    fd, name = tempfile.mkstemp(prefix=".pandora-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
            os.fchown(stream.fileno(), uid, gid)
        os.link(name, path)
    finally:
        os.unlink(name)
    return True


def skel_default(root, relative, data):
    """Replace only a verified pristine RPM skel default, never a custom one."""
    filename = f"etc/skel/{relative}"
    path = provision.destination(root, filename)
    if path.exists() and path.read_bytes() != data:
        listing = provision.run_in(root, "rpm", "-qf", "--queryformat",
                                   "%{FILEDIGESTALGO}\\n[%{FILENAMES}|%{FILEDIGESTS}\\n]", "/" + filename).splitlines()
        digests = [line.split("|", 1)[1] for line in listing if line.startswith("/" + filename + "|")]
        if not listing or listing[0] != "8" or digests != [hashlib.sha256(path.read_bytes()).hexdigest()]:
            raise ValueError("Existing skel default is customized; refusing overwrite")
        print(f"Replacing verified pristine RPM skel default: /{filename}")
    provision.atomic(root, filename, data)
    path.chmod(0o644)
    os.chown(path, 0, 0)


def archive_tree(archive, commit):
    prefix = f"ohmyzsh-{commit}"
    result = {}
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            path = PurePosixPath(member.name)
            if not path.parts or path.is_absolute() or ".." in path.parts or path.parts[0] != prefix:
                raise ValueError("Unsafe vendor archive path")
            relative = str(path.relative_to(prefix))
            if member.isdir():
                continue
            if relative == "." or relative in result:
                raise ValueError("Duplicate/invalid vendor archive entry")
            if member.issym():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), member.linkname))
                if member.linkname.startswith("/") or target == ".." or target.startswith("../"):
                    raise ValueError("Unsafe vendor symlink")
                result[relative] = ("link", member.linkname)
            elif member.isfile():
                result[relative] = ("file", bundle.extractfile(member).read(),
                                    0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError("Unsupported vendor archive entry")
    if "oh-my-zsh.sh" not in result or "LICENSE.txt" not in result:
        raise ValueError("Incomplete Oh My Zsh payload")
    return result


def installed_tree(directory):
    result = {}
    for path in directory.rglob("*"):
        relative = str(path.relative_to(directory))
        if path.is_symlink():
            result[relative] = ("link", os.readlink(path))
        elif path.is_file():
            result[relative] = ("file", path.read_bytes(), path.stat().st_mode & 0o777)
        elif not path.is_dir():
            raise ValueError("Unexpected vendor file type")
    return result


def install_vendor(root, source, lock):
    vendor = lock["oh_my_zsh"]
    commit = vendor["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid Oh My Zsh commit")
    filename = f"payload/vendor/oh-my-zsh-{commit}.tar.gz"
    if vendor["archive_payload_file"] != filename:
        raise ValueError("Unexpected vendor archive path")
    archive = source / filename
    provision.hashed(archive, vendor["archive_sha256"])
    expected = archive_tree(archive, commit)
    if hashlib.sha256(expected["LICENSE.txt"][1]).hexdigest() != vendor["license_sha256"]:
        raise ValueError("Oh My Zsh license mismatch")
    directory = provision.destination(root, f"usr/share/pandora-linux/oh-my-zsh/{commit}")
    if directory.exists():
        if not directory.is_dir() or installed_tree(directory) != expected:
            raise ValueError("Existing root-managed Oh My Zsh differs from pinned payload")
        for path in (directory, *directory.rglob("*")):
            info = path.lstat()
            if info.st_uid != os.geteuid() or (not path.is_symlink() and info.st_mode & 0o022):
                raise ValueError("Root-managed Oh My Zsh ownership/permissions changed")
        return
    provision.mkdir_public(root, str(directory.parent.relative_to(root)))
    with tempfile.TemporaryDirectory(prefix=".pandora-omz-", dir=directory.parent) as staging:
        with tarfile.open(archive) as bundle:
            bundle.extractall(staging, filter="data")
        tree = Path(staging) / f"ohmyzsh-{commit}"
        tree.chmod(0o755)
        for path in tree.rglob("*"):
            if path.is_symlink():
                continue
            path.chmod(0o755 if path.is_dir() or expected[str(path.relative_to(tree))][2] == 0o755 else 0o644)
        if installed_tree(tree) != expected:
            raise ValueError("Extracted vendor tree mismatch")
        os.rename(tree, directory)


def apply(root, source, lock):
    accounts = users(provision.run_in(root, "getent", "passwd"), (root / "etc/login.defs").read_text())
    session = root / "usr/share/wayland-sessions/hyprland-uwsm.desktop"
    if "Exec=uwsm start -e -D Hyprland hyprland.desktop\n" not in session.read_text():
        raise ValueError("UWSM session differs from tested RPM")
    if "Exec=/usr/bin/start-hyprland\n" not in (session.parent / "hyprland.desktop").read_text():
        raise ValueError("Unexpected compositor session entry")
    # Reject a competing DMS start path; do not disable a user's service silently.
    for base in (root / "etc/systemd/user", root / "usr/lib/systemd/user"):
        if any(p.parent.name.endswith((".wants", ".requires")) for p in base.rglob("dms.service")):
            raise ValueError("DMS must not be globally enabled alongside compositor autostart")
    defaults = {}
    skel = source / "payload/files/etc/skel"
    for path in sorted(skel.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinked skel input")
        if path.is_file():
            defaults[path.relative_to(skel).as_posix()] = path.read_bytes()
    vendor_path = f"/usr/share/pandora-linux/oh-my-zsh/{lock['oh_my_zsh']['commit']}"
    if f"export ZSH={vendor_path}\n".encode() not in defaults[".zshrc"]:
        raise ValueError("Zsh default and source-lock commit disagree")
    for _, uid, _, home in accounts:
        directory = provision.destination(root, home.lstrip("/"))
        if not directory.is_dir() or directory.stat().st_uid != uid:
            raise ValueError("Regular home missing or not owned by its user")
        if any(p.parent.name.endswith((".wants", ".requires"))
               for p in (directory / ".config/systemd/user").rglob("dms.service")):
            raise ValueError("User DMS unit conflicts with compositor autostart")
        for relative in defaults:
            # Validate parents even when the default itself already exists.
            provision.destination(root, str(Path(home.lstrip("/")) / relative).rsplit("/", 1)[0])
    install_vendor(root, source, lock)
    files = source / "payload/files"
    system_paths = set()
    for path in sorted(files.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinked system file input")
        if not path.is_file() or path.is_relative_to(skel):
            continue
        relative = path.relative_to(files).as_posix()
        if relative.startswith("usr/share/pandora-linux/keys/"):
            continue  # Installed and fingerprint-checked by provision.repositories.
        provision.atomic(root, relative, path.read_bytes(), preserve=True)
        (root / relative).chmod(path.stat().st_mode & 0o777)
        system_paths.add("/" + relative)
        system_paths.update("/" + p.as_posix() for p in Path(relative).parents if str(p) != ".")
    for relative, data in defaults.items():
        skel_default(root, relative, data)
    for name, uid, gid, home in accounts:
        for relative, data in defaults.items():
            copy_missing(root, f"{home.lstrip('/')}/{relative}", data, uid, gid)
        provision.run_in(root, "usermod", "--shell", SHELL, "--", name)
        # Only the owned default paths; no recursive relabel/chown of HOME.
        provision.run_in(root, "restorecon", *[f"{home}/{p}" for p in defaults])
        parents = {f"{home}/{p}" for name in defaults for p in Path(name).parents if str(p) != "."}
        if parents:
            provision.run_in(root, "restorecon", *sorted(parents))
    provision.run_in(root, "useradd", "-D", "-s", SHELL)
    if system_paths:
        provision.run_in(root, "restorecon", *sorted(system_paths))
    provision.run_in(root, "restorecon", "-RF", "/etc/skel", "/usr/share/pandora-linux/oh-my-zsh", "/etc/default/useradd")
    print("Desktop defaults applied; existing user files preserved; no service started")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        provision.guard(args.target_root)
        lock, _ = provision.inputs(args.source_root)
        apply(args.target_root, args.source_root, lock)
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        sys.exit(f"Pandora desktop defaults failed: {error}")
