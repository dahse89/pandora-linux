#!/usr/bin/env bash
# Configure the explicitly mounted Fedora target. Never start target services here.
set -Eeuo pipefail
export LC_ALL=C
TARGET_ROOT=
SOURCE_ROOT=
RESOLVER_FROM=
RESOLVER_BACKUP=
RESOLVER_MOVED=0
RESOLVER_INSTALLED=0
WORK=
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

fail() { printf 'Pandora installation: %s\n' "$*" >&2; exit 1; }

cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n $RESOLVER_BACKUP ]]; then
        if [[ $RESOLVER_INSTALLED -eq 1 ]]; then
            if ! rm -f -- "$TARGET_ROOT/etc/resolv.conf"; then status=1; fi
        fi
        if [[ $RESOLVER_MOVED -eq 1 ]]; then
            if ! mv -- "$RESOLVER_BACKUP/original" "$TARGET_ROOT/etc/resolv.conf"; then
                printf 'Resolver restoration failed; backup retained at %s\n' "$RESOLVER_BACKUP" >&2
                exit 1
            fi
        fi
        if ! rm -f -- "$RESOLVER_BACKUP/replacement"; then status=1; fi
        if ! rmdir -- "$RESOLVER_BACKUP"; then status=1; fi
    fi
    if [[ -n $WORK ]]; then
        if ! rm -rf -- "$WORK"; then status=1; fi
    fi
    exit "$status"
}

