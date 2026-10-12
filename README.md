# Pandora Linux

Philipp's Adaptive Native Desktop, built on Fedora.

My personal Fedora remix. Pandora combines a lightweight Fedora base with Hyprland and DankMaterialShell, my terminal setup, and a few carefully chosen defaults. This repository describes the system and builds a custom installation ISO. Use it as a starting point for your own setup.

![Pandora Linux desktop](assets/pandora-desktop.png)

## What's included

- Fedora 44 Everything for x86_64 with UEFI
- Hyprland with DankMaterialShell and Quickshell, logging in through SDDM and UWSM
- A Pandora SDDM login theme with the desktop wallpaper, blue accents, and German controls
- Ghostty, Zsh, and a pinned version of Oh My Zsh
- NetworkManager with Wi-Fi support, PipeWire, and WirePlumber
- Flatpak with Flathub configured, without preinstalled Flatpak apps
- Screenshot area selection with Grim and Slurp, including PNG clipboard support
- German locale, German keyboard layout, and the Europe/Berlin time zone
- LUKS2 and Btrfs with separate subvolumes for `/` and `/home`

The ISO is an online installer, not a live desktop. Installation requires internet access to Fedora, the COPR repositories in use, and Flathub. You choose the target disk, encryption passphrase, and user account in the installer.

This setup has been manually tested for my own use. Before installing it on your computer, try it in a VM and back up your data. Secure Boot is not guaranteed; Snapper and snapshot rollback are not configured. Pandora is a personal Fedora remix, not an official Fedora product.

## Repository

```text
.
├── README.md                      Usage, build, and customization
├── AGENTS.md                      Development guidelines
├── Makefile                       make check, make iso, make iso-docker, make clean
├── Dockerfile                     Fedora 44 build tools, without product files
├── iso.py                         Source verification, payload, and ISO build
├── config/
│   ├── profile.json               Language, keyboard, time zone, and ISO name
│   ├── packages-base.txt          Anaconda base packages
│   ├── packages-desktop.txt       Desktop packages and version pins
│   ├── repos/                     Restricted COPR package repositories
│   └── sources.lock.json          Sources, public keys, and hashes
├── kickstart/
│   └── pandora-linux.ks.in         Fedora installer template
└── payload/
    ├── files/                     Files mapped to their target-system paths
    ├── installer/                 Target-system installation and verification
    ├── flatpak/                   Flathub definition and public key
    └── vendor/                    Oh My Zsh archive and license
```

`cache/`, `build/`, and `artifacts/` are generated during the build and are not tracked by Git. The ISO includes only the product files from `config/` and `payload/`, not the rest of the repository.

## Build the ISO

ISO builds run on Fedora 44/x86_64 as a regular user and require at least 20 GiB of free space. Use a Fedora machine or the Docker builder on another Linux host. The Fedora release and non-root checks apply in both cases.

### Native Fedora build

Use a Fedora 44 VM or Fedora 44 x86_64 machine with a regular user account that can use sudo. Install the build tools once:

```bash
sudo dnf install lorax xorriso isomd5sum pykickstart ShellCheck \
  make python3 curl git gnupg2 mtools dnf5 dnf5-plugins qt6-qtdeclarative-devel
```

From the cloned project directory:

```bash
make check
make iso
```

### Docker build on Linux

On a Linux/x86_64 host with a running local, rootful Docker daemon, Python 3, Make, and `/dev/loop-control`, run as your normal user:

```bash
make iso-docker
```

The first run builds a tools-only Fedora 44 image from the digest pinned in `Dockerfile`. Later runs reuse Docker's image cache. The container runs the same `make iso` with your host UID/GID, so generated files remain yours. The repository is mounted read-only; only `cache/`, `build/`, and `artifacts/` are writable. Host packages, home directories, and the Docker socket are not mounted or modified.

The EFI-image step needs `SYS_ADMIN` and one unused loop device. A short-lived helper with no network or repository mounts selects that device through `/dev/loop-control`. The build container can access only the selected block device and has no loop-control device or physical disks. Only `mkksiso` and its output ownership correction use sudo; the container's initial device-node setup also runs as root. Newly created loop devices are removed after the build if idle; existing devices are not removed, and a busy device is never force-detached.

This uses neither `--privileged` nor disabled integrity checks. Mount capabilities are still powerful, and Docker access itself grants substantial host privileges: build trusted code only. Rootless Docker, user namespace remapping, and remote Docker daemons are not supported. A Fedora VM provides stronger isolation.

### Verification and outputs

