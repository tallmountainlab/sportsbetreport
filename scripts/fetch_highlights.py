#!/usr/bin/env python3
"""Collect recent league highlight videos from official YouTube channel feeds.

Writes data/highlights.json: the last 10 days of videos from each league's
official channel with view counts, so the site can show the most-watched ones.
Uses YouTube's public RSS feeds (no key). Never fails the daily run: if a feed
can't be read, the previous videos for that league are kept.
"""
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
OUT = ROOT / "data" / "highlights.json"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "m": "http://search.yahoo.com/mrss/"}
UA = {"User-Agent": "sportsbetreport.com highlights/1.0"}
KEEP_DAYS = 10


def feed(params):
    req = urllib.request.Request("https://www.youtube.com/feeds/videos.xml?" + params, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return ET.fromstring(r.read())


def parse(root, league):
    vids = []
    for e in root.findall("a:entry", NS):
        g = e.find("m:group", NS)
        stats = g.find("m:community/m:statistics", NS) if g is not None else None
        vids.append({
            "league": league,
            "id": e.findtext("yt:videoId", namespaces=NS),
            "title": e.findtext("a:title", namespaces=NS),
            "published": e.findtext("a:published", namespaces=NS),
            "views": int(stats.get("views", 0)) if stats is not None else 0,
        })
    return vids


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {"videos": []}
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    videos = []
    for ch in SITE.get("highlights", []):
        got = None
        for params in (f"channel_id={ch['channel_id']}", f"user={ch.get('user', '')}"):
            if params.endswith("="):
                continue
            try:
                root = feed(params)
                print(f"{ch['league']}: feed '{root.findtext('a:title', namespaces=NS)}' via {params}")
                got = parse(root, ch["league"])
                break
            except Exception as e:
                print(f"{ch['league']}: {params} failed: {e}")
        if got is None:
            got = [v for v in old.get("videos", []) if v["league"] == ch["league"]]
            print(f"{ch['league']}: keeping {len(got)} saved videos")
        videos += got
    videos = [v for v in videos if v.get("id") and datetime.fromisoformat(v["published"].replace("Z", "+00:00")) > cutoff]
    videos.sort(key=lambda v: v["views"], reverse=True)
    OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                               "videos": videos}, indent=1, ensure_ascii=False))
    print(f"Saved {len(videos)} videos")


if __name__ == "__main__":
    main()
