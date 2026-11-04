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


def shortcodes(body):
    body = re.sub(r"\{\{tool:(\w+)\}\}", lambda m: tool(m.group(1)), body)
    return body.replace("{{ad}}", ad_slot()).replace("{{newsletter}}", newsletter()).replace("{{sponsor}}", sponsor())


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
        rows.append(f"<tr><td class=\"g\"><span class=\"lg\">{e(m['sport'])}</span>{e(nick(m['away']))} @ {e(nick(m['home']))}"
                    f"<span class=\"sub\">{game_time(m['commence'])}</span></td>"
                    f"<td data-l=\"Market\">{m['kind'].title()}</td><td data-l=\"Opened\">{o}</td><td data-l=\"Now\"><strong>{n}</strong></td>"
                    f"<td class=\"num\" data-l=\"Moved\">{pts(m['size'], False)} pt{"" if m["size"] == 1 else "s"}</td></tr>")
    return ('<div class="tbl"><table><thead><tr><th>Game</th><th>Market</th><th>Opened</th><th>Now</th>'
            '<th class="num">Pts</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def sport_table(s):
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
            f"<tr><td class=\"t\">{game_time(g['commence'])}</td>"
            f"<td class=\"g\"><strong>{e(g['away'])}</strong><span class=\"sub\">at {e(g['home'])}</span>{best}</td>"
            f"<td data-l=\"Spread\"><span>{spread_label(g)}{disagree}<span class=\"sub\">Move {move_html(g['move_spread'], 's')}</span></span></td>"
            f"<td data-l=\"Total\"><span>{pts(g['total'], False)}<span class=\"sub\">Move {move_html(g['move_total'], 't')}</span></span></td>"
            f"<td data-l=\"ML away / home\">{ml(g['ml_away'])} / {ml(g['ml_home'])}</td>"
            f"<td data-l=\"Win % away / home\">{pct(g['prob_away'])} / {pct(g['prob_home'])}</td></tr>")
    return (f'<section class="league" id="{e(s["key"])}"><h2>{e(s["name"])}</h2>'
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
        '<article class="report wrap">'
        f'<p class="kicker">The morning line</p><h1>{long_date(r["date"])}</h1>'
        f'<p class="opener">{e(opener(r))}</p>'
        f'<p class="lede">{e(summary(r))}</p>'
        f'<p class="meta">Lines captured at {gen}. {source_line(r)} '
        '<a href="/guides/how-to-read-betting-odds/">How to read this</a></p>'
        f"{sponsor()}"
        + (f'<h2>The story on the board</h2><ul class="stories">{stories}</ul>' if stories else "")
        + f'<h2>The big movers since the opening line</h2>{movers_table(r["movers"])}'
        f"{ad_slot()}"
        + (f'<p class="jump">Jump to: {jump}</p>' if jump else "")
        + "".join(sport_table(s) for s in r["sports"])
        + '<p class="muted small">Spread shows the favorite. Totals are points or goals for both teams combined. '
        "Win % is the moneyline's implied probability with the bookmaker margin removed. "
        "Moves are measured from the first line we recorded for the game.</p>"
        f"{SAFE_NOTE}{newsletter()}{nav}</article>")


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


def render(title, description, content, path, extra_head=""):
    head = extra_head
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
    }.items():
        out = out.replace(k, v)
    return out


def write(rel, text):
    dest = OUT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def guide_card(g):
    return (f'<a class="card" href="/guides/{g["slug"]}/"><span class="kicker">{e(g.get("category", "Guide"))}</span>'
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
    for g in guides:
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": g["title"],
              "description": g.get("description", ""), "datePublished": g.get("date"), "dateModified": g["updated"],
              "publisher": {"@type": "Organization", "name": SITE["name"]}}
        content = (f'<article class="post"><p class="kicker">{e(g.get("category", "Guide"))}</p>'
                   f'<h1>{e(g["title"])}</h1><p class="lede">{e(g.get("description", ""))}</p>'
                   f'{ad_slot()}<div class="prose">{shortcodes(g["body"])}</div>{SAFE_NOTE}{newsletter()}'
                   '<h2 class="more">More explainers</h2><div class="grid">'
                   + "".join(guide_card(x) for x in guides if x["slug"] != g["slug"]) + "</div></article>")
        write(f"guides/{g['slug']}/index.html", render(
            g["title"], g.get("description", ""), content, f"/guides/{g['slug']}/",
            f'<script type="application/ld+json">{json.dumps(ld)}</script><meta property="og:type" content="article">'))
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
        movers = f'<h2>The big movers</h2>{movers_table(latest["movers"], 6)}'
    else:
        top = ('<p class="kicker">The morning line</p><h1>The sports page you grew up with, back on the kitchen table.</h1>'
               '<p class="lede">Remember checking the lines in the Sunday paper before kickoff? Every morning we do it for you: '
               "the spreads, totals and moneylines for the NFL, college football, NBA, NHL and MLB, which numbers moved "
               "overnight, and what they say about each team's chances. The first edition runs the morning after launch.</p>"
               '<a class="btn" href="/guides/how-to-read-betting-odds/">Start with how odds work</a>')
        movers = ""
    home = (f'<section class="hero"><div class="wrap">{top}</div></section>'
            f'<section class="wrap">{sponsor()}{movers}'
            + (f'<h2>Recent editions</h2><div class="rows">{"".join(report_card(r) for r in reversed(reports[-7:]))}</div>'
               '<p><a href="/reports/">Full archive &rarr;</a></p>' if reports else "")
            + f'{newsletter()}<h2>From the explainer desk</h2><div class="grid">{"".join(guide_card(g) for g in guides[:6])}</div>'
            f"{ad_slot()}{SAFE_NOTE}</section>")
    write("index.html", render(SITE["name"], SITE["description"], home, "/"))

    pages = list((ROOT / "content" / "pages").glob("*.html"))
    for p in pages:
        pg = parse(p)
        write(f"{pg['slug']}/index.html", render(
            pg["title"], pg.get("description", ""),
            f'<article class="post"><h1>{e(pg["title"])}</h1><div class="prose">{shortcodes(pg["body"])}</div></article>',
            f"/{pg['slug']}/"))

    write("404.html", render("Page not found", "", '<section class="wrap"><h1>Page not found</h1>'
          '<p><a href="/reports/">See the latest reports</a></p></section>', "/404"))

    urls = ["/", "/reports/", "/guides/"] + [f"/reports/{d}/" for d in dates] + \
           [f"/guides/{g['slug']}/" for g in guides] + [f"/{p.stem}/" for p in pages]
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
    print(f"Built {len(reports)} reports and {len(guides)} explainers into {OUT}")


if __name__ == "__main__":
    main()
