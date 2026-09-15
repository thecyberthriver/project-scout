#!/usr/bin/env python3
"""
discord_setup.py — provision the private TLDP server in one run (rerunnable: skips what exists by name).
stdlib only (+ Pillow, optional, for the server icon).

  python discord_setup.py               # build / update everything, print secrets to set
  python discord_setup.py --invites 45  # print 45 single-use 7-day invite links (Discord max) (one per student, CSV)

Reads DISCORD_BOT_TOKEN / DISCORD_GUILD_ID from env or ../secrets_local.py. Needs the bot invited with
Manage Server, Manage Roles, Manage Channels, Manage Webhooks, Create Invite, Send/Manage Messages (805317681).

What it does:
  1. Server: verification Medium, notifications = mentions only, @everyone loses "Create Invite", TLDP icon.
  2. Roles: "TLDP Staff", "TLDP Student" (gate), one mentionable role per major.
  3. Categories + channels. Feed channels are FORUMS: every drop is its own post/thread, students discuss
     inside it and react 🙋 to claim it. Feed + Collaborate + Study Rooms are hidden until /verify grants
     "TLDP Student"; START HERE stays visible so newcomers can read #welcome and run /verify.
  4. One webhook per feed forum (+ #announcements) -> printed as the DISCORD_WEBHOOKS secret.
  5. A 45-use 7-day invite on #welcome + a pinned welcome post.
"""
import base64
import io
import json
import os
import sys
import urllib.parse
import urllib.request

try:
    import secrets_local as s
except ImportError:
    s = None
TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or getattr(s, "DISCORD_BOT_TOKEN", "")
GUILD = os.environ.get("DISCORD_GUILD_ID") or getattr(s, "DISCORD_GUILD_ID", "")
APP_ID = os.environ.get("DISCORD_APP_ID") or getattr(s, "DISCORD_APP_ID", "")
API = "https://discord.com/api/v10"
MAX_STUDENTS = 45

CREATE_INVITE, VIEW, SEND = 0x1, 0x400, 0x800
STAFF_PERMS = 805317681  # what the bot itself was invited with — a bot cannot grant more than it holds
TEXT, VOICE, CATEGORY, FORUM = 0, 2, 4, 15

MAJOR_ROLES = {"quant": ("Quant", 0x2ECC71), "fintech": ("Finance/FinTech", 0x1ABC9C), "swe": ("SWE", 0x3498DB),
               "cyber": ("Cybersecurity", 0xE74C3C), "data": ("Data Analytics", 0x9B59B6),
               "pm": ("Project Management", 0xF1C40F), "marketing": ("Digital Marketing", 0xE67E22)}

# category -> gated? , [(name, topic, type, feed key)]
LAYOUT = {
    "📌 START HERE": (False, [
        ("welcome", "Rules, how the bot works, and /verify to unlock the server.", TEXT, None),
        ("announcements", "TLDP staff announcements + weekly hackathon list. Read-only.", TEXT, "announcements"),
        ("introductions", "Name · major · what you want to build this semester.", TEXT, None),
    ]),
    "🧪 PROJECT SCOUT FEED": (True, [
        ("📊│data-analytics", "Fresh data analytics repos, good-first-issues and paper code. One post per drop — react 🙋 to claim.", FORUM, "data"),
        ("💻│swe", "Fresh software projects, good-first-issues and paper code. React 🙋 to claim.", FORUM, "swe"),
        ("🔐│cybersecurity", "Fresh cybersecurity repos, good-first-issues and paper code. React 🙋 to claim.", FORUM, "cyber"),
        ("📈│quant", "Fresh quant repos, good-first-issues and paper code. React 🙋 to claim.", FORUM, "quant"),
        ("💳│finance-fintech", "Fresh finance/fintech repos, good-first-issues and paper code. React 🙋 to claim.", FORUM, "fintech"),
        ("📋│project-management", "Fresh project-management tools and good-first-issues. React 🙋 to claim.", FORUM, "pm"),
        ("📣│digital-marketing", "Fresh marketing/SEO/analytics repos and good-first-issues. React 🙋 to claim.", FORUM, "marketing"),
        ("🤝│open-source-orgs", "Non-profit, public-sector and company repos you can contribute to — resume-ready.", FORUM, "orgs"),
    ]),
    "🤝 COLLABORATE": (True, [
        ("scout-search", "Run /scout here: /scout major:Cybersecurity lane:Contribute keywords:honeypot", TEXT, None),
        ("find-a-team", "Post the project you picked and who you need. Weekly 'claimed this week' list lands here.", TEXT, None),
        ("show-your-work", "Merged PRs, demos, repos, resume lines. Friday leaderboard counts links posted here.", TEXT, None),
        ("help", "Stuck on git, a PR, an environment? Ask here.", TEXT, None),
        ("general-chat", "Everything else.", TEXT, None),
    ]),
    "🎯 SPRING REQUIREMENTS": (True, [
        ("🏁│nyc-hackathons", "In-person hackathons in the NYC area, city-wide + private + public sector, updated every 6 h from Devpost and MLH. Attend one by spring. Reply in a post to find teammates.", FORUM, "hackathons"),
        ("🎓│capstone", "Your capstone project, judged in spring. Post your idea, repo link, weekly progress, and questions for staff.", TEXT, None),
    ]),
    "🎧 STUDY ROOMS": (True, [("Study Room 1", "", VOICE, None), ("Study Room 2", "", VOICE, None)]),
}
OLD_FEED_NAMES = {"data-analytics", "swe", "cybersecurity", "quant", "finance-fintech", "project-management",
                  "digital-marketing", "open-source-orgs"}  # pre-forum text channels; replaced

