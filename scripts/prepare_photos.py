#!/usr/bin/env python3
"""Turn chosen candidate photos into web images + credits.

Usage: python3 scripts/prepare_photos.py <candidates_dir>
<candidates_dir> holds candidates.json and <slug>/<n>.jpg from the
"Fetch photo candidates" workflow (branch photo-candidates).
For each entry in data/photos.json whose "from" is "<slug>/<n>", writes
static/img/<key>.jpg (1600px) and static/img/<key>-sm.jpg (720px), and
fills in title/author/license/page so build.py can print credits.
"""
import json
import sys
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1])
cands = json.loads((src / "candidates.json").read_text())
photos_path = ROOT / "data" / "photos.json"
photos = json.loads(photos_path.read_text())
out = ROOT / "static" / "img"
out.mkdir(parents=True, exist_ok=True)

for key, p in photos.items():
    if (out / f"{key}.jpg").exists() and p.get("author"):
        continue
    slug, n = p["from"].split("/")
    if slug not in cands:
        print("skip (not in this batch)", key)
        continue
    c = cands[slug][int(n) - 1]
    im = ImageOps.exif_transpose(Image.open(src / slug / f"{n}.jpg")).convert("RGB")
    for suffix, w in (("", 1600), ("-sm", 720)):
        x = im.copy()
        x.thumbnail((w, w * 2))
        x.save(out / f"{key}{suffix}.jpg", quality=78, optimize=True, progressive=True)
    p.update({k: c[k] for k in ("title", "page", "author", "license", "license_url")})
    print("ok", key)

photos_path.write_text(json.dumps(photos, indent=1, ensure_ascii=False))
