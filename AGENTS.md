# Pandora Linux

Pandora ist Philipps persönlicher Fedora-Remix zum Teilen und Anpassen. Die Basis bleibt klein: Fedora 44 Everything, Hyprland mit DankMaterialShell/Quickshell, Ghostty und Zsh. README.md beschreibt Build, Installation und Anpassungen für Menschen.

## Zuständigkeiten

- `config/profile.json`: nicht geheime Installationsvorgaben. Fedora 44/x86_64, UEFI und Online-Installation sind derzeit fest unterstützt.
- `config/packages-base.txt`: Anaconda-Basispakete aus dem Fedora-Release-Repository.
- `config/packages-desktop.txt`: zusätzliche DNF-Pakete, einschließlich exakter COPR-Versionspins. Keine Duplikate zwischen den Listen.
- `config/repos/`: Paketquellen mit explizitem `includepkgs`, Signatur- und TLS-Prüfung.
- `config/sources.lock.json`: externe Quellen, öffentliche Schlüsselfingerprints und Hashes. Eigene Paketlisten und Defaults werden beim Build automatisch gehasht.
- `kickstart/pandora-linux.ks.in`: interaktive Installer-Vorlage mit zwei äußeren Post-Installationsphasen.
- `iso.py`: Download-Verifikation, Produktdateiauswahl, Payloadmanifest, Kickstart-Rendering, mkksiso und Medienprüfung. `Makefile` bietet nur die öffentlichen Einstiegspunkte.
- `payload/installer/installer.py`: verifizierten ISO-Payload auf das explizite Ziel kopieren und konfigurieren.
- `payload/installer/configure.sh`: Pakete installieren, Flathub einrichten und System-/Desktopvorgaben anwenden.
- `payload/installer/provision.py`: Quellen-, Paket-, Konto- und Zielprüfungen sowie sichere Dateioperationen.
- `payload/installer/desktop.py`: Oh My Zsh installieren, Systemdateien und Benutzerdefaults übernehmen.
- `payload/installer/storage.py`: reale LUKS2-/Btrfs-Mountbeziehungen ausschließlich lesend prüfen.
- `payload/installer/manifest.py`: Payload-Inventar, Hashes und normalisierte Dateimodi.
- `payload/files/`: Zielsystempfade. `etc/skel/` wird zusätzlich auf bestehende Installer-Benutzer angewendet; vorhandene persönliche Dateien bleiben erhalten.
- `payload/flatpak/` und `payload/vendor/`: geprüfte Drittanbieterdefinitionen und gebündelte Quellen samt Lizenz.

## Erweiterungen

Ändere die zuständige Paketliste oder Konfigurationsdatei direkt. Neue normale Systemdateien und Skel-Defaults werden aus `payload/files/` automatisch aufgenommen; eigene Systemdateien bevorzugt in `conf.d` ablegen. Ausführbare Systemdateien mit Executable-Bit versionieren. Kein separates Generierungs- oder VM-Orchestrierungssystem hinzufügen.

Neue Drittquellen benötigen eine `.repo`-Datei, einen Source-Lock-Eintrag mit eindeutiger `pandora-…`-ID, einen unabhängig geprüften öffentlichen Schlüssel und eine begrenzte Paketauswahl. Versionspins stehen in der Desktop-Paketliste. Änderungen an Schlüsselmaterial, Oh-My-Zsh-Archiv oder Flathub-Definition benötigen aktualisierte, verifizierte Hashes. Bei einem neuen Oh-My-Zsh-Commit auch den Pfad in `.zshrc` aktualisieren.

Die Hyprland-Konfiguration ist Lua für den gepinnten Release. DMS startet ausschließlich über Hyprland/UWSM; keine konkurrierende globale oder benutzerspezifische DMS-Serviceaktivierung. Systemkonfiguration darf bestehende abweichende Dateien nicht stillschweigend überschreiben.

