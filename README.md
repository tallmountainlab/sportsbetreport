# sportsbetreport.com

Daily odds and line-movement report. Static site, rebuilt automatically every morning.

- `fetch_odds.py` – pulls lines (The Odds API if the `ODDS_API_KEY` secret is set, otherwise ESPN's public scoreboard), tracks movement in `data/lines/`, writes `data/reports/YYYY-MM-DD.json`
- `build.py` – zero-dependency builder, writes `public/` (reports, archive, explainers, pages, sitemap, RSS)
- `content/guides/*.html` – evergreen explainers; `content/pages/*.html` – about, responsible gambling, disclosure, advertise, terms, privacy
- `site.json` – settings, sports list, monetization slots (empty = hidden; never a sportsbook link)
- `.github/workflows/daily-report.yml` – runs both scripts at 12:00 UTC daily and commits the result
- `.github/workflows/traffic.yml` + `scripts/fetch_traffic.py` – Sundays 09:17 UTC, saves 30 days of Cloudflare traffic to `data/traffic.json` (repo secrets `CF_API_TOKEN`, `CF_ZONE_ID`)

Host: Cloudflare Workers static assets (`wrangler.jsonc` serves `public/`). Connected to the repo with no build command and deploy command `npx wrangler deploy`; every push redeploys.
Run by hand: GitHub → Actions → Daily odds report → Run workflow.
Test without network: `python3 fetch_odds.py --from-dir DIR` (DIR holds saved API responses named `<sport>.json`).

## My team, highlights, photos
- `data/teams.json` – 124 NFL/NBA/NHL/MLB teams with colors; `static/team.js` re-colors the site and builds the "Your team" box (choice saved in the visitor's browser only).
- `scripts/fetch_highlights.py` – daily, reads the official league YouTube channel feeds (channels in `site.json` → `highlights`), writes `data/highlights.json`; the sidebar shows the most-watched of the last 10 days.
- Photos: `data/photo_queries.json` → "Fetch photo candidates" workflow (branch `photo-candidates`) → pick in `data/photos.json` → `scripts/prepare_photos.py <dir>` → `static/img/`. Credits page at `/photo-credits/`.
