# Discord permissions and Worker secrets

## Runtime (what runs every day)

| Component | Discord permission needed | Why |
|---|---|---|
| `discord.js` Worker (`/scout`, `/verify`) | none beyond the `applications.commands` scope | it only reads `published.json` and edits its own deferred reply; role assignment was removed |
| `worker.js` Worker (Telegram) | none (not a Discord component) | renders `published.json` |
| Feed publisher (GitHub Actions, `project_scout.py`) | none — posts through channel **webhooks** | a webhook can post only into its own channel |
| Weekly job (`discord_weekly.py`) | View Channels, Read Message History, Send Messages, Add Reactions | reads 🙋 reactions and #show-your-work links, posts summaries |

The bot role must sit **below** TLDP Staff in the role list, and **Administrator is not required** for anything. Bot
privileges stay under staff privileges so a leaked bot token can never out-rank a staff member.

## Setup (run once, by a staff member, from their own machine)

`discord_setup.py` needs Manage Channels, Manage Roles, Manage Webhooks, Send Messages, Manage Messages (to pin the
welcome post). Grant them for the setup run and remove Manage Roles / Manage Channels afterwards, or run setup with a
staff account's temporary role. The setup script is the only place these permissions are used.

## What changed and why

- **Live GitHub / GitLab / Devpost / MLH searches were removed from both Workers.** A live search returned repos that had
  never been through screening, so a student typing a keyword could bypass every check. Both Workers now render only
  `published.json`, which the publisher writes after each repo passes the gate. If the snapshot is missing, marked
  degraded, or has no screening in 36 hours, every repo lane replies with a fixed pause message.
- **Name-based `/verify` was removed.** Matching a typed first/last name against a roster proves nothing and leaked
  roster membership through guesses. `/verify` now only tells the student that staff enroll them. No `ROSTER` secret,
  no bot token on the Worker, no role assignment from the Worker.
- **Every message carries `allowed_mentions: {parse: []}`**, third-party text is escaped, and a link is rendered only for
  `https://` URLs on an allowlist of known hosts; anything else is shown as plain text.
- **Every interaction** must carry a valid Ed25519 signature, a timestamp within 5 minutes, the configured guild id,
  a known command with known options (keywords ≤ 60 chars, safe characters), and a caller holding the TLDP Student or
  TLDP Staff role. Duplicate interaction ids and more than 6 requests per user per minute are refused. Replay and
  rate-limit state is per Worker isolate (best effort); a KV namespace or Durable Object is the upgrade if abuse appears.

## Secrets per Worker

| Worker | Secrets | Notes |
|---|---|---|
| `project-scout-discord` (`wrangler.discord.toml`) | `DISCORD_PUBLIC_KEY`, `DISCORD_APP_ID`, `DISCORD_GUILD_ID`, `STUDENT_ROLE_ID`, `STAFF_ROLE_ID` | all required; a missing one fails closed |
| `project-scout-bot` (`wrangler.toml`) | `TELEGRAM_BOT_TOKEN`, `WEBHOOK_SECRET`, optional `OWNER_CHAT_ID` | `WEBHOOK_SECRET` is now required |

Removed from both: `GITHUB_TOKEN`, `ROSTER`, `DISCORD_BOT_TOKEN`, `MAJOR_ROLES`.

Deploying these changes is a separate, approved step (`npx wrangler deploy …`) and requires re-running
`register_discord.py` because the `/verify` options changed.
