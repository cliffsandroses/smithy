"""The backups page (Moosa, 2026-11-02: "I want a full map of all my folders and backup across all my devices … Build the
page for backups"). netwatch sample runs this every 6 hours; `python3 backupmap.py` makes it now.

Reads Syncthing (folders, which device shares each, how far each device is, version history) and the backup logs
(nightly config sets, the nightly folder sets, the offsite push, Proxmox's own job) and writes
~/Projects/claude-artifacts/backup-map.html (Soma → Vault → Artifacts → Backup Map).
"""
import datetime as dt, glob, html, json, os, re, subprocess, time, urllib.request, xml.etree.ElementTree as ET

PAGE = os.path.expanduser("~/Projects/claude-artifacts/backup-map.html")
STATE = os.path.expanduser("~/.local/share/netwatch/backupmap.json")
NAMES = {"4KHIJFB": "Homelab", "GQY7B5D": "Laptop", "DRLSEMU": "Phone", "MLTSFNB": "Work PC"}
B = "/mnt/data/Backups"


def st():
    cfg = next(p for p in (os.path.expanduser("~/.local/state/syncthing/config.xml"), os.path.expanduser("~/.config/syncthing/config.xml")) if os.path.exists(p))
    root = ET.parse(cfg).getroot(); key = root.find("gui/apikey").text
    get = lambda path: json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8384" + path, headers={"X-API-Key": key}), timeout=10).read())
    conn = get("/rest/system/connections")["connections"]
    folders = []
    for f in root.findall("folder"):
        fid = f.get("id"); devs = []
        for d in f.findall("device"):
            did = d.get("id")[:7]
            if did == "4KHIJFB": continue
            c = get(f"/rest/db/completion?folder={fid}&device={d.get('id')}")
            devs.append({"name": NAMES.get(did, did), "pct": round(c.get("completion", 0)), "state": c.get("remoteState"),
                         "online": conn.get(d.get("id"), {}).get("connected", False)})
        v = f.find("versioning")
        folders.append({"label": f.get("label") or fid, "path": f.get("path"), "type": f.get("type"), "devices": devs,
                        "versions": (v.get("type") if v is not None and v.get("type") else "none")})
    return folders


def du(p):
    r = subprocess.run(["du", "-sh", p], capture_output=True, text=True); return r.stdout.split("\t")[0] if r.returncode == 0 else "?"


def backups():
    out = []
    log = open(os.path.expanduser("~/homelab/backup/backup.log")).read().splitlines()
    last = [l for l in log if l in ("OK", "COMPLETED WITH FAILURES")][-1:] or ["?"]
    fails = sorted({l.strip()[5:] for l in log[-60:] if l.strip().startswith("FAIL")} - {"git mirror smithy"} if os.path.exists("/mnt/data/Backups/git-mirrors/smithy.git/refs/remotes/origin") else {l.strip()[5:] for l in log[-60:] if l.strip().startswith("FAIL")})
    sets = sorted(glob.glob(f"{B}/homelab/20*"))
    out.append({"what": "Homelab configs and databases", "where": f"{B}/homelab (backup disk)", "when": "nightly 03:15",
                "last": os.path.basename(sets[-1]) if sets else "none", "kept": f"{len(sets)} sets", "size": du(f"{B}/homelab"),
                "ok": last[0] == "OK", "note": ("failing: " + ", ".join(fails)) if fails else "all steps OK"})
    fs = sorted(glob.glob(f"{B}/folders/20*"))
    out.append({"what": "Your folders: Axon, Projects, EC01, EC01-work, Aedon; laptop Documents, Desktop, Pictures, Videos",
                "where": f"{B}/folders", "when": "nightly 03:15", "last": os.path.basename(fs[-1]) if fs else "none",
                "kept": f"{len(fs)} of 14 nights", "size": du(f"{B}/folders"), "ok": bool(fs), "note": "unchanged files are hard links"})
    off = open(os.path.expanduser("~/homelab/backup/offsite-retry.log")).read().splitlines()[-1:] or ["?"]
    out.append({"what": "Offsite copy (configs to the laptop, Immich library)", "where": "laptop + offsite", "when": "after the nightly set",
                "last": off[0][:19], "kept": "latest", "size": "", "ok": "nothing to do" in off[0] or "pushed" in off[0], "note": off[0][20:120]})
    px = sorted(glob.glob(f"{B}/proxmox/*"))
    out.append({"what": "Proxmox guests (whole VM and LXC snapshots)", "where": f"{B}/proxmox", "when": "Proxmox's own job",
                "last": os.path.basename(px[-1]) if px else "none", "kept": f"{len(px)} files", "size": du(f"{B}/proxmox"), "ok": bool(px), "note": ""})
    out.append({"what": "Git mirrors (smithy, Soma)", "where": f"{B}/git-mirrors", "when": "on every push", "last": "",
                "kept": "", "size": du(f"{B}/git-mirrors"), "ok": "git mirror smithy" not in " ".join(fails), "note": ""})
    return out


