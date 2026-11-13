#!/usr/bin/env python3
"""Phone backup without root (Moosa, 2026-11-11: "back up my phone and all its apps along with the config ... every
other day"). Runs from the laptop over wireless adb. What no-root adb CAN get:
  - every user-installed app's APK (incl. split APKs) + the app list with versions, so all apps can be reinstalled
  - phone settings (settings list system/secure/global) and the home-screen/app permissions list
  - shared storage: DCIM, Pictures, Documents, Music, Movies, Download, Android/media (WhatsApp media etc.)
What it CAN'T: private app data (logins, chats inside apps) - Android blocks that without root; use each app's own
backup (WhatsApp → Google Drive, etc.). Incremental: a file is pulled only if new or its size/mtime changed.
Usage: phone-backup.py [--dry-run]   Output: ~/Backups/phone/<serial>/{apks,settings,storage}, log in last-run.json
"""
import json, os, subprocess, sys, time

DEV = os.environ.get("PHONE_ADB", "192.168.10.16:5555")
SERIAL = "RZCYA1H6KVJ"
ROOT = os.path.expanduser("~/Backups/phone")
DIRS = ["DCIM", "Pictures", "Documents", "Music", "Movies", "Download", "Android/media"]
DRY = "--dry-run" in sys.argv


def adb(*a, t=600) -> str:
    r = subprocess.run(["adb", "-s", DEV, *a], capture_output=True, timeout=t)
    return r.stdout.decode("utf-8", "replace")


def find_phone():
    """The phone's IP changes (DHCP): find it by its adb mDNS name instead of a fixed address."""
    global DEV
    try:
        out = subprocess.run(["adb", "mdns", "services"], capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            if SERIAL in line and "_adb._tcp" in line: DEV = line.split()[-1]; break
    except Exception: pass
    subprocess.run(["adb", "connect", DEV], capture_output=True, timeout=20)


def main():
    find_phone()
    serial = adb("shell", "getprop", "ro.serialno").strip()
    if not serial: print("phone not reachable over adb at", DEV); return 2
    base = f"{ROOT}/{serial}"; os.makedirs(f"{base}/apks", exist_ok=True); os.makedirs(f"{base}/settings", exist_ok=True)
    log = {"started": time.strftime("%F %T"), "apps": 0, "apks_new": 0, "files_new": 0, "bytes_new": 0, "errors": []}

    # 1) apps: list with versions + every APK split, skipped when that version is already saved
    pk = [l.split("package:", 1)[1].strip() for l in adb("shell", "pm", "list", "packages", "-3", "--user", "0").splitlines() if l.startswith("package:")]
    apps = {}
    for p in pk:
        ver = next((l.split("=", 1)[1] for l in adb("shell", "dumpsys", "package", p).splitlines() if "versionName=" in l), "?").strip()
        apps[p] = ver; d = f"{base}/apks/{p}/{ver}".replace(" ", "_")
        if os.path.isdir(d) and os.listdir(d): continue
        paths = [l.split("package:", 1)[1].strip() for l in adb("shell", "pm", "path", "--user", "0", p).splitlines() if l.startswith("package:")]
        if DRY: log["apks_new"] += 1; continue
        os.makedirs(d, exist_ok=True)
        for ap in paths:
            r = subprocess.run(["adb", "-s", DEV, "pull", ap, f"{d}/{os.path.basename(ap)}"], capture_output=True, timeout=900)
            if r.returncode: log["errors"].append(f"{p}: {r.stderr.decode()[:120]}")
        log["apks_new"] += 1
    log["apps"] = len(apps)
    if not DRY: json.dump(apps, open(f"{base}/apps.json", "w"), indent=1)

    # 2) settings + permissions ("config for each")
    if not DRY:
        for ns in ("system", "secure", "global"):
            open(f"{base}/settings/{ns}.txt", "w").write(adb("shell", "settings", "list", ns))
        open(f"{base}/settings/permissions.txt", "w").write(adb("shell", "dumpsys", "package", "--checkin", t=300))
        open(f"{base}/settings/appops.txt", "w").write(adb("shell", "appops", "query-op", "--user", "0", "RUN_IN_BACKGROUND", "allow", t=120))

    # 3) shared storage, incremental by size+mtime
    for top in DIRS:
        out = adb("shell", f"find /sdcard/{top} -type f -exec stat -c '%s %Y %n' {{}} + 2>/dev/null", t=900)
        for line in out.splitlines():
            try: size, mt, path = line.split(" ", 2)
            except ValueError: continue
            dst = f"{base}/storage/{path[len('/sdcard/'):]}"
            if os.path.exists(dst) and os.path.getsize(dst) == int(size) and int(os.path.getmtime(dst)) == int(mt): continue
            log["files_new"] += 1; log["bytes_new"] += int(size)
            if DRY: continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            r = subprocess.run(["adb", "-s", DEV, "pull", "-a", path, dst], capture_output=True, timeout=1800)
            if r.returncode: log["errors"].append(f"{path}: {r.stderr.decode()[:120]}")
    log["finished"] = time.strftime("%F %T"); log["dry_run"] = DRY
    if not DRY: json.dump(log, open(f"{base}/last-run.json", "w"), indent=1)
    print(json.dumps({k: (v[:5] if k == "errors" else v) for k, v in log.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
