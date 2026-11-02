"""Keep pressing Apply on the Oracle free VM stacks until the Always Free Ampere VMs exist (Moosa, 2026-11-03: "How to do
this automatically" — Hyderabad keeps saying "Out of host capacity").

Runs from netwatch, every 10 minutes, and does nothing until ~/.oci/config exists (Moosa makes it; the key is never read
here). Stacks: every ACTIVE Resource Manager stack in the root compartment whose Terraform makes a VM.Standard.A1.Flex VM;
its OCPU count is read from the Terraform once (Moosa's: oracle-ai-instance-…-0118 = 4/24, …-0042 = 2/12).
  - Each round applies every A1 stack whose VM would still fit the free 4 OCPUs and that hasn't made its VM yet.
    Free-tier limits stop anything beyond 4 OCPUs anyway, so nothing can cost money.
  - New VM -> phone message. When the A1 OCPUs in use reach 4 it stops for good and sends the public IPs.
State: ~/.local/share/netwatch/oraclegrab.json. `python3 oraclegrab.py` runs one round now.
"""
import io, json, os, re, subprocess, time, zipfile

H = os.path.expanduser("~"); CFG = f"{H}/.oci/config"; STATE = f"{H}/.local/share/netwatch/oraclegrab.json"
OCI = f"{H}/.local/bin/oci"; EVERY = 600
ONLY = {4}          # which VM sizes (OCPUs) to keep trying; add 2 back to try the 2-OCPU stacks again


def oci(*a):
    r = subprocess.run([OCI, *a, "--output", "json"], capture_output=True, text=True, timeout=180,
                       env={**os.environ, "OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING": "True"})
    if r.returncode: raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1][:300] if (r.stderr or r.stdout).strip() else "oci failed")
    return json.loads(r.stdout or "{}").get("data", [])


def tenancy():
    for l in open(CFG):
        if l.strip().startswith("tenancy"): return l.split("=", 1)[1].strip()


def run(force=False, notify=None):
    if not os.path.exists(CFG) or not os.path.exists(OCI): return None
    try: st = json.load(open(STATE))
    except (OSError, ValueError): st = {}
    if st.get("done") or (not force and time.time() - st.get("at", 0) < EVERY): return None
    st["at"] = time.time(); comp = tenancy(); msg = []
    try:
        vms = [i for i in oci("compute", "instance", "list", "-c", comp, "--all")
               if i["shape"] == "VM.Standard.A1.Flex" and i["lifecycle-state"] not in ("TERMINATED", "TERMINATING")]
        used = sum(int(i["shape-config"]["ocpus"]) for i in vms)
        names = {i["display-name"] for i in vms}
        if used >= 4:
            ips = []
            for i in vms:
                for v in oci("compute", "instance", "list-vnics", "--instance-id", i["id"]): ips.append(f'{i["display-name"]}: {v.get("public-ip")}')
            st["done"] = True; msg.append("Oracle: free VMs ready — " + ", ".join(ips))
        else:
            stacks = [s for s in oci("resource-manager", "stack", "list", "-c", comp, "--all") if s["lifecycle-state"] == "ACTIVE"]
            size = st.setdefault("ocpus", {})
            for s in stacks:                                                             # each stack's VM size, read once from its Terraform
                if s["id"] not in size:
                    z = f"/tmp/oraclegrab-{os.getpid()}.zip"
                    subprocess.run([OCI, "resource-manager", "stack", "get-stack-tf-config", "--stack-id", s["id"], "--file", z], capture_output=True,
                                   env={**os.environ, "OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING": "True"}, timeout=120)
                    tf = "".join(zipfile.ZipFile(z).read(n).decode() for n in zipfile.ZipFile(z).namelist() if n.endswith(".tf")); os.remove(z)
                    m = re.search(r'ocpus\s*=\s*"?(\d+)', tf); size[s["id"]] = int(m.group(1)) if m and "A1.Flex" in tf else 0
            for s in stacks:
                if not size.get(s["id"]): continue                                           # not an A1 VM stack
                if size[s["id"]] not in ONLY: continue                                         # Moosa 2026-11-03: stop trying the 2-OCPU VMs for now
                if used + size[s["id"]] > 4: continue                                         # would not fit the free 4 OCPUs
                jobs = oci("resource-manager", "job", "list", "--stack-id", s["id"], "--all")
                if any(j["lifecycle-state"] in ("ACCEPTED", "IN_PROGRESS") for j in jobs): continue
                if any(j["operation"] == "APPLY" and j["lifecycle-state"] == "SUCCEEDED" for j in jobs): continue   # made its VM
                oci("resource-manager", "job", "create-apply-job", "--stack-id", s["id"], "--execution-plan-strategy", "AUTO_APPROVED")
                st.setdefault("tries", {}); st["tries"][s["display-name"]] = st["tries"].get(s["display-name"], 0) + 1
            new = [i for i in vms if i["display-name"] not in st.get("seen", [])]
            for i in new: msg.append(f'Oracle: got a free VM ({i["display-name"]}, {int(i["shape-config"]["ocpus"])} OCPU) — trying for the rest')
            st["seen"] = sorted(names)
        st["error"] = ""
    except Exception as e:
        st["error"] = str(e)[:300]
    os.makedirs(os.path.dirname(STATE), exist_ok=True); json.dump(st, open(STATE, "w"), indent=1)
    for m in msg:
        notify and notify("Oracle VM", m)
    return "; ".join(msg) or (f"oraclegrab: tried {st.get('tries', {})}" + (f" error: {st['error']}" if st.get("error") else ""))


if __name__ == "__main__": print(run(force=True))
