"""Where Everything Lives (Moosa, 2026-11-02: "Make me a way to know all the things i need to know. For eg. Pnip and the
scripts where they live how to access it in what machine etc etc for everything in my vault").

One page, rebuilt every 6 hours by netwatch (or now: `python3 atlas.py`): every machine, web app, work item, project,
tool, automation, vault folder and page, with what it is, which machine, the path, how to open it, and how it's kept
safe. Writes ~/Projects/claude-artifacts/where-everything-lives.html (Soma → Vault → Artifacts).
"""
import datetime as dt, glob, html, json, os, re, subprocess, time

H = os.path.expanduser("~"); PAGE = f"{H}/Projects/claude-artifacts/where-everything-lives.html"
STATE = f"{H}/.local/share/netwatch/atlas.json"
LAPTOP = "moosa@192.168.10.30"
e = lambda s: html.escape(str(s or ""))


def sh(cmd, remote=False):
    c = ["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", LAPTOP, cmd] if remote else ["sh", "-c", cmd]
    try: return subprocess.run(c, capture_output=True, text=True, timeout=40).stdout
    except Exception: return ""


def first_line(path):
    try:
        t = open(path, errors="ignore").read(6000)
        t = re.sub(r"^#!.*\n", "", t); t = re.sub(r"<[^>]+>", " ", t)
        for l in t.splitlines():
            l = l.strip().strip('#"/*-= ').strip()
            if len(l) > 12 and not l.lower().startswith(("import ", "from ", "set -", "license", "copyright")): return l[:180]
    except OSError: pass
    return ""


