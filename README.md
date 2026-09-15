# Project Scout

Telegram bot that pulls **project ideas from GitHub** for students majoring in
Quant, Finance/FinTech, Software Engineering, Cybersecurity, and Data Analytics.

The signal is simple: repos **created in the last few weeks that already have
stars** are what people are building right now. Steal the idea, build your own.

## Two halves

| Part | Where it runs | What it does |
|---|---|---|
| `project_scout.py` | GitHub Actions, every 2 hours (`.github/workflows/digest.yml`) | Near-real-time alerts: up to 3 fresh repos per major (created last 14 days, ⭐10+) that have not been sent before (`seen.json`, 60-day TTL). Sends nothing when nothing is new. |
| `cloudflare-webhook/worker.js` | Cloudflare Worker (Telegram webhook) | Instant `/quant` `/fintech` `/swe` `/cyber` `/data` [+ keywords] — queries the GitHub Search API live (last 90 days). |

No scraping, no third parties: everything comes from the public GitHub Search
API (10 req/min anonymous, 30 with a token). stdlib-only Python.

## Setup

1. BotFather → new bot → token.
2. Repo secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (`gh secret set NAME -b "<value>"`).
3. Worker: `cd cloudflare-webhook && npx wrangler deploy`, then `wrangler secret put`
   `TELEGRAM_BOT_TOKEN`, `WEBHOOK_SECRET`, `OWNER_CHAT_ID` (optional `GITHUB_TOKEN`).
4. `python set_webhook.py https://project-scout-bot.<subdomain>.workers.dev`
   (reads `../secrets_local.py`, untracked).

Local dry run: `python project_scout.py --preview`. Self-check: `--self-check`.

## Tuning

Edit `MAJORS` (same table in both files) to change search terms, or `FRESH_DAYS`,
`MIN_STARS`, `PER_MAJOR` at the top of `project_scout.py`.
