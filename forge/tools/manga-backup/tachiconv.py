#!/usr/bin/env python3
"""tachiconv: Kotatsu (.bk.zip) and Nekoyomi/Mihon (.tachibk) backups -> one .tachibk that Suwayomi imports.

Moosa, 2026-11-14: "make a tool to convert nekoyomi and kotatsu backups so I can import it to suwayomi".

  tachiconv.py OUT.tachibk IN [IN ...]          IN = kotatsu_*.bk.zip and/or *.tachibk (Nekoyomi, Mihon)
  tachiconv.py OUT.tachibk IN ... --check URL   also ask Suwayomi (e.g. http://192.168.10.20:4567) which sources
                                                 it is missing, without importing anything

What carries over from Kotatsu: every favourite (into its Kotatsu categories) and every history entry (as a library
entry in a "Kotatsu history" category), with title, cover, author, tags, date added and a last-read time. Kotatsu
does not store chapter URLs in history, so per-chapter read marks can't be rebuilt; Suwayomi fetches the chapter list
when the manga is refreshed. Nekoyomi/Mihon .tachibk files are merged as they are (chapters, read marks, history).
Duplicates (same source + url) are merged, keeping the richer entry.

Source ids follow Tachiyomi: first 8 bytes of md5("<name lowercase>/<lang>/<versionId>") as a positive long.
Kotatsu names its sources by key (MANGADEX, WEBTOONS_EN); SOURCES below maps the ones in Moosa's backups to the
Tachiyomi extension's name and language. Unknown keys are guessed (name = key, lang from a _XX suffix or "en") and
listed at the end so the mapping can be fixed. Stdlib only.
"""
import gzip, hashlib, json, re, sys, urllib.request, zipfile

# Kotatsu source key -> (Tachiyomi/Keiyoushi extension source name, lang, versionId)
SOURCES = {
    "IMHENTAI": ("IMHentai", "en", 1), "NOVELCROW": ("NovelCrow", "en", 1), "WEEBCENTRAL": ("Weeb Central", "en", 1),
    "DEMONICSCANS": ("Demonic Scans", "en", 1), "MANGAPARK": ("MangaPark", "en", 1), "MANGAJINX": ("MangaJinx", "en", 1),
    "READCOMICSONLINE": ("Read Comics Online", "en", 1), "WEBTOONS_EN": ("Webtoons.com", "en", 1),
    "LINEWEBTOONS_EN": ("Webtoons.com", "en", 1), "MANGADEX": ("MangaDex", "en", 1), "MANGACUTE": ("MangaCute", "en", 1),
    "MANGAFOREST": ("Manga Forest", "en", 1), "MANGATOWN": ("MangaTown", "en", 1), "MANGAKAKALOT": ("Mangakakalot", "en", 1),
    "COMICK_FUN": ("Comick", "en", 1), "MANGAXYZ": ("MangaXYZ", "en", 1), "HENTAIFOX": ("HentaiFox", "en", 1),
    "RAVENSCANS": ("Raven Scans", "en", 1), "GDSCANS": ("GD Scans", "en", 1), "MANHUASCAN": ("ManhuaScan", "en", 1),
    "KSGROUPSCANS": ("KSGroupScans", "en", 1), "MANGABUDDY": ("MangaBuddy", "en", 1), "MANGAPUMA": ("MangaPuma", "en", 1),
    "NINEMANGA_EN": ("NineManga", "en", 1), "LOCAL": None,
}