def diagram(bks, folders):
    """The whole flow as a picture: devices ⇄ Syncthing ⇄ homelab → backup disk → laptop / MEGA."""
    ok = {b["what"][:14]: b["ok"] for b in bks}
    phone_ec = all(d["state"] != "notSharing" for f in folders for d in f["devices"] if d["name"] == "Phone" and f["label"] == "EC01")
    G, R, A = "#3DDC97", "#FF4D6D", "#00E5FF"
    def box(x, y, w, h, title, sub, col=A):
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#0d0f14" stroke="{col}" stroke-opacity=".55"/>'
                f'<text x="{x + 14}" y="{y + 26}" fill="#F4F7FF" font-size="15" font-weight="600">{title}</text>'
                + "".join(f'<text x="{x + 14}" y="{y + 48 + 17 * i}" fill="#C3CBE2" font-size="12.5">{t}</text>' for i, t in enumerate(sub)))
    def arrow(x1, y1, x2, y2, label, col=A, both=False):
        mid = ((x1 + x2) / 2, (y1 + y2) / 2 - 8)
        return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="2" marker-end="url(#h{col[1:]})"'
                f'{f' marker-start="url(#t{col[1:]})"' if both else ""}/><text x="{mid[0]}" y="{mid[1]}" fill="{col}" font-size="12" text-anchor="middle">{label}</text>')
    defs = "".join(f'<marker id="h{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="{c}"/></marker>'
                   f'<marker id="t{c[1:]}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10,0L0,5L10,10z" fill="{c}"/></marker>' for c in (A, G, R))
    return f'''<svg viewBox="0 0 1060 470" width="100%" role="img" aria-label="How your data is synced and backed up" style="font-family:Urbanist,sans-serif">
<defs>{defs}</defs>
{box(10, 20, 200, 92, "Phone", ["Syncthing: Backups, Aedon", "EC01: " + ("synced" if phone_ec else "not accepted yet")], G if phone_ec else R)}
{box(10, 140, 200, 92, "Laptop", ["Syncthing: Axon, Projects,", "Claude, EC01, EC01-work"])}
{box(10, 260, 200, 92, "Work PC", ["Syncthing: EC01 (send only:", "it sends, never receives)"])}
{box(360, 120, 260, 150, "Homelab VM", ["Every synced folder lives here", "Apps: Immich, Nextcloud, Soma,", "Jellyfin config, AdGuard …", "Version history on every folder", "(old + deleted files kept 1 year)"])}
{arrow(212, 66, 358, 160, "Syncthing", A, True)}{arrow(212, 186, 358, 190, "Syncthing", A, True)}{arrow(212, 306, 358, 230, "Syncthing (to it only)", A)}
{box(760, 20, 290, 112, "Backup disk  /mnt/data", ["Configs + databases (7 nights)", "Your folders + laptop folders (14 nights)", "Immich photos · Proxmox VM dumps", "Git mirrors"])}
{arrow(622, 160, 758, 80, "03:15 nightly", G if ok.get("Homelab config", True) else R)}
{box(760, 180, 290, 92, "Laptop (second place)", ["Config set + Immich library", "Nextcloud files (nightly)", "retried every 2 h if it sleeps"], G if ok.get("Offsite copy (", True) else R)}
{arrow(905, 134, 905, 178, "after the nightly set", G if ok.get("Offsite copy (", True) else R)}
{box(760, 330, 290, 92, "MEGA (offsite, encrypted)", ["One encrypted file a night, 4 kept", "Stopped: the MEGA login fails"], R)}
{arrow(1000, 134, 1000, 328, "", R)}
{box(360, 330, 260, 92, "Proxmox host", ["Snapshots of the whole VM and", "the Jellyfin box → backup disk"])}
{arrow(622, 376, 758, 110, "Proxmox's own job", G)}
</svg>'''


