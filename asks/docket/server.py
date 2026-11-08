#!/usr/bin/env python3
"""Docket: a plain app over ~/Projects/asks/ledger.json. No AI, no agent, no network calls.

Moosa asked for a Docket that works WITHOUT any AI and is AI-agnostic: this reads and writes
ledger.json itself, so you can add asks, add steps, edit proof and close things by hand. Agents
write to the same file; both sides see the same data.

    server.py                 # http://127.0.0.1:8755
    server.py --port 8755 --host 0.0.0.0
    server.py --selftest      # read, edit and roll back a copy; prints OK

Every write: flock on ledger.json.lock, a dated .bak on the first write of the day, then an
atomic replace. Unknown fields on an ask or item are preserved exactly.
"""
import argparse, fcntl, gzip, json, os, shutil, sys, time, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = Path(os.environ.get("DOCKET_LEDGER") or Path.home() / "Projects/asks/ledger.json")
STATES = ("open", "waiting", "blocked", "done", "said", "chat")


def lockfile():
    return LEDGER.with_suffix(LEDGER.suffix + ".lock")


def load():
    with open(LEDGER, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("asks", {})
    return d


def save(d):
    lf = lockfile()
    lf.touch(exist_ok=True)
    with open(lf, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            bak = LEDGER.with_name(LEDGER.name + ".bak-docket-" + datetime.now().strftime("%Y%m%d"))
            if not bak.exists():
                shutil.copy2(LEDGER, bak)
            tmp = LEDGER.with_suffix(".tmp-docket")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, LEDGER)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------- operations (pure dict edits, so --selftest can drive them) ----------

def op_ask_add(d, p):
    aid = str(uuid.uuid4())
    d["asks"][aid] = {
        "at": now_iso(),
        "title": (p.get("title") or "").strip() or "Untitled",
        "text": (p.get("text") or "").strip(),
        "where": (p.get("where") or "Docket").strip(),
        "session": "docket",
        "items": [],
    }
    return {"id": aid}


def op_ask_delete(d, p):
    d["asks"].pop(p["id"], None)
    return {"id": p["id"]}


def op_ask_patch(d, p):
    a = d["asks"][p["id"]]
    for k in ("title", "text", "where"):
        if k in p:
            a[k] = p[k]
    return {"id": p["id"]}


def op_item_add(d, p):
    a = d["asks"][p["id"]]
    a.setdefault("items", []).append({
        "t": (p.get("t") or "").strip() or "New step",
        "s": p.get("s") if p.get("s") in STATES else "open",
        "p": p.get("p") or "",
        "by": p.get("by") or "moosa",
        "steps": p.get("steps") or [],
        "check": p.get("check") or "",
    })
    return {"id": p["id"], "i": len(a["items"]) - 1}


def op_item_patch(d, p):
    it = d["asks"][p["id"]]["items"][int(p["i"])]
    for k in ("t", "p", "check", "by", "m", "e"):
        if k in p:
            it[k] = p[k]
    if "s" in p:
        if p["s"] not in STATES:
            raise ValueError("bad status " + str(p["s"]))
        it["s"] = p["s"]
    if "steps" in p:
        it["steps"] = [s for s in p["steps"] if str(s).strip()]
    return {"ok": True}


def op_item_delete(d, p):
    items = d["asks"][p["id"]]["items"]
    del items[int(p["i"])]
    return {"ok": True}


OPS = {"ask.add": op_ask_add, "ask.patch": op_ask_patch, "ask.delete": op_ask_delete,
       "item.add": op_item_add, "item.patch": op_item_patch, "item.delete": op_item_delete}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        gz = len(body) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(code)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/ledger"):
            try:
                d = load()
            except Exception as e:
                return self._send(500, {"error": str(e)})
            asks = []
            for k, v in d["asks"].items():
                a = dict(v, id=k)
                t = a.get("text") or ""
                if len(t) > 300:          # keep the list small; /api/text?id= has the rest
                    a["text"] = t[:300]
                    a["more"] = True
                asks.append(a)
            return self._send(200, {"asks": asks, "updated": int(time.time()),
                                    "ledger": str(LEDGER), "states": STATES})
        if self.path.startswith("/api/text?"):
            aid = self.path.split("id=", 1)[-1]
            try:
                return self._send(200, {"text": load()["asks"][aid].get("text") or ""})
            except Exception:
                return self._send(404, {"error": "no such ask"})
        path = "index.html" if self.path in ("/", "") else self.path.lstrip("/").split("?")[0]
        f = (HERE / path).resolve()
        if f.parent != HERE or not f.is_file():
            return self._send(404, "not found", "text/plain")
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript", "css": "text/css"}.get(f.suffix[1:], "application/octet-stream")
        return self._send(200, f.read_bytes(), ctype)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            op = OPS[req["op"]]
        except Exception as e:
            return self._send(400, {"error": "bad request: %s" % e})
        try:
            d = load()
            out = op(d, req)
            save(d)
        except KeyError as e:
            return self._send(404, {"error": "no such ask/step: %s" % e})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        return self._send(200, dict(out, ok=True))


def selftest():
    global LEDGER
    src = LEDGER
    tmp = Path("/tmp/docket-selftest.json")
    shutil.copy2(src, tmp)
    LEDGER = tmp
    d = load()
    before = len(d["asks"])
    r = op_ask_add(d, {"title": "selftest", "text": "t"})
    op_item_add(d, {"id": r["id"], "t": "step one"})
    op_item_patch(d, {"id": r["id"], "i": 0, "s": "done", "p": "proof", "steps": ["a", "b", ""]})
    save(d)
    d2 = load()
    a = d2["asks"][r["id"]]
    assert len(d2["asks"]) == before + 1, "ask not added"
    assert a["items"][0]["s"] == "done" and a["items"][0]["steps"] == ["a", "b"], a["items"][0]
    op_item_delete(d2, {"id": r["id"], "i": 0})
    op_ask_delete(d2, {"id": r["id"]})
    save(d2)
    d3 = load()
    assert len(d3["asks"]) == before, "rollback failed"
    assert json.loads(src.read_text())["asks"].keys() == d3["asks"].keys(), "real ledger changed"
    print("OK: %d asks, add/patch/delete/rollback all fine (copy at %s)" % (before, tmp))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8755)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        sys.exit(0)
    if not LEDGER.is_file():
        sys.exit("no ledger at %s" % LEDGER)
    print("Docket on http://%s:%d  (ledger %s)" % (args.host, args.port, LEDGER))
    ThreadingHTTPServer((args.host, args.port), H).serve_forever()