`make iso` downloads the original Everything netinstall ISO and Fedora's signed CHECKSUM file. Existing downloads are also re-verified against the pinned Fedora signing key, file size, and SHA256. The build then combines the package lists and local files, renders the Kickstart template, and creates the ISO with `mkksiso`. Only `mkksiso` and the ownership correction for its output require sudo.

`make check` also runs the SDDM theme's Qt Quick tests when Qt 6 `qmltestrunner` is available. They use mock login and power actions with offscreen software rendering; they never authenticate or change the host. Missing ShellCheck, F44 ksvalidator, or Qt test tools are reported as skipped. The Docker builder includes all three.

Before publishing, the build checks the embedded payload, Kickstart file, UEFI boot parameters, both EFI images, and the media checksum. These checks do not replace an installation test.

The build outputs are:

```text
artifacts/pandora-linux-f44-x86_64.iso
artifacts/pandora-linux-f44-x86_64.iso.sha256
artifacts/pandora-linux-f44-x86_64.iso.manifest.json
```

You can verify the hash separately:

```bash
(cd artifacts && sha256sum --check pandora-linux-f44-x86_64.iso.sha256)
```

After making changes, run `make iso` again. A successful build replaces the previous output; a failure before publication leaves the previous ISO in place. `make clean` removes build outputs and generated Pandora ISOs but keeps the download cache. If a cache entry is corrupted, remove that specific file under `cache/base-iso/` and build again. Integrity-check failures are never bypassed automatically.

The manifests record inputs and tool versions; they are not independent signatures. Fedora packages come from the current release and update repositories, so byte-identical rebuilds are not guaranteed. Pinned COPR versions must still be available when you install.

## Install

Write the finished ISO to a USB drive with an image-writing tool, or attach it to a UEFI VM. Check the target carefully: writing the image overwrites its data.

1. Boot from the ISO in UEFI mode and connect to the network.
2. In the installation destination screen, select only the intended disk and open custom partitioning.
3. Choose Btrfs and explicitly enable encryption. Check the proposed layout: `/boot/efi` and `/boot` must remain unencrypted; `/` and `/home` must be separate subvolumes in the same LUKS2-encrypted Btrfs filesystem. The installation script rejects any other layout.
4. Set your own LUKS passphrase. Leave the root account disabled and create a user with administrator privileges (sudo requiring a password).
5. Complete the installation, remove the installation media, and reboot. After unlocking the disk, choose the Hyprland/UWSM session in SDDM.

Keep your passphrase safe. This repository contains no accounts, passwords, or recovery keys. SELinux remains enforcing on the installed system, the firewall remains enabled, and sudo requires a password.

Installation logs are stored under `/var/log/pandora-linux/`. An early copy failure is logged by the installer at `/tmp/pandora-payload-copy.log`. Check logs for personal information before publishing them.

## Usage

`Super` is usually the Windows key.

| Shortcut | Action |
| --- | --- |
| Super + Enter | Open Ghostty |
| Super + Space | Open DMS app launcher |
| Super + Q | Close the active window |
| Super + V | Toggle floating mode |
| Super + Arrow key | Change window focus |
| Super + 1 through 0 | Select workspace 1 through 10 |
| Super + Shift + 1 through 0 | Move the window to a workspace |
| Super + Shift + S | Select a screenshot area |
| Super + Shift + E | Open the logout, restart, and shutdown menu |

Screenshots are saved under `~/.local/share/pandora-linux/screenshots/` and copied to the clipboard as PNGs. Pressing Escape to cancel does not change the clipboard.

## Customize

### For the next ISO

Edit the files in the repository and rebuild. `payload/files/` maps to paths on the installed system:

| Repository file | Purpose |
| --- | --- |
| `config/profile.json` | Language, keyboard layout, time zone, and output name |
| `payload/files/etc/skel/.config/hypr/hyprland.lua` | Monitors, layout, shortcuts, and DMS startup |
| `payload/files/etc/skel/.config/ghostty/config` | Terminal settings |
| `payload/files/etc/skel/.zshrc` | Zsh theme and Oh My Zsh plugins |
| `payload/files/etc/skel/.config/DankMaterialShell/settings.json` | DMS theme, panel, widgets, and workspace settings |
| `payload/files/etc/skel/.local/state/DankMaterialShell/session.json` | DMS wallpaper path and weather location |
| `payload/files/usr/share/backgrounds/pandora/wallpaper.png` | Desktop and SDDM wallpaper |
| `payload/files/usr/share/sddm/themes/pandora/` | SDDM login layout, colors, and background path |
| `payload/files/etc/sddm.conf.d/30-pandora-theme.conf` | Select the Pandora SDDM theme |

Hyprland is configured in Lua here. Examples for an older `hyprland.conf` do not apply to this configuration. DMS is started by Hyprland; do not also enable a DMS autostart service.

