#!/usr/bin/env python3
"""
project_scout.py — near-real-time GitHub project-idea alerts for students, sent to Telegram.

Three lanes per major (Quant, FinTech, SWE, Cyber, Data):
  🧪 build     repos CREATED in the last 14 days that already have stars = what people build now
  🤝 oss       active repos with open "good first issue" tickets = contribution opportunities
  🔬 research  fresh repos whose README cites arXiv = paper code / research to join or reproduce
Anything already sent is skipped (seen.json, 60-day TTL); sends nothing when nothing is new.
Runs every 2 hours in GitHub Actions.

  python project_scout.py            # send
  python project_scout.py --preview  # print instead of sending
  python project_scout.py --self-check

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, optional GITHUB_TOKEN (raises the
search rate limit from 10 to 30 req/min; Actions passes its built-in token).
stdlib only.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

SEEN_TTL_DAYS = 60
SEEN = "seen.json"

# major -> (label, OR-list search terms for the build lane, single anchor word for the other lanes, evergreen list)
MAJORS = {
    "quant": ("📈 Quant",
              '"quantitative finance" OR backtesting OR "algorithmic trading" OR "options pricing" OR "portfolio optimization"',
              "trading", "https://github.com/wilsonfreitas/awesome-quant"),
    "fintech": ("💳 Finance / FinTech",
                'fintech OR payments OR "personal finance" OR "open banking" OR budgeting OR "stock market"',
                "finance", "https://github.com/topics/fintech"),
    "swe": ("💻 Software Engineering",
            '"build your own" OR "from scratch" OR "project ideas" OR "portfolio project" OR "full stack"',
            "software", "https://github.com/codecrafters-io/build-your-own-x"),
    "cyber": ("🔐 Cybersecurity",
              'cybersecurity OR "penetration testing" OR "threat detection" OR "malware analysis" OR "security tool" OR CTF',
              "security", "https://github.com/sindresorhus/awesome#security"),
    "data": ("📊 Data Analytics",
             '"data analytics" OR "data analysis" OR "exploratory data analysis" OR "data pipeline" OR "data visualization"',
             "data", "https://github.com/academic/awesome-datascience"),
}


def ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# lane -> (label, picks per major, sort, query builder(terms, anchor))
# GitHub search has no parentheses, so only the build lane uses the OR list; others use the anchor word.
LANES = {
    "build": ("🧪 Build this", 3, "stars",
              lambda terms, anchor: f"{terms} created:>={ago(14)} stars:>=10 archived:false"),
    "oss": ("🤝 Contribute — open good-first-issues", 2, "updated",
            lambda terms, anchor: f"{anchor} good-first-issues:>0 stars:>=50 pushed:>={ago(30)} archived:false"),
    "research": ("🔬 Research — fresh paper code (cites arXiv)", 2, "stars",
                 lambda terms, anchor: f"{RESEARCH_ANCHOR[anchor]} arxiv in:readme,description created:>={ago(30)} stars:>=5 archived:false"),
}
# a bare word + arxiv returns generic AI repos; a field phrase keeps research on-major
RESEARCH_ANCHOR = {"trading": '"quantitative finance"', "finance": '"financial"', "software": '"software engineering"',
                   "security": "cybersecurity", "data": '"data analysis"'}


def gh_search(q: str, sort: str = "stars", n: int = 15) -> list[dict]:
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": sort, "order": "desc", "per_page": n})
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "project-scout"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r).get("items", [])


def load_seen() -> dict:
    try:
        seen = json.load(open(SEEN))
    except (OSError, ValueError):
        return {}
    cutoff = ago(SEEN_TTL_DAYS)
    return {k: v for k, v in seen.items() if v >= cutoff}


def english(desc: str) -> bool:
    """Skip mostly non-ASCII (e.g. CJK) descriptions — students here read English."""
    return not desc or sum(ord(c) < 128 for c in desc) / len(desc) >= 0.7


def pick(items: list[dict], seen: dict, n: int) -> list[dict]:
    out = []
    for it in items:
        if it["full_name"] in seen or not english(it.get("description") or ""):
            continue
        seen[it["full_name"]] = date.today().isoformat()
        out.append(it)
        if len(out) == n:
            break
    return out


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


GFI = '/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22'


def render_repo(it: dict, lane: str) -> str:
    desc = (it.get("description") or "").strip()
    desc = desc[:140] + "…" if len(desc) > 140 else desc
    lang = f" · {it['language']}" if it.get("language") else ""
    tail = f'\n  👉 <a href="{it["html_url"]}{GFI}">open good-first-issues</a>' if lane == "oss" else ""
    return (f'• <a href="{it["html_url"]}">{esc(it["full_name"])}</a> ⭐{it["stargazers_count"]}{lang}\n'
            f"  {esc(desc) or '(no description)'}{tail}")


def build_digest(seen: dict) -> list[str]:
    """One chunk per major that has unseen repos; empty list = nothing new, send nothing."""
    chunks = []
    for key, (label, terms, anchor, evergreen) in MAJORS.items():
        parts = []
        for lane, (lane_label, n, sort, q) in LANES.items():
            try:
                picks = pick(gh_search(q(terms, anchor), sort), seen, n)
            except Exception as e:  # one bad query must not kill the run
                print(f"{key}/{lane}: {e}", file=sys.stderr)
                continue
            if picks:
                parts.append(f"<i>{lane_label}</i>\n" + "\n".join(render_repo(p, lane) for p in picks))
        if parts:
            chunks.append(f"\n<b>{label}</b>\n" + "\n".join(parts) + f'\n  📚 <a href="{evergreen}">evergreen idea list</a>')
    if not chunks:
        return []
    chunks.insert(0, "<b>🧪 Project Scout — new on GitHub</b>\n"
                     "Build it, contribute to it, or reproduce the research — steal the idea, make your own version.")
    chunks[-1] += "\n\n<i>/quant /fintech /swe /cyber /data · /oss &lt;major&gt; · /research &lt;major&gt; — live search anytime.</i>"
    return chunks


def send(text: str) -> None:
    tok, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:  # 400 "chat not found" = press Start on the bot first; 404 = bad token
        raise SystemExit(f"telegram {e.code}: {e.read()[:200].decode(errors='replace')}")


def discord(text: str) -> None:
    """Optional: mirror to a Discord channel webhook (DISCORD_WEBHOOK_URL) — Telegram HTML -> Discord markdown."""
    import re
    md = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"[\2](<\1>)", text)
    md = re.sub(r"</?b>", "**", md)
    md = re.sub(r"</?i>", "*", md)
    md = md.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    for part in [md[i:i + 1900] for i in range(0, len(md), 1900)]:  # Discord cap is 2000 chars
        req = urllib.request.Request(os.environ["DISCORD_WEBHOOK_URL"], data=json.dumps({"content": part}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "project-scout"})
        with urllib.request.urlopen(req, timeout=30) as r:
            assert r.status in (200, 204), r.status


def messages(chunks: list[str], limit: int = 3900) -> list[str]:
    """Pack chunks into as few Telegram messages (<4096 chars) as possible."""
    msgs, cur = [], ""
    for c in chunks:
        if cur and len(cur) + len(c) + 1 > limit:
            msgs.append(cur)
            cur = ""
        cur = f"{cur}\n{c}" if cur else c
    return msgs + [cur] if cur else msgs


def self_check() -> None:
    assert messages(["a" * 3000, "b" * 3000, "c"]) == ["a" * 3000, "b" * 3000 + "\nc"]
    assert messages([]) == []
    assert pick([{"full_name": "x/y"}, {"full_name": "a/b"}, {"full_name": "c/d"}], {"x/y": "2099-01-01"}, 1) \
        == [{"full_name": "a/b"}]
    assert english("") and english("Agent-native backtesting") and not english("面向基本面因子研究的智能体-AI agent")
    r = {"full_name": "<b>", "html_url": "u", "stargazers_count": 1, "description": ""}
    assert "&lt;b&gt;" in render_repo(r, "build") and "good-first-issues" in render_repo(r, "oss")
    assert "good-first-issues:>0" in LANES["oss"][3]("t", "trading")
    assert LANES["research"][3]("t", "trading").startswith('"quantitative finance" arxiv')
    print("self-check ok")


def main() -> int:
    if "--self-check" in sys.argv:
        self_check()
        return 0
    seen = load_seen()
    msgs = messages(build_digest(seen))
    if "--preview" in sys.argv:
        print("\n\n=====\n\n".join(msgs) or "(nothing new)")
        return 0
    for m in msgs:
        send(m)
        if os.environ.get("DISCORD_WEBHOOK_URL"):
            discord(m)
    json.dump(seen, open(SEEN, "w"), indent=0)
    print(f"sent {len(msgs)} message(s) at {datetime.now():%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
