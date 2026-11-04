#!/usr/bin/env python3
"""Fetch betting lines, track line movement, and write today's report data.

Runs once a day from GitHub Actions (see .github/workflows/daily-report.yml).
No dependencies, just Python 3.9+.

Data sources, in order:
  1. The Odds API (https://the-odds-api.com) when the ODDS_API_KEY environment
     variable is set. Free plan = 500 credits/month. Each run costs 3 credits per
     sport with games (h2h + spreads + totals, US region), about 12-15 a day.
     Gives every major US book, so we can show consensus and book disagreement.
  2. ESPN's public scoreboard feed otherwise. One line per game, no key needed.

Files written:
  data/lines/<sport>.json      every tracked game: first line seen ("open"),
                                latest line, and one snapshot per day
  data/reports/<YYYY-MM-DD>.json  the day's report, read by build.py

Usage:
  python3 fetch_odds.py            normal daily run
  python3 fetch_odds.py --from-dir DIR   read saved API responses instead of the
                                         network (DIR/<sport>.json); for testing
"""
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(SITE.get("timezone", "America/New_York"))
LINES = ROOT / "data" / "lines"
REPORTS = ROOT / "data" / "reports"
NOW = datetime.now(timezone.utc)
UA = {"User-Agent": "sportsbetreport.com daily report (+https://sportsbetreport.com/about/)"}


# ---------------------------------------------------------------- helpers
def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        remaining = r.headers.get("x-requests-remaining")
        if remaining is not None:
            print(f"  odds api credits remaining: {remaining}")
        return json.load(r)


def num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def median(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    m = statistics.median(vals)
    return round(m * 2) / 2  # spreads/totals to the half point


def to_dec(ml):
    return None if ml is None or ml == 0 else (1 + ml / 100 if ml > 0 else 1 + 100 / -ml)


def median_ml(vals):
    """Median moneyline, taken in decimal odds so -105 and +105 don't average to 0."""
    dec = [to_dec(v) for v in vals if to_dec(v)]
    if not dec:
        return None
    d = statistics.median(dec)
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def implied(ml):
    if ml is None:
        return None
    return -ml / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def no_vig(ml_a, ml_b):
    a, b = implied(ml_a), implied(ml_b)
    if a is None or b is None or a + b == 0:
        return None, None
    return round(a / (a + b), 3), round(b / (a + b), 3)


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------- sources
def from_odds_api(raw):
    games = []
    for ev in raw:
        home, away = ev["home_team"], ev["away_team"]
        spreads, totals, ml_h, ml_a = [], [], [], []
        best_h, best_a = None, None
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                outs = mk.get("outcomes", [])
                if mk["key"] == "spreads":
                    for o in outs:
                        if o["name"] == home and num(o.get("point")) is not None:
                            spreads.append(num(o["point"]))
                elif mk["key"] == "totals":
                    for o in outs:
                        if o["name"] == "Over" and num(o.get("point")) is not None:
                            totals.append(num(o["point"]))
                elif mk["key"] == "h2h":
                    for o in outs:
                        p = num(o.get("price"))
                        if p is None:
                            continue
                        if o["name"] == home:
                            ml_h.append(p)
                            if best_h is None or p > best_h["price"]:
                                best_h = {"price": p, "book": bk["title"]}
                        elif o["name"] == away:
                            ml_a.append(p)
                            if best_a is None or p > best_a["price"]:
                                best_a = {"price": p, "book": bk["title"]}
        games.append({
            "id": "oa:" + ev["id"], "home": home, "away": away,
            "commence": ev["commence_time"],
            "spread": median(spreads), "total": median(totals),
            "ml_home": median_ml(ml_h), "ml_away": median_ml(ml_a),
            "books": len(ev.get("bookmakers", [])),
            "spread_range": [min(spreads), max(spreads)] if spreads else None,
            "best_home": best_h, "best_away": best_a,
        })
    return games


def espn_home_spread(odds, home_abbr, away_abbr):
    details = (odds.get("details") or "").strip()
    if details.upper() in ("EVEN", "PK", "PICK"):
        return 0.0
    parts = details.rsplit(" ", 1)
    if len(parts) == 2 and num(parts[1]) is not None:
        val = num(parts[1])
        if abs(val) >= 30:  # NHL/MLB "details" holds the moneyline, not a spread
            return num(odds.get("spread"))
        if parts[0] == home_abbr:
            return val
        if parts[0] == away_abbr:
            return -val
    return num(odds.get("spread"))


def from_espn(raw):
    games = []
    for ev in raw.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("state", "pre") != "pre":
            continue
        teams = {c.get("homeAway"): c.get("team", {}) for c in comp.get("competitors", [])}
        if "home" not in teams or "away" not in teams:
            continue
        odds = (comp.get("odds") or [None])[0]
        if not odds:
            continue
        h, a = teams["home"], teams["away"]
        ml_h = num((odds.get("homeTeamOdds") or {}).get("moneyLine"))
        ml_a = num((odds.get("awayTeamOdds") or {}).get("moneyLine"))
        games.append({
            "id": "espn:" + str(ev["id"]), "home": h.get("displayName"), "away": a.get("displayName"),
            "commence": ev["date"],
            "spread": espn_home_spread(odds, h.get("abbreviation"), a.get("abbreviation")),
            "total": num(odds.get("overUnder")), "ml_home": ml_h, "ml_away": ml_a,
            "books": 1, "spread_range": None, "best_home": None, "best_away": None,
            "provider": (odds.get("provider") or {}).get("name"),
        })
    return games


def fetch_sport(sport, key, from_dir):
    if from_dir:
        p = Path(from_dir) / f"{sport['key']}.json"
        if not p.exists():
            return [], None
        raw = json.loads(p.read_text())
        return (from_odds_api(raw), "odds_api") if isinstance(raw, list) else (from_espn(raw), "espn")
    if key:
        qs = urllib.parse.urlencode({"apiKey": key, "regions": "us", "markets": "h2h,spreads,totals",
                                     "oddsFormat": "american", "dateFormat": "iso"})
        return from_odds_api(get_json(f"https://api.the-odds-api.com/v4/sports/{sport['odds_api']}/odds?{qs}")), "odds_api"
    start = NOW.astimezone(TZ).date()
    rng = f"{start:%Y%m%d}-{start + timedelta(days=6):%Y%m%d}"
    extra = "&groups=80&limit=300" if sport["key"] == "ncaaf" else "&limit=300"
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport['espn']}/scoreboard?dates={rng}{extra}"
    return from_espn(get_json(url)), "espn"


