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
                'fintech OR payments OR "personal finance" OR "open banking" OR "stock market" OR "financial data"',
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
    "pm": ("📋 Project Management",
           '"project management" OR scrum OR kanban OR "task management" OR "agile" OR roadmap',
           '"project management"', "https://github.com/topics/project-management"),
    "marketing": ("📣 Digital Marketing",
                  '"digital marketing" OR SEO OR "marketing analytics" OR "social media" OR "email marketing" OR "growth hacking"',
                  "marketing", "https://github.com/topics/marketing"),
}


def ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# lane -> (label, picks per major, sort, query builder(terms, anchor))
# GitHub search has no parentheses, so only the build lane uses the OR list; others use the anchor word.
LANES = {
    "build": ("🧪 Build this", 2, "stars",
              lambda terms, anchor: f"{terms} created:>={ago(14)} stars:>=10 archived:false"),
    "oss": ("🤝 Contribute — open good-first-issues", 2, "updated",
            lambda terms, anchor: f"{anchor} good-first-issues:>0 stars:>=50 pushed:>={ago(30)} archived:false"),
    "research": ("🔬 Research — fresh paper code (cites arXiv)", 2, "stars",
                 lambda terms, anchor: f"{RESEARCH_ANCHOR[anchor]} {anchor} arxiv in:readme,description created:>={ago(30)} stars:>=20 archived:false"),
}
# Most new GitHub repos right now are LLM wrappers; keep them out of the non-software majors.
AI_SPAM = __import__("re").compile(r"\b(agents?|llms?|gpt|chatgpt|copilot|claude|openai|langchain|rag)\b", __import__("re").I)
AI_OK = {"swe", "data"}
# a bare word + arxiv returns generic AI repos; a field phrase keeps research on-major
RESEARCH_ANCHOR = {"trading": '"quantitative finance"', "finance": '"financial"', "software": '"software engineering"',
                   "security": "cybersecurity", "data": '"data analysis"', '"project management"': '"project management"',
                   "marketing": '"digital marketing"'}

# Mission-driven orgs whose GitHub repos welcome outside contributors (good-first-issues) — resume-ready experience.
# Each GitHub org -> display name. LinkedIn is login-walled, so rows link to a LinkedIn company search, not a scrape.
# Keep each sector <= 12 orgs: GitHub search queries max out at 256 chars.
ORGS = {
    "nonprofit": ("🌱 Non-profit", {"mozilla": "Mozilla", "OWASP": "OWASP", "wikimedia": "Wikimedia", "EFForg": "EFF",
                                    "datakind": "DataKind", "ushahidi": "Ushahidi", "hackforla": "Hack for LA",
                                    "codeforamerica": "Code for America",
                                    "torproject": "Tor Project",
                                    "freeCodeCamp": "freeCodeCamp", "BetaNYC": "BetaNYC (NYC civic tech)"}),
    "public": ("🏛 Public sector", {"cisagov": "CISA", "GSA": "US GSA", "18F": "18F", "usds": "US Digital Service",
                                   "nasa": "NASA", "usnistgov": "NIST", "CDCgov": "CDC",
                                   "CityOfNewYork": "City of New York", "NYCPlanning": "NYC Dept of City Planning",
                                   "alphagov": "UK GDS"}),
    "private": ("🏢 Private sector", {"microsoft": "Microsoft", "google": "Google", "aws": "AWS", "IBM": "IBM",
                                     "cloudflare": "Cloudflare", "elastic": "Elastic", "goldmansachs": "Goldman Sachs", "man-group": "Man Group",
                                     "jpmorganchase": "JPMorgan Chase", "bloomberg": "Bloomberg"}),
}
ORG_NAME = {o: n for _, orgs in ORGS.values() for o, n in orgs.items()}

