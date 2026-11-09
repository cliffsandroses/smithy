"""Grab ONE Oracle Always Free Ampere VM and grow it to the free maximum: 4 OCPU / 24 GB RAM / 200 GB boot volume.
Moosa, 2026-11-03: "How to do this automatically"; 2026-11-09: "Set up an automation for 4, 2 and 1 cores ... make it
limit aware so the tries are not wasted and check oracles official limits for requests."; 2026-11-09: every error class
handled with backoff and retry tracking; prefer one VM grown to the free max.

Runs from netwatch (cron); does nothing until ~/.oci/config exists. Each round:
  1. Read the A1 instances, boot + block volumes, and (once a day) `oci limits value list` for compute/block-storage.
     Caps used = min(Always Free 4 OCPU / 24 GB / 200 GB, the tenancy's limit values). This tenancy's own A1 limits are
     higher (16 cores / 96 GB regional), so the free numbers are the hard ceiling and nothing can bill.
  2. No A1 VM yet -> launch 4/24, else 2/12, else 1/6 (6 GB per OCPU); boot volume = 200 GB minus every existing
     boot/block volume (never launches below 50 GB, Oracle's minimum). First success ends the round.
  3. A VM below 4 OCPU -> `instance update --shape-config` to 4/24, then 3/18, then 2/12 (only larger than now).
     Resizing a running Flex instance reboots it (docs.oracle.com/iaas/Content/Compute/Tasks/resizinginstances.htm);
     Moosa accepted that - a phone message says when it happens.
  4. Free storage left under 200 GB -> `bv boot-volume update --size-in-gbs` grows the boot volume online
     (the partition inside the VM still has to be grown).
  5. VM at 4/24 with 200 GB total -> done, grabber stops.

Errors (Oracle docs: usingapi.htm "Request Throttling" - no number published, exponential back-off from a few seconds to
max 60 s on 429; apierrors.htm - 429/500/503 retryable, LimitExceeded not):
  - 429 TooManyRequests     -> stop the round, back off 60 s x2 per repeat (max 30 min), resumes by itself.
  - Out of host capacity    -> normal; try the next smaller size now, next round at the normal 5 min cadence.
  - 5xx / timeout / network -> stop the round, back off 60 s x2 (max 15 min).
  - LimitExceeded / Quota   -> that step is skipped until the account's VMs change.
  - auth / config (401/403, NotAuthorizedOrNotFound, bad key/config) -> one phone message, retry hourly, never stuck.
  - anything else           -> recorded, retried at normal cadence.
State: ~/.local/share/netwatch/oraclegrab.json - per step ("launch 4", "grow 3", "grow boot"): tries, last error, last
try; plus next_attempt, backoff, error_class. `python3 oraclegrab.py` = one round now.
"""
import json, os, re, subprocess, time

H = os.path.expanduser("~"); CFG = f"{H}/.oci/config"; STATE = f"{H}/.local/share/netwatch/oraclegrab.json"
OCI = f"{H}/.local/bin/oci"; EVERY = 300; AUTH_EVERY = 3600; LIMITS_EVERY = 86400
FREE_OCPU, FREE_MEM, FREE_GB, MIN_BOOT = 4, 24, 200, 50
LAUNCH = (4, 2, 1); GROW = (4, 3, 2); GB_PER_OCPU = 6; SHAPE = "VM.Standard.A1.Flex"
AD = "YTeh:AP-HYDERABAD-1-AD-1"
SUBNET = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaateqymgryehyqktzgdlneu4lck5llzluqu2f5x6hc57mxlx3tyioa"   # public subnet-oracle-net
IMAGE = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaamvzbsljz2ja6iegrtbe2hak37xuahdhb6uylqnw37iyq7zgvrjqq"     # same image as Moosa's stacks
KEYS = f"{H}/.local/share/netwatch/oraclegrab.pub"                                                     # public keys from the stack's Terraform
ENV = {**os.environ, "OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING": "True"}
GONE = ("TERMINATED", "TERMINATING")


class OciError(Exception):
    def __init__(self, kind, msg): super().__init__(msg); self.kind = kind


def classify(status, code, msg):
    t = f"{code} {msg}".lower()
    if status == 429 or "toomanyrequests" in t or "too many requests" in t: return "throttle"
    if "out of host capacity" in t or "insufficient capacity" in t: return "capacity"
    if re.search(r"limitexceeded|quotaexceeded|exceeds? .*limit|service limit", t): return "limit"
    if status in (401, 403) or "notauthorizedornotfound" in t or re.search(
            r"notauthenticated|config file|key_file|private key|invalidkey|fingerprint|invalidconfig", t): return "auth"
    if (status or 0) >= 500 or re.search(r"timed out|timeout|connection|network|name resolution|temporarily", t): return "transient"
    return "other"


