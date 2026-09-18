# Project Scout

Telegram bot that pulls **project ideas, open-source contribution opportunities and
research code from GitHub** for students majoring in Quant, Finance/FinTech,
Software Engineering, Cybersecurity, and Data Analytics.

Four lanes per major:

| Lane | Signal | GitHub query shape |
|---|---|---|
| 🧪 Build this | Repos **created in the last 2 weeks** that already have ⭐10+ = what people are building right now. Steal the idea, build your own. | `<terms> created:>=… stars:>=10` |
| 🤝 Contribute | Active repos with **open "good first issue" tickets** (⭐50+, pushed in the last 30 days). Link goes straight to the issue list. | `<anchor> good-first-issues:>0 pushed:>=…` |
| 🔬 Research | Fresh repos whose README **cites arXiv** = paper code to reproduce, extend, or join. | `"<field>" arxiv in:readme created:>=…` |
| 🤗 Hugging Face | Models, datasets and Spaces students can build **on top of** — a dataset to analyse, a model to fine-tune, a Space to duplicate. Link-screened, **not** code-scanned (see below). | HF Hub API, `sort=likes`, short single-word terms per major |

Hugging Face rows also carry an **industry label** (🏥 healthcare · 🏦 finance · 🛒 retail · 🏨 hospitality · 🎮 gaming
· 📱 social media · 🎓 education · 🏛 public sector) read off the item's own card text, and are grouped by it inside the section — no extra API call, and
an item that matches nothing is simply unlabelled. The GitHub lanes have no industry axis: every industry there would
be another search against the 30/min limit and the `SEARCH_BUDGET`.

## Two halves, one gate

Discovery is separated from what students see, and **every** student-visible path goes through the same gate
(`gate.eligible`). See **`docs/SCREENING.md`** for the full model and the honest limits.

| Part | Where it runs | What it does |
|---|---|---|
| `project_scout.py --discover` → `--publish` | GitHub Actions, two jobs (`.github/workflows/digest.yml`) | **screen** (untrusted, no secrets): search GitHub, screen every candidate through the gate (clone + Semgrep + deep vet + link screen), write `build/`. **publish** (secrets): re-validate offline, send, commit `published.json`/`screening.json`/`seen.json`/`index.json`. |
| `cloudflare-webhook/worker.js`, `discord.js` | Cloudflare Workers | Render the pre-screened `published.json` snapshot only. **No live GitHub/GitLab search.** Fail closed (pause) if screening is stale, degraded, or missing. |

`published.json` also carries a `huggingface` section, screened by `hf.py` (metadata + README, no clone) and
re-validated at publish time like every other section.

`published.json` (served to the Workers from the repo) contains only repositories that passed the gate and are inside
the 30-day freshness window; each row carries its screening record (reviewed SHA + expiry) and the label
"Automated checks completed; not a safety guarantee." stdlib-only Python; the Workers make no GitHub calls.

Status any time: `python gate.py --status`.

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
- **Students never hit the API for normal searches.** Every run merges everything it found into
  `index.json` (committed; ~430 rows, 45-day TTL, curated sets refreshed weekly, full rebuild every
  Monday). The Workers read that file from `raw.githubusercontent.com` (a CDN, no rate limit),
  cached 30 min, and only fall back to the live API, one request at a time, for a keyword the
  index can't answer.
- Give the bot its own identity: a machine account (e.g. `tldp-project-scout`) with a fine-grained
  token that has no permissions, set as `GITHUB_TOKEN` on each Worker and as a repo secret used by
  the workflows. If anything is ever limited, it's that account, not yours.

## Safety: the one publishing gate

Scam and malware repos show up in GitHub search. **Discovery** finds candidates; **screening** decides what students
see; the two are separate files and separate CI jobs. Full detail and honest limits: **`docs/SCREENING.md`**; scanner
choices and coverage: **`docs/SCANNERS.md`**.

A repo is published only if `gate.eligible` says yes: **not quarantined** (`quarantine.json`), a **passing screening
record** whose reviewed commit SHA matches and has not expired, adequate scan **coverage** for its language, and — for
a fresh row — **pushed within 30 days**. Anything that fails, times out, is incomplete, or is unsupported is
**withheld**; nothing is silently downgraded. If nothing qualifies, a self-contained synthetic project idea is offered
instead of an unchecked repo.