# "Start here": curated, evergreen repos that give students project IDEAS and the basics to get going
# (idea lists, roadmaps, beginner courses, sample apps). Verified live 2026-09-15. Posted once per major
# with --starters; served on demand as /basics <major> (Telegram) and lane "Start here" (Discord).
STARTERS = {
    "quant": ["wilsonfreitas/awesome-quant", "stefan-jansen/machine-learning-for-trading", "je-suis-tm/quant-trading",
              "microsoft/qlib", "QuantConnect/Lean", "ranaroussi/yfinance"],
    "fintech": ["OpenBB-finance/OpenBB", "plaid/pattern", "stripe-samples/checkout-one-time-payments",
                "firefly-iii/firefly-iii", "actualbudget/actual", "ranaroussi/yfinance"],
    "swe": ["practical-tutorials/project-based-learning", "codecrafters-io/build-your-own-x", "florinpop17/app-ideas",
            "karan/Projects", "nilbuild/developer-roadmap", "ossu/computer-science"],
    "cyber": ["sbilly/awesome-security", "OWASP/CheatSheetSeries", "juice-shop/juice-shop", "OWASP/wstg",
              "swisskyrepo/PayloadsAllTheThings", "mitre-attack/attack-navigator"],
    "data": ["microsoft/Data-Science-For-Beginners", "jakevdp/PythonDataScienceHandbook", "Yorko/mlcourse.ai",
             "awesomedata/awesome-public-datasets", "streamlit/streamlit", "academic/awesome-datascience"],
    "pm": ["dend/awesome-product-management", "opf/openproject", "makeplane/plane", "wekan/wekan",
           "mattermost-community/focalboard"],
    "marketing": ["PostHog/posthog", "umami-software/umami", "matomo-org/matomo", "mautic/mautic", "knadh/listmonk",
                  "n8n-io/n8n"],
}
STARTER_WHY = {
    "quant": "idea list → book code with notebooks → example strategies → two real backtest engines → free market data",
    "fintech": "open-source Bloomberg-style terminal → bank-linking sample app → payments sample → two budgeting apps to study → market data",
    "swe": "project tutorials → build-your-own-X → app idea lists (easy/medium/hard) → roadmaps → a full CS curriculum",
    "cyber": "tools & resources list → OWASP cheat sheets → a deliberately vulnerable app to practice on → testing guide → payloads → ATT&CK map",
    "data": "beginner course → free textbook with notebooks → ML course → public datasets → dashboards in Python → resources list",
    "pm": "PM resources list → three open-source PM tools to run, study or contribute to → kanban you can extend",
    "marketing": "product analytics → two web-analytics platforms → marketing automation → newsletters → workflow automation",
}


# ---- NYC in-person hackathons (spring requirement) --------------------------------------------------
# Sources with public data: Devpost's listing JSON (filtered to NYC-area in-person events) and Major League
# Hacking's season page (embeds event JSON). Everything else is login-walled, so it's linked, not scraped.
NYC_RE = __import__("re").compile(
    r"\b(new york|nyc|brooklyn|manhattan|queens|bronx|staten island|jersey city|hoboken|newark|long island city|"
    r"columbia university|nyu|cornell tech|cuny|baruch|fordham|pace university|stevens|stony brook|hofstra)\b", __import__("re").I)
HACK_LINKS = [
    ("MLH season calendar (filter New York)", "https://mlh.io/seasons/2027/events"),
    ("Devpost — in-person hackathons", "https://devpost.com/hackathons?challenge_type[]=in-person&order_by=deadline&search=new+york"),
    ("Eventbrite NYC — hackathon", "https://www.eventbrite.com/d/ny--new-york/hackathon/"),
    ("Meetup NYC — hackathon", "https://www.meetup.com/find/?keywords=hackathon&location=us--ny--New%20York&source=EVENTS"),
    ("Luma NYC — hackathon", "https://lu.ma/nyc?q=hackathon"),
    ("NYC Civic Tech Hackathon (CUNY, annual)", "https://www.cuny.edu/civic-tech-hackathon/"),
    ("NASA Space Apps Challenge — NYC (October)", "https://www.spaceappschallenge.org/"),
    ("BetaNYC civic hack nights", "https://beta.nyc/events/"),
    ("NYC Open Data events", "https://opendata.cityofnewyork.us/events/"),
]


