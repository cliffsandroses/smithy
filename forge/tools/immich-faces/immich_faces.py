#!/usr/bin/env python3
"""immich_faces.py OUT_DIR [N]: export N face crops per NAMED person from Immich (read-only DB query + preview
files) for training Frigate face recognition (2026-11-23, Moosa: "can you use immich people?").
Picks each person's largest, most frontal-looking faces (biggest boxes) from different photos."""
import json, os, subprocess, sys, io
from PIL import Image

OUT = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 15
VM = "192.168.10.20"
SQL = """
with f as (
  select p.name, a."assetId", a."imageWidth" w, a."imageHeight" h, a."boundingBoxX1" x1, a."boundingBoxY1" y1, a."boundingBoxX2" x2, a."boundingBoxY2" y2,
         row_number() over (partition by p.name order by (a."boundingBoxX2"-a."boundingBoxX1")::float/a."imageWidth" desc) rn
  from person p join asset_face a on a."personGroupId" = p."personGroupId"
  where p.name <> '' and not p."isHidden" and a."deletedAt" is null and a."imageWidth" > 0
)
select json_agg(json_build_object('name',f.name,'w',f.w,'h',f.h,'x1',f.x1,'y1',f.y1,'x2',f.x2,'y2',f.y2,'path',af.path))
from f join asset_file af on af."assetId" = f."assetId" and af.type = 'preview' where f.rn <= %d;""" % (N * 2)
cmd = ("U=$(docker exec immich_postgres printenv POSTGRES_USER); D=$(docker exec immich_postgres printenv POSTGRES_DB); "
       "docker exec -i immich_postgres psql -U $U -d $D -At")
rows = json.loads(subprocess.run(["ssh", VM, cmd], input=SQL, capture_output=True, text=True, check=True).stdout.strip())
done = {}
for r in rows:
    if done.get(r["name"], 0) >= N: continue
    host = r["path"].replace("/usr/src/app/upload", "/mnt/data/immich/library", 1)
    b = subprocess.run(["ssh", VM, f"cat '{host}'"], capture_output=True).stdout
    if not b: continue
    try: im = Image.open(io.BytesIO(b)).convert("RGB")
    except Exception: continue
    sx, sy = im.width / r["w"], im.height / r["h"]
    x1, y1, x2, y2 = r["x1"] * sx, r["y1"] * sy, r["x2"] * sx, r["y2"] * sy
    pw, ph = (x2 - x1) * .25, (y2 - y1) * .25            # a little margin around the face, as Frigate's own crops have
    c = im.crop((max(0, x1 - pw), max(0, y1 - ph), min(im.width, x2 + pw), min(im.height, y2 + ph)))
    if c.width < 80: continue
    d = os.path.join(OUT, r["name"]); os.makedirs(d, exist_ok=True)
    k = done.get(r["name"], 0); c.save(os.path.join(d, f"{k:02d}.jpg"), quality=92); done[r["name"]] = k + 1
print(json.dumps(done))