def oci(*a):
    try: r = subprocess.run([OCI, *a, "--output", "json"], capture_output=True, text=True, timeout=180, env=ENV)
    except subprocess.TimeoutExpired: raise OciError("transient", "oci timed out after 180 s")
    except OSError as e: raise OciError("auth", f"oci not runnable: {e}")
    if r.returncode:
        out = (r.stderr or r.stdout).strip(); m = re.search(r'"message":\s*"([^"]+)"', out)
        c = re.search(r'"code":\s*"([^"]+)"', out); s = re.search(r'"status":\s*(\d+)', out)
        code = c.group(1) if c else ""; msg = (m.group(1) if m else out.splitlines()[-1] if out else "oci failed")[:200]
        raise OciError(classify(int(s.group(1)) if s else None, code, msg), f"{code}: {msg}" if code else msg)
    return json.loads(r.stdout).get("data", []) if r.stdout.strip() else []


def tenancy():
    for l in open(CFG):
        if l.strip().startswith("tenancy"): return l.split("=", 1)[1].strip()
    raise OciError("auth", "no tenancy in ~/.oci/config")


def caps(st, comp, now):
    """min(Always Free, tenancy limit values); refreshed daily. The free numbers stay the ceiling either way."""
    lim = st.get("limits") or {}
    if now - lim.get("at", 0) > LIMITS_EVERY:
        def vals(svc): return {x["name"]: x["value"] for x in oci("limits", "value", "list", "--service-name", svc, "-c", comp, "--all")
                               if x.get("availability-domain") in (None, AD)}
        v, b = vals("compute"), vals("block-storage")
        lim = {"at": now, "a1_ocpu": min(v.get("standard-a1-core-regional-count", FREE_OCPU), v.get("standard-a1-core-count", FREE_OCPU)),
               "a1_mem": min(v.get("standard-a1-memory-regional-count", FREE_MEM), v.get("standard-a1-memory-count", FREE_MEM)),
               "free_gb": min(b.get("total-free-storage-gb-regional", FREE_GB), b.get("total-free-storage-gb", FREE_GB))}
        st["limits"] = lim
    return min(FREE_OCPU, lim["a1_ocpu"]), min(FREE_MEM, lim["a1_mem"]), min(FREE_GB, lim["free_gb"])


