#!/usr/bin/env python3
"""Build sportsbetreport.com into ./public. No dependencies, just Python 3.9+.

Inputs:
  data/reports/*.json        daily report data written by fetch_odds.py
  content/guides/*.html      evergreen explainers (front matter + HTML body)
  content/pages/*.html       about, responsible gambling, disclosure, privacy...
  site.json                  settings and monetization slots (empty = hidden)
  templates/base.html, static/

Shortcodes inside guide and page bodies:
  {{tool:odds_tool}}  -> partner tool box (hidden until its URL is set in site.json)
  {{sponsor}}         -> sponsor box (hidden until sponsor.url is set)
  {{ad}}              -> ad slot (hidden until adsense_client_id is set)
  {{newsletter}}      -> email sign-up box (hidden until newsletter_form_action is set)
"""
import html
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "public"
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
TEMPLATE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TZ = ZoneInfo(SITE.get("timezone", "America/New_York"))
TZ_LABEL = "ET"
TEAMS = json.loads((ROOT / "data" / "teams.json").read_text(encoding="utf-8"))
HL_FILE = ROOT / "data" / "highlights.json"
HIGHLIGHTS = json.loads(HL_FILE.read_text(encoding="utf-8")).get("videos", []) if HL_FILE.exists() else []
PH_FILE = ROOT / "data" / "photos.json"
PHOTOS = {k: v for k, v in (json.loads(PH_FILE.read_text(encoding="utf-8")) if PH_FILE.exists() else {}).items()
          if (ROOT / "static" / "img" / f"{k}.jpg").exists()}
LEAGUE_KEY = {sp["name"]: sp["key"] for sp in SITE["sports"]}
LEAGUE_NAME = {sp["key"]: sp["name"] for sp in SITE["sports"]}
e = html.escape


# ---------------------------------------------------------------- formatting
def pts(v, signed=True):
    if v is None:
        return "–"
    s = f"{v:+.1f}" if signed else f"{v:.1f}"
    return s.replace(".0", "")


def ml(v):
    return "–" if v is None else (f"+{v:.0f}" if v > 0 else f"{v:.0f}")


def pct(v):
    return "–" if v is None else f"{v * 100:.0f}%"


def nick(team):
    """'Kansas City Chiefs' -> 'Chiefs'; keeps two-word nicknames like 'Red Sox'."""
    if not team:
        return ""
    two = ("Red Sox", "White Sox", "Blue Jays", "Maple Leafs", "Golden Knights", "Blue Jackets",
           "Red Wings", "Trail Blazers", "Crimson Tide", "Fighting Irish", "Tar Heels", "Golden Bears",
           "Sun Devils", "Yellow Jackets", "Blue Devils", "Nittany Lions", "Golden Gophers", "Red Raiders",
           "Horned Frogs", "Demon Deacons", "Scarlet Knights", "Mean Green", "Black Knights")
    for t in two:
        if team.endswith(t):
            return t
    return team.split()[-1] if " " in team else team


def spread_label(g, home_spread=None):
    s = g["spread"] if home_spread is None else home_spread
    if s is None:
        return "–"
    if s == 0:
        return "Pick'em"
    team = g["home"] if s < 0 else g["away"]
    return f"{e(nick(team))} {pts(-abs(s))}"


def game_time(iso):
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    return t.strftime("%a %-I:%M %p ") + TZ_LABEL


