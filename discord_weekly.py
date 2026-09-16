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
    """Friday reminder: every NYC in-person hackathon currently listed (spring requirement), pointing at the forum."""
    from project_scout import hackathons_nyc, HACK_LINKS
    hs = hackathons_nyc()
    rows = [f"• [{h['title']}](<{h['url']}>) — {h['when']} · {h['where']} · via {h['src']}" for h in hs[:10]]
    more = " · ".join(f"[{n}](<{u}>)" for n, u in HACK_LINKS[:5])
    body = "\n".join(rows) if rows else "Nothing listed this week — check the links below and post what you find in 🏁 nyc-hackathons."
    return ("🏁 **Spring requirement: attend one in-person hackathon.** Currently listed in the NYC area:\n" + body +
            f"\n\nNew listings post automatically in 🏁 nyc-hackathons. More: {more}")


def webhook_post_body(url: str, body: dict) -> None:
    urllib.request.urlopen(urllib.request.Request(url + "?wait=true", data=json.dumps(body).encode(),
                                                  headers={"Content-Type": "application/json", "User-Agent": UA}), timeout=30)


def webhook_post(url: str, content: str) -> None:
    webhook_post_body(url, {"content": content[:2000]})


def telegram(text: str) -> None:
    body = json.dumps({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                                                  data=body, headers={"Content-Type": "application/json"}), timeout=30)


def gh(path: str):
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(f"https://api.github.com{path}", headers=h), timeout=30) as r:
        return json.load(r)


def newest_issues(repo: str, n: int = 2) -> list[str]:
    """Newest open issues in a case collection = cases waiting for someone (1 search request)."""
    import time
    time.sleep(2.5)
    q = urllib.parse.quote(f"repo:{repo} is:issue is:open")
    items = gh(f"/search/issues?q={q}&sort=created&order=desc&per_page={n}").get("items", [])
    return [f"  · [{i['title'][:80]}](<{i['html_url']}>)" for i in items]


def case_of_the_week() -> dict[str, str]:
    """Monday drop per forum: this week's live cases to pick up. Keys match DISCORD_WEBHOOKS."""
    y = datetime.now(timezone.utc).year
    out = {}
    try:  # data: newest Tidy Tuesday dataset + the two Tableau/Power BI weekly challenges
        folders = sorted(f["name"] for f in gh(f"/repos/rfordatascience/tidytuesday/contents/data/{y}") if f["type"] == "dir")
        latest = folders[-1]
        tt = f"https://github.com/rfordatascience/tidytuesday/tree/main/data/{y}/{latest}"
        out["data"] = (f"📁 **Case of the week — Data Analytics**\n• Tidy Tuesday **{latest}** dataset: <{tt}> — analyze it, open a pull request with your notebook or chart.\n"
                       f"• Makeover Monday: <https://www.makeovermonday.co.uk/> · Workout Wednesday: <https://www.workout-wednesday.com/> (Tableau / Power BI, publish and share the link here)")
    except Exception as e:
        print(f"tidytuesday: {e}", file=sys.stderr)
    for key, repos, label in (("cyber", ["redcanaryco/atomic-red-team", "SigmaHQ/sigma"], "Cybersecurity"),
                              ("swe", ["donnemartin/system-design-primer", "aosabook/aosabook"], "Software Engineering"),
                              ("marketing", ["PostHog/posthog.com", "mautic/user-documentation"], "Digital Marketing"),
                              ("fintech", ["OpenBB-finance/OpenBB"], "Finance / FinTech"),
                              ("quant", ["QuantConnect/Lean"], "Quant")):
        lines = []
        for r in repos:
            try:
                lines += [f"• **{r}** — newest open issues:"] + newest_issues(r)
            except Exception as e:
                print(f"{r}: {e}", file=sys.stderr)
        if lines:
            out[key] = f"📁 **Case of the week — {label}**\n" + "\n".join(lines) + "\nClaim one by commenting on the issue, then post your PR in #show-your-work."
    out["cases"] = ("📁 **Case of the week** — new cases posted in each major's forum. Reminder: every student adds one case of their own to "
                    "<https://github.com/thecyberthriver/tldp-case-studies> by spring (template in the repo).")
    return out


def main() -> int:
    day = "friday" if "--friday" in sys.argv else "monday" if "--monday" in sys.argv else \
        ("friday" if datetime.now(timezone.utc).weekday() == 4 else "monday")
    if day == "monday":
        telegram("📌 Pick of the week: choose 1 repo per major from this week's drops in TLDP_2026_2027, "
                 "post it in #announcements and pin it. 45 people focus better on 7 shared projects than on 200.")
        hooks = json.loads(os.environ.get("DISCORD_WEBHOOKS") or "{}")
        for key, text in case_of_the_week().items():
            if hooks.get(key):
                body = {"content": text[:2000]}
                if key != "cases":
                    body["thread_name"] = f"📁 Case of the week · {datetime.now():%b %d}"  # feed channels are forums
                try:
                    webhook_post_body(hooks[key], body)
                except Exception as e:
                    print(f"case post {key}: {e}", file=sys.stderr)
        print("monday reminder + case of the week sent")
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
