"""Grab Oracle Always Free Ampere VMs: 4 cores first, then 2, then 1, until the free 4 OCPUs are in use.
Moosa, 2026-11-03: "How to do this automatically"; 2026-11-09: "Set up an automation for 4, 2 and 1 cores ... make it
limit aware so the tries are not wasted and check oracles official limits for requests."

Runs from netwatch (every few minutes); does nothing until ~/.oci/config exists. Each round, for 4, 2 and 1 OCPUs in that
order, launches a VM.Standard.A1.Flex (6 GB per OCPU, 50 GB boot) if it still fits the free 4 OCPU / 24 GB / 200 GB.
Whatever it gets it keeps, and keeps trying to fill the rest (a 1-core VM now means the 4-core one can no longer fit;
Moosa asked for the 1-core "for now").

Limit-aware, per Oracle's docs (docs.oracle.com/iaas/Content/API/Concepts/usingapi.htm "Request Throttling": no number
is published; on 429 TooManyRequests "implement an exponential back-off, starting from a few seconds to a maximum of 60
seconds"; apierrors.htm: 429 is retryable with backoff, LimitExceeded is not):
  - 429 / TooManyRequests -> stop this round at once, back off 2x (5 min .. 60 min), no further calls until then.
  - "Out of host capacity" -> normal; the next size is still tried this round (smaller shapes free up more often).
  - LimitExceeded / QuotaExceeded -> that size can't fit the account; skip it until a VM changes.
  - One read (instance list) + at most 3 launches per round, a few seconds apart.
New VM -> phone message with its IP. State: ~/.local/share/netwatch/oraclegrab.json. `python3 oraclegrab.py` = one round now.
"""
import json, os, re, subprocess, time

H = os.path.expanduser("~"); CFG = f"{H}/.oci/config"; STATE = f"{H}/.local/share/netwatch/oraclegrab.json"
OCI = f"{H}/.local/bin/oci"; EVERY = 300; SIZES = (4, 2, 1); GB_PER_OCPU = 6; BOOT_GB = 50
AD = "YTeh:AP-HYDERABAD-1-AD-1"
SUBNET = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaateqymgryehyqktzgdlneu4lck5llzluqu2f5x6hc57mxlx3tyioa"   # public subnet-oracle-net
IMAGE = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaamvzbsljz2ja6iegrtbe2hak37xuahdhb6uylqnw37iyq7zgvrjqq"     # same image as Moosa's stacks
KEYS = f"{H}/.local/share/netwatch/oraclegrab.pub"                                                     # public keys from the stack's Terraform
ENV = {**os.environ, "OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING": "True"}


class Throttled(Exception): pass


def oci(*a):
    r = subprocess.run([OCI, *a, "--output", "json"], capture_output=True, text=True, timeout=180, env=ENV)
    if r.returncode:
        out = (r.stderr or r.stdout).strip(); m = re.search(r'"message":\s*"([^"]+)"', out); c = re.search(r'"code":\s*"([^"]+)"', out)
        msg = (m.group(1) if m else out.splitlines()[-1] if out else "oci failed")[:300]
        if '"status": 429' in out or (c and c.group(1) == "TooManyRequests") or "Too many requests" in msg: raise Throttled(msg)
        raise RuntimeError(f"{c.group(1) if c else ''}: {msg}")
    return json.loads(r.stdout or "{}").get("data", [])


def tenancy():
    for l in open(CFG):
        if l.strip().startswith("tenancy"): return l.split("=", 1)[1].strip()


def run(force=False, notify=None):
    if not os.path.exists(CFG) or not os.path.exists(OCI) or not os.path.exists(KEYS): return None
    try: st = json.load(open(STATE))
    except (OSError, ValueError): st = {}
    now = time.time()
    if st.get("done") or (not force and now < max(st.get("at", 0) + EVERY, st.get("backoff_until", 0))): return None
    st["at"] = now; comp = tenancy(); msg = []; tries = st.setdefault("tries", {}); skip = st.setdefault("skip", [])
    try:
        vms = [i for i in oci("compute", "instance", "list", "-c", comp, "--all")
               if i["shape"] == "VM.Standard.A1.Flex" and i["lifecycle-state"] not in ("TERMINATED", "TERMINATING")]
        used = sum(int(float(i["shape-config"]["ocpus"])) for i in vms)
        if sorted(i["id"] for i in vms) != st.get("ids"): skip.clear()                 # account changed: re-try every size
        st["ids"] = sorted(i["id"] for i in vms); st["used"] = used; st["last"] = {}
        for n in SIZES:
            if used + n > 4 or n in skip: continue
            tries[str(n)] = tries.get(str(n), 0) + 1
            try:
                v = oci("compute", "instance", "launch", "-c", comp, "--availability-domain", AD, "--display-name", f"free-{n}core",
                        "--shape", "VM.Standard.A1.Flex", "--shape-config", json.dumps({"ocpus": n, "memoryInGBs": n * GB_PER_OCPU}),
                        "--image-id", IMAGE, "--boot-volume-size-in-gbs", str(BOOT_GB), "--subnet-id", SUBNET,
                        "--assign-public-ip", "true", "--ssh-authorized-keys-file", KEYS)
                used += n; st["last"][str(n)] = "launched"
                msg.append(f"Oracle: got a free {n}-core VM (free-{n}core, {v.get('id', '')[-8:]}); IP in the console in ~1 min" +
                           ("" if used >= 4 else f" - still trying for {4 - used} more core(s)"))
            except RuntimeError as e:
                st["last"][str(n)] = str(e)[:120]
                if re.search(r"LimitExceeded|QuotaExceeded|limit", str(e), re.I) and "capacity" not in str(e).lower(): skip.append(n)
            time.sleep(5)
        if used >= 4: st["done"] = True; msg.append("Oracle: all 4 free cores are in use - grabber stopped.")
        st["error"] = ""; st["backoff"] = 0
    except Throttled as e:                                                               # Oracle said slow down: obey it
        b = min(max(st.get("backoff", 0) * 2, 300), 3600); st["backoff"] = b; st["backoff_until"] = now + b
        st["error"] = f"429 {e} - backing off {b // 60} min"
    except Exception as e:
        st["error"] = str(e)[:300]
    os.makedirs(os.path.dirname(STATE), exist_ok=True); t = STATE + ".tmp"; json.dump(st, open(t, "w"), indent=1); os.replace(t, STATE)
    for m in msg: notify and notify("Oracle VM", m)
    return "; ".join(msg) or f"oraclegrab: used {st.get('used')} tries {tries} last {st.get('last')}" + (f" error: {st['error']}" if st.get("error") else "")


if __name__ == "__main__": print(run(force=True))
