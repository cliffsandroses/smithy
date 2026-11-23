#!/bin/bash
# Nightly PC backup: refresh package lists and game saves, then snapshot ~ with Kopia.
# Run by pc-backup.timer. Exclusions live in ~/.kopiaignore. See ../RESTORE.md.
#
# 2026-10-21: the Kopia repository on the homelab was created on 29 Sept and never received a
# single snapshot, and nothing noticed until the laptop's drive was gone. So this script now
# refuses to report success unless a snapshot really landed, and the package lists also go
# straight to the homelab's data disk so they survive even when Kopia is broken.
set -euo pipefail

out=~/Backups/pc
COPY_TO="${PC_BACKUP_COPY:-moosa@192.168.10.20:/mnt/data/Backups/laptop-pc/}"   # empty = skip
KOPIA="${KOPIA_BIN:-$(command -v kopia || echo /opt/KopiaUI/resources/server/kopia)}"
mkdir -p "$out"

if command -v pacman >/dev/null; then
    pacman -Qqen > "$out/pkglist-native.txt"
    pacman -Qqem > "$out/pkglist-aur.txt"
fi
command -v flatpak >/dev/null && flatpak list --app --columns=application > "$out/flatpaks.txt"
# System settings changed by hand (2026-10-26: zram/oomd, phone approval in PAM, sysctl): the readable ones, so a
# reinstall gets them back. Secrets in /etc (shadow, ssh host keys) are root-only and stay out.
tar -czf "$out/etc-config.tar.gz" --ignore-failed-read -C / \
    etc/pam.d etc/systemd/zram-generator.conf etc/sysctl.d etc/fstab etc/pacman.conf etc/mkinitcpio.conf \
    etc/udev/rules.d etc/X11/xorg.conf.d etc/modprobe.d etc/hostname etc/locale.conf etc/vconsole.conf 2>/dev/null || true
ls /usr/local/bin > "$out/usr-local-bin.txt" 2>/dev/null || true
command -v ludusavi >/dev/null && ludusavi backup --force >/dev/null
date -Is > "$out/last-run.txt"

# A second copy of the lists, independent of Kopia. Best-effort: the laptop may be away from home.
if [ -n "$COPY_TO" ]; then
    rsync -a --timeout=60 -e "ssh -o BatchMode=yes -o ConnectTimeout=10" "$out/" "$COPY_TO" \
        || echo "warning: could not copy package lists to $COPY_TO" >&2
fi

"$KOPIA" repository status >/dev/null 2>&1 \
    || { echo "Kopia is not connected to its repository: see RESTORE.md 1.6" >&2; exit 1; }
"$KOPIA" snapshot create ~

# Prove it: the newest snapshot of ~ must be from this run.
newest=$("$KOPIA" snapshot list ~ --json 2>/dev/null | python3 -c '
import json, sys, datetime
s = json.load(sys.stdin)
print(max(x["startTime"] for x in s) if s else "")')
[ -n "$newest" ] || { echo "Kopia made no snapshot of ~" >&2; exit 1; }
age=$(( $(date +%s) - $(date -d "$newest" +%s) ))
[ "$age" -lt 3600 ] || { echo "Newest Kopia snapshot is $((age / 3600)) h old, not from this run" >&2; exit 1; }
echo "Kopia snapshot of ~ taken at $newest"
