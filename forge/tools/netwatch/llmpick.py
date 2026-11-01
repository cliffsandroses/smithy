"""The automatic model picker for OpenClaw (Moosa, 2026-11-02: "Build the automated freellmapi" … "For models i want ones
that are the best and the most intelligent with more context"). netwatch sample runs this every 6 hours.

It reads FreeLLMAPI's own database (read-only): every enabled model with tool use and at least 200k context, its
intelligence rank, and how its attempts went in the last 24 hours (ok vs rate-limited, timeouts, quota, not found).
Score = rank + 40 × failure share (a model that keeps failing drops below a slightly less clever one that answers).
OpenClaw gets the best three as primary and fallbacks, then "auto" (FreeLLMAPI picks any working model) last, each with
its real context window. The change is written to ~/.openclaw/openclaw.json on the laptop only when the order changes;
OpenClaw reloads its config by itself. Log: ~/.local/share/netwatch/llmpick.log
"""
import json, os, re, sqlite3, subprocess, time

DB = os.path.expanduser("~/homelab/freellmapi/data/freeapi.db")
D = os.path.expanduser("~/.local/share/netwatch"); STATE, LOG = f"{D}/llmpick.json", f"{D}/llmpick.log"
LAPTOP = "moosa@192.168.10.30"
BAD = ("rate_limited", "timeout", "daily_quota_exhausted", "upstream_error", "error", "model_not_found", "empty_completion", "auth", "forbidden")


def base(model_id):   # the name FreeLLMAPI answers to: "unorouter glm-5.3:free" → "glm-5.3", "qwen/qwen3.8-max:free" → "qwen3.8-max"
    return re.sub(r":free$", "", model_id.split("/")[-1]).lower()


def ranked():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    models = {}
    for plat, mid, rank, ctx in c.execute("select platform, model_id, intelligence_rank, context_window from models "
                                          "where enabled=1 and supports_tools=1 and intelligence_rank is not null"):
        b = base(mid); m = models.setdefault(b, {"rank": rank, "ctx": 0})
        m["rank"] = min(m["rank"], rank); m["ctx"] = max(m["ctx"], ctx or 0)
    health = {}
    for mid, out in c.execute("select a.model_id, a.outcome from request_attempts a join requests r on r.id = a.request_id "
                              "where r.created_at > datetime('now','-1 day')"):
        h = health.setdefault(base(mid), [0, 0]); h[0] += 1; h[1] += out in BAD
    out = []
    for b, m in models.items():
        if m["ctx"] < 200000: continue
        n, bad = health.get(b, [0, 0])
        out.append((m["rank"] + 40 * (bad / n if n >= 3 else 0), b, m["ctx"], n, bad))
    return sorted(out)


def run(force=False):
    try: st = json.load(open(STATE))
    except (OSError, ValueError): st = {}
    if not force and time.time() - st.get("at", 0) < 6 * 3600: return None
    top = ranked()[:3]
    pick = [b for _, b, *_ in top]
    st["at"] = time.time()
    if pick == st.get("pick"):
        json.dump(st, open(STATE, "w")); return f"llmpick: unchanged ({', '.join(pick)})"
    ctx = {b: c for _, b, c, *_ in top}
    py = f"""
import json,os
p=os.path.expanduser("~/.openclaw/openclaw.json"); c=json.load(open(p))
ms=c["models"]["providers"]["freellmapi"]["models"]; have={{m["id"]:m for m in ms}}
for b,x in {json.dumps(ctx)}.items():
    if b in have: have[b]["contextWindow"]=x
    else:
        t=dict(have.get("glm-5.3") or ms[0]); t.update(id=b,name=b,contextWindow=x); ms.append(t)
d=c["agents"]["defaults"]["model"]; d["primary"]="freellmapi/"+{json.dumps(pick[0])}
d["fallbacks"]=["freellmapi/"+b for b in {json.dumps(pick[1:])}]+["freellmapi/auto"]
json.dump(c,open(p+".tmp","w"),indent=2); os.replace(p+".tmp",p); print(d)
"""
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", LAPTOP, "python3", "-"], input=py, capture_output=True, text=True, timeout=60)
    ok = r.returncode == 0
    with open(LOG, "a") as f:
        f.write(time.strftime("%F %T ") + json.dumps([[round(s, 1), b, c, n, bad] for s, b, c, n, bad in top]) +
                (" → OpenClaw updated\n" if ok else f" → laptop unreachable: {r.stderr.strip()[:120]}\n"))
    if ok: st["pick"] = pick
    json.dump(st, open(STATE, "w"))
    return f"llmpick: {' → '.join(pick)} → auto" + ("" if ok else " (laptop unreachable, retry next time)")
