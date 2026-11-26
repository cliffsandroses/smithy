#!/usr/bin/env python3
"""Claim the rest of Oracle's Always Free tier (Moosa 2026-11-26: "Get all resources used from oracle that are in the free teir").
Read-only first, then creates only what's missing and free: a 2nd micro VM (free-micro-2, 50 GB boot) and the 2 Always Free
Autonomous Databases (20 GB each). The A1 VM is left to oraclegrab (it sizes its boot disk from what's left of the 200 GB).
ADB admin password: generated, kept in ~/.config/oracle/adb-admin.txt (0600), never printed."""
import os, secrets, string, sys
sys.path.insert(0, os.path.expanduser("~/Projects/smithy/forge/tools/netwatch"))
import oraclegrab as g

comp = g.tenancy()
vms = [i for i in g.oci("compute", "instance", "list", "-c", comp, "--all") if i["lifecycle-state"] != "TERMINATED"]
micros = [i for i in vms if i["shape"] == "VM.Standard.E2.1.Micro"]
print("micro VMs:", [i["display-name"] for i in micros])
if len(micros) < 2:
    imgs = g.oci("compute", "image", "list", "-c", comp, "--operating-system", "Canonical Ubuntu", "--shape", "VM.Standard.E2.1.Micro", "--sort-by", "TIMECREATED", "--all")
    img = next(i for i in imgs if "Minimal" in i["display-name"] or "24.04" in i["display-name"])
    for ad in [a["name"] for a in g.oci("iam", "availability-domain", "list", "-c", comp)]:
        try:
            v = g.oci("compute", "instance", "launch", "-c", comp, "--availability-domain", ad, "--display-name", "free-micro-2",
                      "--shape", "VM.Standard.E2.1.Micro", "--image-id", img["id"], "--boot-volume-size-in-gbs", "50", "--subnet-id", g.SUBNET,
                      "--assign-public-ip", "true", "--ssh-authorized-keys-file", g.KEYS)
            print("LAUNCHED free-micro-2", v["lifecycle-state"], ad); break
        except g.OciError as e:
            print("micro failed in", ad, e.kind, str(e)[:160])

pw_file = os.path.expanduser("~/.config/oracle/adb-admin.txt")
if not os.path.exists(pw_file):
    os.makedirs(os.path.dirname(pw_file), mode=0o700, exist_ok=True)
    a = string.ascii_letters + string.digits
    pw = "".join(secrets.choice(a) for _ in range(14)) + "Aa1#"   # ADB rule: 12-30 chars, upper, lower, digit, special
    fd = os.open(pw_file, os.O_WRONLY | os.O_CREAT, 0o600); os.write(fd, pw.encode()); os.close(fd)
pw = open(pw_file).read().strip()
adbs = [d for d in g.oci("db", "autonomous-database", "list", "-c", comp) if d["lifecycle-state"] not in ("TERMINATED", "TERMINATING")]
print("autonomous DBs:", [d["display-name"] for d in adbs])
for name in ["homelab1", "homelab2"]:
    if any(d["db-name"] == name for d in adbs) or len(adbs) >= 2: continue
    try:
        d = g.oci("db", "autonomous-database", "create", "-c", comp, "--db-name", name, "--display-name", name, "--is-free-tier", "true",
                  "--admin-password", pw, "--db-workload", "OLTP", "--compute-model", "ECPU", "--compute-count", "2",
                  "--data-storage-size-in-gbs", "20")
        print("CREATED ADB", name, d["lifecycle-state"]); adbs.append(d)
    except g.OciError as e:
        print("ADB failed", name, e.kind, str(e)[:200])