initialize() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --target-root) [[ $# -ge 2 ]] || fail 'Missing target root'; TARGET_ROOT=$2; shift 2 ;;
            --source-root) [[ $# -ge 2 ]] || fail 'Missing source root'; SOURCE_ROOT=$2; shift 2 ;;
            --resolver-from) [[ $# -ge 2 ]] || fail 'Missing resolver path'; RESOLVER_FROM=$2; shift 2 ;;
            *) fail "Unknown argument: $1" ;;
        esac
    done
    [[ -n $TARGET_ROOT && -n $SOURCE_ROOT ]] || fail 'Require --target-root and --source-root'
    [[ $TARGET_ROOT == /* && $SOURCE_ROOT == /* ]] || fail 'Use absolute paths'
    python3 "$SCRIPT_DIR/provision.py" guard --target-root "$TARGET_ROOT" --source-root "$SOURCE_ROOT"
    # Storage checks need the real mounts, outside the chroot.
    python3 "$SCRIPT_DIR/storage.py" --target-root "$TARGET_ROOT"
    [[ -z $RESOLVER_FROM || $TARGET_ROOT != / ]] || fail 'Resolver replacement is installer-only'
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    WORK=$(mktemp -d /tmp/pandora-install.XXXXXX)
}

check() {
    python3 "$SCRIPT_DIR/provision.py" "$1" --target-root "$TARGET_ROOT" --source-root "$SOURCE_ROOT"
}

target() { chroot "$TARGET_ROOT" "$@"; }

dns_probe() {
    local host
    for host in dl.fedoraproject.org download.copr.fedorainfracloud.org dl.flathub.org; do
        if ! timeout 20 chroot "$TARGET_ROOT" getent ahosts "$host" > /dev/null; then
            return 1
        fi
    done
}

network_check() {
    local url
    if ! dns_probe; then
        [[ -n $RESOLVER_FROM && -f $RESOLVER_FROM && -s $RESOLVER_FROM ]] || \
            fail 'Target DNS failed. Supply the installer resolver with --resolver-from.'
        [[ ! -d $TARGET_ROOT/etc/resolv.conf ]] || fail 'Resolver is a directory'
        # Preserve the original file or symlink exactly, on the same filesystem.
        RESOLVER_BACKUP=$(mktemp -d "$TARGET_ROOT/etc/.pandora-resolver.XXXXXX")
        if [[ -e $TARGET_ROOT/etc/resolv.conf || -L $TARGET_ROOT/etc/resolv.conf ]]; then
            RESOLVER_MOVED=1
            mv -- "$TARGET_ROOT/etc/resolv.conf" "$RESOLVER_BACKUP/original"
        fi
        install -m 0644 -- "$RESOLVER_FROM" "$RESOLVER_BACKUP/replacement"
        mv -- "$RESOLVER_BACKUP/replacement" "$TARGET_ROOT/etc/resolv.conf"
        RESOLVER_INSTALLED=1
        target restorecon /etc/resolv.conf
        dns_probe || fail 'DNS still fails with the supplied installer resolver'
    fi
    for url in \
        'https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/x86_64/os/repodata/repomd.xml' \
        'https://download.copr.fedorainfracloud.org/results/avengemedia/dms/pubkey.gpg' \
        'https://dl.flathub.org/repo/flathub.flatpakrepo'; do
        target curl --fail --silent --show-error --head --location \
            --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 30 \
            --retry 1 --retry-max-time 60 "$url" > /dev/null
    done
}

initialize "$@"

# Install the package lists from Fedora and the authenticated third-party sources.
network_check
check repos
check specs > "$WORK/specs.txt"
mapfile -t specs < "$WORK/specs.txt"
[[ ${#specs[@]} -gt 0 ]] || fail 'Empty package selection'
python3 - "$SOURCE_ROOT/config/sources.lock.json" > "$WORK/repos.txt" <<'PY'
import json, sys
for repo in json.load(open(sys.argv[1]))['desktop']['repositories']:
    print('--repo=' + repo['id'])
PY
mapfile -t repos < "$WORK/repos.txt"
target restorecon -RF /usr/share/pandora-linux/keys /etc/yum.repos.d
target dnf --refresh --repo=fedora --repo=updates "${repos[@]}" \
    --setopt=gpgcheck=True --setopt=sslverify=True --setopt=skip_if_unavailable=False \
    --setopt=retries=2 --setopt=timeout=30 --setopt=install_weak_deps=True \
    install --assumeyes "${specs[@]}"
check manifest
target restorecon -RF /usr/share/pandora-linux

# Require the administrator created interactively by Anaconda.
check packages
check admins
check defaults
remote_url=$(target flatpak remotes --system --columns=name,url | awk '$1 == "flathub" {print $2}')
if [[ -n $remote_url && $remote_url != https://dl.flathub.org/repo/ ]]; then
    fail 'Existing system Flathub has an unexpected URL'
fi
if [[ -z $remote_url ]]; then
    timeout 180 chroot "$TARGET_ROOT" flatpak remote-add --system --from flathub \
        /usr/share/pandora-linux/flathub.flatpakrepo
else
    python3 - "$SOURCE_ROOT/payload/flatpak/flathub.flatpakrepo" > "$WORK/flathub.gpg" <<'PY'
import base64, configparser, sys
config = configparser.ConfigParser(interpolation=None)
config.read(sys.argv[1])
sys.stdout.buffer.write(base64.b64decode(config['Flatpak Repo']['GPGKey'], validate=True))
PY
    timeout 180 chroot "$TARGET_ROOT" flatpak remote-modify --system \
        --gpg-import=- --gpg-verify flathub < "$WORK/flathub.gpg"
fi
target python3 - <<'PY'
import configparser
config = configparser.ConfigParser(interpolation=None)
config.read('/var/lib/flatpak/repo/config')
section = config['remote "flathub"']
assert section['url'] == 'https://dl.flathub.org/repo/'
assert section.getboolean('gpg-verify') and section.getboolean('gpg-verify-summary')
assert not section.getboolean('xa.disable', fallback=False)
PY
for unit in NetworkManager.service firewalld.service sddm.service; do
    systemctl --root "$TARGET_ROOT" enable "$unit"
    systemctl --root "$TARGET_ROOT" is-enabled "$unit"
done
systemctl --root "$TARGET_ROOT" set-default graphical.target
systemctl --root "$TARGET_ROOT" --global preset pipewire.socket pipewire-pulse.socket wireplumber.service
for unit in pipewire.socket pipewire-pulse.socket wireplumber.service; do
    systemctl --root "$TARGET_ROOT" --global is-enabled "$unit"
done
target passwd --lock root
target passwd --status root | awk '$2 != "L" {exit 1} END {if (NR != 1) exit 1}'
check manifest
target restorecon -RF /etc/pandora-linux-release /etc/sddm.conf.d /etc/systemd/system \
    /etc/systemd/user /usr/share/pandora-linux /var/lib/flatpak

# Copy defaults for existing and future users without overwriting personal files.
check packages
check admins
python3 "$SCRIPT_DIR/desktop.py" --target-root "$TARGET_ROOT" --source-root "$SOURCE_ROOT"
printf 'PANDORA_CONFIGURATION_OK\n'
