#!/usr/bin/env python3
"""Download freely licensed candidate photos from Wikimedia Commons.

Runs inside GitHub Actions (the build machine has open internet).
Reads data/photo_queries.json ({slug: [search, ...]}) and writes
photos/<slug>/<n>.jpg plus photos/candidates.json with author/license
for each file. A human (or Claude) then picks one per page.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "photos"
UA = "sportsbetreport.com photo fetcher/1.0 (hello@sportsbetreport.com)"
API = "https://commons.wikimedia.org/w/api.php"
OK_LICENSES = ("cc by", "cc-by", "cc0", "public domain", "pd")
PER_SLUG = 8


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def strip(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def search(q, quality):
    term = f'{q} incategory:"Quality images"' if quality else q
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": 6, "gsrlimit": 15, "gsrsearch": term,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1800,
    }
    data = json.loads(get(API + "?" + urllib.parse.urlencode(params)))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = strip(meta.get("LicenseShortName", {}).get("value"))
        if ii.get("mime") != "image/jpeg":
            continue
        if ii.get("width", 0) < 1000 or ii["width"] < ii.get("height", 0) * 1.2:
            continue
        if not lic.lower().startswith(OK_LICENSES):
            continue
        yield {
            "title": p["title"],
            "page": ii.get("descriptionurl"),
            "thumb": ii.get("thumburl"),
            "author": strip(meta.get("Artist", {}).get("value"))[:120],
            "license": lic,
            "license_url": strip(meta.get("LicenseUrl", {}).get("value")),
            "description": strip(meta.get("ImageDescription", {}).get("value"))[:200],
            "query": q,
            "quality_image": quality,
        }


def main():
    queries = json.loads((ROOT / "data" / "photo_queries.json").read_text())
    only = set(sys.argv[1:])
    OUT.mkdir(exist_ok=True)
    cpath = OUT / "candidates.json"
    allc = json.loads(cpath.read_text()) if cpath.exists() else {}
    for slug, qs in queries.items():
        if only and slug not in only:
            continue
        picks, seen = [], set()
        per_query = max(2, PER_SLUG // len(qs))
        for q in qs:  # spread picks across queries so one search can't fill every slot
            taken = 0
            for quality in (True, False):
                try:
                    for c in search(q, quality):
                        if taken < per_query and c["title"] not in seen and len(picks) < PER_SLUG:
                            seen.add(c["title"])
                            picks.append(c)
                            taken += 1
                except Exception as e:  # keep going on one bad query
                    print("search failed", slug, q, e)
        d = OUT / slug
        d.mkdir(exist_ok=True)
        for i, c in enumerate(picks, 1):
            try:
                (d / f"{i}.jpg").write_bytes(get(c["thumb"]))
                c["file"] = f"photos/{slug}/{i}.jpg"
            except Exception as e:
                print("download failed", c["title"], e)
        allc[slug] = picks
        print(slug, len(picks), "candidates")
    cpath.write_text(json.dumps(allc, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
