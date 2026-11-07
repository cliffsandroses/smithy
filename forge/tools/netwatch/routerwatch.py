"""OpenWrt support for the Cudy WR1300 V4, watched (Moosa, 2026-10-27: "Automate the looking for support for my router
and link each thing so I can see it somewhere"). netwatch sample runs this every 12 hours. It reads the places support
lands (the patch, the GitHub request, OpenWrt's source tree, the release downloads, the forum thread), writes the page
~/Projects/claude-artifacts/router-openwrt-watch.html (Soma → Vault → Artifacts), and sends a phone alert when anything
changes. A few kB per check.
"""
import base64, datetime as dt, html, json, os, re, time, urllib.request

D = os.path.expanduser("~/.local/share/netwatch"); STATE = f"{D}/routerwatch.json"
os.makedirs(D, exist_ok=True)   # 2026-11-07: without this the save crashed, so no state was kept and no alert ever fired
PAGE = os.path.expanduser("~/Projects/claude-artifacts/router-openwrt-watch.html")
PHOTO = f"{D}/wr1300.jpg"
UA = {"User-Agent": "routerwatch (homelab)", "Accept": "application/json"}


def get(url, raw=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as f:
        b = f.read(); return b if raw else json.loads(b)


def ok(url):
    try: urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=40); return True
    except Exception: return False


def checks():
    out = []
    def add(key, name, url, state, good, note=""): out.append(dict(key=key, name=name, url=url, state=state, good=good, note=note))
    try:
        p = get("https://patchwork.ozlabs.org/api/patches/2238004/")
        add("patch", "The V4 patch (v2) on OpenWrt's mailing list", p["web_url"], p["state"], p["state"] == "accepted",
            "Accepted means it's in OpenWrt's code; images follow in the next snapshot build.")
    except Exception as e: add("patch", "The V4 patch", "https://patchwork.ozlabs.org/project/openwrt/list/?q=WR1300", "unreachable", False, type(e).__name__)
    try:
        i = get("https://api.github.com/repos/openwrt/openwrt/issues/22082")
        add("issue", "GitHub request: add support for the WR1300 v4", i["html_url"], f"{i['state']}, {i['comments']} comments", i["state"] == "closed")
    except Exception as e: add("issue", "GitHub request", "https://github.com/openwrt/openwrt/issues/22082", "unreachable", False, type(e).__name__)
    dts = "target/linux/ramips/dts/mt7621_cudy_wr1300-v4.dts"
    for br in ("main", "openwrt-25.12"):
        try: get(f"https://api.github.com/repos/openwrt/openwrt/contents/{dts}?ref={br}"); s, g = "in the code", True
        except Exception: s, g = "not yet", False
        add(f"tree-{br}", f"V4 in OpenWrt's source ({'development' if br == 'main' else 'stable 25.12'})",
            f"https://github.com/openwrt/openwrt/blob/{br}/{dts}", s, g)
    base = "https://downloads.openwrt.org/snapshots/targets/ramips/mt7621/"
    g = ok(base + "openwrt-ramips-mt7621-cudy_wr1300-v4-squashfs-sysupgrade.bin")
    add("image", "Official V4 image (snapshot)", "https://firmware-selector.openwrt.org/?target=ramips%2Fmt7621&id=cudy_wr1300-v4",
        "ready" if g else "not built", g, "This is the one to flash once it exists.")
    try:
        t = get("https://forum.openwrt.org/t/244677.json")
        add("forum", "Forum thread: Cudy WR1300 v4", "https://forum.openwrt.org/t/cudy-wr1300-v4/244677",
            f"{t['posts_count']} posts, last {t['last_posted_at'][:10]}", False)
    except Exception as e: add("forum", "Forum thread", "https://forum.openwrt.org/t/cudy-wr1300-v4/244677", "unreachable", False, type(e).__name__)
    add("community", "Community-built V4 image (tested on two units)", "https://github.com/GuoShuangyan/Openwrt-Cudy-WR1300-v4",
        "works, unofficial", False, "Not OpenWrt's own build: wait for the official image unless you want it now.")
    return out


