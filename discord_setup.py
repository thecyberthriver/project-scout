#!/usr/bin/env python3
"""
discord_setup.py — provision the private TLDP Students server in one run (idempotent-ish: skips
channels/roles that already exist by name). stdlib only.

  DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python discord_setup.py

Reads secrets_local.py as a fallback. Needs the bot invited with: Manage Server, Manage Roles,
Manage Channels, Manage Webhooks, Create Invite, Send/Manage Messages (permissions=805317681).

What it does:
  1. Server: verification level Medium (verified email), notifications = mentions only,
     @everyone loses "Create Invite" -> only you hand out the 45-use invite.
  2. Roles: "TLDP Staff" (admin, hoisted).
  3. Categories + channels (see LAYOUT). #announcements is read-only for students.
  4. One webhook per feed channel -> printed as JSON for the DISCORD_WEBHOOKS repo secret.
  5. A 45-use, 7-day invite on #welcome + a pinned welcome post.
"""
import json
import os
import sys
import urllib.request

try:
    import secrets_local as s
except ImportError:
    s = None
TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or getattr(s, "DISCORD_BOT_TOKEN", "")
GUILD = os.environ.get("DISCORD_GUILD_ID") or getattr(s, "DISCORD_GUILD_ID", "")
API = "https://discord.com/api/v10"
MAX_STUDENTS = 45

CREATE_INVITE, SEND_MESSAGES, ADMIN = 0x1, 0x800, 0x8

# category -> [(channel name, topic, feed key or None)]; feed key = key posted by project_scout.py
LAYOUT = {
    "📌 START HERE": [
        ("welcome", "Rules, how the bot works, and how to get the most out of this server.", None),
        ("announcements", "TLDP staff announcements. Read-only.", None),
        ("introductions", "Name · major · what you want to build this semester.", None),
    ],
    "🧪 PROJECT SCOUT FEED": [
        ("data-analytics", "Fresh data analytics repos, good-first-issues and paper code. Auto-posted every 2 h.", "data"),
        ("swe", "Fresh software projects, good-first-issues and paper code. Auto-posted every 2 h.", "swe"),
        ("cybersecurity", "Fresh cybersecurity repos, good-first-issues and paper code. Auto-posted every 2 h.", "cyber"),
        ("quant", "Fresh quant repos, good-first-issues and paper code. Auto-posted every 2 h.", "quant"),
        ("finance-fintech", "Fresh finance/fintech repos, good-first-issues and paper code. Auto-posted every 2 h.", "fintech"),
        ("project-management", "Fresh project-management tools, templates and good-first-issues. Auto-posted every 2 h.", "pm"),
        ("digital-marketing", "Fresh marketing/SEO/analytics repos and good-first-issues. Auto-posted every 2 h.", "marketing"),
        ("open-source-orgs", "Non-profit, public-sector and company repos you can contribute to — resume-ready. Auto-posted every 2 h.", "orgs"),
    ],
    "🤝 COLLABORATE": [
        ("scout-search", "Run /scout here: /scout major:Cyber · lane:Contribute · keywords:honeypot", None),
        ("find-a-team", "Post the project you picked and who you need. Teams of 2-4 work best.", None),
        ("show-your-work", "Merged PRs, demos, repos, resume lines. Celebrate wins here.", None),
        ("help", "Stuck on git, a PR, an environment? Ask here.", None),
        ("general-chat", "Everything else.", None),
    ],
}
VOICE = [("🎧 STUDY ROOMS", ["Study Room 1", "Study Room 2"])]

WELCOME = """**Welcome to TLDP Students** 🎓

This is a private server for the 45 TLDP students. Please don't share the invite link.

**What's here**
• **#data-analytics, #swe, #cybersecurity, #quant, #finance-fintech, #project-management, #digital-marketing** — every 2 hours the Project Scout bot posts fresh GitHub repos for your major: things to build, open-source repos with *good first issues*, and new paper code.
• **#open-source-orgs** — non-profit, public-sector and company repos that welcome contributors, with a LinkedIn link and a ready-to-paste resume line.
• **#scout-search** — search on demand: `/scout major:Cyber`, `/scout lane:Contribute major:Data`, `/scout lane:Orgs keywords:python`.
• **#find-a-team** → pick a repo, post it, find 1-3 teammates.
• **#show-your-work** → post merged PRs, demos and the resume line you earned.

**Start now:** introduce yourself in #introductions, then pick one repo this week and open one good-first-issue PR.
"""


