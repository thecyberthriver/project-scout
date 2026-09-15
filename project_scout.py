#!/usr/bin/env python3
"""
project_scout.py — near-real-time GitHub project-idea alerts for students, sent to Telegram.

For each major it searches GitHub for repos CREATED in the last FRESH_DAYS that
already earned MIN_STARS stars (= what people are building right now), skips
anything already sent (seen.json, 60-day TTL) and posts only what is new.
Runs every 2 hours in GitHub Actions; sends nothing when nothing is new.

  python project_scout.py            # send digest
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

FRESH_DAYS = 14
MIN_STARS = 10
PER_MAJOR = 3
SEEN_TTL_DAYS = 60
SEEN = "seen.json"

# major -> (label, search terms, evergreen idea list)
MAJORS = {
    "quant": ("📈 Quant",
              '"quantitative finance" OR backtesting OR "algorithmic trading" OR "options pricing" OR "portfolio optimization"',
              "https://github.com/wilsonfreitas/awesome-quant"),
    "fintech": ("💳 Finance / FinTech",
                'fintech OR payments OR "personal finance" OR "open banking" OR budgeting OR "stock market"',
                "https://github.com/topics/fintech"),
    "swe": ("💻 Software Engineering",
            '"build your own" OR "from scratch" OR "project ideas" OR "portfolio project" OR "full stack"',
            "https://github.com/codecrafters-io/build-your-own-x"),
    "cyber": ("🔐 Cybersecurity",
              'cybersecurity OR "penetration testing" OR "threat detection" OR "malware analysis" OR "security tool" OR CTF',
              "https://github.com/sindresorhus/awesome#security"),
    "data": ("📊 Data Analytics",
             '"data analytics" OR "data analysis" OR "exploratory data analysis" OR "data pipeline" OR "data visualization"',
             "https://github.com/academic/awesome-datascience"),
}


def gh_search(terms: str, since: date, n: int = 15) -> list[dict]:
    q = f"{terms} created:>={since.isoformat()} stars:>={MIN_STARS} archived:false"
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": "stars", "order": "desc", "per_page": n})
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
    cutoff = (date.today() - timedelta(days=SEEN_TTL_DAYS)).isoformat()
    return {k: v for k, v in seen.items() if v >= cutoff}


def pick(items: list[dict], seen: dict) -> list[dict]:
    out = []
    for it in items:
        if it["full_name"] in seen or not english(it.get("description") or ""):
            continue
        seen[it["full_name"]] = date.today().isoformat()
        out.append(it)
        if len(out) == PER_MAJOR:
            break
    return out


def english(desc: str) -> bool:
    """Skip mostly non-ASCII (e.g. CJK) descriptions — students here read English."""
    return not desc or sum(ord(c) < 128 for c in desc) / len(desc) >= 0.7


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_repo(it: dict) -> str:
    desc = (it.get("description") or "").strip()
    desc = desc[:140] + "…" if len(desc) > 140 else desc
    lang = f" · {it['language']}" if it.get("language") else ""
    return (f'• <a href="{it["html_url"]}">{esc(it["full_name"])}</a> ⭐{it["stargazers_count"]}{lang}\n'
            f"  {esc(desc) or '(no description)'}")


def build_digest(seen: dict) -> list[str]:
    """Only majors with unseen repos are included; empty list = nothing new, send nothing."""
    since = date.today() - timedelta(days=FRESH_DAYS)
    chunks = []
    for key, (label, terms, evergreen) in MAJORS.items():
        try:
            picks = pick(gh_search(terms, since), seen)
        except Exception as e:  # one bad query must not kill the run
            print(f"{key}: {e}", file=sys.stderr)
            continue
        if picks:
            body = "\n".join(render_repo(p) for p in picks)
            chunks.append(f"\n<b>{label}</b>\n{body}\n  📚 <a href=\"{evergreen}\">evergreen idea list</a>")
    if not chunks:
        return []
    chunks.insert(0, f"<b>🧪 Project Scout — new on GitHub</b>\n"
                     f"Repos created in the last {FRESH_DAYS} days with ⭐{MIN_STARS}+ — steal the idea, build your own version.")
    chunks[-1] += "\n\n<i>/quant /fintech /swe /cyber /data here for a live search anytime.</i>"
    return chunks


def send(text: str) -> None:
    tok, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.status == 200, r.status


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
    s = {"x/y": (date.today() - timedelta(days=SEEN_TTL_DAYS + 1)).isoformat()}
    json.dump(s, open(SEEN + ".tmp", "w"))
    assert pick([{"full_name": "x/y"}, {"full_name": "a/b"}], {"x/y": "2099-01-01"}) == [{"full_name": "a/b"}]
    os.remove(SEEN + ".tmp")
    assert english("") and english("Agent-native backtesting") and not english("面向基本面因子研究的智能体-AI agent")
    assert "&lt;b&gt;" in render_repo({"full_name": "<b>", "html_url": "u", "stargazers_count": 1, "description": ""})
    print("self-check ok")


def main() -> int:
    if "--self-check" in sys.argv:
        self_check()
        return 0
    seen = load_seen()
    msgs = messages(build_digest(seen))
    if "--preview" in sys.argv:
        print("\n\n=====\n\n".join(msgs))
        return 0
    for m in msgs:
        send(m)
    json.dump(seen, open(SEEN, "w"), indent=0)
    print(f"sent {len(msgs)} message(s) at {datetime.now():%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