def page(folders, bks, when):
    dot = lambda ok: f'<span class="dot {"ok" if ok else "bad"}"></span>'
    frows = "".join(
        f'<tr><td><b>{html.escape(f["label"])}</b><br><span class="mono">{html.escape(f["path"])}</span></td><td>{f["type"]}</td>'
        f'<td>{"".join(f"<div>{dot(d["pct"] == 100 and d["state"] == "valid")}{d["name"]} {d["pct"]}%{"" if d["online"] else " · offline"}{" · not sharing" if d["state"] == "notSharing" else ""}</div>" for d in f["devices"]) or "homelab only"}</td>'
        f'<td>{dot(f["versions"] != "none")}{f["versions"]}</td></tr>' for f in folders)
    brows = "".join(f'<tr><td>{dot(b["ok"])}<b>{html.escape(b["what"])}</b><br><span class="mono">{html.escape(b["where"])}</span></td><td>{b["when"]}</td>'
                    f'<td class="mono">{html.escape(b["last"])}</td><td>{b["kept"]}</td><td class="mono">{b["size"]}</td><td>{html.escape(b["note"])}</td></tr>' for b in bks)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Backup Map</title>
<link href="https://fonts.googleapis.com/css2?family=Italiana&family=Urbanist:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>:root{{--night:#050608;--panel:#0d0f14;--ink:#F4F7FF;--ink2:#C3CBE2;--mute:#8A93B2;--acc:#00E5FF;--ok:#3DDC97;--bad:#FF4D6D}}*{{box-sizing:border-box}}
body{{margin:0;background:var(--night);color:var(--ink);font:15px/1.55 Urbanist,sans-serif}}main{{max-width:1100px;margin:0 auto;padding:40px 16px 64px}}
h1{{font:400 50px/1.05 Italiana,serif;margin:0 0 8px}}h2{{font:400 28px Italiana,serif;margin:32px 0 10px}}p,td{{color:var(--ink2)}}b{{color:var(--ink)}}
.box{{background:var(--panel);border-radius:16px;padding:6px 14px;box-shadow:0 1px 0 #ffffff10 inset,0 16px 40px #0008;overflow-x:auto}}table{{width:100%;border-collapse:collapse}}
td,th{{padding:10px 8px;border-top:1px solid #ffffff0d;text-align:left;vertical-align:top}}tr:first-child td{{border-top:0}}th{{color:var(--mute);font-weight:600}}
.mono{{font:12px 'JetBrains Mono',monospace;color:var(--mute)}}.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}}.ok{{background:var(--ok)}}.bad{{background:var(--bad)}}
.flow{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 0}}.flow span{{background:var(--panel);border-radius:10px;padding:7px 11px;box-shadow:0 1px 0 #ffffff10 inset}}.flow i{{color:var(--acc);font-style:normal}}</style></head><body><main>
<h1>Backup map</h1><p>Every synced folder on every device, and every backup, with its state. Checked {when}; refreshed every 6 hours by the homelab.</p>
<div class="box" style="padding:14px">{diagram(bks, folders)}</div>
<h2>Synced folders</h2><div class="box"><table><tr><th>Folder</th><th>Mode on the homelab</th><th>Other devices</th><th>Version history</th></tr>{frows}</table></div>
<h2>Backups</h2><div class="box"><table><tr><th>What</th><th>When</th><th>Last</th><th>Kept</th><th>Size</th><th>Note</th></tr>{brows}</table></div>
</main></body></html>'''


def run(force=False):
    try: s = json.load(open(STATE))
    except (OSError, ValueError): s = {}
    if not force and time.time() - s.get("at", 0) < 6 * 3600: return None
    f, b = st(), backups()
    open(PAGE, "w").write(page(f, b, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    json.dump({"at": time.time()}, open(STATE, "w"))
    return f"backupmap: {len(f)} folders, {sum(not x['ok'] for x in b)} backups need attention"


if __name__ == "__main__": print(run(force=True))