def source_id(name, lang, version=1):
    return int.from_bytes(hashlib.md5(f"{name.lower()}/{lang}/{version}".encode()).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF


# ---------- minimal protobuf (proto2 wire format), enough for the Mihon/Tachiyomi Backup message ----------
def _varint(n):
    n &= (1 << 64) - 1; out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n: out.append(b | 0x80)
        else: out.append(b); return bytes(out)

def _key(f, t): return _varint((f << 3) | t)
def f_int(f, v): return _key(f, 0) + _varint(int(v))
def f_bool(f, v): return f_int(f, 1 if v else 0)
def f_bytes(f, b): return _key(f, 2) + _varint(len(b)) + b
def f_str(f, s): return f_bytes(f, (s or "").encode())

def _rv(b, i):
    r = s = 0
    while True:
        x = b[i]; i += 1; r |= (x & 0x7F) << s; s += 7
        if x < 0x80: return r, i

def fields(b):
    """Yield (field, wiretype, value, raw_bytes_of_whole_field)."""
    i = 0
    while i < len(b):
        start = i; k, i = _rv(b, i); f, t = k >> 3, k & 7
        if t == 0: v, i = _rv(b, i)
        elif t == 2: n, i = _rv(b, i); v = b[i:i + n]; i += n
        elif t == 5: v = b[i:i + 4]; i += 4
        elif t == 1: v = b[i:i + 8]; i += 8
        else: raise ValueError(f"unsupported wire type {t}")
        yield f, t, v, b[start:i]


# ---------- Kotatsu ----------
def kotatsu(path, unknown):
    z = zipfile.ZipFile(path)
    load = lambda n: json.loads(z.read(n)) if n in z.namelist() else []
    cats = {c["category_id"]: c for c in load("categories")}
    hist = {h["manga_id"]: h for h in load("history")}
    mangas = {}   # (sid, url) -> dict
    def add(m, cat_title, added, last_read):
        src = m.get("source", "")
        if src not in SOURCES: unknown.add(src); g = re.match(r"(.+?)_([A-Z]{2})$", src); SOURCES[src] = ((g.group(1) if g else src).title(), (g.group(2).lower() if g else "en"), 1)
        if SOURCES[src] is None: return
        sid = source_id(*SOURCES[src]); k = (sid, m["url"])
        e = mangas.setdefault(k, {"source": sid, "url": m["url"], "title": m.get("title", ""), "author": m.get("author") or "",
                                  "thumb": m.get("large_cover_url") or m.get("cover_url") or "", "genre": [t["title"] for t in m.get("tags") or []],
                                  "added": added or 0, "cats": set(), "last_read": 0, "src_key": src})
        if cat_title: e["cats"].add(cat_title)
        e["last_read"] = max(e["last_read"], last_read or 0); e["added"] = min(x for x in (e["added"], added or e["added"]) if x) if e["added"] else added
    for fav in load("favourites"):
        c = cats.get(fav.get("category_id"), {}); h = hist.get(fav["manga_id"], {})
        add(fav["manga"], c.get("title"), fav.get("created_at"), h.get("updated_at"))
    for h in hist.values():
        add(h["manga"], "Kotatsu history", h.get("created_at"), h.get("updated_at"))
    order = [c["title"] for c in sorted(cats.values(), key=lambda c: c.get("sort_key", 0))]
    return mangas, order


def encode_kotatsu_manga(e, cat_index):
    b = f_int(1, e["source"]) + f_str(2, e["url"]) + f_str(3, e["title"])
    if e["author"]: b += f_str(5, e["author"])
    for g in e["genre"]: b += f_str(7, g)
    if e["thumb"]: b += f_str(9, e["thumb"])
    b += f_int(13, e["added"] or 0)
    for c in sorted(e["cats"]): b += f_int(17, cat_index[c])
    b += f_bool(100, True)
    return b


# ---------- Tachibk (Nekoyomi / Mihon) ----------
def tachibk(path):
    raw = open(path, "rb").read()
    data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    mangas, cats, sources, other = {}, [], [], []
    for f, t, v, whole in fields(data):
        if f == 1:
            sid = url = None
            for ff, tt, vv, _ in fields(v):
                if ff == 1: sid = vv
                elif ff == 2: url = vv.decode()
            mangas[(sid, url)] = v
        elif f == 2:
            name = order = None
            for ff, tt, vv, _ in fields(v):
                if ff == 1: name = vv.decode()
                elif ff == 2: order = vv
            cats.append((name, order or 0, v))
        elif f == 101: sources.append(v)
        else: other.append(whole)
    return mangas, cats, sources, other


def main(argv):
    check = None
    if "--check" in argv: i = argv.index("--check"); check = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
    if len(argv) < 3: print(__doc__); return 2
    out, ins = argv[1], argv[2:]
    unknown = set(); k_mangas = {}; k_order = []; t_mangas = {}; t_cats = []; t_sources = []
    for p in ins:
        if p.endswith(".zip"):
            m, o = kotatsu(p, unknown)
            for k, e in m.items():
                if k in k_mangas: k_mangas[k]["cats"] |= e["cats"]; k_mangas[k]["last_read"] = max(k_mangas[k]["last_read"], e["last_read"])
                else: k_mangas[k] = e
            k_order += [c for c in o if c not in k_order]
        else:
            m, c, s, _ = tachibk(p); t_mangas.update(m); t_cats += c; t_sources += s
    # categories: tachibk ones first (their order values kept), then Kotatsu's, then "Kotatsu history"
    names, cat_bytes = [], []
    for name, order, raw in t_cats:
        if name not in names: names.append(name); cat_bytes.append(raw)
    nxt = max([o for _, o, _ in t_cats] + [0]) + 1
    cat_index = {}
    for name, order, _ in t_cats: cat_index.setdefault(name, order)
    for name in k_order + ["Kotatsu history"]:
        if name not in cat_index: cat_index[name] = nxt; cat_bytes.append(f_str(1, name) + f_int(2, nxt) + f_int(100, 0)); nxt += 1
    body = b""
    kept = 0
    for k, raw in t_mangas.items(): body += f_bytes(1, raw); kept += 1
    for k, e in k_mangas.items():
        if k in t_mangas: continue            # the tachibk copy has chapters + read marks: keep it
        body += f_bytes(1, encode_kotatsu_manga(e, cat_index)); kept += 1
        if e["last_read"]: pass               # no chapter url in Kotatsu history -> nothing to attach
    for cb in cat_bytes: body += f_bytes(2, cb)
    seen = set()
    for s in t_sources:
        sid = next((vv for ff, _, vv, _ in fields(s) if ff == 2), None)
        if sid not in seen: seen.add(sid); body += f_bytes(101, s)
    for src, v in SOURCES.items():
        if v and any(e["src_key"] == src for e in k_mangas.values()):
            sid = source_id(*v)
            if sid not in seen: seen.add(sid); body += f_bytes(101, f_str(1, v[0]) + f_int(2, sid))
    open(out, "wb").write(gzip.compress(body))
    print(f"wrote {out}: {kept} manga ({len(t_mangas)} from tachibk, {kept - len(t_mangas)} from Kotatsu), {len(cat_bytes)} categories, {len(seen)} sources")
    if unknown: print("guessed source names for:", ", ".join(sorted(unknown)), "(fix in SOURCES if Suwayomi says they're missing)")
    if check: print(remap(out, check)); print(suwayomi_check(check, out))
    return 0


def remap(path, base):
    """Point every manga at the source Suwayomi actually has installed, matched by name (case/punctuation-blind),
    preferring en, then all. Fixes ids that differ from the computed ones (versionId bumps, renamed sources)."""
    def G(q):
        r = urllib.request.Request(base.rstrip("/") + "/api/graphql", data=json.dumps({"query": q}).encode(), headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(r, timeout=120))
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    have = {}
    for s in sorted(G("{ sources { nodes { id name lang } } }")["data"]["sources"]["nodes"], key=lambda s: {"en": 0, "all": 1}.get(s["lang"], 2), reverse=True):
        have[norm(s["name"])] = int(s["id"])
    ids = set(have.values())
    data = gzip.decompress(open(path, "rb").read())
    names = {}
    for f, t, v, _ in fields(data):
        if f == 101:
            n = sid = None
            for ff, tt, vv, _ in fields(v):
                if ff == 1: n = vv.decode()
                elif ff == 2: sid = vv
            names[sid] = n
    out = b""; moved = 0
    for f, t, v, whole in fields(data):
        if f == 1:
            sid = next(vv for ff, _, vv, _ in fields(v) if ff == 1)
            new = have.get(norm(names.get(sid, ""))) if sid not in ids else None
            if new and new != sid:
                v = f_int(1, new) + b"".join(w for ff, _, _, w in fields(v) if ff != 1); moved += 1
            out += f_bytes(1, v)
        elif f == 101:
            n = names.get(next((vv for ff, _, vv, _ in fields(v) if ff == 2), None))
            new = have.get(norm(n))
            out += f_bytes(101, f_str(1, n) + f_int(2, new)) if new else whole
        else:
            out += whole
    open(path, "wb").write(gzip.compress(out))
    return f"remapped {moved} manga to installed source ids"


def suwayomi_check(base, path):
    """Ask Suwayomi which sources/trackers the backup needs that it doesn't have. Imports nothing."""
    boundary = "tachiconv"; q = '{"query":"query($b: Upload!){ validateBackup(input:{backup:$b}){ missingSources{ id name } missingTrackers{ name } } }","variables":{"b":null}}'
    data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"operations\"\r\n\r\n{q}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"map\"\r\n\r\n{{\"0\":[\"variables.b\"]}}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"0\"; filename=\"b.tachibk\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() \
        + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    r = urllib.request.Request(base.rstrip("/") + "/api/graphql", data=data, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    res = json.load(urllib.request.urlopen(r, timeout=60))
    if res.get("errors"): return "Suwayomi said: " + res["errors"][0].get("message", "")
    v = res["data"]["validateBackup"]
    ms = v["missingSources"]
    return f"Suwayomi check: {len(ms)} missing sources" + (": " + ", ".join(s["name"] for s in ms) if ms else " (all present)")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
