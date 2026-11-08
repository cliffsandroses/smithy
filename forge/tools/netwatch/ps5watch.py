"""PS5 jailbreak watch (Moosa, 2026-11-07: "multi-source watcher so the info stays current, like routerwatch does").

Reads the console's own firmware off the LAN, then the places a new PS5 exploit actually lands (the UMTX2
host, etaHEN, the ELF loader, PS5Dev, the lua loader). Writes ~/Projects/claude-artifacts/ps5-jailbreak-watch.html
(Soma -> Vault -> Artifacts) and alerts the phone when a line changes - above all when a release's supported
firmware range grows past what the console runs. netwatch runs this every 6 hours. A few kB per check.

The decision it answers: is this console's firmware inside any public exploit's supported range, yes or no.
"""
import datetime as dt, html, json, os, re, socket, time, urllib.request

D = os.path.expanduser("~/.local/share/netwatch"); STATE = f"{D}/ps5watch.json"
os.makedirs(D, exist_ok=True)
PAGE = os.path.expanduser("~/Projects/claude-artifacts/ps5-jailbreak-watch.html")
UA = {"User-Agent": "ps5watch (homelab)", "Accept": "application/vnd.github+json"}
BCAST = ("192.168.10.255", "255.255.255.255")

# Repos that host or build the public chain. "fw" = where its supported firmware range is written.
REPOS = [
    ("umtx2", "UMTX2 jailbreak host (the exploit you would run)", "idlesauce/umtx2"),
    ("etahen", "etaHEN (payload/plugin loader after the exploit)", "LightningMods/etaHEN"),
    ("elfldr", "ELF loader (runs homebrew once jailbroken)", "ptr-yudai/elfldr" if 0 else "john-tornblom/elfldr"),
    ("ps5dev", "PS5Dev UMTX jailbreak (the original chain)", "PS5Dev/PS5-UMTX-Jailbreak"),
    ("lua", "remote_lua_loader (where new bugs show up first)", "shahrilnet/remote_lua_loader"),
]
# Scene news, so a new exploit shows up here even before a repo moves.
FEEDS = [("wololo", "Scene news (wololo.net)", "https://wololo.net/feed/", "https://wololo.net/")]
RANGE = re.compile(r"(\d+\.\d\d)\s*(?:-|to|–)\s*(\d+\.\d\d)")


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as f:
        return json.loads(f.read())


def text(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]}), timeout=40) as f:
        return f.read().decode("utf-8", "replace")


