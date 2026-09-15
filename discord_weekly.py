#!/usr/bin/env python3
"""
discord_weekly.py — the human-loop jobs for the TLDP server. stdlib only. Run by .github/workflows/weekly.yml.

  Friday  : 🙋 claims of the week (who reacted on which feed post)  -> #find-a-team
            🏆 leaderboard (links posted in #show-your-work this week) -> #show-your-work
            🏁 hackathons closing soon (Devpost public JSON)         -> #announcements (webhook)
  Monday  : "pick of the week" reminder                              -> YOUR private Telegram bot
  python discord_weekly.py --friday | --monday   (default: pick by today's weekday)

Env: DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_WEBHOOKS (needs the "announcements" key),
     TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. The bot role needs Read Message History (set in Server Settings > Roles).
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

API = "https://discord.com/api/v10"
TOKEN, GUILD = os.environ.get("DISCORD_BOT_TOKEN", ""), os.environ.get("DISCORD_GUILD_ID", "")
UA = "project-scout (github.com/thecyberthriver/project-scout, 1.0)"
WEEK = datetime.now(timezone.utc) - timedelta(days=7)
CLAIM = urllib.parse.quote("🙋")


def api(method, path, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r) if r.status != 204 else None


def snowflake_time(sf: str) -> datetime:
    return datetime.fromtimestamp(((int(sf) >> 22) + 1420070400000) / 1000, tz=timezone.utc)


def post(channel_id: str, content: str) -> None:
    api("POST", f"/channels/{channel_id}/messages", {"content": content[:2000], "allowed_mentions": {"parse": []}})


def claims(channels: dict) -> str:
    forums = {c["id"]: c["name"] for c in channels.values() if c["type"] == 15}
    lines = []
    for t in api("GET", f"/guilds/{GUILD}/threads/active")["threads"]:
        if t["parent_id"] not in forums or snowflake_time(t["id"]) < WEEK:
            continue
        try:
            users = api("GET", f"/channels/{t['id']}/messages/{t['id']}/reactions/{CLAIM}?limit=50")
        except urllib.error.HTTPError:
            continue
        if users:
            who = ", ".join(f"<@{u['id']}>" for u in users)
            lines.append(f"• **{t['name']}** ({forums[t['parent_id']]}) — {who}")
    if not lines:
        return "🙋 **Claims this week:** nobody claimed a drop yet. React 🙋 on a feed post to claim it and find teammates here."
    return "🙋 **Claims this week** — same repo? Team up.\n" + "\n".join(lines[:30])


def leaderboard(channel_id: str) -> str:
    msgs = api("GET", f"/channels/{channel_id}/messages?limit=100")
    c = Counter(m["author"]["id"] for m in msgs if snowflake_time(m["id"]) >= WEEK and "http" in m.get("content", "")
                and not m["author"].get("bot"))
    if not c:
        return "🏆 **This week's leaderboard:** no links posted yet. Post your merged PR or demo link here to get on the board."
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    rows = [f"{medals[i]} <@{uid}> — {n} post{'s' if n != 1 else ''}" for i, (uid, n) in enumerate(c.most_common(10))]
    return "🏆 **This week's leaderboard** (links posted in #show-your-work)\n" + "\n".join(rows)


def hackathons() -> str:
    url = "https://devpost.com/api/hackathons?status[]=open&order_by=deadline&per_page=8"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30) as r:
            hs = json.load(r).get("hackathons", [])
    except Exception as e:  # Devpost's JSON is unofficial; degrade to a link
        return f"🏁 **Hackathons:** browse open ones at https://devpost.com/hackathons?status[]=open ({e})"
    rows = []
    for h in hs[:6]:
        prize = f" · {h['prize_amount']}" if h.get("prize_amount") else ""
        rows.append(f"• [{h['title']}](<{h['url']}>) — {h.get('submission_period_dates', '')}{prize} · {h.get('displayed_location', {}).get('location', '')}")
    return "🏁 **Hackathons closing soon** (Devpost) — a deadline beats a to-do list. Kaggle: https://www.kaggle.com/competitions\n" + "\n".join(rows)


def webhook_post(url: str, content: str) -> None:
    urllib.request.urlopen(urllib.request.Request(url, data=json.dumps({"content": content[:2000]}).encode(),
                                                  headers={"Content-Type": "application/json", "User-Agent": UA}), timeout=30)


def telegram(text: str) -> None:
    body = json.dumps({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                                                  data=body, headers={"Content-Type": "application/json"}), timeout=30)


def main() -> int:
    day = "friday" if "--friday" in sys.argv else "monday" if "--monday" in sys.argv else \
        ("friday" if datetime.now(timezone.utc).weekday() == 4 else "monday")
    if day == "monday":
        telegram("📌 Pick of the week: choose 1 repo per major from this week's drops in TLDP_2026_2027, "
                 "post it in #announcements and pin it. 45 people focus better on 7 shared projects than on 200.")
        print("monday reminder sent")
        return 0
    channels = {c["name"]: c for c in api("GET", f"/guilds/{GUILD}/channels")}
    post(channels["find-a-team"]["id"], claims(channels))
    post(channels["show-your-work"]["id"], leaderboard(channels["show-your-work"]["id"]))
    hooks = json.loads(os.environ.get("DISCORD_WEBHOOKS") or "{}")
    if hooks.get("announcements"):
        webhook_post(hooks["announcements"], hackathons())
    print("friday: claims, leaderboard, hackathons posted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
