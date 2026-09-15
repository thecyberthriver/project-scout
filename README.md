# Project Scout

Telegram bot that pulls **project ideas, open-source contribution opportunities and
research code from GitHub** for students majoring in Quant, Finance/FinTech,
Software Engineering, Cybersecurity, and Data Analytics.

Three lanes per major:

| Lane | Signal | GitHub query shape |
|---|---|---|
| 🧪 Build this | Repos **created in the last 2 weeks** that already have ⭐10+ = what people are building right now. Steal the idea, build your own. | `<terms> created:>=… stars:>=10` |
| 🤝 Contribute | Active repos with **open "good first issue" tickets** (⭐50+, pushed in the last 30 days). Link goes straight to the issue list. | `<anchor> good-first-issues:>0 pushed:>=…` |
| 🔬 Research | Fresh repos whose README **cites arXiv** = paper code to reproduce, extend, or join. | `"<field>" arxiv in:readme created:>=…` |

## Two halves

| Part | Where it runs | What it does |
|---|---|---|
| `project_scout.py` | GitHub Actions, every 2 hours (`.github/workflows/digest.yml`) | Push alerts: anything new in any lane, de-duped for 60 days via `seen.json`. Sends nothing when nothing is new. Optional mirror to a Discord channel (`DISCORD_WEBHOOK_URL`). |
| `cloudflare-webhook/worker.js` | Cloudflare Worker (Telegram webhook) | Instant answers: `/quant` `/fintech` `/swe` `/cyber` `/data` [+ keywords], `/oss <major>`, `/research <major>` — queries the GitHub Search API live. |

No scraping, no third parties: everything comes from the public GitHub Search
API (10 req/min anonymous, 30 with a token). stdlib-only Python.

## Setup

1. BotFather → new bot → token.
2. Repo secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (`gh secret set NAME -b "<value>"`).
   Optional `DISCORD_WEBHOOK_URL` (channel → Integrations → Webhooks) to mirror alerts into Discord.
3. Worker: `cd cloudflare-webhook && npx wrangler deploy`, then `wrangler secret put`
   `TELEGRAM_BOT_TOKEN`, `WEBHOOK_SECRET`, `OWNER_CHAT_ID` (optional `GITHUB_TOKEN`).
   Delete `OWNER_CHAT_ID` to let any student DM the bot.
4. `python set_webhook.py https://project-scout-bot.<subdomain>.workers.dev`
   (reads `../secrets_local.py`, untracked).

Local dry run: `python project_scout.py --preview`. Self-check: `--self-check`.

## Tuning

`MAJORS` (search terms + anchor word per major), `LANES` (window, star floor, picks)
and `RESEARCH_ANCHOR` live at the top of `project_scout.py`; the same tables are
mirrored in `worker.js`.