def attempt(st, key, fn):
    """One tracked try: per-step tries / last error / last try time."""
    s = st.setdefault("sizes", {}).setdefault(key, {"tries": 0, "last_error": "", "last_try": ""})
    s["tries"] += 1; s["last_try"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try: r = fn(); s["last_error"] = ""; return r
    except OciError as e: s["last_error"] = f"{e.kind}: {e}"[:160]; raise


def run(force=False, notify=None):
    if not os.path.exists(CFG) or not os.path.exists(OCI) or not os.path.exists(KEYS): return None
    try: st = json.load(open(STATE))
    except (OSError, ValueError): st = {}
    if "sizes" not in st: st = {}                                                       # old format: start clean
    now = time.time()
    if st.get("done") or (not force and now < st.get("next_at", 0)): return None
    st["at"] = now; msg = []; skip = st.setdefault("skip", []); wait = EVERY; kind = ""
    try:
        comp = tenancy(); cap_c, cap_m, cap_gb = caps(st, comp, now)
        vms = [i for i in oci("compute", "instance", "list", "-c", comp, "--all")
               if i["shape"] == SHAPE and i["lifecycle-state"] not in GONE]
        if sorted(i["id"] for i in vms) != st.get("ids"): skip.clear()                  # account changed: re-try every step
        st["ids"] = sorted(i["id"] for i in vms)
        bvs = [v for v in oci("bv", "boot-volume", "list", "-c", comp, "--availability-domain", AD) if v["lifecycle-state"] not in GONE]
        vols = [v for v in oci("bv", "volume", "list", "-c", comp, "--all") if v["lifecycle-state"] not in GONE]
        used_gb = sum(int(v["size-in-gbs"]) for v in bvs + vols); free_gb = cap_gb - used_gb
        st["storage"] = {"used_gb": used_gb, "cap_gb": cap_gb}; st["caps"] = {"ocpu": cap_c, "mem_gb": cap_m}
        if not vms:                                                                     # 2. launch the biggest that fits
            st.pop("vm", None)
            if free_gb < MIN_BOOT: raise OciError("limit", f"only {free_gb} GB free storage, need {MIN_BOOT}")
            for n in LAUNCH:
                if n > cap_c or n * GB_PER_OCPU > cap_m or f"launch {n}" in skip: continue
                try:
                    v = attempt(st, f"launch {n}", lambda n=n: oci(
                        "compute", "instance", "launch", "-c", comp, "--availability-domain", AD, "--display-name", "free-a1",
                        "--shape", SHAPE, "--shape-config", json.dumps({"ocpus": n, "memoryInGBs": n * GB_PER_OCPU}),
                        "--image-id", IMAGE, "--boot-volume-size-in-gbs", str(free_gb), "--subnet-id", SUBNET,
                        "--assign-public-ip", "true", "--ssh-authorized-keys-file", KEYS))
                    msg.append(f"Oracle: got free VM {n} OCPU/{n * GB_PER_OCPU} GB/{free_gb} GB (free-a1 ..{v.get('id', '')[-6:]})"); break
                except OciError as e:
                    if e.kind == "limit": skip.append(f"launch {n}")
                    elif e.kind != "capacity": raise
                time.sleep(5)
        else:
            vm = max(vms, key=lambda i: float(i["shape-config"]["ocpus"])); cur = int(float(vm["shape-config"]["ocpus"]))
            other = sum(float(i["shape-config"]["ocpus"]) for i in vms if i is not vm)
            st["vm"] = {"id": vm["id"], "name": vm["display-name"], "state": vm["lifecycle-state"], "ocpus": cur,
                        "mem_gb": float(vm["shape-config"]["memory-in-gbs"])}
            if len(vms) > 1: st["note"] = f"{len(vms)} A1 VMs exist; growing the largest only"
            if vm["lifecycle-state"] in ("RUNNING", "STOPPED"):
                for n in GROW:                                                          # 3. grow OCPU/RAM in place
                    if n <= cur or n + other > cap_c or n * GB_PER_OCPU > cap_m or f"grow {n}" in skip: continue
                    try:
                        attempt(st, f"grow {n}", lambda n=n: oci("compute", "instance", "update", "--instance-id", vm["id"], "--force",
                                "--shape-config", json.dumps({"ocpus": n, "memoryInGBs": n * GB_PER_OCPU})))
                        msg.append(f"Oracle: {vm['display-name']} resized {cur}->{n} OCPU/{n * GB_PER_OCPU} GB - it reboots now"); cur = n; break
                    except OciError as e:
                        if e.kind == "limit": skip.append(f"grow {n}")
                        elif e.kind != "capacity": raise
                    time.sleep(5)
                att = {a["boot-volume-id"] for a in oci("compute", "boot-volume-attachment", "list", "-c", comp,
                                                        "--availability-domain", AD, "--instance-id", vm["id"])}
                bv = next((b for b in bvs if b["id"] in att), None)
                if bv and free_gb > 0 and "grow boot" not in skip:                        # 4. boot volume up to the free total
                    new = int(bv["size-in-gbs"]) + free_gb
                    try:
                        attempt(st, "grow boot", lambda: oci("bv", "boot-volume", "update", "--boot-volume-id", bv["id"],
                                                             "--size-in-gbs", str(new), "--force"))
                        msg.append(f"Oracle: boot volume {bv['size-in-gbs']}->{new} GB (grow the partition inside the VM)"); free_gb = 0
                    except OciError as e:
                        if e.kind == "limit": skip.append("grow boot")
                        else: raise
            if cur >= cap_c and free_gb <= 0:
                st["done"] = True; msg.append(f"Oracle: VM at free max {cur} OCPU/{cur * GB_PER_OCPU} GB/{cap_gb} GB - grabber stopped.")
        st["backoff"] = 0; st["auth_notified"] = False
    except OciError as e:
        kind = e.kind; st["error"] = f"{kind}: {e}"[:200]
        if kind in ("throttle", "transient"):                                           # exponential, resumes by itself
            st["backoff"] = wait = min(max(st.get("backoff", 0) * 2, 60), 1800 if kind == "throttle" else 900)
        elif kind == "auth":
            wait = AUTH_EVERY
            if not st.get("auth_notified"): msg.append(f"Oracle grabber: auth/config error, retrying hourly - {str(e)[:80]}"); st["auth_notified"] = True
    except Exception as e:                                                              # bad JSON etc.: record, normal cadence
        kind = "other"; st["error"] = f"other: {type(e).__name__} {e}"[:200]
    if not kind: st["error"] = ""
    end = time.time(); st["error_class"] = kind; st["next_at"] = end + wait                # from round end: oci calls can take minutes
    st["next_attempt"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end + wait))
    os.makedirs(os.path.dirname(STATE), exist_ok=True); t = STATE + ".tmp"; json.dump(st, open(t, "w"), indent=1); os.replace(t, STATE)
    for m in msg: notify and notify("Oracle VM", m)
    return "; ".join(msg) or f"oraclegrab: {st.get('vm', 'no VM')} next {st['next_attempt']}" + (f" error: {st['error']}" if st.get("error") else "")


if __name__ == "__main__": print(run(force=True))