def rows(title, head, data, note=""):
    return (f'<section><h2>{e(title)}</h2>{f"<p class=note>{note}</p>" if note else ""}<table><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in data) + "</table></section>")


def diagrams(n):
    box=lambda x,y,w,t,sub,c="#00E5FF": f'<g><rect x="{x}" y="{y}" width="{w}" height="62" rx="14" fill="#0d0f14" stroke="{c}" stroke-opacity=".55"/><text x="{x+w/2}" y="{y+27}" fill="#F4F7FF" font-size="15" font-weight="600" text-anchor="middle">{t}</text><text x="{x+w/2}" y="{y+47}" fill="#8A93B2" font-size="11.5" text-anchor="middle" font-family="JetBrains Mono">{sub}</text></g>'
    ln=lambda x1,y1,x2,y2,c,d="": f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{c}" stroke-width="2" fill="none" {"stroke-dasharray=\'6 6\'" if d else ""} class="flow"/>'
    lab=lambda x,y,t,c: f'<text x="{x}" y="{y}" fill="{c}" font-size="11.5" text-anchor="middle">{t}</text>'
    C,V,P,G="#00E5FF","#B388FF","#FF6FB5","#5CFFB0"
    topo=('<svg viewBox="0 0 1000 400" class="dg">'
      + ln(500,95,500,170,C)+ln(500,232,180,300,V,1)+ln(500,232,820,300,V,1)+ln(500,232,500,300,G)+ln(180,95,410,95,C)+ln(820,95,590,95,P,1)
      + ln(820,97,820,170,P,1)+'<path d="M180 97 L180 201 L410 201" stroke="#00E5FF" stroke-width="2" fill="none" class="flow"/>'
      + box(410,35,180,"Router","192.168.10.1")+box(410,170,180,"Homelab VM","10.20 · ts .0.4",G)+box(90,35,180,"Proxmox","10.13 · Jellyfin LXC")
      + box(730,35,180,"Work PC","EC01 send only",P)+box(90,300,180,"Laptop (Mak)","10.30 · ts .0.5",V)+box(730,300,180,"Phone S25","ts .0.3",V)
      + box(410,300,180,"Soma door","soma.meldev…",G)+box(730,170,180,"ntfy to-work","work PC inbox",P)
      + lab(300,85,"LAN",C)+lab(260,193,"hosts the VM",C)+lab(660,85,"EC01 via Syncthing",P)+lab(310,250,"Syncthing + ssh",V)+lab(700,250,"Tailscale (Headscale)",V)+lab(540,276,"Caddy",G)+lab(870,145,"to-work",P)
      + '</svg>')
    flow=('<svg viewBox="0 0 1000 150" class="dg">'
      + "".join(ln(x+150,75,x+200,75,P) for x in (20,220,420,620))
      + box(20,44,150,"Work PC","EC01 folder",P)+box(220,44,150,"EC01 inbox","recording link",P)+box(420,44,150,"pcai-inbox","netwatch, 1 min",C)
      + box(620,44,150,"EC01-work","transcripts · pnip",G)+box(820,44,150,"PNIP build.py","→ Soma Artifacts",G)
      + '</svg>')
    stats="".join(f'<div class=st><b>{v}</b><span>{k}</span></div>' for k,v in n)
    return (f'<div class=stats>{stats}</div><section><h2>The map</h2><p class=note>Solid = always on · dashed = sync / remote.</p>{topo}</section>'
            f'<section><h2>Work flow: recording to PNIP</h2>{flow}</section>')


def build():
    a = lambda u, t=None: f'<a href="{e(u)}">{e(t or u)}</a>'
    code = lambda t: f"<code>{e(t)}</code>"
    sec = []
    # machines
    sec.append(rows("Machines", ["Machine", "What it does", "Address at home", "Tailscale", "Get in"], [
        ["<b>Homelab VM</b>", "Runs every app, Soma, backups, AdGuard, Headscale, the pipelines", code("192.168.10.20"), code("100.64.0.4"), code("ssh moosa@100.64.0.4") + " · Soma Shell"],
        ["<b>Laptop (Mak)</b>", "Your desktop; OpenClaw, Hermes, Kaggle runs, Chromium previews", code("192.168.10.30"), code("100.64.0.5"), code("ssh moosa@100.64.0.5")],
        ["<b>Proxmox</b>", "The physical server; runs the VM and the Jellyfin box (LXC 200, 192.168.10.21)", code("192.168.10.13"), code("100.64.0.1"), a("https://192.168.10.13:8006", "web UI :8006")],
        ["<b>Phone (S25)</b>", "Syncthing (Backups, Aedon), Termius, Tailscale, KDE Connect", code("192.168.10.16"), code("100.64.0.3"), "—"],
        ["<b>Work PC</b>", "EC01 source (Syncthing send only: it never receives)", code("192.168.10.87") + " at home", "—", "to-work channel"],
        ["<b>Router</b>", "Cudy WR1300 V4, stock firmware", code("192.168.10.1"), "—", a("http://192.168.10.1")]]))
    # web apps from Caddy + quick links
    try:
        r = json.loads(sh("docker exec caddy wget -qO- http://127.0.0.1:2019/config/apps/http/servers"))
        hosts = sorted({h for s in r.values() for rt in s.get("routes", []) for m in rt.get("match", []) for h in m.get("host", [])})
    except Exception: hosts = []
    apps = [["<b>Soma</b>", "Your home-server manager (CasaOS alternative)", a("https://soma.meldev.duckdns.org"), "home: " + a("http://192.168.10.20:8443")],
            ["<b>Nucleus</b>", "Homelab status + the Docket", a("http://192.168.10.20:8090/web/"), a("http://192.168.10.20:8090/web/#asks", "Docket")],
            ["<b>FreeLLMAPI</b>", "Free AI models router (OpenClaw, freellm)", a("https://freellmapi.meldev.duckdns.org"), a("http://192.168.10.20:3001")],
            ["<b>AdGuard</b>", "Ad blocking + DNS for the house and tailnet", a("https://adguard.meldev.duckdns.org"), a("http://192.168.10.20:8080")]]
    known = {x[0] for x in apps}
    for h in hosts:
        n = h.split(".")[0]
        if n in ("soma", "adguard", "freellmapi", "hs", "id"): continue
        apps.append([f"<b>{e(n.capitalize())}</b>", "", a("https://" + h), ""])
    apps += [["<b>Headscale</b>", "Your Tailscale control server", a("https://hs.meldev.duckdns.org"), ""], ["<b>Pocket ID</b>", "Sign-in for apps", a("https://id.meldev.duckdns.org"), ""]]
    sec.append(rows("Web apps", ["App", "What", "From anywhere", "At home"], apps, "From anywhere = through Soma's door: only approved devices get in. All run on the homelab VM in Docker."))
    # work
    sec.append(rows("Work (EC01)", ["Thing", "What", "Where", "Open it"], [
        ["<b>PNIP</b>", "PCAI Network Intelligence Platform", code("~/EC01-work/pnip") + " (homelab + laptop)", a("https://soma.meldev.duckdns.org", "Soma → Vault → Artifacts → PNIP") + " · laptop: " + code("~/EC01-work/pnip/index.html")],
        ["PNIP rebuild", "After changing a page: menu, search index, Soma copy", code("~/EC01-work/pnip/build.py"), code("cd ~/EC01-work/pnip && python3 build.py")],
        ["Demo prep (private)", "Your demo script and timing sheet, kept outside PNIP", code("~/EC01-work/demo-prep"), ""],
        ["PNIP data", "228 SN4700M parts, NVIDIA list, sources", code("~/EC01-work/pnip/data"), ""],
        ["<b>EC01</b>", "Your work notes and files (from the work PC)", code("~/EC01") + " (homelab, laptop, work PC)", "the work PC only sends; work there"],
        ["<b>EC01-work</b>", "Everything made from EC01 (never wiped by the work PC)", code("~/EC01-work") + " (homelab + laptop)", "backed up nightly"],
        ["KT pack", "The PCAI network KT files you uploaded", code("~/EC01-work/inbox/fw-kt-0351"), ""],
        ["Recordings → transcripts", "Put a recording link file in EC01\\PCAI\\inbox on the work PC", code("~/EC01-work/transcripts, screens, recordings"), "automatic (netwatch)"],
        ["PCAI Study", "Your own learning: study pages, call prep (not PNIP)", code("~/EC01/PCAI/PCAI-Study"), code("Standard-Call-Prep.html")],
        ["Send to the work PC", "Text, links, files", code("to-work \"text\"  ·  to-work -f file"), a("https://ntfy.sh/" + (open(f"{H}/.config/to-work/topic").read().strip() if os.path.exists(f"{H}/.config/to-work/topic") else ""), "the work PC's channel")],
        ["<b>Résumé</b>", "Source + PDF", code("~/Projects/job-hunt/resume"), code("typst compile resume.typ")],
        ["Résumé project", "GitOps platform on Oracle, step by step", code("~/Projects/job-hunt/project-gitops-platform.md"), "Soma → Vault → Artifacts → GitOps Project Guide"],
        ["Instagram case", "Ticket S-1670101841456146, GAC draft, deadline ~15 Nov", code("~/Axon/Personal/instagram-disabled-2026-10-30.md"), ""]]))
    # projects
    pr = []
    for d in sorted(glob.glob(f"{H}/Projects/*/")):
        n = os.path.basename(d.rstrip("/")); readme = next((p for p in glob.glob(d + "README*") + glob.glob(d + "*.md")), "")
        git = os.path.isdir(d + ".git"); mirror = os.path.isdir(f"/mnt/data/Backups/git-mirrors/{n}.git")
        pr.append([f"<b>{e(n)}</b>", e(first_line(readme)) if readme else "", code(f"~/Projects/{n}"), ("git" if git else "") + (" · mirrored nightly" if mirror else "")])
    sec.append(rows("Projects", ["Project", "What", "Where (homelab + laptop via Syncthing)", "Kept safe"], pr, "All of ~/Projects syncs homelab ⇄ laptop with version history, and is in the nightly folder backup."))
    # tools
    lap_bin = set(sh("ls ~/.local/bin", remote=True).split()); vm_bin = set(os.listdir(f"{H}/.local/bin")) if os.path.isdir(f"{H}/.local/bin") else set()
    tl = []
    for d in sorted(glob.glob(f"{H}/Projects/smithy/forge/tools/*/")):
        n = os.path.basename(d.rstrip("/"))
        main = next((p for p in [d + n, d + n + ".py"] + glob.glob(d + "*") if os.path.isfile(p) and not p.endswith((".md", ".pyc"))), "")
        where = ", ".join(x for x, s in (("homelab", vm_bin), ("laptop", lap_bin)) if n in s) or "run from the folder"
        tl.append([f"<b>{e(n)}</b>", e(first_line(main)), code(f"~/Projects/smithy/forge/tools/{n}"), e(where)])
    sec.append(rows("Tools (smithy)", ["Tool", "What", "Source", "Installed as a command on"], tl, "smithy is public on GitHub (cliffsandroses/smithy): no secrets in it."))
    # automations
    au = [["netwatch sample (every minute)", "homelab", "internet usage, data guard, router watch (12 h), model picker (6 h), backup map + this page (6 h), PCAI inbox"],
          ["netwatch quality (every 5 min)", "homelab", "line quality, alerts"],
          ["backup-homelab.sh (03:15 nightly)", "homelab", "configs, databases, your folders, git mirrors, offsite to the laptop"],
          ["offsite-retry.sh (every 2 h)", "homelab", "retries the offsite push if the laptop slept"],
          ["automode (every 20 s)", "laptop", "OpenClaw/Hermes priority, pauses for streaming, clip jobs"],
          ["agent-switch", "laptop", "Agent: OpenClaw / Agent: Hermes in the app menu"],
          ["soma-touch", "laptop", "fingerprint sign-in to Soma"]]
    sec.append(rows("Automations", ["What", "Machine", "Does"], [[f"<b>{e(x)}</b>", e(m), e(d)] for x, m, d in au]))
    # vault
    vt = []
    for p in sorted(glob.glob(f"{H}/Axon/*")):
        n = os.path.basename(p)
        if n.startswith((".", "graphify")): continue
        f = p if os.path.isfile(p) else next(iter(sorted(glob.glob(p + "/*.md"))), "")
        vt.append([f"<b>{e(n)}</b>", e(first_line(f)) if f else "", code(f"~/Axon/{n}")])
    sec.append(rows("Vault (Axon)", ["Item", "What", "Where"], vt, "~/Axon syncs homelab ⇄ laptop with version history and is in the nightly backup. Rules for every AI agent: AGENTS.md (also as the moosa-rules skill)."))
    # pages
    try: arts = json.load(open(f"{H}/Projects/claude-artifacts/artifacts.json"))
    except Exception: arts = []
    sec.append(rows("Pages (Soma → Vault → Artifacts)", ["Page", "What", "File"], [[f"<b>{e(x.get('title'))}</b>", e(x.get("about")), code(f"~/Projects/claude-artifacts/{x['id']}.html")] for x in sorted(arts, key=lambda x: x.get("made", ""), reverse=True)]))
    sec.append(rows("Folders, sync and backups", ["See", "Where"], [[a("https://soma.meldev.duckdns.org", "Backup Map"), "Soma → Vault → Artifacts → Backup Map: every synced folder on every device and every backup, with a diagram"]]))
    dg = diagrams([("machines",6),("web apps",len(apps)),("projects",len(pr)),("tools",len(tl)),("vault items",len(vt)),("pages",len(arts))])
    when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    toc = "".join(f'<a href="#s{i}">{re.search(r"<h2>(.*?)</h2>", s).group(1)}</a>' for i, s in enumerate(sec))
    body = "".join(s.replace("<section>", f'<section id="s{i}">', 1) for i, s in enumerate(sec))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Where Everything Lives</title>
<link href="https://fonts.googleapis.com/css2?family=Italiana&family=Urbanist:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>:root{{--night:#050608;--panel:#0d0f14;--ink:#F4F7FF;--ink2:#C3CBE2;--mute:#8A93B2;--acc:#00E5FF}}*{{box-sizing:border-box}}body{{margin:0;background:var(--night);color:var(--ink);font:15px/1.5 Urbanist,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:40px 16px 64px}}h1{{font:400 50px/1.05 Italiana,serif;margin:0 0 8px}}h2{{font:400 28px Italiana,serif;margin:34px 0 8px}}p,td{{color:var(--ink2)}}b{{color:var(--ink)}}a{{color:var(--acc)}}
.toc{{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}}.toc a{{background:var(--panel);border-radius:99px;padding:6px 12px;text-decoration:none;font-size:13.5px}}#q{{width:100%;padding:12px 14px;border-radius:10px;border:1px solid #ffffff22;background:var(--panel);color:var(--ink);font:inherit}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border-radius:14px;overflow:hidden}}td,th{{padding:9px 10px;border-top:1px solid #ffffff0d;text-align:left;vertical-align:top;font-size:14px}}th{{color:var(--mute);font-weight:600}}
code{{font:12.5px 'JetBrains Mono',monospace;color:var(--acc);word-break:break-all}}.note{{font-size:13.5px;color:var(--mute)}}.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:22px 0}}.st{{background:linear-gradient(160deg,#121722,#0b0d12);border:1px solid #ffffff12;border-radius:16px;padding:16px}}.st b{{display:block;font:400 40px Italiana,serif;color:var(--acc)}}.st span{{color:var(--mute);font-size:13px}}.dg{{width:100%;height:auto;background:radial-gradient(ellipse at top,#0f1a24,#07090c);border:1px solid #ffffff10;border-radius:18px;padding:10px;font-family:Urbanist}}.flow{{animation:dash 1.4s linear infinite}}@keyframes dash{{to{{stroke-dashoffset:-24}}}}body{{background:radial-gradient(1200px 600px at 80% -10%,#0b2a33 0,transparent 60%),radial-gradient(900px 500px at -10% 10%,#1d1233 0,transparent 55%),var(--night)}}h1{{background:linear-gradient(90deg,#F4F7FF,#00E5FF 60%,#B388FF);-webkit-background-clip:text;color:transparent}}section{{margin-top:8px}}tr:hover td{{background:#ffffff06}}.toc{{position:sticky;top:0;z-index:5;background:#050608cc;backdrop-filter:blur(10px);padding:8px 0}}</style></head><body><main>
<h1>Where everything lives</h1><p>Every machine, app, work item, project, tool, automation, vault folder and page: what it is, where it is, how to open it. Rebuilt {when}; refreshes itself every 6 hours.</p>
<input id="q" placeholder="Find anything: pnip, resume, backup, jellyfin, to-work …"><div class="toc">{toc}</div>{dg}{body}</main>
<script>document.getElementById("q").oninput=e=>{{const w=e.target.value.toLowerCase();document.querySelectorAll("tr").forEach((r,i)=>{{if(!r.querySelector("td"))return;r.style.display=r.textContent.toLowerCase().includes(w)?"":"none"}})}}</script></body></html>'''


def run(force=False):
    try: st = json.load(open(STATE))
    except (OSError, ValueError): st = {}
    if not force and time.time() - st.get("at", 0) < 6 * 3600: return None
    open(PAGE, "w").write(build())
    try:
        arts = json.load(open(f"{H}/Projects/claude-artifacts/artifacts.json"))
        if not any(x["id"] == "where-everything-lives" for x in arts):
            arts.append({"id": "where-everything-lives", "title": "Where Everything Lives", "about": "Every machine, app, work item, project, tool, automation, vault folder and page: what, where, how to open", "project": "Homelab", "updated": time.strftime("%Y-%m-%d"), "url": "", "claude_id": "", "made": time.strftime("%Y-%m-%d")})
            json.dump(arts, open(f"{H}/Projects/claude-artifacts/artifacts.json", "w"), indent=1)
    except Exception: pass
    json.dump({"at": time.time()}, open(STATE, "w"))
    return "atlas: page rebuilt"


if __name__ == "__main__": print(run(force=True))