def _get(url: str, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 project-scout", "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def hackathons_nyc() -> list[dict]:
    """Upcoming/open in-person hackathons in the NYC area, newest deadline first. Fields: title,url,when,where,org,src."""
    out, seen_urls = [], set()
    try:  # Devpost: page through in-person listings, keep NYC-area locations
        for page in range(1, 6):
            data = json.loads(_get("https://devpost.com/api/hackathons?status[]=open&status[]=upcoming&challenge_type[]=in-person"
                                   f"&order_by=deadline&per_page=50&page={page}"))
            hs = data.get("hackathons", [])
            if not hs:
                break
            for h in hs:
                loc = (h.get("displayed_location") or {}).get("location", "")
                if NYC_RE.search(loc) or NYC_RE.search(h["title"]):
                    out.append({"title": h["title"], "url": h["url"], "when": h.get("submission_period_dates", ""),
                                "where": loc, "org": h.get("organization_name") or "", "src": "Devpost",
                                "prize": h.get("prize_amount") or ""})
    except Exception as e:
        print(f"devpost: {e}", file=sys.stderr)
    try:  # MLH: the season page embeds one JSON object per event
        import re
        html = _get("https://mlh.io/seasons/2027/events", "text/html").decode("utf-8", "replace")
        for m in re.finditer(r'\{"id":"[0-9a-f-]{36}","slug":.*?"venueAddress":\{[^}]*\}\}', html):
            try:
                ev = json.loads(m.group(0))
            except ValueError:
                continue
            va = ev.get("venueAddress") or {}
            where = ev.get("location") or f"{va.get('city', '')}, {va.get('state', '')}"
            if ev.get("formatType") in ("physical", "hybrid") and (NYC_RE.search(where) or va.get("state") == "New York"):
                out.append({"title": ev["name"], "url": ev.get("websiteUrl") or "https://mlh.io" + ev.get("url", ""),
                            "when": ev.get("dateRange", ""), "where": where, "org": "MLH", "src": "MLH", "prize": ""})
    except Exception as e:
        print(f"mlh: {e}", file=sys.stderr)
    uniq = []
    for h in out:
        if h["url"] not in seen_urls:
            seen_urls.add(h["url"])
            uniq.append(h)
    return uniq


def render_hack(h: dict) -> str:
    prize = f" · 🏆 {esc(h['prize'])}" if h.get("prize") else ""
    org = f" · {esc(h['org'])}" if h.get("org") and h["org"] != h["src"] else ""
    return (f'• <a href="{h["url"]}">{esc(h["title"])}</a>{prize}\n'
            f"  📅 {esc(h['when'])} · 📍 {esc(h['where'])}{org} · via {h['src']}")


def hack_footer() -> str:
    links = " · ".join(f'<a href="{u}">{esc(n)}</a>' for n, u in HACK_LINKS[:5])
    return f"\n  🔎 More: {links}"


def gh_repo(full_name: str) -> dict | None:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "project-scout"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{full_name}", headers=headers), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"{full_name}: {e.code}", file=sys.stderr)
        return None


def starters() -> list[tuple[str, str]]:
    """One evergreen 'Start here' chunk per major: ideas + basics to get going."""
    chunks = []
    for key, (label, *_rest) in MAJORS.items():
        repos = [r for r in (gh_repo(f) for f in STARTERS[key]) if r]
        rows = "\n".join(render_repo(r, "build") for r in repos)
        chunks.append((key, f"\n<b>📚 Start here — {label}: ideas &amp; basics</b>\n<i>{esc(STARTER_WHY[key])}</i>\n{rows}\n"
                            "  💡 Pick one, read its README, then run /scout for something fresh to build on top of it."))
    return chunks


def org_query(orgs: dict, anchor: str = "") -> str:
    return f"{anchor} {' '.join('org:' + o for o in orgs)} good-first-issues:>0 archived:false pushed:>={ago(90)}".strip()


def linkedin(name: str) -> str:
    return "https://www.linkedin.com/search/results/companies/?keywords=" + urllib.parse.quote(name)


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
    return {k: v for k, v in seen.items() if k == "_meta" or v >= cutoff}


def english(desc: str) -> bool:
    """English-only: require a description and >= 90% ASCII (drops CJK, Cyrillic, mixed-language repos)."""
    return bool(desc.strip()) and sum(ord(c) < 128 for c in desc) / len(desc) >= 0.9


def difficulty(it: dict) -> str:
    """Rough on-ramp hint from repo size (KB) and stars — so freshmen don't pick a 20k-star monorepo."""
    size, stars = it.get("size") or 0, it.get("stargazers_count") or 0
    if size < 5000 and stars < 500:
        return "🟢 starter"
    if size < 50000 and stars < 5000:
        return "🟡 intermediate"
    return "🔴 advanced"


def pick(items: list[dict], seen: dict, n: int, major: str = "") -> list[dict]:
    out = []
    for it in items:
        if it["full_name"] in seen or not english(f'{it["full_name"]} {it.get("description") or ""}') or not (it.get("description") or "").strip():
            continue
        if major not in AI_OK and AI_SPAM.search(f"{it['full_name']} {it.get('description') or ''}"):
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
    return (f'• <a href="{it["html_url"]}">{esc(it["full_name"])}</a> ⭐{it["stargazers_count"]}{lang} · {difficulty(it)}\n'
            f"  {esc(desc) or '(no description)'}{tail}")


def render_org(it: dict, sector_label: str) -> str:
    org = it["full_name"].split("/")[0]
    name = ORG_NAME.get(org, org)
    return (render_repo(it, "oss") +
            f'\n  🏷 {sector_label} · {esc(name)} · <a href="{linkedin(name)}">LinkedIn</a>'
            f'\n  📝 Resume: Open-Source Contributor, {esc(name)} ({esc(it["full_name"].split("/")[1])})')


def build_digest(seen: dict) -> list[tuple[str, str]]:
    """(key, chunk) per major/orgs section that has unseen repos; empty list = nothing new, send nothing."""
    chunks = []
    for key, (label, terms, anchor, evergreen) in MAJORS.items():
        parts = []
        for lane, (lane_label, n, sort, q) in LANES.items():
            try:
                picks = pick(gh_search(q(terms, anchor), sort), seen, n, key)
            except Exception as e:  # one bad query must not kill the run
                print(f"{key}/{lane}: {e}", file=sys.stderr)
                continue
            if picks:
                parts.append(f"<i>{lane_label}</i>\n" + "\n".join(render_repo(p, lane) for p in picks))
        if parts:
            chunks.append((key, f"\n<b>{label}</b>\n" + "\n".join(parts) + f'\n  📚 <a href="{evergreen}">evergreen idea list</a>'))
    parts = []
    for sector, (sector_label, orgs) in ORGS.items():
        try:
            picks = pick(gh_search(org_query(orgs), "updated"), seen, 2)
        except Exception as e:
            print(f"orgs/{sector}: {e}", file=sys.stderr)
            continue
        parts += [render_org(p, sector_label) for p in picks]
    new_hacks = []
    for h in hackathons_nyc():
        if "hack:" + h["url"] not in seen:
            seen["hack:" + h["url"]] = date.today().isoformat()
            new_hacks.append(h)
    if new_hacks:
        chunks.append(("hackathons", "\n<b>🏁 NYC in-person hackathons — new listings</b>\n<i>Spring requirement: attend one. Register early, teams fill up.</i>\n" +
                       "\n".join(render_hack(h) for h in new_hacks[:8]) + hack_footer()))
    if parts:
        chunks.append(("orgs", "\n<b>🤝 Contribute to mission-driven orgs — resume-ready experience</b>\n" + "\n".join(parts) +
                       '\n  🔎 <a href="https://www.linkedin.com/jobs/search/?keywords=%22open%20source%22%20volunteer">'
                       "open-source volunteer roles on LinkedIn</a>"))
    return chunks


HEADER = ("<b>🧪 Project Scout — new on GitHub</b>\n"
          "Build it, contribute to it, or reproduce the research — steal the idea, make your own version.")
FOOTER = "\n\n<i>/quant /fintech /swe /cyber /data /pm /marketing · /oss &lt;major&gt; · /research &lt;major&gt; · /orgs — live search anytime.</i>"


def targets() -> list[tuple[str, str]]:
    """(bot token, chat id) pairs: your private bot + optional campus bot -> public channel students join."""
    t = [(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])]
    if os.environ.get("CAMPUS_BOT_TOKEN") and os.environ.get("CAMPUS_CHAT_ID"):
        t.append((os.environ["CAMPUS_BOT_TOKEN"], os.environ["CAMPUS_CHAT_ID"]))
    return t