def api(method: str, path: str, body=None, ok=(200, 201, 204)):
    req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json",
                                          "User-Agent": "project-scout (github.com/thecyberthriver/project-scout, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            assert r.status in ok, r.status
            return json.load(r) if r.status != 204 else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}")


def main() -> int:
    if not TOKEN or not GUILD:
        print(__doc__)
        return 1
    g = api("GET", f"/guilds/{GUILD}")
    print("guild:", g["name"])

    # 1. server hardening
    api("PATCH", f"/guilds/{GUILD}", {"verification_level": 2, "default_message_notifications": 1})
    roles = {r["name"]: r for r in api("GET", f"/guilds/{GUILD}/roles")}
    everyone = roles["@everyone"]
    perms = int(everyone["permissions"]) & ~CREATE_INVITE
    api("PATCH", f"/guilds/{GUILD}/roles/{everyone['id']}", {"permissions": str(perms)})
    print("server: verification=medium, @everyone cannot create invites")

    # 2. staff role
    if "TLDP Staff" not in roles:
        api("POST", f"/guilds/{GUILD}/roles", {"name": "TLDP Staff", "permissions": str(ADMIN), "hoist": True, "color": 0x5865F2, "mentionable": True})
        print("role: TLDP Staff created")

    # 3. channels
    existing = {c["name"]: c for c in api("GET", f"/guilds/{GUILD}/channels")}
    webhooks = {}
    for cat, chans in LAYOUT.items():
        parent = existing.get(cat) or api("POST", f"/guilds/{GUILD}/channels", {"name": cat, "type": 4})
        existing[cat] = parent
        for name, topic, key in chans:
            ch = existing.get(name)
            if not ch:
                body = {"name": name, "type": 0, "topic": topic, "parent_id": parent["id"]}
                if name == "announcements":
                    body["permission_overwrites"] = [{"id": everyone["id"], "type": 0, "deny": str(SEND_MESSAGES)}]
                ch = api("POST", f"/guilds/{GUILD}/channels", body)
                existing[name] = ch
                print("channel:", f"#{name}")
            if key:  # 4. one webhook per feed channel
                hooks = api("GET", f"/channels/{ch['id']}/webhooks")
                hook = next((h for h in hooks if h["name"] == "Project Scout"), None) or \
                    api("POST", f"/channels/{ch['id']}/webhooks", {"name": "Project Scout"})
                webhooks[key] = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"
    for cat, rooms in VOICE:
        parent = existing.get(cat) or api("POST", f"/guilds/{GUILD}/channels", {"name": cat, "type": 4})
        for room in rooms:
            if room not in existing:
                api("POST", f"/guilds/{GUILD}/channels", {"name": room, "type": 2, "parent_id": parent["id"]})
                print("voice:", room)
    for old in ("general", "General"):  # Discord's defaults; replaced by general-chat / Study Rooms
        if old in existing and existing[old]["id"] != existing.get("general-chat", {}).get("id"):
            api("DELETE", f"/channels/{existing[old]['id']}")
            print("deleted default:", old)

    # 5. invite + welcome
    welcome = existing["welcome"]
    inv = api("POST", f"/channels/{welcome['id']}/invites", {"max_age": 7 * 86400, "max_uses": MAX_STUDENTS, "unique": True})
    msg = api("POST", f"/channels/{welcome['id']}/messages", {"content": WELCOME})
    api("PUT", f"/channels/{welcome['id']}/pins/{msg['id']}")
    print(f"\nINVITE (45 uses, 7 days): https://discord.gg/{inv['code']}")
    print("\nSet this repo secret (feed -> per-major channels):")
    print("gh secret set DISCORD_WEBHOOKS -R thecyberthriver/project-scout -b '" + json.dumps(webhooks) + "'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