Halte Kommentare auf Gründe und Sicherheitsgrenzen beschränkt. Aktualisiere README.md bei Änderungen an Bedienung oder Build. Keine zusätzlichen Ablaufberichte oder Hilfsskriptsammlungen anlegen.

## Sicherheitsgrenzen

- Datenträgerauswahl, Partitionierung, Benutzer, Passwörter und LUKS-Passphrase bleiben interaktiv. Keine automatischen Löschbefehle, festen Konten oder eingebetteten Zugangsdaten.
- `/` und `/home` sind getrennte, nicht ineinander verschachtelte Subvolumes auf genau einem LUKS2-verschlüsselten Btrfs-Gerät. EFI und `/boot` bleiben unverschlüsselt. Dieses Layout allein bietet keinen Snapshot-Rollback.
- Beide Kickstart-Phasen laufen mit `--nochroot`, damit Speicherprüfungen die tatsächlichen Mounts sehen. Zielbefehle erst nach Prüfung explizit chrooten. Das Ziel bleibt `/mnt/sysroot`, die ISO-Quelle `/run/install/repo/payload`.
- Sämtliche Payload-Hashes werden vor dessen Python-Imports geprüft. `PYTHONDONTWRITEBYTECODE=1` verhindert zusätzliche Dateien im geprüften Baum.
- SELinux im Ziel enforcing, Firewall aktiv, Root gesperrt und gewöhnliches passwortgeschütztes sudo für den interaktiv angelegten Administrator. Ein permissiver Anaconda-Kernel ist nur bei den exakt geprüften ISO-/Zielmounts zulässig.
- RPM-Signaturen, gepinnte Schlüssel und TLS prüfen. Keine ungeprüften Internet-Installationsskripte ausführen. Dienste während der Installation nur aktivieren, nicht starten. Temporäre DNS-Anpassungen müssen den ursprünglichen Resolver wiederherstellen.
- Keine Host-Dotfiles, SSH-Zugänge, privaten Schlüssel, VM-Datenträger oder unbereinigten Installer-Logs ins Repository oder ISO übernehmen.

## Prüfung und Arbeitsumgebung

`make check` prüft Produktdaten, Archiv-/Payloadintegrität und Syntax. ShellCheck und F44-ksvalidator werden ausgeführt, wenn vorhanden; ein fehlendes Werkzeug wird sichtbar gemeldet. `make iso` verlangt alle Build-Werkzeuge, Fedora 44/x86_64 und einen normalen Benutzer mit sudo. Nur mkksiso und seine Ausgabeeigentümerkorrektur werden privilegiert ausgeführt.

Nach Codeänderungen `make check` ausführen. Änderungen am Build zusätzlich mit einem echten Fedora-Build prüfen; Änderungen an der Installation in einer frischen UEFI-VM mit eigenem verschlüsselten Testdatenträger. Durchgeführte Prüfungen und Einschränkungen wahrheitsgemäß nennen. Medienintegrität ist kein Boot- oder Hardwaretest. Sicherheitsprüfungen bei Fehlern nicht lockern.

Host-Pakete, Host-Konfiguration und vorhandene VM-Disks nur mit ausdrücklicher Freigabe ändern. Eine vorhandene Build-VM samt Disk/NVRAM wiederverwenden; für Neuinstallationstests ausschließlich ausdrücklich als Wegwerf-Testmaterial gekennzeichnete Disks/NVRAM erneuern. Niemals Build-Datenträger löschen. Lokalen Entwicklungszugang außerhalb des Repositorys halten.

`cache/`, `build/` und `artifacts/` sind ignorierte, generierte Verzeichnisse. Keine Byte-identische Reproduzierbarkeit oder allgemeine Secure-Boot-/Hardwarekompatibilität behaupten. Für eine andere Fedora-Version müssen Quellen, Pins und Installerprüfungen gemeinsam angepasst und getestet werden.