def console():
    """Ask the PS5 on the LAN what it is. Returns (name, firmware string) or (None, None)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3); s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    msg = b"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n"
    for ip in BCAST:
        try: s.sendto(msg, (ip, 9302))
        except OSError: pass
    name = fw = None
    try:
        while True:
            d, _ = s.recvfrom(2048)
            d = d.decode("utf-8", "replace")
            if "host-type:PS5" not in d: continue
            name = (re.search(r"host-name:(.+)", d) or [None, None])[1]
            v = (re.search(r"system-version:(\d+)", d) or [None, None])[1]
            if v:   # 14200007 -> 14.20
                fw = "%d.%02d" % (int(v[:-6]), int(v[-6:-4]))
            break
    except (socket.timeout, OSError):
        pass
    finally:
        s.close()
    return (name and name.strip()), fw


def highest_supported():
    """The highest firmware any public release claims, with where it was read."""
    best, src = None, ""
    try:
        r = text("https://raw.githubusercontent.com/idlesauce/umtx2/main/README.md")
        m = RANGE.search(r)
        if m: best, src = m.group(2), "umtx2 README"
    except Exception:
        pass
    return best, src


def checks(known_fw=None):
    out = []
    def add(key, name, url, state, good, note=""): out.append(dict(key=key, name=name, url=url, state=state, good=good, note=note))

    name, fw = console()
    asleep = not fw
    if asleep and known_fw:        # rest mode: the firmware it had last time is still the firmware it has
        fw = known_fw
    cap, capsrc = highest_supported()
    inside = bool(fw and cap and float(fw) <= float(cap))
    add("console", f"This console{f' ({name})' if name else ''}", "https://www.playstation.com/",
        f"firmware {fw}" if fw else "not found on the LAN", False,
        ("Last known firmware; console was asleep this time." if asleep else "Read straight off the console over the network.")
        if fw else "Console asleep or on another network, and no firmware seen yet.")
    add("verdict", "Is this firmware jailbreakable?", "https://umtx2.pages.dev/",
        ("YES, run UMTX2" if inside else f"NO - public chain stops at {cap}") if (fw and cap) else "unknown",
        inside, f"Highest public support: {cap} ({capsrc})." if cap else "")

    for key, label, repo in REPOS:
        try:
            rel = get(f"https://api.github.com/repos/{repo}/releases/latest")
            st = f"{rel['tag_name']}, {rel['published_at'][:10]}"
            url = rel["html_url"]
        except Exception:
            try:
                c = get(f"https://api.github.com/repos/{repo}/commits?per_page=1")[0]
                st = f"last commit {c['commit']['committer']['date'][:10]}"
                url = c["html_url"]
            except Exception as e:
                st, url = "unreachable (%s)" % type(e).__name__, f"https://github.com/{repo}"
        add(key, label, url, st, False)

    for key, label, feed, home in FEEDS:
        try:
            x = text(feed)
            items = re.findall(r"<item>(.*?)</item>", x, re.S)
            hit = next((i for i in items if re.search(r"ps5|playstation 5", i, re.I)), items[0] if items else "")
            title = html.unescape(re.sub(r"<[^>]+>", "", (re.search(r"<title>(.*?)</title>", hit, re.S) or [None, ""])[1])).strip()
            link = (re.search(r"<link>(.*?)</link>", hit, re.S) or [None, home])[1].strip()
            add(key, label, link or home, (title or "no PS5 story")[:90], False, "Newest PS5 story on the scene feed.")
        except Exception as e:
            add(key, label, home, "unreachable (%s)" % type(e).__name__, False)
    return out


def page(rows, when):
    v = next((r for r in rows if r["key"] == "verdict"), None)
    verdict = v["state"] if v else "unknown"
    li = "".join(f'<a class="row" href="{html.escape(r["url"])}" target="_blank" rel="noopener">'
                 f'<span class="dot {"ok" if r["good"] else "wait"}"></span>'
                 f'<span class="name">{html.escape(r["name"])}<small>{html.escape(r["note"])}</small></span>'
                 f'<span class="st">{html.escape(r["state"])}</span></a>' for r in rows)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PS5 Jailbreak Watch</title>
<link href="https://fonts.googleapis.com/css2?family=Italiana&family=Urbanist:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>
:root{{--night:#050608;--panel:#0d0f14;--ink:#F4F7FF;--ink2:#C3CBE2;--mute:#8A93B2;--acc:#00E5FF;--ok:#3DDC97;--warn:#FFB020}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--night);color:var(--ink);font:16px/1.5 Urbanist,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:40px 16px 64px}}
h1{{font:400 44px/1.05 Italiana,serif;margin:0 0 8px}}
.verdict{{font-weight:600;color:var(--acc)}}.when{{color:var(--mute);font:13px 'JetBrains Mono',monospace}}
.list{{margin-top:32px;background:var(--panel);border-radius:18px;box-shadow:0 1px 0 #ffffff10 inset,0 16px 40px #0008;overflow:hidden}}
.row{{display:flex;gap:14px;align-items:center;padding:16px 18px;color:inherit;text-decoration:none;border-top:1px solid #ffffff0d;min-height:56px}}
.row:first-child{{border-top:0}}.row:hover{{background:#ffffff08}}
.dot{{width:10px;height:10px;border-radius:50%;flex:none}}.ok{{background:var(--ok);box-shadow:0 0 12px var(--ok)}}.wait{{background:var(--warn)}}
.name{{flex:1}}.name small{{display:block;color:var(--mute);font-size:13px}}
.st{{font:13px 'JetBrains Mono',monospace;color:var(--ink2);text-align:right}}
p.foot{{color:var(--mute);font-size:14px;margin-top:24px}}
</style></head><body><main>
<h1>PS5 · jailbreak watch</h1><div class="verdict">{html.escape(verdict)}</div><div class="when">checked {when}</div>
<div class="list">{li}</div>
<p class="foot">Checked every few hours by the homelab (netwatch); your phone gets an alert when a line changes.
The console's firmware is read off the LAN, so keep blocking PlayStation's update hosts: once it climbs, it never comes back down.</p>
</main></body></html>"""


def run(notify, force=False):
    try: st = json.load(open(STATE))
    except (OSError, ValueError): st = {}
    if not force and time.time() - st.get("at", 0) < 6 * 3600: return None
    rows = checks(st.get("fw")); when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    old = st.get("rows", {}); new = {r["key"]: r["state"] for r in rows}
    # Never alert on "the console was asleep": only on real news about an exploit.
    quiet = ("unknown", "not found on the LAN")
    feeds = {k for k, *_ in FEEDS}   # news headlines change every day: shown on the page, never an alert
    changed = [r for r in rows if old and old.get(r["key"]) != r["state"] and r["key"] not in feeds
               and "unreachable" not in r["state"] and r["state"] not in quiet]
    big = [r for r in changed if r["key"] == "verdict"]
    if big: notify("PS5: jailbreak status changed", "; ".join(f"{r['name']}: {r['state']}" for r in big))
    elif changed: notify("PS5: jailbreak sources moved", "; ".join(f"{r['name']}: {r['state']}" for r in changed[:4]))
    os.makedirs(os.path.dirname(PAGE), exist_ok=True)
    open(PAGE + ".tmp", "w").write(page(rows, when)); os.replace(PAGE + ".tmp", PAGE)
    fw = next((r["state"].removeprefix("firmware ") for r in rows if r["key"] == "console" and r["state"].startswith("firmware ")), st.get("fw"))
    json.dump({"at": time.time(), "rows": new, "fw": fw}, open(STATE, "w"))
    return f"ps5watch: {len(rows)} checked, {len(changed)} changed"
