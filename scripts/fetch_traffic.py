#!/usr/bin/env python3
"""Pull daily traffic for the zone from Cloudflare's GraphQL API into data/traffic.json.
Needs env CF_API_TOKEN (Analytics: Read) and CF_ZONE_ID. No dependencies."""
import json, os, urllib.request
from datetime import date, timedelta

token, zone = os.environ.get("CF_API_TOKEN"), os.environ.get("CF_ZONE_ID")
if not token or not zone:
    raise SystemExit("CF_API_TOKEN / CF_ZONE_ID not set; skipping")
since = (date.today() - timedelta(days=30)).isoformat()
q = """query($zone:String!,$since:Date!){viewer{zones(filter:{zoneTag:$zone}){
 httpRequests1dGroups(limit:31,filter:{date_geq:$since},orderBy:[date_ASC]){
  dimensions{date} sum{requests pageViews} uniq{uniques}}}}}"""
req = urllib.request.Request("https://api.cloudflare.com/client/v4/graphql",
    data=json.dumps({"query": q, "variables": {"zone": zone, "since": since}}).encode(),
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
res = json.load(urllib.request.urlopen(req, timeout=30))
if res.get("errors"):
    raise SystemExit(f"Cloudflare API error: {res['errors']}")
rows = [{"date": g["dimensions"]["date"], "page_views": g["sum"]["pageViews"],
         "requests": g["sum"]["requests"], "unique_visitors": g["uniq"]["uniques"]}
        for g in res["data"]["viewer"]["zones"][0]["httpRequests1dGroups"]]
os.makedirs("data", exist_ok=True)
json.dump({"source": "cloudflare", "updated": date.today().isoformat(), "days": rows},
          open("data/traffic.json", "w"), indent=1)
print(f"Saved {len(rows)} days")