# ---------------------------------------------------------------- tracking
LINE_KEYS = ("spread", "total", "ml_home", "ml_away")


def update_lines(sport, games):
    path = LINES / f"{sport['key']}.json"
    db = json.loads(path.read_text()) if path.exists() else {}
    today = NOW.astimezone(TZ).date().isoformat()
    for g in games:
        snap = {k: g[k] for k in LINE_KEYS}
        rec = db.get(g["id"])
        if rec is None:
            rec = db[g["id"]] = {"home": g["home"], "away": g["away"], "commence": g["commence"],
                                 "open": dict(snap, seen=NOW.isoformat(timespec="minutes")), "history": []}
        # fill in any side of the opener that was missing the first time we saw it
        for k in LINE_KEYS:
            if rec["open"].get(k) is None and snap[k] is not None:
                rec["open"][k] = snap[k]
        rec["commence"] = g["commence"]
        rec["current"] = snap
        hist = [h for h in rec["history"] if h["day"] != today]
        rec["history"] = hist + [dict(snap, day=today)]
    # forget games that started more than 3 days ago
    cutoff = NOW - timedelta(days=3)
    db = {k: v for k, v in db.items() if parse_time(v["commence"]) > cutoff}
    path.write_text(json.dumps(db, indent=1, sort_keys=True))
    return db


def delta(a, b):
    return None if a is None or b is None else round(b - a, 1)


def build_game(g, rec):
    prev = rec["history"][-2] if len(rec["history"]) > 1 else None
    p_home, p_away = no_vig(g["ml_home"], g["ml_away"])
    return dict(g,
                open_spread=rec["open"].get("spread"), open_total=rec["open"].get("total"),
                open_seen=rec["open"].get("seen"),
                move_spread=delta(rec["open"].get("spread"), g["spread"]),
                move_total=delta(rec["open"].get("total"), g["total"]),
                day_spread=delta(prev and prev.get("spread"), g["spread"]),
                day_total=delta(prev and prev.get("total"), g["total"]),
                prob_home=p_home, prob_away=p_away)


def main():
    from_dir = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--from-dir" else None
    key = os.environ.get("ODDS_API_KEY", "").strip()
    LINES.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    window_end = NOW + timedelta(hours=SITE.get("report_window_hours", 36))
    report = {"date": NOW.astimezone(TZ).date().isoformat(),
              "generated": NOW.isoformat(timespec="minutes"), "sports": [], "movers": [], "sources": []}

    if not key and not from_dir:
        print("ODDS_API_KEY is not set; trying ESPN's public scoreboard instead.")
    failed = 0
    for sport in SITE["sports"]:
        try:
            games, source = fetch_sport(sport, key, from_dir)
        except Exception as e:  # one bad feed should not sink the report
            print(f"{sport['name']}: fetch failed: {e}")
            failed += 1
            continue
        games = [g for g in games if parse_time(g["commence"]) > NOW]
        if not games:
            print(f"{sport['name']}: no upcoming games")
            continue
        db = update_lines(sport, games)
        built = [build_game(g, db[g["id"]]) for g in games]
        for b in built:
            for field, label in (("move_spread", "spread"), ("move_total", "total")):
                if b[field]:
                    report["movers"].append({"sport": sport["name"], "kind": label, "size": abs(b[field]), **b})
        slate = sorted([b for b in built if parse_time(b["commence"]) <= window_end], key=lambda b: b["commence"])
        if slate:
            report["sports"].append({"key": sport["key"], "name": sport["name"], "source": source, "games": slate})
        if source not in report["sources"]:
            report["sources"].append(source)
        print(f"{sport['name']}: {len(games)} upcoming, {len(slate)} on today's slate ({source})")

    if failed == len(SITE["sports"]):
        # Every feed errored: fail the run so it shows red in GitHub Actions and gets fixed.
        sys.exit("Every odds feed failed; no report written.")
    report["movers"].sort(key=lambda m: m["size"], reverse=True)
    report["movers"] = report["movers"][:12]
    if not report["sports"] and not report["movers"]:
        print("Nothing to report today; leaving the previous report up.")
        return
    (REPORTS / f"{report['date']}.json").write_text(json.dumps(report, indent=1))
    print(f"Wrote data/reports/{report['date']}.json")


if __name__ == "__main__":
    main()