Add new user defaults under `payload/files/etc/skel/`. The installer applies them to the account created during installation and to future users. Existing personal files are preserved.

DMS starts with the blue theme, a compact top bar, and weather for Berlin. When importing DMS preferences from another installation, leave out launcher history, notes, cache, and hardware-specific session state.

System configuration can go in paths such as `payload/files/etc/NetworkManager/conf.d/`. Prefer your own `conf.d` files where possible. For safety, an existing system file that differs from the provided one is not overwritten. Executable system files need the executable bit (`chmod +x`); user configuration files are installed with mode 0644. SELinux labels are restored.

### Preview the login theme

SDDM uses its own Qt 6 theme, separate from DMS and the lock screen. The theme has editable usernames, session and keyboard-layout selectors, a Caps Lock warning, optional password visibility, and restart/shutdown controls. It remembers SDDM's last user and session; choose Hyprland/UWSM on the first login. The form scrolls on short screens. Authentication still goes through SDDM/PAM; automatic login remains disabled.

On a Fedora 44 system with SDDM installed, preview the installed theme without changing your current login session:

```bash
sddm-greeter-qt6 --test-mode --theme /usr/share/sddm/themes/pandora
```

Login and power actions have no effect in this test mode. To preview repository edits, pass `"$PWD/payload/files/usr/share/sddm/themes/pandora"` as the theme path. The configured wallpaper must be readable at the path in `theme.conf`; it must not live in a private home directory. If that file is missing, the theme uses a plain dark background.

Changes take effect on the next SDDM start. Do not restart SDDM from an active desktop session: that ends the session. To stop using the theme, remove only `/etc/sddm.conf.d/30-pandora-theme.conf`, leaving the separate interactive-login settings intact. Test new theme changes in a VM before using them for your only login path.

### On an installed system

Edit your own files under `~/.config/hypr/`, `~/.config/ghostty/`, and `~/.zshrc`. Reload Hyprland with `hyprctl reload`; for session startup changes, log out and back in. Adjust the panel, theme, widgets, and wallpaper in DMS.

Repository changes do not modify an existing installation. Apply any settings you want there deliberately; the installation scripts are not an update tool for a running system.

## Install more packages

### Include them in the ISO

Add Fedora package names, one per line:

- `config/packages-base.txt`: Packages Anaconda installs from the Fedora release repository. Keep `@core`.
- `config/packages-desktop.txt`: Additional packages installed later with DNF from Fedora and its updates. For example, you can add `htop` here.

Lines beginning with `#` are comments, and blank lines are ignored. Do not list a package in both files. You do not need to update hashes manually for changes to these lists.

COPR desktop packages are pinned as `name-epoch:version-release.arch`. When updating one, change the pin in `packages-desktop.txt` and test the new version in a fresh installation. To add packages from another COPR, add their names to `includepkgs` in the appropriate file under `config/repos/`. This restriction prevents the third-party repository from replacing arbitrary Fedora packages.

A new package repository needs its own `.repo` file, an entry under `desktop.repositories` in `config/sources.lock.json`, and its public key under `payload/files/usr/share/pandora-linux/keys/`. Verify the key fingerprint independently with the provider and record its URL, fingerprint, and SHA256 in the source lock. RPM signature and TLS verification must remain enabled. COPR is a third-party source, not an official Fedora repository; COPR metadata is not separately signed, but RPMs are signature-checked.

Flathub is already configured. To preinstall Flatpak apps, add explicit `flatpak install --system --noninteractive flathub APP-ID` commands to `payload/installer/configure.sh` after the remote is configured. These apps are also downloaded online.

### On the running system

```bash
sudo dnf install htop
flatpak install --system flathub org.mozilla.firefox
```

The Flathub remote is available system-wide. With `--system`, Flatpak installs are available to all users and may require administrator authorization. These commands change only the installed machine, not your ISO package lists.

## Sources and licenses

Fedora provides the base system and installer. Hyprland packages come from [lionheartp/Hyprland](https://copr.fedorainfracloud.org/coprs/lionheartp/Hyprland/), DankMaterialShell from [avengemedia/dms](https://copr.fedorainfracloud.org/coprs/avengemedia/dms/), and Quickshell and other desktop packages from [avengemedia/danklinux](https://copr.fedorainfracloud.org/coprs/avengemedia/danklinux/).

The specific sources and integrity data are listed in [`config/sources.lock.json`](config/sources.lock.json). Oh My Zsh is included as a pinned archive with its MIT license under `payload/vendor/`. The respective upstream licenses apply to other third-party software. No explicit license has yet been set for the project's own files.