def send(text: str) -> None:
    for tok, chat in targets():
        body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:  # 400 "chat not found" = press Start / make bot channel admin; 404 = bad token
            print(f"telegram {e.code} for chat {chat}: {e.read()[:200].decode(errors='replace')}", file=sys.stderr)  # other targets still get it


def to_markdown(text: str) -> str:
    """Telegram HTML -> Discord markdown (<url> suppresses embeds)."""
    import re
    md = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"[\2](<\1>)", text)
    md = re.sub(r"</?b>", "**", md)
    md = re.sub(r"</?i>", "*", md)
    return md.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def discord(key: str, text: str) -> None:
    """Optional Discord mirror. DISCORD_WEBHOOKS = JSON {major key or "orgs": webhook url} posts each section into its
    own channel (see discord_setup.py); DISCORD_WEBHOOK_URL posts everything into one channel."""
    hooks = json.loads(os.environ.get("DISCORD_WEBHOOKS") or "{}")
    url = hooks.get(key) or os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return
    md = to_markdown(text).strip()
    title = md.splitlines()[0].replace("*", "")[:60] + f" · {datetime.now():%b %d %H:%M}"
    thread = None  # feed channels are forums: the first part opens a post, later parts reply inside it
    for part in [md[i:i + 1900] for i in range(0, len(md), 1900)]:  # Discord cap is 2000 chars
        body = {"content": part}
        if thread is None:
            body["thread_name"] = title
        u = url + ("?wait=true" if thread is None else f"?wait=true&thread_id={thread}")
        req = urllib.request.Request(u, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "project-scout"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                thread = json.load(r).get("channel_id")
        except urllib.error.HTTPError as e:
            err = e.read()[:200].decode(errors="replace")
            if e.code == 400 and "thread_name" in err:  # plain text channel (single-channel DISCORD_WEBHOOK_URL)
                body.pop("thread_name", None)
                urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(),
                                       headers={"Content-Type": "application/json", "User-Agent": "project-scout"}), timeout=30)
                thread = 0
            else:
                print(f"discord {e.code} for {key}: {err}", file=sys.stderr)
                return