def long_date(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %B %-d, %Y")


def short_date(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d, %Y")


def move_html(v, kind):
    if not v:
        return '<span class="flat">0</span>'
    cls = "up" if v > 0 else "down"
    arrow = "▲" if v > 0 else "▼"
    return f'<span class="{cls}">{arrow} {pts(abs(v), False)}</span>'


# ---------------------------------------------------------------- narrative
def mover_sentence(m):
    match = f"{e(m['away'])} at {e(m['home'])}"
    if m["kind"] == "spread":
        toward = m["home"] if m["move_spread"] < 0 else m["away"]
        return (f"<strong>{e(m['sport'])}:</strong> the spread in {match} moved "
                f"{pts(m['size'], False)} points toward the {e(nick(toward))}. It opened at "
                f"{spread_label(m, m['open_spread'])} and now sits at {spread_label(m)}.")
    word = "up" if m["move_total"] > 0 else "down"
    return (f"<strong>{e(m['sport'])}:</strong> the total in {match} went {word} "
            f"{pts(m['size'], False)} points, from {pts(m['open_total'], False)} to {pts(m['total'], False)}.")


OPENERS = [
    "Pour the coffee. Here's how the board looks this morning.",
    "Like reading the agate page over breakfast, minus the newsprint on your fingers.",
    "Good morning. The numbers moved while you slept; here's where they settled.",
    "Remember circling games in the Sunday paper? Grab a pen.",
    "Same ritual as always: lines are posted, coffee's hot, and here's what changed.",
    "Pull up a chair at the kitchen table. Here's the morning line.",
    "The old sports page had one column of numbers. We kept the spirit and added a few.",
]


def opener(r):
    return OPENERS[datetime.strptime(r["date"], "%Y-%m-%d").toordinal() % len(OPENERS)]


def summary(r):
    n = sum(len(s["games"]) for s in r["sports"])
    names = [s["name"] for s in r["sports"]]
    leagues = ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1] if names else ""
    out = f"{n} game{'s' if n != 1 else ''} on the board in the next day and a half"
    out += f" across {leagues}." if leagues else "."
    if r["movers"]:
        out += " " + re.sub(r"<[^>]+>", "", mover_sentence(r["movers"][0]))
    return out


# ---------------------------------------------------------------- blocks
def ad_slot():
    cid = SITE.get("adsense_client_id")
    if not cid:
        return ""
    return ('<div class="ad"><ins class="adsbygoogle" style="display:block" '
            f'data-ad-client="{e(cid)}" data-ad-format="auto" data-full-width-responsive="true"></ins>'
            "<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>")


def newsletter():
    action = SITE.get("newsletter_form_action")
    if not action:
        return ""
    return ('<section class="news"><h3>Get the report in your inbox</h3>'
            "<p>Like the paper landing on the porch: the morning line in your inbox before the first game. Free.</p>"
            f'<form action="{e(action)}" method="post" target="_blank">'
            '<input type="email" name="email" placeholder="you@example.com" required aria-label="Email">'
            "<button>Subscribe</button></form><p class=\"small\">21+ only. Unsubscribe any time.</p></section>")


def sponsor():
    sp = SITE.get("sponsor") or {}
    if not sp.get("url"):
        return ""
    return (f'<aside class="sponsor"><span class="tag">Sponsor</span>'
            f'<a href="{e(sp["url"])}" rel="sponsored nofollow noopener" target="_blank">'
            f'<strong>{e(sp.get("label", ""))}</strong> {e(sp.get("text", ""))} &rarr;</a></aside>')


def tool(key):
    t = (SITE.get("tools") or {}).get(key)
    if not t or not t.get("url"):
        return ""
    return (f'<aside class="sponsor"><span class="tag">Partner</span>'
            f'<a href="{e(t["url"])}" rel="sponsored nofollow noopener" target="_blank">{e(t["label"])} &rarr;</a></aside>')


def credit(p):
    lic = e(p.get("license", ""))
    if p.get("license_url"):
        lic = f'<a href="{e(p["license_url"])}" rel="license noopener" target="_blank">{lic}</a>'
    return (f'Photo: <a href="{e(p.get("page", ""))}" rel="noopener" target="_blank">'
            f'{e(p.get("author", "Wikimedia Commons"))}</a>, {lic}, via Wikimedia Commons')


def img_tag(key, cls="", sizes="100vw", eager=False):
    p = PHOTOS.get(key)
    if not p:
        return ""
    lazy = "" if eager else ' loading="lazy"'
    return (f'<img class="{cls}" src="/img/{key}.jpg" srcset="/img/{key}-sm.jpg 720w, /img/{key}.jpg 1600w" '
            f'sizes="{sizes}" alt="{e(p["alt"])}"{lazy} decoding="async">')


def figure(key, cls="photo", eager=False):
    p = PHOTOS.get(key)
    if not p:
        return ""
    return (f'<figure class="{cls}">{img_tag(key, sizes="(max-width: 760px) 100vw, 700px", eager=eager)}'
            f'<figcaption>{e(p["caption"])} <span class="credit">{credit(p)}</span></figcaption></figure>')


def shortcodes(body):
    body = re.sub(r"\{\{photo:([\w-]+)\}\}", lambda m: figure(m.group(1)), body)
    body = re.sub(r"\{\{tool:(\w+)\}\}", lambda m: tool(m.group(1)), body)
    return body.replace("{{ad}}", ad_slot()).replace("{{newsletter}}", newsletter()).replace("{{sponsor}}", sponsor())


def pool(prefix):
    return [k for k in PHOTOS if k.startswith(prefix)]


def daily_pick(keys, day, n=1, salt=0):
    """Rotate photos by date so each day's edition looks different."""
    if not keys:
        return []
    start = (date.fromisoformat(day).toordinal() + salt) % len(keys) if day else 0
    return [keys[(start + i) % len(keys)] for i in range(min(n, len(keys)))]


def league_banner(key, name, day, games=None):
    pic = daily_pick(pool(f"sport-{key}-"), day)
    count = f'<span class="lb-n">{len(games)} game{"s" if len(games) != 1 else ""}</span>' if games is not None else ""
    if not pic:
        return f"<h2>{e(name)}</h2>"
    p = PHOTOS[pic[0]]
    return (f'<header class="lbanner"><img src="/img/{pic[0]}-sm.jpg" alt="{e(p["alt"])}" loading="lazy" decoding="async">'
            f'<h2>{e(name)}{count}</h2><p class="lb-cap">{e(p["caption"])} <span class="credit">{credit(p)}</span></p></header>')


def vault(day, n=3, title="From the vault"):
    keys = daily_pick(pool("vault-") + pool("sport-"), day, n, salt=7)
    if not keys:
        return ""
    tiles = "".join(
        f'<figure><img src="/img/{k}-sm.jpg" alt="{e(PHOTOS[k]["alt"])}" loading="lazy" decoding="async">'
        f'<figcaption>{e(PHOTOS[k]["caption"])} <span class="credit">{credit(PHOTOS[k])}</span></figcaption></figure>'
        for k in keys)
    return (f'<section class="vault"><h2>{e(title)}</h2><p class="muted small">Old photographs from the days when the '
            f'only line you saw was in the morning paper. A new set every day.</p><div class="vault-grid">{tiles}</div></section>')


def league_tiles(r):
    """Photo tiles for each league on today's board, linking into the report."""
    tiles = []
    for s in r["sports"]:
        pic = daily_pick(pool(f"sport-{s['key']}-"), r["date"])
        style = f' style="--img:url(/img/{pic[0]}-sm.jpg)"' if pic else ""
        n = len(s["games"])
        tiles.append(f'<a class="ltile" href="/reports/{r["date"]}/#{e(s["key"])}"{style}><b>{e(s["name"])}</b>'
                     f'<span>{n} game{"s" if n != 1 else ""} on the board</span></a>')
    return '<div class="ltiles">' + "".join(tiles) + "</div>" if tiles else ""


def slugify(t):
    t = re.sub(r"<[^>]+>", "", html.unescape(t)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "section"


def add_toc(body):
    toc, used = [], set()

    def fix(m):
        attrs, inner = m.group(1), m.group(2)
        hid = slugify(inner)
        while hid in used:
            hid += "-2"
        used.add(hid)
        toc.append((hid, re.sub(r"<[^>]+>", "", inner)))
        return f'<h2{attrs} id="{hid}">{inner}</h2>' if "id=" not in attrs else m.group(0)

    body = re.sub(r"<h2([^>]*)>(.*?)</h2>", fix, body, flags=re.S)
    box = ("" if len(toc) < 3 else '<nav class="toc"><p class="toc-h">In this explainer</p><ol>'
           + "".join(f'<li><a href="#{i}">{e(t)}</a></li>' for i, t in toc) + "</ol></nav>")
    return body, box


def read_min(body):
    return max(1, round(len(re.sub(r"<[^>]+>", " ", body).split()) / 220))


def share_row(title, path):
    from urllib.parse import quote
    u, t = quote(SITE["url"] + path, safe=""), quote(title, safe="")
    links = (("X", f"https://x.com/intent/post?url={u}&text={t}"),
             ("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={u}"),
             ("Reddit", f"https://www.reddit.com/submit?url={u}&title={t}"),
             ("Email", f"mailto:?subject={t}&body={u}"))
    return ('<p class="share"><span>Pass it along:</span> '
            + " ".join(f'<a href="{h}" target="_blank" rel="noopener">{n}</a>' for n, h in links) + "</p>")


def today_box(latest):
    if not latest:
        return ""
    n = sum(len(s["games"]) for s in latest["sports"])
    return (f'<aside class="todaybox"><span class="kicker">Today\'s edition</span>'
            f'<strong>{long_date(latest["date"])}: {n} games on the board</strong>'
            f'<span>{e(summary(latest).split(". ")[0].rstrip("."))}.</span>'
            f'<a href="/reports/{latest["date"]}/">Read the morning line &rarr;</a></aside>')


SAFE_NOTE = ('<p class="note"><strong>Information only, 21+.</strong> Lines change constantly and may differ '
             "where you are. Sports betting is not legal in every state. We do not take bets or link to "
             f'sportsbooks. If gambling stops being fun, call or text <strong>{e(SITE["help_line"])}</strong> '
             'or see our <a href="/responsible-gambling/">responsible gambling page</a>.</p>')


# ---------------------------------------------------------------- report page
def source_line(r):
    srcs = []
    if "odds_api" in r["sources"]:
        srcs.append("consensus (median) of the US sportsbooks listed by The Odds API")
    if "espn" in r["sources"]:
        srcs.append("the line published on ESPN's public scoreboard")
    return "Lines are the " + " and ".join(srcs) + "."


def row_attrs(league, g):
    return f'data-lg="{e(league)}" data-home="{e(g["home"])}" data-away="{e(g["away"])}"'


def ago(iso):
    d = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    return "today" if d < 1 else ("yesterday" if d == 1 else f"{d} days ago")


def views(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else (f"{n / 1e3:.0f}K" if n >= 1e3 else str(n))


def video_card(v):
    return (f'<a class="vid" href="https://www.youtube.com/watch?v={e(v["id"])}" target="_blank" rel="noopener" '
            f'data-lg="{e(v["league"])}" data-title="{e(v["title"])}">'
            f'<span class="thumb"><img src="https://i.ytimg.com/vi/{e(v["id"])}/mqdefault.jpg" alt="" loading="lazy" '
            'width="320" height="180"><span class="play" aria-hidden="true">&#9654;</span></span>'
            f'<span class="vt">{e(v["title"])}</span>'
            f'<span class="vm">{e(LEAGUE_NAME.get(v["league"], v["league"].upper()))} · {views(v["views"])} views · {ago(v["published"])}</span></a>')


def highlights_aside(limit=8):
    if not HIGHLIGHTS:
        return ""
    return ('<aside class="side"><h2>Around the league</h2>'
            '<p class="muted small">The most-watched highlights from the official league channels this week.</p>'
            '<div class="vids">' + "".join(video_card(v) for v in HIGHLIGHTS[:limit]) + "</div></aside>")


YOUR_TEAM = '<section id="yourteam" class="yourteam" hidden></section>'


def team_picker():
    groups = []
    for lg in ("nfl", "nba", "nhl", "mlb"):
        btns = "".join(f'<button type="button" data-team="{t["id"]}" style="--c:{t["primary"]}">{e(t["name"])}</button>'
                       for t in TEAMS if t["league"] == lg)
        groups.append(f'<div class="pg"><h3>{LEAGUE_NAME.get(lg, lg.upper())}</h3>{btns}</div>')
    return ('<details class="picker"><summary><span id="myteam-label">Pick your team</span></summary>'
            '<div class="picker-panel"><p class="small muted">Pick a team and the paper prints in its colors, '
            'with its games and highlights first. Saved on this device only.</p>'
            + "".join(groups) + '<button type="button" class="clear" data-team="">Clear my team</button></div></details>')


def movers_table(movers, limit=8):
    if not movers:
        return ('<p class="muted">No line moves yet. Movement is measured from the first line we record, '
                "so this fills in from the second day of tracking.</p>")
    rows = []
    for m in movers[:limit]:
        if m["kind"] == "spread":
            o, n = spread_label(m, m["open_spread"]), spread_label(m)
        else:
            o, n = f"O/U {pts(m['open_total'], False)}", f"O/U {pts(m['total'], False)}"
        rows.append(f"<tr {row_attrs(LEAGUE_KEY.get(m['sport'], ''), m)}><td class=\"g\"><span class=\"lg\">{e(m['sport'])}</span>{e(nick(m['away']))} @ {e(nick(m['home']))}"
                    f"<span class=\"sub\">{game_time(m['commence'])}</span></td>"
                    f"<td data-l=\"Market\">{m['kind'].title()}</td><td data-l=\"Opened\">{o}</td><td data-l=\"Now\"><strong>{n}</strong></td>"
                    f"<td class=\"num\" data-l=\"Moved\">{pts(m['size'], False)} pt{"" if m["size"] == 1 else "s"}</td></tr>")
    return ('<div class="tbl"><table><thead><tr><th>Game</th><th>Market</th><th>Opened</th><th>Now</th>'
            '<th class="num">Pts</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def sport_table(s, day=""):
    rows = []
    for g in s["games"]:
        best = ""
        if g.get("best_home") and g.get("best_away"):
            best = (f'<span class="sub">Best: {e(nick(g["away"]))} {ml(g["best_away"]["price"])} '
                    f'({e(g["best_away"]["book"])}), {e(nick(g["home"]))} {ml(g["best_home"]["price"])} '
                    f'({e(g["best_home"]["book"])})</span>')
        disagree = ""
        rng = g.get("spread_range")
        if rng and rng[1] - rng[0] >= 1:
            disagree = f'<span class="sub flag">Books split: {pts(rng[0])} to {pts(rng[1])}</span>'
        rows.append(
            f"<tr {row_attrs(s['key'], g)}><td class=\"t\">{game_time(g['commence'])}</td>"
            f"<td class=\"g\"><strong>{e(g['away'])}</strong><span class=\"sub\">at {e(g['home'])}</span>{best}</td>"
            f"<td data-l=\"Spread\"><span>{spread_label(g)}{disagree}<span class=\"sub\">Move {move_html(g['move_spread'], 's')}</span></span></td>"
            f"<td data-l=\"Total\"><span>{pts(g['total'], False)}<span class=\"sub\">Move {move_html(g['move_total'], 't')}</span></span></td>"
            f"<td data-l=\"ML away / home\">{ml(g['ml_away'])} / {ml(g['ml_home'])}</td>"
            f"<td data-l=\"Win % away / home\">{pct(g['prob_away'])} / {pct(g['prob_home'])}</td></tr>")
    return (f'<section class="league" id="{e(s["key"])}">{league_banner(s["key"], s["name"], day, s["games"])}'
            '<div class="tbl"><table><thead><tr><th>Time</th><th>Matchup</th><th>Spread</th><th>Total</th>'
            '<th>ML away / home</th><th>Win % away / home</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></section>")


def report_page(r, prev, nxt):
    jump = " · ".join(f'<a href="#{e(s["key"])}">{e(s["name"])}</a>' for s in r["sports"])
    stories = "".join(f"<li>{mover_sentence(m)}</li>" for m in r["movers"][:4])
    nav = '<nav class="pager">'
    nav += f'<a href="/reports/{prev}/">&larr; {short_date(prev)}</a>' if prev else "<span></span>"
    nav += f'<a href="/reports/{nxt}/">{short_date(nxt)} &rarr;</a>' if nxt else "<span></span>"
    nav += "</nav>"
    gen = datetime.fromisoformat(r["generated"]).astimezone(TZ).strftime("%-I:%M %p ") + TZ_LABEL
    return (
        '<div class="wrap layout"><article class="report">'
        f'<p class="kicker">The morning line</p><h1>{long_date(r["date"])}</h1>'
        f'<p class="opener">{e(opener(r))}</p>'
        f'<p class="lede">{e(summary(r))}</p>'
        f'<p class="meta">Lines captured at {gen}. {source_line(r)} '
        '<a href="/guides/how-to-read-betting-odds/">How to read this</a></p>'
        f"{YOUR_TEAM}{sponsor()}"
        + (f'<h2>The story on the board</h2><ul class="stories">{stories}</ul>' if stories else "")
        + f'<h2>The big movers since the opening line</h2>{movers_table(r["movers"])}'
        f"{ad_slot()}"
        + (f'<p class="jump">Jump to: {jump}</p>' if jump else "")
        + "".join(sport_table(s, r["date"]) for s in r["sports"])
        + '<p class="muted small">Spread shows the favorite. Totals are points or goals for both teams combined. '
        "Win % is the moneyline's implied probability with the bookmaker margin removed. "
        "Moves are measured from the first line we recorded for the game.</p>"
        f"{share_row('Odds report for ' + short_date(r['date']), '/reports/' + r['date'] + '/')}"
        f"{SAFE_NOTE}{newsletter()}{nav}{vault(r['date'])}</article>{highlights_aside(10)}</div>")


# ---------------------------------------------------------------- shared
def parse(path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    meta["slug"] = path.stem
    meta["body"] = body.strip()
    meta.setdefault("updated", meta.get("date", ""))
    return meta


TEAM_PICKER = team_picker()


def render(title, description, content, path, extra_head="", image=None):
    head = extra_head
    image = image if image in PHOTOS else "ebbets-opening-day"
    if image in PHOTOS:
        head += (f'<meta property="og:image" content="{SITE["url"]}/img/{image}.jpg">'
                 f'<meta name="twitter:image" content="{SITE["url"]}/img/{image}.jpg">')
    if SITE.get("adsense_client_id"):
        head += ('<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
                 f'?client={e(SITE["adsense_client_id"])}" crossorigin="anonymous"></script>')
    full = title if title == SITE["name"] else f"{title} | {SITE['name']}"
    out = TEMPLATE
    for k, v in {
        "{{title}}": e(full), "{{description}}": e(description), "{{canonical}}": SITE["url"] + path,
        "{{site_name}}": SITE["name"], "{{tagline}}": e(SITE["tagline"]), "{{extra_head}}": head,
        "{{content}}": content, "{{year}}": str(date.today().year),
        "{{contact_email}}": SITE["contact_email"], "{{help_line}}": e(SITE["help_line"]),
        "{{edition_date}}": datetime.now(TZ).strftime("%A, %B %-d, %Y"),
        "{{team_picker}}": TEAM_PICKER,
    }.items():
        out = out.replace(k, v)
    return out


def write(rel, text):
    dest = OUT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def guide_card(g):
    pic = img_tag(g["image"], "card-img", "(max-width: 640px) 100vw, 340px") if g.get("image") in PHOTOS else ""
    return (f'<a class="card" href="/guides/{g["slug"]}/">{pic}<span class="kicker">{e(g.get("category", "Guide"))}</span>'
            f'<h3>{e(g["title"])}</h3><p>{e(g.get("description", ""))}</p></a>')


def report_card(r):
    top = r["movers"][0] if r["movers"] else None
    line = re.sub(r"<[^>]+>", "", mover_sentence(top)) if top else summary(r)
    n = sum(len(s["games"]) for s in r["sports"])
    return (f'<a class="row" href="/reports/{r["date"]}/"><span class="d">{short_date(r["date"])}</span>'
            f'<span class="x">{e(line)}</span><span class="n">{n} games</span></a>')


# ---------------------------------------------------------------- main
def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(ROOT / "static", OUT, dirs_exist_ok=True)

    reports = [json.loads(p.read_text()) for p in sorted((ROOT / "data" / "reports").glob("*.json"))]
    dates = [r["date"] for r in reports]
    for i, r in enumerate(reports):
        prev = dates[i - 1] if i else None
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        leagues = ", ".join(s["name"] for s in r["sports"])
        title = f"Odds report for {short_date(r['date'])}" + (f": {leagues}" if leagues else "")
        ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": title,
              "datePublished": r["generated"], "dateModified": r["generated"],
              "publisher": {"@type": "Organization", "name": SITE["name"]}}
        write(f"reports/{r['date']}/index.html", render(
            title, summary(r), report_page(r, prev, nxt), f"/reports/{r['date']}/",
            f'<script type="application/ld+json">{json.dumps(ld)}</script><meta property="og:type" content="article">'))

    write("reports/index.html", render(
        "Report archive", "Every daily odds and line-movement report from Sportsbet Report.",
        '<section class="wrap"><h1>Report archive</h1><div class="rows">'
        + ("".join(report_card(r) for r in reversed(reports)) or '<p class="muted">The first report is on its way.</p>')
        + "</div></section>", "/reports/"))

    guides = [parse(p) for p in (ROOT / "content" / "guides").glob("*.html")]
    guides = [g for g in guides if g.get("draft", "").lower() != "true"]
    guides.sort(key=lambda g: (g.get("order", "9"), g["title"]))
    latest = reports[-1] if reports else None
    for gi, g in enumerate(guides):
        body, toc = add_toc(shortcodes(g["body"]))
        nxt_g = guides[(gi + 1) % len(guides)] if len(guides) > 1 else None
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": g["title"],
              "description": g.get("description", ""), "datePublished": g.get("date"), "dateModified": g["updated"],
              "publisher": {"@type": "Organization", "name": SITE["name"]}}
        content = (f'<article class="post"><p class="kicker">{e(g.get("category", "Guide"))}</p>'
                   f'<h1>{e(g["title"])}</h1><p class="lede">{e(g.get("description", ""))}</p>'
                   f'<p class="meta">{read_min(g["body"])} min read</p>'
                   f'{figure(g.get("image", ""), "photo cover", eager=True)}{toc}'
                   f'{ad_slot()}<div class="prose">{body}</div>{today_box(latest)}'
                   f'{share_row(g["title"], "/guides/" + g["slug"] + "/")}{SAFE_NOTE}{newsletter()}'
                   + (f'<a class="nextread" href="/guides/{nxt_g["slug"]}/"><span>Next explainer &rarr;</span>{e(nxt_g["title"])}</a>' if nxt_g else "")
                   + '<h2 class="more">More explainers</h2><div class="grid">'
                   + "".join(guide_card(x) for x in guides if x["slug"] != g["slug"]) + "</div></article>")
        write(f"guides/{g['slug']}/index.html", render(
            g["title"], g.get("description", ""), content, f"/guides/{g['slug']}/",
            f'<script type="application/ld+json">{json.dumps(ld)}</script><meta property="og:type" content="article">',
            g.get("image")))
    write("guides/index.html", render(
        "Betting explainers", "Plain-English explainers on odds, spreads, totals, line movement and implied probability.",
        '<section class="wrap"><h1>Explainers</h1><p class="lede">How odds work, in plain English.</p>'
        '<div class="grid">' + "".join(guide_card(g) for g in guides) + "</div></section>", "/guides/"))

    # Home
    latest = reports[-1] if reports else None
    if latest:
        top = (f'<p class="kicker">Today\'s morning line · {long_date(latest["date"])}</p>'
               f'<p class="opener">{e(opener(latest))}</p>'
               f'<h1>{e(summary(latest).split(". ")[0].rstrip("."))}.</h1>'
               f'<p class="lede">{e(". ".join(summary(latest).split(". ")[1:]))}</p>'
               f'<a class="btn" href="/reports/{latest["date"]}/">Read today\'s full report</a>')
        movers = (f'<h2>Today\'s board</h2>{league_tiles(latest)}'
                  f'<h2>The big movers</h2>{movers_table(latest["movers"], 6)}')
    else:
        top = ('<p class="kicker">The morning line</p><h1>The sports page you grew up with, back on the kitchen table.</h1>'
               '<p class="lede">Remember checking the lines in the Sunday paper before kickoff? Every morning we do it for you: '
               "the spreads, totals and moneylines for the NFL, college football, NBA, NHL and MLB, which numbers moved "
               "overnight, and what they say about each team's chances. The first edition runs the morning after launch.</p>"
               '<a class="btn" href="/guides/how-to-read-betting-odds/">Start with how odds work</a>')
        movers = ""
    hero_pic = ""
    if "ebbets-opening-day" in PHOTOS:
        hero_pic = (f'<figure class="hero-photo">{img_tag("ebbets-opening-day", "", "(max-width: 900px) 100vw, 860px", eager=True)}'
                    f'<figcaption>{e(PHOTOS["ebbets-opening-day"]["caption"])} '
                    f'<span class="credit">{credit(PHOTOS["ebbets-opening-day"])}</span></figcaption></figure>')
    home = (f'<section class="hero"><div class="wrap">{hero_pic}{top}</div></section>'
            f'<div class="wrap layout"><section>{YOUR_TEAM}{sponsor()}{movers}'
            + (f'<h2>Recent editions</h2><div class="rows">{"".join(report_card(r) for r in reversed(reports[-7:]))}</div>'
               '<p><a href="/reports/">Full archive &rarr;</a></p>' if reports else "")
            + f'{newsletter()}<h2>From the explainer desk</h2><div class="grid">{"".join(guide_card(g) for g in guides[:6])}</div>'
            f"{vault(latest['date'] if latest else date.today().isoformat(), 3)}{ad_slot()}{SAFE_NOTE}</section>{highlights_aside(8)}</div>")
    write("index.html", render(SITE["name"], SITE["description"], home, "/"))

    pages = list((ROOT / "content" / "pages").glob("*.html"))
    for p in pages:
        pg = parse(p)
        write(f"{pg['slug']}/index.html", render(
            pg["title"], pg.get("description", ""),
            f'<article class="post"><h1>{e(pg["title"])}</h1><div class="prose">{shortcodes(pg["body"])}</div></article>',
            f"/{pg['slug']}/"))

    if PHOTOS:
        rows = "".join(f'<li><img src="/img/{k}-sm.jpg" alt="" loading="lazy"><div><strong>{e(p["caption"])}</strong>'
                       f'<br>{credit(p)}</div></li>' for k, p in PHOTOS.items())
        write("photo-credits/index.html", render(
            "Photo credits", "Where the photographs on Sportsbet Report come from.",
            '<article class="post"><h1>Photo credits</h1><p>Our photographs come from Wikimedia Commons and are public '
            'domain or shared under Creative Commons licenses. Thank you to every photographer and archive below. '
            'We resize the images for the web and do not otherwise change them.</p>'
            f'<ul class="credits">{rows}</ul></article>', "/photo-credits/"))
        pages_extra = ["/photo-credits/"]
    else:
        pages_extra = []

    write("404.html", render("Page not found", "", '<section class="wrap"><h1>Page not found</h1>'
          '<p><a href="/reports/">See the latest reports</a></p></section>', "/404"))

    urls = ["/", "/reports/", "/guides/"] + [f"/reports/{d}/" for d in dates] + \
           [f"/guides/{g['slug']}/" for g in guides] + [f"/{p.stem}/" for p in pages] + pages_extra
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"  <url><loc>{SITE['url']}{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE['url']}/sitemap.xml\n")
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = "".join(
        f"<item><title>Odds report for {short_date(r['date'])}</title><link>{SITE['url']}/reports/{r['date']}/</link>"
        f"<guid>{SITE['url']}/reports/{r['date']}/</guid><description>{e(summary(r))}</description></item>"
        for r in reversed(reports[-20:]))
    write("feed.xml", f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
          f"<title>{e(SITE['name'])}</title><link>{SITE['url']}</link>"
          f"<description>{e(SITE['description'])}</description><lastBuildDate>{now}</lastBuildDate>"
          f"{items}</channel></rss>")
    if SITE.get("adsense_client_id"):
        pub = SITE["adsense_client_id"].replace("ca-", "")
        write("ads.txt", f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n")
    write("teams.json", json.dumps(TEAMS, separators=(",", ":")))
    write("highlights.json", json.dumps({"videos": HIGHLIGHTS}, separators=(",", ":"), ensure_ascii=False))
    print(f"Built {len(reports)} reports and {len(guides)} explainers into {OUT}")


if __name__ == "__main__":
    main()