WELCOME = """**Welcome to TLDP_2026_2027** 🎓

Private server for the 45 TLDP students. Please don't share the invite link.

**Step 1 — unlock the server:** type `/verify name:<your full name>` (add `major:` to get your major role). Your name is matched against the TLDP roster; if it fails, post in #introductions and staff will let you in.

**What's here once you're in**
• **Feed forums** (📊 data-analytics · 💻 swe · 🔐 cybersecurity · 📈 quant · 💳 finance-fintech · 📋 project-management · 📣 digital-marketing) — every 6 hours the Project Scout bot opens a post with fresh GitHub repos for that major: things to build, open-source repos with *good first issues*, and new paper code. Each row shows 🟢 starter / 🟡 intermediate / 🔴 advanced.
• **React 🙋 on a post to claim it.** Every Friday the bot lists who claimed what in #find-a-team so you can team up.
• **🤝 open-source-orgs** — non-profit, public-sector and company repos that welcome contributors, with a LinkedIn link and a ready-to-paste resume line.
• **#scout-search** — search on demand: `/scout major:Cybersecurity`, `/scout lane:Contribute major:Data Analytics`, `/scout lane:Orgs keywords:python`.
• **#show-your-work** — post merged PRs and demos. Friday leaderboard lives here.
• **#announcements** — staff posts.

**Spring requirements (both graded)**
• **🏁 nyc-hackathons** — attend one in-person hackathon in the NYC area. New listings from Devpost and MLH land here automatically; reply in a post to find teammates.
• **🎓 capstone** — your capstone project, judged in spring. Post your idea, your repo, and weekly progress there.

**Start now:** /verify, introduce yourself, pick one repo this week and open one good-first-issue PR.
"""


def api(method, path, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json",
                                          "User-Agent": "project-scout (github.com/thecyberthriver/project-scout, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r) if r.status != 204 else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}")


