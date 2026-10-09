#!/usr/bin/env python3
"""Build a Fedora netinstall remix from config/, kickstart/ and payload/.

Only local input checks run on other systems. ISO creation requires Fedora 44;
mkksiso is the only build operation that needs sudo.
"""
import argparse
import ast
import configparser
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "payload/installer"))
import desktop
import manifest
import provision

BOOTSTRAP = ("python3", "dnf5", "gnupg2", "shadow-utils", "coreutils", "findutils", "rpm")
TOOLS = ("curl", "gpg", "dnf", "mkksiso", "xorriso", "checkisomd5", "ksvalidator", "shellcheck", "mcopy", "sudo")
TOOL_RPMS = ("lorax", "xorriso", "isomd5sum", "pykickstart", "ShellCheck", "python3", "mtools")


def run(*args, capture=False):
    result = subprocess.run([str(a) for a in args], check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else None


def profile(root):
    value = json.loads((root / "config/profile.json").read_text())
    fields = {"fedora_release", "architecture", "boot_mode", "installation_mode",
              "locale", "keyboard_layout", "timezone", "output_iso"}
    if set(value) != fields or not all(isinstance(v, str) for v in value.values()):
        raise ValueError("Profile must contain only the documented, non-secret settings")
    if (value["fedora_release"], value["architecture"], value["boot_mode"], value["installation_mode"]) != (
            "44", "x86_64", "uefi", "online"):
        raise ValueError("This installer supports Fedora 44/x86_64, UEFI and online installation")
    patterns = {"locale": r"[A-Za-z_]+\.[A-Za-z0-9-]+", "keyboard_layout": r"[a-z0-9_-]+",
                "timezone": r"[A-Za-z_]+/[A-Za-z_+/-]+", "output_iso": r"pandora-linux-[A-Za-z0-9_.-]+\.iso"}
    for key, pattern in patterns.items():
        if not re.fullmatch(pattern, value[key]):
            raise ValueError(f"Invalid profile setting: {key}")
    return value


def local_file(root, name):
    relative = Path(name)
    if (relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name
            or not re.fullmatch(r"[A-Za-z0-9_.+/-]+", name)):
        raise ValueError(f"Unsafe input path: {name}")
    path = root / relative
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink():
            raise ValueError(f"Symlinked input: {name}")
    if not path.is_file():
        raise ValueError(f"Missing regular input: {name}")
    return path


def input_files(root, lock):
    """Include product inputs only, never the repository, development logs or caches."""
    names = {"config/profile.json", "config/sources.lock.json", "config/packages-base.txt",
             "config/packages-desktop.txt", lock["flathub"]["payload_file"],
             lock["oh_my_zsh"]["archive_payload_file"], lock["oh_my_zsh"]["license_payload_file"]}
    names.update(r["prepared_repo_file"] for r in lock["desktop"]["repositories"])
    for folder in ("payload/installer", "payload/files"):
        base = root / folder
        if base.is_symlink() or not base.is_dir():
            raise ValueError(f"Expected a real product directory: {folder}")
        for path in base.rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError(f"Symlinked product input: {path}")
            if path.is_file():
                names.add(path.relative_to(root).as_posix())
            elif not path.is_dir():
                raise ValueError(f"Unsupported product input: {path}")
    return sorted(names)


def safety(text, kickstart=False):
    """Catch accidental destructive/security shortcuts; this is not a secret scanner."""
    patterns = (r"\b(?:wipefs|mkfs(?:\.[a-z0-9]+)?)\b", r"\bdd\s+[^\n]*(?:if|of)=",
                r"/dev/(?:sd[a-z]|nvme\d+n\d+)", r"\bsetenforce\s+0\b",
                r"\b(?:gpgcheck|sslverify)\s*[=:]\s*(?:0|false)\b", r"\bSELINUX=disabled\b",
                r"--(?:nogpgcheck|noverifyssl|insecure)\b", r"curl\s+[^\n]*\s-k(?:\s|$)",
                r"(?:curl|wget)[^\n]*\|\s*(?:sh|bash|zsh)\b",
                r"\b(?:password|passphrase|luks_key)\s*=\s*['\"][^'\"]+['\"]", r"\bNOPASSWD:\s*ALL\b",
                r"\bsystemctl\b[^\n]*(?:\s(?:start|restart)\b|--now)")
    if any(re.search(p, text, re.I) for p in patterns):
        raise ValueError("Unsafe disk, security or service operation in product inputs")
    if kickstart:
        directives = "clearpart|zerombr|part|partition|autopart|raid|volgroup|logvol|bootloader|user|rootpw|reboot|ignoredisk"
        if re.search(rf"^\s*(?:{directives})(?:\s|$)", text, re.M):
            raise ValueError("Disk selection, partitioning and accounts must remain interactive")
        if re.search(r"^\s*%(?:include|ksappend)\b", text, re.M):
            raise ValueError("External Kickstart includes are not supported")


def validated_inputs(root):
    settings = profile(root)
    lock, _ = provision.inputs(root)
    base, key = lock["base_iso"], lock["fedora_signing_key"]
    for field in ("filename", "checksum_filename"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", base[field]):
            raise ValueError("Unsafe Fedora download filename")
    if (not re.fullmatch(r"[a-f0-9]{64}", base["sha256"])
            or not re.fullmatch(r"[A-F0-9]{40}", key["fingerprint"])
            or type(base["size_bytes"]) is not int or base["size_bytes"] <= 0):
        raise ValueError("Invalid Fedora hash, key fingerprint or ISO size")
    for url in (base["url"], base["checksum_url"], key["bundle_url"]):
        if not url.startswith("https://") or any(c.isspace() for c in url):
            raise ValueError("Fedora downloads must use HTTPS")
    for name in input_files(root, lock):
        path = local_file(root, name)
        if path.suffix in (".sh", ".py", ".repo") or name.endswith("pandora-screenshot"):
            safety(path.read_text())
    vendor = lock["oh_my_zsh"]
    if (not re.fullmatch(r"[0-9a-f]{40}", vendor["commit"])
            or vendor["archive_payload_file"] != f"payload/vendor/oh-my-zsh-{vendor['commit']}.tar.gz"
            or vendor["license_payload_file"] != "payload/vendor/oh-my-zsh-LICENSE.txt"):
        raise ValueError("Unexpected Oh My Zsh archive or license path")
    archive = local_file(root, vendor["archive_payload_file"])
    provision.hashed(archive, vendor["archive_sha256"])
    license_data = provision.hashed(local_file(root, vendor["license_payload_file"]), vendor["license_sha256"])
    if desktop.archive_tree(archive, vendor["commit"])["LICENSE.txt"][1] != license_data:
        raise ValueError("Oh My Zsh archive and license disagree")
    return settings, lock


def kickstart(root, payload):
    settings = profile(root)
    text = local_file(root, "kickstart/pandora-linux.ks.in").read_text()
    packages = []
    for line in (root / "config/packages-base.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line != "@core" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.-]*", line):
            raise ValueError("Base packages must be names, not version pins")
        packages.append(line)
    if packages.count("@core") != 1:
        raise ValueError("Expected exactly one @core group")
    values = {"@LOCALE@": settings["locale"], "@KEYBOARD@": settings["keyboard_layout"],
              "@TIMEZONE@": settings["timezone"],
              "@FEDORA_REPO@": "https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/x86_64/os/",
              "@BASE_PACKAGES@": "\n".join(dict.fromkeys([*packages, *BOOTSTRAP])),
              "@MANIFEST_SHA256@": manifest.digest(payload / "manifest.json"),
              "@PAYLOAD_SHA256@": "\n".join(f"{manifest.digest(payload / name)}  {name}" for name in
                                          [*input_files(root, json.loads((root / 'config/sources.lock.json').read_text())), "manifest.json"])}
    for token, value in values.items():
        if token not in text:
            raise ValueError(f"Missing Kickstart token: {token}")
        text = text.replace(token, value)
    if re.search(r"@[A-Z_]+@", text):
        raise ValueError("Unresolved Kickstart token")
    safety(text, kickstart=True)
    return text


def prepare(root, stage):
    settings, lock = validated_inputs(root)
    payload = stage / "payload"
    payload.mkdir(mode=0o755)
    for name in input_files(root, lock):
        source = local_file(root, name)
        output = payload / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)
        output.chmod(0o755 if source.stat().st_mode & 0o111 or name.endswith(".sh") else 0o644)
    for path in payload.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
    record = {"schema_version": 1, "kind": "pandora-linux-payload", "profile": settings,
              "source_iso": lock["base_iso"], "sources_lock": lock,
              "kickstart_template_sha256": manifest.digest(root / "kickstart/pandora-linux.ks.in"),
              "files": manifest.inventory(payload)}
    (payload / "manifest.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (payload / "manifest.json").chmod(0o644)
    (stage / "pandora-linux.ks").write_text(kickstart(root, payload))
    (stage / "pandora-linux.ks").chmod(0o644)
    return manifest.verify(payload, manifest.digest(payload / "manifest.json"))


def verify_stage(root, stage):
    settings, lock = validated_inputs(root)
    payload = stage / "payload"
    record = manifest.verify(payload, manifest.digest(local_file(payload, "manifest.json")))
    if record["profile"] != settings or record["sources_lock"] != lock or record["source_iso"] != lock["base_iso"]:
        raise ValueError("Embedded profile or sources differ from current inputs")
    if record["kickstart_template_sha256"] != manifest.digest(root / "kickstart/pandora-linux.ks.in"):
        raise ValueError("Embedded Kickstart template differs from current inputs")
    files = {name for name, entry in record["files"].items() if entry["type"] == "file"}
    if files != set(input_files(root, lock)):
        raise ValueError("Embedded payload file selection differs from current inputs")
    for name in files:
        source = local_file(root, name)
        if local_file(payload, name).read_bytes() != source.read_bytes():
            raise ValueError(f"Embedded payload differs: {name}")
        mode = 0o755 if source.stat().st_mode & 0o111 or name.endswith(".sh") else 0o644
        if record["files"][name]["mode"] != mode:
            raise ValueError(f"Embedded payload mode differs: {name}")
    if local_file(stage, "pandora-linux.ks").read_text() != kickstart(root, payload):
        raise ValueError("Embedded Kickstart differs from current inputs")


def check(root, stage):
    prepare(root, stage)
    verify_stage(root, stage)
    for path in [root / "iso.py", *(root / "payload/installer").glob("*.py")]:
        ast.parse(path.read_text(), filename=str(path))
    shell = [*(root / "payload/installer").glob("*.sh"), root / "payload/files/usr/local/bin/pandora-screenshot"]
    for path in shell:
        run("bash", "-n", path)
    for tool in ("shellcheck", "ksvalidator"):
        if shutil.which(tool):
            if tool == "shellcheck":
                run(tool, *shell)
            else:
                run(tool, "-v", "F44", stage / "pandora-linux.ks")
        else:
            print(f"{tool} not installed; its check was skipped")
    print("Product inputs, payload integrity and available syntax checks passed")


def build_environment(root):
    provision.release(Path("/etc/os-release"))
    if platform.machine() != "x86_64" or os.geteuid() == 0:
        raise ValueError("Build as a normal user on Fedora 44/x86_64, not as root")
    for tool in TOOLS:
        if not shutil.which(tool):
            raise ValueError(f"Missing build tool: {tool}; see README.md")
    if shutil.disk_usage(root).free < 20 * 1024 ** 3:
        raise ValueError("ISO creation requires at least 20 GiB free")


def directory(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"Expected a real directory: {path}")
    path.mkdir(exist_ok=True, mode=0o755)
    return path


@contextmanager
def locked(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Unsafe build lock: {path}")
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def fetch(root, lock):
    """Verify the signed CHECKSUM, pinned signer, size and full hash even on cache hits."""
    cache = directory(root / "cache")
    cache = directory(cache / "base-iso")
    base, key = lock["base_iso"], lock["fedora_signing_key"]
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=cache) as temporary:
        work = Path(temporary)
        downloads = {}
        for name, url in (("fedora.gpg", key["bundle_url"]), (base["checksum_filename"], base["checksum_url"]),
                          (base["filename"], base["url"])):
            path = cache / name
            if path.exists() or path.is_symlink():
                local_file(cache, name)
            else:
                path = work / name
                run("curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                    "--connect-timeout", "15", "--max-time", "1800", "--retry", "2", "--output", path, url)
                downloads[name] = path
        home = work / "gnupg"
        home.mkdir(mode=0o700)
        gpg = ("gpg", "--homedir", home, "--batch", "--no-tty")
        run(*gpg, "--import", downloads.get("fedora.gpg", cache / "fedora.gpg"))
        signed = downloads.get(base["checksum_filename"], cache / base["checksum_filename"])
        status = run(*gpg, "--status-fd", "1", "--output", work / "checksum.txt", "--decrypt", signed, capture=True)
        signers = [line.split()[2:] for line in status.splitlines() if line.startswith("[GNUPG:] VALIDSIG ")]
        if not signers or any(key["fingerprint"] not in (s[0], s[-1]) for s in signers):
            raise ValueError("Fedora CHECKSUM signer differs from the pinned fingerprint")
        checksums = re.findall(rf"^SHA256 \({re.escape(base['filename'])}\) = ([a-f0-9]{{64}})$",
                               (work / "checksum.txt").read_text(), re.M)
        if checksums != [base["sha256"]]:
            raise ValueError("Signed Fedora CHECKSUM disagrees with sources.lock.json")
        iso = downloads.get(base["filename"], cache / base["filename"])
        if iso.stat().st_size != base["size_bytes"] or manifest.digest(iso) != base["sha256"]:
            raise ValueError("Fedora ISO size or SHA256 mismatch; cache was not replaced")
        for name, path in downloads.items():
            os.replace(path, cache / name)
    return cache / base["filename"]


def verify_iso(root, stage, source_iso, iso, work):
    source_pvd = run("xorriso", "-indev", source_iso, "-pvd_info", capture=True)
    layout = run("xorriso", "-indev", iso, "-pvd_info", "-report_el_torito", "plain",
                 "-report_system_area", "plain", capture=True)
    extracted = work / "extracted"
    extracted.mkdir()
    run("xorriso", "-osirrox", "on", "-indev", iso,
        "-extract", "/pandora-linux.ks", extracted / "pandora-linux.ks",
        "-extract", "/payload", extracted / "payload", "-extract", "/EFI", extracted / "EFI",
        "-extract_boot_images", extracted / "boot-images")
    if (stage / "payload/manifest.json").read_bytes() != (extracted / "payload/manifest.json").read_bytes():
        raise ValueError("Embedded payload manifest differs from the staged manifest")
    verify_stage(root, extracted)
    run("ksvalidator", "-v", "F44", extracted / "pandora-linux.ks")
    labels = re.findall(r"^Volume Id\s*:\s*(.+)$", source_pvd, re.M)
    if len(labels) != 1 or re.findall(r"^Volume Id\s*:\s*(.+)$", layout, re.M) != labels:
        raise ValueError("Original ISO volume ID changed or is ambiguous")
    if (not re.search(r"El Torito boot img\s*:\s*\d+\s+UEFI\s+y\b", layout)
            or not re.search(r"GPT type GUID\s*:\s*2\s+28732ac11ff8d211ba4b00a0c93ec93b", layout)):
        raise ValueError("Missing UEFI El Torito image or appended GPT EFI partition")
    label = labels[0].strip()
    for name in ("grub.cfg", "BOOT.conf"):
        config = (extracted / "EFI/BOOT" / name).read_text()
        kernels = [shlex.split(line) for line in config.splitlines() if re.match(r"\s*linux(?:efi)?\s", line)]
        if not kernels:
            raise ValueError(f"No kernel entries in {name}")
        for args in kernels:
            if ([a for a in args if a.startswith("inst.ks=")] != [f"inst.ks=hd:LABEL={label}:/pandora-linux.ks"]
                    or [a for a in args if a.startswith("inst.stage2=")] != [f"inst.stage2=hd:LABEL={label}"]):
                raise ValueError(f"Incorrect Kickstart or stage2 boot argument in {name}")
    for image in ("eltorito_img2_uefi.img", "gpt_part2_efi.img"):
        image_path = extracted / "boot-images" / image
        for name in ("grub.cfg", "BOOT.conf", "BOOTX64.EFI", "grubx64.efi"):
            dest = extracted / f"{image}-{name}"
            run("mcopy", "-i", image_path, f"::/EFI/BOOT/{name}", dest)
            if dest.read_bytes() != (extracted / "EFI/BOOT" / name).read_bytes():
                raise ValueError(f"EFI boot image contents differ: {image}/{name}")
    run("checkisomd5", "--verbose", iso)


def build(root):
    build_environment(root)
    build_dir = directory(root / "build")
    artifacts = directory(root / "artifacts")
    with locked(build_dir / ".iso.lock"), tempfile.TemporaryDirectory(prefix="iso-", dir=build_dir) as temporary:
        work = Path(temporary)
        stage = work / "stage"
        stage.mkdir(mode=0o755)
        check(root, stage)
        settings, lock = validated_inputs(root)
        source_iso = fetch(root, lock)
        for line in (root / "config/packages-base.txt").read_text().splitlines() + list(BOOTSTRAP):
            package = line.strip()
            if not package or package.startswith(("#", "@")):
                continue
            matches = run("dnf", "-q", "repoquery", "--available", "--repo=fedora", "--arch=x86_64,noarch",
                          "--qf", "%{name}\\n", package, capture=True).splitlines()
            if package not in matches:
                raise ValueError(f"Base package absent from the Fedora release repository: {package}")
        candidate = work / settings["output_iso"]
        # mkksiso needs readable input directories despite the private temporary parent.
        work.chmod(0o755)
        run("sudo", "mkksiso", "--ks", stage / "pandora-linux.ks", "--add", stage / "payload",
            "--tmp", work, source_iso, candidate)
        run("sudo", "chown", "--no-dereference", f"{os.getuid()}:{os.getgid()}", candidate)
        local_file(work, candidate.name)
        verify_iso(root, stage, source_iso, candidate, work)
        record = {"schema_version": 1, "kind": "pandora-linux-iso", "iso_name": candidate.name,
                  "size_bytes": candidate.stat().st_size, "sha256": manifest.digest(candidate),
                  "payload_manifest_sha256": manifest.digest(stage / "payload/manifest.json"),
                  "kickstart_sha256": manifest.digest(stage / "pandora-linux.ks"), "profile": settings,
                  "source_iso_sha256": lock["base_iso"]["sha256"],
                  "build_tool_rpms": run("rpm", "-q", *TOOL_RPMS, capture=True).splitlines()}
        for suffix in ("", ".manifest.json", ".sha256"):
            output = artifacts / (candidate.name + suffix)
            if output.is_symlink() or (output.exists() and not output.is_file()):
                raise ValueError(f"Refusing unsafe output: {output}")
        (work / (candidate.name + ".manifest.json")).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        (work / (candidate.name + ".sha256")).write_text(f"{record['sha256']}  {candidate.name}\n")
        # Publish the ISO last. Failed builds leave the previous published image intact.
        for suffix in (".manifest.json", ".sha256", ""):
            os.replace(work / (candidate.name + suffix), artifacts / (candidate.name + suffix))
        print(f"Created and checked: {artifacts / candidate.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "build"))
    args = parser.parse_args()
    os.environ["LC_ALL"] = "C"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        if args.action == "build":
            build(ROOT)
        else:
            with tempfile.TemporaryDirectory(prefix="pandora-check-") as temporary:
                check(ROOT, Path(temporary))
    except (OSError, ValueError, KeyError, configparser.Error, subprocess.SubprocessError) as error:
        sys.exit(f"Pandora ISO: {error}")