Screening (`gate.screen_one`, only stage that touches an untrusted repo) runs, per candidate:

1. **Quarantine** — named incident repos and clone-name patterns can never return.
2. **Content policy** (`gate.py`) — prohibited wording (drainers, stealers, phishing kits, cracked software) fails;
   ambiguous dual-use offensive tooling is kept out of the general feed; curated security tools are not flagged.
3. **Deep vet** (`vet.py`) — root binaries, README-only shells, bought stars, brand-new owners, clone farms, Scorecard.
4. **Link + install screening** (`links.py`) — download hosts, executable links, archive passwords, "disable your
   antivirus", `curl | sh` all block; shorteners warn. Repo text is data, never instructions. Optional shortener
   resolution is **SSRF-guarded** (refuses private/loopback/link-local/metadata IPs, re-validates every redirect hop).
5. **Isolated code scan** (`scan.py`) — clone at the pinned commit into an empty-HOME throwaway dir, no hooks, no LFS,
   no submodules, non-https disabled; **nothing in the repo is executed**. Semgrep static-only with
   `semgrep-rules/malware.yml` + `p/security-audit` + `p/secrets`, timeouts and caps. Any malware-rule or secrets hit
   withholds; matched text is discarded so a discovered secret never lands in a report or message.

Records (`screening.json`) carry identity, reviewed SHA, scan time, scanner + rule versions, coverage and result, and
**expire** (14 days fresh, 30 curated); a changed commit forces a re-screen. The Cloudflare Workers render only
`published.json` and **pause** if screening is stale. `python vet.py` still writes the private `docs/vetting-report.md`;
`purge_posts.py` edits already-posted Discord messages if a rule is added later.

### Hugging Face (`hf.py`) — screened, but never code-scanned

Hugging Face repos are git repos, but HF's git server ignores `--filter=blob:limit`: cloning `google/flan-t5-small`
pulls **1.3 GB** of weights, so screening models the way `scan.py` screens GitHub repos is not viable. HF items are
instead screened from public metadata **pinned to the commit SHA the API reports**, and they never claim a code scan —
the feed line says *"link-screened metadata + README, not code-scanned"*.

Withheld: private / disabled / **gated**, anything failing the same `gate.content_policy` the repo feed uses, no
license, below the likes floor (models 50, datasets/Spaces 25), untouched for a year, no usable English description,
throwaway-looking owner, an **executable or archive** in the file list, **pickle-only weights** (no
`.safetensors`/`.gguf`/`.onnx`) or a dataset shipping `.pkl`, and any blocking `links.py` finding in the README — or,
for a Space, in the app file it actually runs. A README that exists but cannot be read is *incomplete* → withheld.

Published with a **warning**, not withheld: custom code (`.py`) in a model or dataset repo — that is what
`trust_remote_code=True` costs, and the student is told. Flip `hf.ALLOW_CUSTOM_CODE = False` to withhold instead;
`hf.REQUIRE_SAFETENSORS = False` relaxes the pickle rule (it currently withholds popular pickle-only models).

Records expire after 14 days like the repo gate, `hf.eligible()` re-checks them offline at publish time, and
`dedupe_posts.py` fingerprints HF links alongside GitHub ones. Self-check: `python hf.py` · live preview:
`python hf.py --preview`.

Students can pull the lane themselves, so nobody has to ask staff for a re-query: **`/scout lane:Hugging Face`** on
Discord (re-register the command once with `register_discord.py` so the new choice appears) and **`/hf <major>`** on
Telegram — aliases `/huggingface`, `/models`, `/datasets`, `/spaces`. The Workers render the same pre-screened
`published.json` snapshot, re-check each row's record (passing screen, 40-hex pinned SHA, not expired) before it is
shown, and pause with everything else when screening is stale. `huggingface.co` is on the Worker link allowlist;
`node --test cloudflare-webhook/test_workers.mjs` covers the lane.

## Enrollment (roster-gated, no name oracle)

Your roster of student names is the distribution list, not a self-typed password. `python enroll.py --invites` mints
one unique, single-use, 7-day Discord invite per roster entry (into gitignored `roster_invites_local.json`, never
printed); staff DM each student their link. `python enroll.py --grant` gives the Student role to everyone who joined.
`/verify` no longer checks names. Stronger SSO / signed-token options are documented but not enabled.

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