def icon_png() -> str | None:
    """512x512 'TLDP' icon as a data URI (needs Pillow); None if Pillow is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    im = Image.new("RGB", (512, 512), (88, 101, 242))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arialbd.ttf", 150)
    except OSError:
        font = ImageFont.load_default()
    d.text((256, 230), "TLDP", fill="white", font=font, anchor="mm")
    d.text((256, 350), "2026–27", fill=(220, 224, 255), font=ImageFont.truetype("arial.ttf", 60) if font else font, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def staff(names: list[str]) -> int:
    """--staff "Nii Ato" "Cristina": give the TLDP Staff role to members whose username/display name matches."""
    role = next(r for r in api("GET", f"/guilds/{GUILD}/roles") if r["name"] == "TLDP Staff")
    for name in names:
        q = name.split()[0]
        hits = api("GET", f"/guilds/{GUILD}/members/search?query={urllib.parse.quote(q)}&limit=10")
        low = name.lower()
        hit = next((m for m in hits if low in " ".join(filter(None, [m["user"]["username"], m["user"].get("global_name"), m.get("nick")])).lower()), None) \
            or (hits[0] if len(hits) == 1 else None)
        if not hit:
            print(f"{name}: not in the server yet (send them an invite, then rerun)")
            continue
        api("PUT", f"/guilds/{GUILD}/members/{hit['user']['id']}/roles/{role['id']}")
        print(f"{name}: TLDP Staff granted to @{hit['user']['username']}")
    return 0


def invites(n: int) -> int:
    chans = {c["name"]: c for c in api("GET", f"/guilds/{GUILD}/channels")}
    print("student_number,invite_url")
    for i in range(1, n + 1):
        inv = api("POST", f"/channels/{chans['welcome']['id']}/invites", {"max_age": 7 * 86400, "max_uses": 1, "unique": True})
        print(f"{i},https://discord.gg/{inv['code']}")
    return 0


def main() -> int:
    if not TOKEN or not GUILD:
        print(__doc__)
        return 1
    if "--invites" in sys.argv:
        return invites(int(sys.argv[sys.argv.index("--invites") + 1]))
    if "--staff" in sys.argv:
        return staff(sys.argv[sys.argv.index("--staff") + 1:])
    print("guild:", api("GET", f"/guilds/{GUILD}")["name"])

    # 1. server hardening + icon
    patch = {"verification_level": 2, "default_message_notifications": 1}
    icon = icon_png()
    if icon:
        patch["icon"] = icon
    api("PATCH", f"/guilds/{GUILD}", patch)
    roles = {r["name"]: r for r in api("GET", f"/guilds/{GUILD}/roles")}
    everyone = roles["@everyone"]
    api("PATCH", f"/guilds/{GUILD}/roles/{everyone['id']}", {"permissions": str(int(everyone["permissions"]) & ~CREATE_INVITE)})
    bot_role = next((r for r in roles.values() if r.get("tags", {}).get("bot_id") == APP_ID), None)
    print("server: verification=medium, invites staff-only, icon", "set" if icon else "skipped (no Pillow)")

    # 2. roles
    def role(name, perms, color, hoist=False):
        if name not in roles:
            roles[name] = api("POST", f"/guilds/{GUILD}/roles", {"name": name, "permissions": str(perms), "color": color,
                                                                 "hoist": hoist, "mentionable": True})
            print("role:", name)
        return roles[name]
    staff = role("TLDP Staff", STAFF_PERMS, 0x5865F2, hoist=True)
    student = role("TLDP Student", 0, 0x57F287, hoist=True)
    major_ids = {k: role(n, 0, c)["id"] for k, (n, c) in MAJOR_ROLES.items()}

    # 3. channels
    gate = [{"id": everyone["id"], "type": 0, "deny": str(VIEW)},
            {"id": student["id"], "type": 0, "allow": str(VIEW)},
            {"id": staff["id"], "type": 0, "allow": str(VIEW)}]
    if bot_role:
        gate.append({"id": bot_role["id"], "type": 0, "allow": str(VIEW)})
    existing = {c["name"]: c for c in api("GET", f"/guilds/{GUILD}/channels")}
    for old in OLD_FEED_NAMES | {"general", "General"}:
        if old in existing and existing[old]["type"] in (TEXT, VOICE):
            api("DELETE", f"/channels/{existing.pop(old)['id']}")
            print("replaced old channel:", old)
    webhooks = {}
    for cat, (gated, chans) in LAYOUT.items():
        parent = existing.get(cat) or api("POST", f"/guilds/{GUILD}/channels", {"name": cat, "type": CATEGORY})
        existing[cat] = parent
        api("PATCH", f"/channels/{parent['id']}", {"permission_overwrites": gate if gated else []})
        for name, topic, ctype, key in chans:
            ch = existing.get(name)
            body = {"name": name, "type": ctype, "parent_id": parent["id"]}
            if ctype != VOICE:
                body["topic"] = topic
            body["permission_overwrites"] = list(gate) if gated else []
            if name == "announcements":
                body["permission_overwrites"] = [{"id": everyone["id"], "type": 0, "deny": str(SEND)}]
            if not ch:
                ch = existing[name] = api("POST", f"/guilds/{GUILD}/channels", body)
                print("channel:", name)
            else:
                api("PATCH", f"/channels/{ch['id']}", {k: v for k, v in body.items() if k != "type"})
            if key:  # 4. webhooks
                hooks = api("GET", f"/channels/{ch['id']}/webhooks")
                hook = next((h for h in hooks if h["name"] == "Project Scout"), None) or \
                    api("POST", f"/channels/{ch['id']}/webhooks", {"name": "Project Scout"})
                webhooks[key] = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"

    # 5. invite + welcome (reused on rerun)
    welcome = existing["welcome"]
    inv = next((i for i in api("GET", f"/guilds/{GUILD}/invites") if i.get("max_uses") == MAX_STUDENTS), None) or \
        api("POST", f"/channels/{welcome['id']}/invites", {"max_age": 7 * 86400, "max_uses": MAX_STUDENTS, "unique": True})
    old_msgs = api("GET", f"/channels/{welcome['id']}/messages?limit=5")
    for m in old_msgs:  # refresh the welcome text on rerun
        if m.get("author", {}).get("id") == APP_ID:
            api("DELETE", f"/channels/{welcome['id']}/messages/{m['id']}")
    msg = api("POST", f"/channels/{welcome['id']}/messages", {"content": WELCOME})
    try:
        api("PUT", f"/channels/{welcome['id']}/messages/pins/{msg['id']}")
    except SystemExit as e:
        print("pin skipped:", e)

    print(f"\nINVITE (45 uses, 7 days): https://discord.gg/{inv['code']}")
    print("\nRepo secret (feed -> per-channel):")
    print("gh secret set DISCORD_WEBHOOKS -R thecyberthriver/project-scout -b '" + json.dumps(webhooks) + "'")
    print("\nWorker secrets for /verify (wrangler secret bulk -c wrangler.discord.toml):")
    print(json.dumps({"STUDENT_ROLE_ID": student["id"], "MAJOR_ROLES": json.dumps(major_ids),
                      "SHOW_YOUR_WORK_ID": existing["show-your-work"]["id"], "FIND_A_TEAM_ID": existing["find-a-team"]["id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
