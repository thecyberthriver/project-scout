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

## GitHub rate-limit safety

GitHub allows 30 search requests per minute with a token (10 without) and can temporarily
block an account or IP that keeps hammering after a 403. The feed is built to never get there:

- `SEARCH_BUDGET` (default 26) caps searches per run and `SEARCH_SPACING` (2.5 s) keeps the rate
  under 24/min regardless. When the budget is spent the run stops cleanly; majors rotate order
  each run so nothing is starved.
- On a 403/429 the run waits exactly as long as `Retry-After` / `X-RateLimit-Reset` says, once,
  then stops. It never loops. Your private Telegram bot gets an alert with the remaining quota.
- Contribute and Research lanes alternate runs; SWE's five languages rotate three per run.
- Every run ends by printing the remaining search quota (free call) in the Actions log.
- The Workers cache every result 15 min and, after one 403/429, refuse further GitHub calls for
  two minutes ("try again in 2 minutes") so a classroom can't trigger a block by retrying.
- Add a no-permissions fine-grained token as `GITHUB_TOKEN` on each Worker to move student
  searches from the shared anonymous limit to the token's own limit.

## Tuning

`MAJORS` (search terms + anchor word per major), `LANES` (window, star floor, picks)
and `RESEARCH_ANCHOR` live at the top of `project_scout.py`; the same tables are
mirrored in `worker.js`.

## Students on Discord (slash commands + channel feed)

`cloudflare-webhook/discord.js` is a second Worker that serves a `/scout` slash
command (Ed25519-verified Discord Interactions endpoint, deferred reply, same
GitHub search + 15-min cache as the Telegram Worker). The 2-hourly feed is
mirrored into a channel through a plain Discord webhook.

1. **Create the app:** discord.com/developers → New Application "Project Scout" →
   copy **Application ID** and **Public Key** (General Information) → Bot tab →
   Reset Token → copy the **bot token**.
2. **Deploy + secrets:**
   ```
   cd cloudflare-webhook
   npx wrangler deploy -c wrangler.discord.toml
   npx wrangler secret put DISCORD_PUBLIC_KEY -c wrangler.discord.toml
   npx wrangler secret put DISCORD_APP_ID    -c wrangler.discord.toml
   ```
3. **Register the command:** `DISCORD_APP_ID=… DISCORD_BOT_TOKEN=… python register_discord.py`
4. **Point Discord at the Worker:** General Information → Interactions Endpoint URL =
   `https://project-scout-discord.<subdomain>.workers.dev` → Save (Discord pings it to verify).
5. **Invite to your server:** OAuth2 → URL Generator → scope `applications.commands` → open the URL.
6. **Feed channel:** channel settings → Integrations → Webhooks → New Webhook → copy URL →
   `gh secret set DISCORD_WEBHOOK_URL -b "<url>"`. Every alert now lands there too.

Discord vs Telegram: Discord server roles let you gate who sees the feed and who
can run `/scout`; the Telegram campus bot answers anyone who finds it.

### Provisioning the private TLDP server

`discord_setup.py` builds the whole layout in one run once the bot is invited
(`https://discord.com/oauth2/authorize?client_id=<APP_ID>&scope=bot+applications.commands&permissions=805317681&guild_id=<GUILD_ID>`):
categories + channels, read-only #announcements, "TLDP Staff" role, Medium
verification, @everyone stripped of Create Invite, one webhook per feed channel
(printed as the `DISCORD_WEBHOOKS` secret), a 45-use / 7-day invite and a pinned
welcome post. With `DISCORD_WEBHOOKS` set, each 2-hourly section lands in its own
channel (#quant-projects … #open-source-orgs).

### Student loop (Discord)

`discord_weekly.py` + `.github/workflows/weekly.yml`: Friday it posts the 🙋 claims of the week
to #find-a-team, a leaderboard of links posted in #show-your-work, and open hackathons (Devpost)
to #announcements; Monday it reminds you (private Telegram) to pin a "pick of the week".
`/verify name: major:` (Discord) matches the student against the `ROSTER` Worker secret (JSON
array of names — never commit it) and grants the "TLDP Student" + major roles that unlock the
gated categories. `python discord_setup.py --invites 45` prints single-use invite links.