def alert(text: str) -> None:
    """Ops alert to YOUR private bot only (never the campus channel / Discord)."""
    body = json.dumps({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                                                  data=body, headers={"Content-Type": "application/json"}), timeout=30)


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
    assert to_markdown('<b>x</b> <a href="https://u">t</a> &lt;i&gt;') == "**x** [t](<https://u>) <i>"
    assert pick([{"full_name": "x/y", "description": "seen"}, {"full_name": "a/b", "description": "fresh"},
                 {"full_name": "c/d", "description": "extra"}], {"x/y": "2099-01-01"}, 1) == [{"full_name": "a/b", "description": "fresh"}]
    assert pick([{"full_name": "a/b", "description": ""}], {}, 1) == []  # English-only also means: must have a description
    assert not english("") and english("Agent-native backtesting") and not english("面向基本面因子研究的智能体-AI agent")
    r = {"full_name": "<b>", "html_url": "u", "stargazers_count": 1, "description": ""}
    assert "&lt;b&gt;" in render_repo(r, "build") and "good-first-issues" in render_repo(r, "oss")
    assert "good-first-issues:>0" in LANES["oss"][3]("t", "trading")
    assert LANES["research"][3]("t", "trading").startswith('"quantitative finance" trading arxiv')
    assert pick([{"full_name": "x/gpt-agent", "description": "an LLM agent"}, {"full_name": "y/scanner", "description": "port scanner"}], {}, 5, "cyber") \
        == [{"full_name": "y/scanner", "description": "port scanner"}]
    assert difficulty({"size": 100, "stargazers_count": 10}) == "🟢 starter" and difficulty({"size": 99999, "stargazers_count": 10}) == "🔴 advanced"
    print("self-check ok")


def main() -> int:
    if "--self-check" in sys.argv:
        self_check()
        return 0
    if "--starters" in sys.argv:  # one-time evergreen post per major (Telegram + Discord); rerun after editing STARTERS
        chunks = starters()
        for m in messages([t for _, t in chunks]):
            send(m)
        for key, text in chunks:
            discord(key, text)
        print(f"posted {len(chunks)} start-here sections")
        return 0
    seen = load_seen()
    chunks = build_digest(seen)
    msgs = messages([HEADER] + [t for _, t in chunks] + [FOOTER]) if chunks else []
    if "--preview" in sys.argv:
        print("\n\n=====\n\n".join(msgs) or "(nothing new)")
        return 0
    for m in msgs:
        send(m)
    for key, text in chunks:  # Discord: one post per section, into that section's channel
        discord(key, text)
    meta = seen.pop("_meta", {}) if isinstance(seen.get("_meta"), dict) else {}
    now = datetime.now()
    if chunks:
        meta["last_sent"] = now.isoformat(timespec="minutes")
    elif meta.get("last_sent") and now - datetime.fromisoformat(meta["last_sent"]) > timedelta(hours=48):
        alert(f"⚠️ Project Scout has posted nothing since {meta['last_sent']} — check the Actions log / GitHub search terms.")
    seen["_meta"] = meta
    json.dump(seen, open(SEEN, "w"), indent=0)
    print(f"sent {len(msgs)} message(s) at {datetime.now():%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
