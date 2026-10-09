#!/usr/bin/env python3
"""Validate package sources, accounts and target settings used by configure.sh."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile


QUERY = "%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\\n"
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9+_.-]*)-(\d+):([A-Za-z0-9+_.~^]+)-([A-Za-z0-9+_.]+)\.(x86_64|noarch)")


def output(*args):
    return subprocess.check_output(args, text=True, timeout=60)


def run_in(root, *args):
    return output("chroot", str(root), *args)


def release(path):
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            words = shlex.split(value)
            values[key] = words[0] if len(words) == 1 else value
    if values.get("ID") != "fedora" or values.get("VERSION_ID") != "44":
        raise ValueError("Installation requires Fedora 44")


def guard(root):
    # Check the execution OS first, even before root/target validation.
    release(Path("/etc/os-release"))
    if platform.machine() != "x86_64":
        raise ValueError("Provisioning requires x86_64")
    if os.geteuid() != 0:
        raise ValueError("Target configuration requires root in the Fedora installer")
    if not root.is_absolute() or str(root.resolve()) != str(root) or not root.is_dir():
        raise ValueError("Target root must be an existing absolute canonical path")
    release(root / "usr/lib/os-release")
    target_release = root / "etc/os-release"
    if target_release.is_symlink():
        link = os.readlink(target_release)
        target_release = root / link.lstrip("/") if link.startswith("/") else target_release.parent / link
    if not target_release.resolve().is_relative_to(root.resolve()):
        raise ValueError("Target release file escapes target root")
    release(target_release)
    settings = (root / "etc/selinux/config").read_text()
    if not re.search(r"^SELINUX=enforcing\s*$", settings, re.MULTILINE):
        raise ValueError("Target SELinux configuration must be enforcing")
    runtime = output("getenforce").strip()
    if runtime == "Enforcing":
        return
    # getenforce describes the running kernel, not the unbooted target. Anaconda
    # may be permissive; accept that only for the exact, actually mounted ISO and
    # Btrfs target used by this installer. A running system must be enforcing.
    if runtime != "Permissive" or root != Path("/mnt/sysroot"):
        raise ValueError("SELinux must remain enforcing outside the verified INSTALLER context")
    for mountpoint, filesystem in (("/run/install/repo", "iso9660"), ("/mnt/sysroot", "btrfs")):
        actual = output("findmnt", "-rn", "--mountpoint", mountpoint, "-o", "TARGET,FSTYPE").strip()
        if actual != f"{mountpoint} {filesystem}":
            raise ValueError("Permissive SELinux requires the verified INSTALLER ISO/target mounts")
    print("Verified INSTALLER SELinux runtime is permissive; target remains configured enforcing", file=sys.stderr)


def hashed(path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected regular input: {path}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Locked input hash mismatch: {path}")
    return data


def inputs(source):
    lock = json.loads((source / "config/sources.lock.json").read_text())
    if lock.get("schema_version") != 1 or lock["fedora_release"] != "44" or lock["architecture"] != "x86_64":
        raise ValueError("Wrong source-lock release/architecture")
    specs = []
    for kind in ("base", "desktop"):
        path = source / f"config/packages-{kind}.txt"
        if path.is_symlink() or not path.is_file():
            raise ValueError("Package list must be a regular file")
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line == "@core":
                continue
            if not (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.-]*", line) or PIN.fullmatch(line)):
                raise ValueError(f"Invalid package spec: {line}")
            specs.append(line)
    if not specs or len(set(specs)) != len(specs):
        raise ValueError("Package selection must be nonempty and contain no duplicates")
    repos = lock["desktop"]["repositories"]
    if not repos or len({r["id"] for r in repos}) != len(repos):
        raise ValueError("Repository IDs must be unique and nonempty")
    for repo in repos:
        if (not re.fullmatch(r"pandora-[a-z0-9-]+", repo["id"])
                or repo["prepared_repo_file"] != f"config/repos/{repo['id']}.repo"):
            raise ValueError("Unexpected repo ID or path")
        path = source / repo["prepared_repo_file"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("Repository definition must be a regular file")
        text = path.read_text()
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(text)
        if config.sections() != [repo["id"]]:
            raise ValueError("Duplicate/unexpected repository definition")
        section = config[repo["id"]]
        for key in ("gpgcheck", "sslverify", "enabled"):
            if not section.getboolean(key):
                raise ValueError(f"Required repo security/availability option: {key}")
        if section.getboolean("skip_if_unavailable"):
            raise ValueError("Required repositories must not be silently skipped")
        key = repo["signing_key"]
        filename = key["payload_file"]
        expected = f"payload/files/usr/share/pandora-linux/keys/{Path(filename).name}"
        if filename != expected or Path(filename).suffix != ".asc":
            raise ValueError("Unexpected signing-key payload path")
        hashed(source / filename, key["sha256"])
        if (section["baseurl"] != repo["baseurl"] or not section["baseurl"].startswith("https://")
                or section["gpgkey"] != "file:///" + filename.removeprefix("payload/files/")):
            raise ValueError("Repository URL or key differs from the source lock")
        allowed = section["includepkgs"].split(",")
        if not allowed or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.-]*", name) for name in allowed):
            raise ValueError("Repository must have an explicit package-name allowlist")
    flathub = lock["flathub"]
    if flathub["payload_file"] != "payload/flatpak/flathub.flatpakrepo":
        raise ValueError("Unexpected Flathub path")
    text = hashed(source / flathub["payload_file"], flathub["sha256"]).decode()
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(text)
    if config["Flatpak Repo"]["Url"] != "https://dl.flathub.org/repo/":
        raise ValueError("Unexpected Flathub URL")
    return lock, specs


def destination(root, relative):
    name = Path(relative)
    if name.is_absolute() or ".." in name.parts or str(name) != relative or relative == ".":
        raise ValueError(f"Unsafe target-relative path: {relative}")
    path = root / name
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"Refusing managed symlink: {parent}")
    return path


def mkdir_public(root, relative):
    """Create only missing managed directories as 0755; preserve existing modes."""
    path = destination(root, relative)
    missing = []
    parent = path
    while parent != root and not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o755)
        # mkdir's requested mode is still filtered by the installer's umask 077.
        # Set the public mode only on a directory created by this call.
        directory.chmod(0o755)


def atomic(root, relative, data, preserve=False):
    path = destination(root, relative)
    if path.exists():
        if not path.is_file():
            raise ValueError(f"Not a regular managed file: {path}")
        if path.read_bytes() == data:
            return
        if preserve:
            raise ValueError(f"Existing configuration differs; refusing overwrite: {path}")
    mkdir_public(root, str(path.parent.relative_to(root)))
    fd, name = tempfile.mkstemp(prefix=".pandora-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def repositories(root, source, lock):
    # Validate every fingerprint and existing destination *before* writing any repo.
    with tempfile.TemporaryDirectory(prefix="pandora-gpg-") as directory:
        for repo in lock["desktop"]["repositories"]:
            key = repo["signing_key"]
            listing = output("gpg", "--batch", "--homedir", directory, "--with-colons",
                             "--show-keys", str(source / key["payload_file"]))
            fingerprints = []
            primary = False
            for line in listing.splitlines():
                fields = line.split(":")
                if fields[0] == "pub":
                    primary = True
                elif fields[0] == "sub":
                    primary = False
                elif fields[0] == "fpr" and primary:
                    fingerprints.append(fields[9])
                    primary = False
            if fingerprints != [key["fingerprint"]]:
                raise ValueError("Signing-key primary fingerprint mismatch")
    files = []
    for repo in lock["desktop"]["repositories"]:
        key = repo["signing_key"]
        files.extend([(key["payload_file"], key["payload_file"].removeprefix("payload/files/")),
                      (repo["prepared_repo_file"], f"etc/yum.repos.d/{repo['id']}.repo")])
    for src, dest in files:
        path = destination(root, dest)
        if path.exists() and (not path.is_file() or path.read_bytes() != (source / src).read_bytes()):
            raise ValueError(f"Refusing to replace altered config: {path}")
    for src, dest in files:
        atomic(root, dest, (source / src).read_bytes(), preserve=True)
    for repo in lock["desktop"]["repositories"]:
        path = "/" + repo["signing_key"]["payload_file"].removeprefix("payload/files/")
        run_in(root, "rpmkeys", "--import", path)


def packages(root, lock, specs, write=False):
    origins = {}
    lines = run_in(root, "dnf", "repoquery", "--installed",
                   "--queryformat=%{full_nevra}|%{from_repo}\\n").splitlines()
    for line in lines:
        if "|" in line:
            nevra, repo = line.split("|", 1)
            origins[nevra] = repo
    direct = []
    for spec in specs:
        pin = PIN.fullmatch(spec)
        name = pin[1] if pin else spec
        installed = run_in(root, "rpm", "-q", "--queryformat", QUERY, name).splitlines()
        if pin and installed != [spec]:
            raise ValueError(f"Required package version mismatch: {spec}")
        for nevra in installed:
            origin = origins.get(nevra)
            if not origin:
                raise ValueError(f"Missing installed package origin: {nevra}")
            if pin:
                matches = []
                for repo in lock["desktop"]["repositories"]:
                    config = configparser.ConfigParser(interpolation=None)
                    config.read(root / f"etc/yum.repos.d/{repo['id']}.repo")
                    if name in config[repo["id"]]["includepkgs"].split(","):
                        matches.append(repo["id"])
                if matches != [origin]:
                    raise ValueError(f"Unexpected package source: {nevra}: {origin}")
            direct.append({"spec": spec, "nevra": nevra, "repository": origin})
    if write:
        manifest = {"fedora_release": "44", "architecture": "x86_64",
                    "direct_packages": direct, "source_lock": lock}
        atomic(root, "usr/share/pandora-linux/installed-packages.json",
               (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
        inventory = sorted(run_in(root, "rpm", "-qa", "--queryformat", QUERY).splitlines())
        atomic(root, "usr/share/pandora-linux/installed-rpms.txt", ("\n".join(inventory) + "\n").encode())
    print(f"Verified {len(specs)} package specs and {sum(bool(PIN.fullmatch(s)) for s in specs)} version pins")


def administrators(root):
    settings = (root / "etc/login.defs").read_text()
    limits = {}
    for key in ("UID_MIN", "UID_MAX"):
        match = re.search(rf"^\s*{key}\s+(\d+)", settings, re.MULTILINE)
        if not match:
            raise ValueError(f"Missing login.defs {key}")
        limits[key] = int(match[1])
    wheel = run_in(root, "getent", "group", "wheel").strip().split(":")
    wheel_gid = int(wheel[2])
    members = set(wheel[3].split(","))
    # Never print shadow fields or write them to a report/manifest.
    shadow = {line.split(":")[0]: line.split(":")[1]
              for line in run_in(root, "getent", "shadow").splitlines()}
    admins = []
    for line in run_in(root, "getent", "passwd").splitlines():
        name, _, uid, gid, _, home, shell = line.split(":")
        if (limits["UID_MIN"] <= int(uid) <= limits["UID_MAX"] and home.startswith("/home/")
                and shell not in ("/sbin/nologin", "/usr/sbin/nologin", "/bin/false")
                and (name in members or int(gid) == wheel_gid)):
            password = shadow.get(name, "")
            if not password or password.startswith(("!", "*")):
                continue
            policy = run_in(root, "sudo", "-l", "-U", name)
            if "NOPASSWD:" in policy or not re.search(r"\(ALL(?:\s*:\s*ALL)?\)\s+(?:PASSWD:\s*)?ALL", policy):
                raise ValueError("Administrator must have ordinary password-protected sudo")
            admins.append(name)
    if not admins:
        raise ValueError("No regular wheel administrator with password and sudo found")
    print("Regular administrator with password-protected sudo checked")


def defaults(root, source, lock):
    # Do not override existing autologin settings elsewhere with competing files.
    paths = list((root / "etc/sddm.conf.d").glob("*.conf")) + [root / "etc/sddm.conf"]
    for path in paths:
        if path.exists():
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read(path)
            if config.get("Autologin", "User", fallback="").strip():
                raise ValueError("Existing SDDM autologin is outside the Pandora defaults")
    atomic(root, "etc/sddm.conf.d/20-pandora.conf",
           b"# Pandora Linux: interactive login only.\n[Autologin]\nUser=\nSession=\nRelogin=false\n", preserve=True)
    atomic(root, "etc/pandora-linux-release",
           b'NAME="Pandora Linux"\nBASE="Fedora 44"\nCLAIM="Philipp\'s Adaptive Native Desktop, built on Fedora."\n', preserve=True)
    atomic(root, "usr/share/pandora-linux/flathub.flatpakrepo",
           (source / lock["flathub"]["payload_file"]).read_bytes(), preserve=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("guard", "inputs", "repos", "specs", "packages", "manifest", "admins", "defaults"))
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        guard(args.target_root)
        lock, specs = inputs(args.source_root)
        if args.action == "specs":
            print("\n".join(specs))
        elif args.action == "repos":
            repositories(args.target_root, args.source_root, lock)
        elif args.action in ("packages", "manifest"):
            packages(args.target_root, lock, specs, write=args.action == "manifest")
        elif args.action == "admins":
            administrators(args.target_root)
        elif args.action == "defaults":
            defaults(args.target_root, args.source_root, lock)
    except (OSError, ValueError, KeyError, configparser.Error, subprocess.SubprocessError) as error:
        sys.exit(f"Pandora provisioning check failed: {error}")