def page(rows, when):
    try: img = "data:image/jpeg;base64," + base64.b64encode(open(PHOTO, "rb").read()).decode()
    except OSError: img = ""
    done = sum(r["good"] for r in rows if r["key"] in ("patch", "tree-main", "image"))
    verdict = ("Ready: the official image exists." if any(r["key"] == "image" and r["good"] for r in rows) else
               "Merged, waiting for the image." if done else "Not merged yet: keep the stock firmware.")
    li = "".join(f'<a class="row" href="{html.escape(r["url"])}"><span class="dot {"ok" if r["good"] else "wait"}"></span>'
                 f'<span class="name">{html.escape(r["name"])}<small>{html.escape(r["note"])}</small></span>'
                 f'<span class="st">{html.escape(r["state"])}</span></a>' for r in rows)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Router OpenWrt Watch</title>
<link href="https://fonts.googleapis.com/css2?family=Italiana&family=Urbanist:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>
:root{{--night:#050608;--panel:#0d0f14;--ink:#F4F7FF;--ink2:#C3CBE2;--mute:#8A93B2;--acc:#00E5FF;--ok:#3DDC97;--warn:#FFB020}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--night);color:var(--ink);font:16px/1.5 Urbanist,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:40px 16px 64px}}
.hero{{display:flex;gap:24px;align-items:center;flex-wrap:wrap}}
.hero img{{width:220px;border-radius:18px;background:#fff;box-shadow:0 1px 0 #ffffff14 inset,0 20px 50px #0009}}
h1{{font:400 44px/1.05 Italiana,serif;margin:0 0 8px;text-wrap:balance}}
.verdict{{font-weight:600;color:var(--acc)}}.when{{color:var(--mute);font:13px 'JetBrains Mono',monospace}}
.list{{margin-top:32px;background:var(--panel);border-radius:18px;box-shadow:0 1px 0 #ffffff10 inset,0 16px 40px #0008;overflow:hidden}}
.row{{display:flex;gap:14px;align-items:center;padding:16px 18px;color:inherit;text-decoration:none;border-top:1px solid #ffffff0d;min-height:56px}}
.row:first-child{{border-top:0}}.row:hover{{background:#ffffff08}}
.dot{{width:10px;height:10px;border-radius:50%;flex:none}}.ok{{background:var(--ok);box-shadow:0 0 12px var(--ok)}}.wait{{background:var(--warn)}}
.name{{flex:1}}.name small{{display:block;color:var(--mute);font-size:13px}}
.st{{font:13px 'JetBrains Mono',monospace;color:var(--ink2);text-align:right}}
p.foot{{color:var(--mute);font-size:14px;margin-top:24px}}
</style></head><body><main>
<div class="hero">{f'<img src="{img}" alt="Cudy WR1300">' if img else ''}<div><h1>Cudy WR1300 V4 · OpenWrt</h1>
<div class="verdict">{html.escape(verdict)}</div><div class="when">checked {when}</div></div></div>
<div class="list">{li}</div>
<p class="foot">Checked twice a day by the homelab (netwatch). Your phone gets an alert when any line changes.
<a style="color:var(--acc)" href="https://openwrt.org/toh/cudy/wr1300">OpenWrt's WR1300 page</a> ·
<a style="color:var(--acc)" href="https://www.cudy.com/">Cudy</a></p>
</main></body></html>"""


def run(notify, force=False):
    try: st = json.load(open(STATE))
    except (OSError, ValueError): st = {}
    if not force and time.time() - st.get("at", 0) < 12 * 3600: return None
    rows = checks(); when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    old = st.get("rows", {}); new = {r["key"]: r["state"] for r in rows}
    changed = [r for r in rows if old and old.get(r["key"]) != r["state"] and r["state"] != "unreachable"]
    if changed: notify("Router: OpenWrt news", "; ".join(f"{r['name']}: {r['state']}" for r in changed))
    open(PAGE + ".tmp", "w").write(page(rows, when)); os.replace(PAGE + ".tmp", PAGE)
    json.dump({"at": time.time(), "rows": new}, open(STATE, "w"))
    return f"routerwatch: {len(rows)} checked, {len(changed)} changed"
