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
# Build-lane sub-queries for majors that need more than one search. (label, GitHub query text, picks per run)
# GitHub allows one `language:` per query, so languages are separate searches. SWE is weighted to Python + SQL.
BUILD_QUERIES = {
    "swe": [("🐍 Python backend", '"backend" OR api OR "web app" OR cli OR automation language:Python', 2),
            ("🗄 SQL & databases", 'sql OR postgres OR sqlite OR "data model" OR analytics language:SQL', 1),
            ("🗄 SQL with Python", 'sql OR postgres OR sqlalchemy OR "data pipeline" language:Python', 1),
            ("🖥 Frontend", 'frontend OR react OR vue OR "web app" OR dashboard language:TypeScript', 1),
            ("☕ Other languages", '"backend" OR api OR microservice OR cli language:Go', 1)],
    "data": [("📊 Analysis & pipelines", MAJORS["data"][1], 2),
             ("📈 Power BI", '"power bi" OR powerbi OR DAX OR "power query"', 1),
             ("📉 Tableau", 'tableau OR "tableau public" OR tabpy OR hyper', 1)],
}

# Cybersecurity by the 8 CISSP domains: live search terms + curated legit projects + a reference link each.
CYBER_DOMAINS = {
    "d1": ("D1 Security & Risk Management (GRC)", 'grc OR "risk management" OR compliance OR "security policy" OR "nist csf"',
           ["cisagov/cset", "usnistgov/OSCAL", "mitre/saf"], ("NIST Cybersecurity Framework", "https://www.nist.gov/cyberframework")),
    "d2": ("D2 Asset Security", '"data loss prevention" OR "secrets detection" OR "data classification" OR "asset inventory" OR "pii detection"',
           ["gitleaks/gitleaks", "trufflesecurity/trufflehog", "data-privacy-stack/presidio", "cisagov/ScubaGear", "hashicorp/vault"],
           ("CISA: Asset & data protection resources", "https://www.cisa.gov/resources-tools")),
    "d3": ("D3 Security Architecture & Engineering", '"threat modeling" OR cryptography OR "zero trust" OR "secure design" OR "secrets management"',
           ["OWASP/threat-dragon", "pyca/cryptography", "openbao/openbao", "sigstore/cosign"],
           ("OWASP Threat Modeling", "https://owasp.org/www-community/Threat_Modeling")),
    "d4": ("D4 Communication & Network Security", '"network security" OR firewall OR "intrusion detection" OR "packet capture" OR "network monitoring"',
           ["wireshark/wireshark", "zeek/zeek", "OISF/suricata", "nmap/nmap", "snort3/snort3"],
           ("Wireshark University / sample captures", "https://wiki.wireshark.org/SampleCaptures")),
    "d5": ("D5 Identity & Access Management", 'IAM OR authentication OR "single sign-on" OR OAuth OR passkeys OR "access control"',
           ["keycloak/keycloak", "goauthentik/authentik", "authelia/authelia", "ory/kratos", "oauth2-proxy/oauth2-proxy"],
           ("NIST SP 800-63 Digital Identity Guidelines", "https://pages.nist.gov/800-63-4/")),
    "d6": ("D6 Security Assessment & Testing", '"penetration testing" OR "vulnerability scanner" OR CTF OR fuzzing OR "security testing"',
           ["projectdiscovery/nuclei", "zaproxy/zaproxy", "OWASP/wstg", "juice-shop/juice-shop", "OWASP/Nettacker"],
           ("OWASP Web Security Testing Guide", "https://owasp.org/www-project-web-security-testing-guide/")),
    "d7": ("D7 Security Operations", 'SIEM OR "incident response" OR "threat hunting" OR "detection rules" OR "digital forensics" OR SOC',
           ["SigmaHQ/sigma", "elastic/detection-rules", "wazuh/wazuh", "Velocidex/velociraptor", "mitre-attack/attack-navigator"],
           ("MITRE ATT&CK", "https://attack.mitre.org/")),
    "d8": ("D8 Software Development Security", '"secure coding" OR SAST OR DevSecOps OR "dependency scanning" OR "supply chain security" OR sbom',
           ["OWASP/ASVS", "semgrep/semgrep", "aquasecurity/trivy", "OWASP/CheatSheetSeries", "dependency-check/DependencyCheck", "github/codeql"],
           ("OWASP Top 10 & ASVS", "https://owasp.org/www-project-application-security-verification-standard/")),
}


# Course-aligned searches. Quant = Baruch MFE curriculum (mfe.baruch.cuny.edu/curriculum, fetched 2026-09-15);
# Finance = Zicklin finance major core (FIN 3000/3610/3710) + the elective topics; PM = the tools TLDP asked for.
# One course per major per run rotates through the feed; `--courses` posts an evergreen "top repos per course" map.
COURSES = {
    "quant": [
        ("MTH 9814 Financial Markets & Securities", '"bond pricing" OR "yield curve" OR "financial instruments" OR "option payoff"'),
        ("MTH 9815 Software Engineering for Finance", '"trading system" OR "order book" OR "market data" language:C++'),
        ("MTH 9816 Fundamentals of Trading", '"algorithmic trading" OR "order execution" OR "order book" OR backtest'),
        ("MTH 9821 Numerical Methods for Finance", '"finite difference" OR "monte carlo" OR "binomial tree" OR "option pricing"'),
        ("MTH 9831 Probability & Stochastic Processes", '"stochastic calculus" OR "brownian motion" OR "stochastic process" OR "ito"'),
        ("MTH 9842 Optimization Techniques in Finance", '"portfolio optimization" OR "mean-variance" OR "quadratic programming" OR "efficient frontier"'),
        ("MTH 9845 Market & Credit Risk Management", '"value at risk" OR "expected shortfall" OR "credit risk" OR "risk model"'),
        ("MTH 9855 Asset Allocation & Portfolio Management", '"asset allocation" OR "black-litterman" OR "risk parity" OR "portfolio construction"'),
        ("MTH 9863 Volatility Filtering & Estimation", 'GARCH OR "realized volatility" OR "volatility estimation" OR "kalman filter"'),
        ("MTH 9866 FX Modeling & Market Making", '"foreign exchange" OR "market making" OR "fx options" OR "currency pairs"'),
        ("MTH 9873 / 9878 Interest Rate Models", '"interest rate model" OR "hull-white" OR "term structure" OR swaption'),
        ("MTH 9875 The Volatility Surface", '"volatility surface" OR "implied volatility" OR "local volatility" OR heston OR SABR'),
        ("MTH 9876 Credit Risk Models", '"credit default swap" OR "default probability" OR "merton model" OR "credit risk"'),
        ("MTH 9879 Market Microstructure Models", '"market microstructure" OR "limit order book" OR "order flow" OR "high frequency"'),
        ("MTH 9882 Fixed Income Risk Management", '"fixed income" OR duration OR convexity OR "bond portfolio"'),
        ("MTH 9887 Blockchain Technologies in Finance", 'blockchain OR "smart contract" OR DeFi OR "on-chain"'),
        ("MTH 9893 / 9867 Time Series & Algorithmic Trading", '"time series" OR ARIMA OR cointegration OR "pairs trading"'),
        ("MTH 9894 / 9897 Algorithmic & Systematic Trading", '"systematic trading" OR "trading strategy" OR backtesting OR "momentum strategy"'),
        ("MTH 9896 Behavioral Finance", '"behavioral finance" OR "investor sentiment" OR "sentiment analysis" stocks'),
        ("MTH 9898 / 9899 Data Science & Machine Learning in Finance", '"machine learning" finance OR "stock prediction" OR "factor model" OR "financial data"'),
    ],
    "fintech": [
        ("FIN 3000 Principles of Finance", '"time value of money" OR "capital budgeting" OR NPV OR IRR OR "financial calculator"'),
        ("FIN 3610 Corporate Finance", '"corporate finance" OR WACC OR "capital structure" OR "dividend policy" OR DCF'),
        ("FIN 3710 Investment Analysis", '"investment analysis" OR "portfolio theory" OR CAPM OR "security analysis" OR "efficient frontier"'),
        ("Financial modeling & valuation", '"financial modeling" OR "three statement" OR "DCF model" OR LBO OR "valuation model"'),
        ("Financial statement analysis", '"financial statements" OR "ratio analysis" OR "10-K" OR "SEC EDGAR" OR XBRL'),
        ("Derivatives & options", '"black-scholes" OR "option pricing" OR "options strategy" OR greeks'),
        ("Fixed income", '"fixed income" OR "bond valuation" OR "yield curve" OR duration'),
        ("International finance & FX", '"foreign exchange" OR "exchange rate" OR forex OR "currency hedging"'),
        ("Financial markets & trading", '"stock market" OR "market data" OR "trading platform" OR brokerage'),
        ("Personal finance & fintech apps", '"personal finance" OR budgeting OR "open banking" OR "robo-advisor" OR payments'),
        ("Risk management & credit", '"risk management" OR "credit scoring" OR "fraud detection" OR "credit risk"'),
        ("Real estate finance", '"real estate" OR mortgage OR amortization OR REIT'),
    ],
    "pm": [
        ("Scrum", 'scrum OR sprint OR "scrum master" OR "sprint planning" OR retrospective'),
        ("Jira", 'jira OR "jira api" OR "jira automation" OR "jira dashboard"'),
        ("Confluence", 'confluence OR "confluence api" OR atlassian OR "team wiki"'),
        ("Kanban", 'kanban OR "kanban board" OR "task board" OR "work in progress"'),
        ("Agile metrics & reporting", 'velocity OR burndown OR "agile metrics" OR "cycle time" OR "sprint report"'),
        ("Roadmaps & OKRs", 'roadmap OR OKR OR "product roadmap" OR "release planning"'),
        ("Requirements & user stories", '"user stories" OR "acceptance criteria" OR backlog OR "requirements management"'),
        ("Risk, stakeholders & schedules", '"risk register" OR stakeholder OR "project charter" OR gantt'),
    ],
}


def course_rotation(major: str) -> list[tuple[str, str, int]]:
    """One course per run per major; every course comes around every len(COURSES[major]) runs."""
    cs = COURSES[major]
    i = (datetime.now().timetuple().tm_yday * 4 + datetime.now().hour // 6) % len(cs)
    return [(f"🎓 {cs[i][0]}", cs[i][1], 1)]


def cyber_rotation() -> list[tuple[str, str, int]]:
    """Two CISSP domains per run (all eight covered every 4 runs) plus the general cyber search."""
    keys = list(CYBER_DOMAINS)
    i = (datetime.now().timetuple().tm_yday * 4 + datetime.now().hour // 6) * 2 % len(keys)
    picked = [keys[i], keys[(i + 1) % len(keys)]]
    return [("🔐 General", MAJORS["cyber"][1], 1)] + [(f"🔐 {CYBER_DOMAINS[k][0]}", CYBER_DOMAINS[k][1], 1) for k in picked]


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
             "awesomedata/awesome-public-datasets", "streamlit/streamlit", "academic/awesome-datascience",
             "microsoft/PowerBI-Developer-Samples", "microsoft/powerbi-desktop-samples", "tableau/TabPy",
             "tableau/server-client-python", "tableau/hyper-api-samples"],
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
    "data": "beginner course → free textbook with notebooks → ML course → public datasets → dashboards in Python → resources list → Power BI samples (Microsoft) → Tableau TabPy, API client and Hyper samples",
    "pm": "PM resources list → three open-source PM tools to run, study or contribute to → kanban you can extend",
    "marketing": "product analytics → two web-analytics platforms → marketing automation → newsletters → workflow automation",
}


# ---- NYC in-person hackathons (spring requirement) --------------------------------------------------
# Sources with public data: Devpost's listing JSON (filtered to NYC-area in-person events) and Major League
# Hacking's season page (embeds event JSON). Everything else is login-walled, so it's linked, not scraped.
NYC_RE = __import__("re").compile(
    r"\b(new york, ?ny|new york, new york|nyc|brooklyn|manhattan|queens|bronx|staten island|flushing|jamaica, ny|jersey city|hoboken|newark, ?nj|"
    r"long island city|columbia university|nyu|cornell tech|cuny|baruch|fordham|pace university|stevens|stony brook|hofstra)\b", __import__("re").I)
# note: "<city>, New York" upstate (Ithaca, Troy, Rochester) is deliberately NOT matched — commutable NYC area only.
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
            if ev.get("formatType") in ("physical", "hybrid") and NYC_RE.search(where):
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
        repos = ordered([r for r in (gh_repo(f) for f in STARTERS[key]) if r])
        rows = "\n".join(render_repo(r, "build") for r in repos)
        chunks.append((key, f"\n<b>📚 Start here — {label}: ideas &amp; basics</b>\n<i>{esc(STARTER_WHY[key])}</i>\n{rows}\n"
                            "  💡 Pick one, read its README, then run /scout for something fresh to build on top of it."))
    return chunks


def org_query(orgs: dict, anchor: str = "") -> str:
    return f"{anchor} {' '.join('org:' + o for o in orgs)} good-first-issues:>0 archived:false pushed:>={ago(90)}".strip()


def linkedin(name: str) -> str:
    return "https://www.linkedin.com/search/results/companies/?keywords=" + urllib.parse.quote(name)


# ---- GitHub budget: stay well inside the limits (30 search req/min with a token, 10 without) ----------------
SEARCH_BUDGET = int(os.environ.get("SEARCH_BUDGET", 26))  # hard cap per run; the digest stops when it's spent (majors rotate, so all get covered)
SEARCH_SPACING = 2.5        # seconds between searches → max 24/min even with no other pacing
_calls = {"n": 0, "limited": 0}


class BudgetExceeded(Exception):
    pass


def gh_search(q: str, sort: str = "stars", n: int = 15) -> list[dict]:
    import time
    if _calls["n"] >= SEARCH_BUDGET:
        raise BudgetExceeded(f"search budget {SEARCH_BUDGET} spent")
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": sort, "order": "desc", "per_page": n})
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "project-scout (github.com/thecyberthriver/project-scout)"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    time.sleep(SEARCH_SPACING)
    _calls["n"] += 1
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            return json.load(r).get("items", [])
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):  # rate-limited: back off exactly as GitHub asks, once; never hammer
            _calls["limited"] += 1
            wait = int(e.headers.get("Retry-After") or 0) or max(0, int(e.headers.get("X-RateLimit-Reset") or 0) - int(time.time()))
            if 0 < wait <= 90 and _calls["limited"] == 1:
                print(f"github rate limit: waiting {wait}s once", file=sys.stderr)
                time.sleep(wait + 1)
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    return json.load(r).get("items", [])
            raise BudgetExceeded(f"GitHub rate-limited us ({e.code}); stopping this run early")
        raise


def rate_limit_status() -> str:
    """Remaining search quota (free call, not counted). Used for the end-of-run report."""
    try:
        headers = {"User-Agent": "project-scout"}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
        with urllib.request.urlopen(urllib.request.Request("https://api.github.com/rate_limit", headers=headers), timeout=20) as r:
            s = json.load(r)["resources"]["search"]
            return f"search quota {s['remaining']}/{s['limit']} left"
    except Exception as e:
        return f"rate_limit check failed: {e}"


# ---- index.json: everything the feed found, served to the Workers from GitHub's CDN (raw.githubusercontent) -----
# Students' searches read this snapshot instead of the API, so their traffic never counts against GitHub limits.
INDEX = "index.json"
INDEX_TTL_DAYS, INDEX_ROWS_PER_KEY, STATIC_REFRESH_DAYS = 45, 30, 7
_index: dict = {}


def row(it: dict) -> dict:
    return {"full_name": it["full_name"], "html_url": it["html_url"], "stargazers_count": it.get("stargazers_count") or 0,
            "language": it.get("language"), "description": (it.get("description") or "")[:200], "size": it.get("size") or 0,
            "pushed_at": (it.get("pushed_at") or "")[:10], "seen_at": date.today().isoformat()}


def load_index() -> dict:
    global _index
    try:
        _index = json.load(open(INDEX, encoding="utf-8"))
    except (OSError, ValueError):
        _index = {}
    _index.setdefault("keys", {})
    _index.setdefault("static", {})
    return _index


def index_add(key: str, items: list[dict]) -> None:
    """Merge search results under key "major|lane|sublabel"; newest first, de-duped, capped, 45-day TTL."""
    rows = _index["keys"].setdefault(key, [])
    cutoff = ago(INDEX_TTL_DAYS)
    fresh = [row(it) for it in items if english(f'{it["full_name"]} {it.get("description") or ""}') and (it.get("description") or "").strip()]
    names = {r["full_name"] for r in fresh}
    _index["keys"][key] = (fresh + [r for r in rows if r["full_name"] not in names and r.get("seen_at", "") >= cutoff])[:INDEX_ROWS_PER_KEY]


def refresh_static() -> None:
    """Weekly: curated sets (Start here, CISSP domains) via the core API (5000/h, not the search limit)."""
    import time
    st = _index["static"]
    if st.get("refreshed_at", "") >= ago(STATIC_REFRESH_DAYS):
        return
    starters, domains = {}, {}
    for key, names in STARTERS.items():
        starters[key] = [row(r) for r in (gh_repo(n) for n in names) if r]
        time.sleep(0.3)
    for k, (label, _t, names, ref) in CYBER_DOMAINS.items():
        domains[k] = {"label": label, "ref": list(ref), "repos": [row(r) for r in (gh_repo(n) for n in names) if r]}
        time.sleep(0.3)
    st.update({"refreshed_at": date.today().isoformat(), "starters": starters, "cyber_domains": domains})


def save_index() -> None:
    _index["generated"] = datetime.now().isoformat(timespec="minutes")
    _index["phase"] = list(phase())
    json.dump(_index, open(INDEX, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)


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


RANK = {"🟢 starter": 0, "🟡 intermediate": 1, "🔴 advanced": 2}
PHASES = [(0, "Phase 1 · Sep–Oct · starter projects"), (1, "Phase 2 · Nov–Jan · starter + intermediate"),
          (2, "Phase 3 · Feb–May · everything, including advanced")]


def phase(today: date | None = None) -> tuple[int, str]:
    """Difficulty ceiling rises through the school year so students ease in: 0 starter, 1 intermediate, 2 advanced."""
    m = (today or date.today()).month
    return PHASES[0] if m in (9, 10) else PHASES[1] if m in (11, 12, 1) else PHASES[2]


def ordered(items: list[dict], ceiling: int | None = None) -> list[dict]:
    """Easiest first (starter → intermediate → advanced), then most stars. With a ceiling, harder repos come last
    and are used only if nothing easier exists."""
    ranked = sorted(items, key=lambda it: (RANK[difficulty(it)], -(it.get("stargazers_count") or 0)))
    if ceiling is None:
        return ranked
    easy = [it for it in ranked if RANK[difficulty(it)] <= ceiling]
    return easy + [it for it in ranked if RANK[difficulty(it)] > ceiling]


def pick(items: list[dict], seen: dict, n: int, major: str = "") -> list[dict]:
    out = []
    for it in ordered(items, phase()[0]):
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
    run_no = datetime.now().timetuple().tm_yday * 4 + datetime.now().hour // 6   # 4 runs a day
    order = list(MAJORS)
    order = order[run_no % len(order):] + order[:run_no % len(order)]              # rotate who goes first, so the budget cap is fair
    for key in order:
        label, terms, anchor, evergreen = MAJORS[key]
        parts = []
        for lane, (lane_label, n, sort, q) in LANES.items():
            if lane in ("oss", "research") and (lane == "oss") != (run_no % 2 == 0):
                continue  # oss and research alternate runs → half the calls, still every 12 h each
            subs = ([(None, terms, n)] if lane != "build" else
                    cyber_rotation() if key == "cyber" else BUILD_QUERIES.get(key, [(None, terms, n)]))
            if lane == "build" and len(subs) > 3:                                   # e.g. SWE's 5 languages: 3 per run, rotating
                subs = [subs[(run_no + i) % len(subs)] for i in range(3)]
            if lane == "build" and key in COURSES:  # one course-aligned search per run
                subs = [(s[0], s[1], 1) for s in subs] + course_rotation(key)
            for sub_label, sub_terms, sub_n in subs:
                try:
                    found = gh_search(q(sub_terms, anchor), sort)
                    index_add(f"{key}|{lane}|{sub_label or ''}", found)
                    picks = pick(found, seen, sub_n, key)
                except BudgetExceeded as e:
                    print(f"stopping early: {e}", file=sys.stderr)
                    return finish(chunks, seen)
                except Exception as e:  # one bad query must not kill the run
                    print(f"{key}/{lane}/{sub_label}: {e}", file=sys.stderr)
                    continue
                if picks:
                    head = f"<i>{lane_label}{' · ' + sub_label if sub_label else ''}</i>"
                    parts.append(head + "\n" + "\n".join(render_repo(p, lane) for p in picks))
        if parts:
            chunks.append((key, f"\n<b>{label}</b>\n" + "\n".join(parts) + f'\n  📚 <a href="{evergreen}">evergreen idea list</a>'))
    return finish(chunks, seen)


def full_index() -> None:
    """Every search the feed can make, once, into index.json (~85 searches ≈ 4 min at SEARCH_SPACING). Weekly job."""
    for key, (label, terms, anchor, evergreen) in MAJORS.items():
        subs = [(None, terms, 0)] if key not in BUILD_QUERIES and key != "cyber" else []
        subs += BUILD_QUERIES.get(key, [])
        if key == "cyber":
            subs += [("🔐 General", terms, 0)] + [(f"🔐 {d[0]}", d[1], 0) for d in CYBER_DOMAINS.values()]
        subs += [(f"🎓 {c[0]}", c[1], 0) for c in COURSES.get(key, [])]
        for lane, (lane_label, n, sort, q) in LANES.items():
            for sub_label, sub_terms, _n in (subs if lane == "build" else [(None, terms, 0)]):
                try:
                    index_add(f"{key}|{lane}|{sub_label or ''}", gh_search(q(sub_terms, anchor), sort))
                except BudgetExceeded as e:
                    print(f"full_index stopped: {e}", file=sys.stderr)
                    return
                except Exception as e:
                    print(f"{key}/{lane}/{sub_label}: {e}", file=sys.stderr)
    for sector, (sector_label, orgs) in ORGS.items():
        try:
            index_add(f"orgs|{sector}|{sector_label}", gh_search(org_query(orgs), "updated"))
        except Exception as e:
            print(f"orgs/{sector}: {e}", file=sys.stderr)
    _index["hackathons"] = {"at": datetime.now().isoformat(timespec="minutes"), "items": hackathons_nyc()}


def finish(chunks: list, seen: dict) -> list[tuple[str, str]]:
    """Sections that don't depend on the per-major loop: hackathons (no GitHub) and mission-driven orgs (3 searches)."""
    parts = []
    for sector, (sector_label, orgs) in ORGS.items():
        try:
            found = gh_search(org_query(orgs), "updated")
            index_add(f"orgs|{sector}|{sector_label}", found)
            picks = pick(found, seen, 2)
        except BudgetExceeded:
            break
        except Exception as e:
            print(f"orgs/{sector}: {e}", file=sys.stderr)
            continue
        parts += [render_org(p, sector_label) for p in picks]
    new_hacks = []
    all_hacks = hackathons_nyc()
    _index["hackathons"] = {"at": datetime.now().isoformat(timespec="minutes"), "items": all_hacks}
    for h in all_hacks:
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
          "Build it, contribute to it, or reproduce the research — steal the idea, make your own version.\n"
          f"<i>📶 {phase()[1]}. Lists run easiest → hardest.</i>")
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
    hard, easy = {"full_name": "h", "size": 99999, "stargazers_count": 9}, {"full_name": "e", "size": 10, "stargazers_count": 1}
    assert [r["full_name"] for r in ordered([hard, easy])] == ["e", "h"]
    assert phase(date(2026, 9, 15))[0] == 0 and phase(date(2026, 12, 1))[0] == 1 and phase(date(2027, 3, 1))[0] == 2
    print("self-check ok")


def main() -> int:
    if "--self-check" in sys.argv:
        self_check()
        return 0
    if "--courses" in sys.argv:  # one-time evergreen map: top repos per course/topic, posted per major (optionally: --courses pm fintech)
        wanted = [a for a in sys.argv[sys.argv.index("--courses") + 1:] if a in COURSES] or list(COURSES)
        for key in wanted:
            courses, label = COURSES[key], MAJORS[key][0]
            rows = []
            for name, terms in courses:
                try:
                    items = ordered([r for r in gh_search(f"{terms} stars:>=50 archived:false", "stars", 8)
                                     if english(f'{r["full_name"]} {r.get("description") or ""}') and (r.get("description") or "").strip()])[:2]
                except Exception as e:
                    print(f"{key}/{name}: {e}", file=sys.stderr)
                    continue
                if items:
                    rows.append(f"<i>🎓 {esc(name)}</i>\n" + "\n".join(render_repo(r, "build") for r in items))
            head = (f"\n<b>🎓 {label} — course-aligned project ideas (Baruch)</b>\n"
                    "<i>Two well-known repos per course or topic, easiest first. Live search: /courses in the bot lists the codes.</i>")
            for m in messages([head] + rows):  # packs under Telegram's 4096-char limit across course rows
                send(m)
            if os.environ.get("DISCORD_WEBHOOKS"):
                discord(key, head + "\n" + "\n".join(rows))
            print(f"posted course map: {key} ({len(rows)} courses)")
        return 0
    if "--cyber-domains" in sys.argv:  # one-time: 8 curated posts (one per CISSP domain) into the cyber channel
        for k, (label, _t, repos, (ref_name, ref_url)) in CYBER_DOMAINS.items():
            items = ordered([r for r in (gh_repo(f) for f in repos) if r])
            text = (f"\n<b>🔐 {esc(label)} — legit projects to learn from and contribute to</b>\n" +
                    "\n".join(render_repo(r, "oss") for r in items) +
                    f'\n  📖 Reference: <a href="{ref_url}">{esc(ref_name)}</a>\n  💡 Live search: /cyber {k}')
            for m in messages([text]):
                send(m)
            discord("cyber", text)
        print("posted 8 cyber-domain sections")
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
    load_index()
    if "--index-only" in sys.argv:  # full rebuild of index.json (every lane, language, course, domain); sends nothing
        full_index()
        refresh_static()
        save_index()
        print(f"index: {sum(len(v) for v in _index['keys'].values())} rows in {len(_index['keys'])} keys · {_calls['n']} searches")
        return 0
    chunks = build_digest(seen)
    try:
        refresh_static()
    except Exception as e:
        print(f"static refresh: {e}", file=sys.stderr)
    save_index()
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
    status = rate_limit_status()
    print(f"sent {len(msgs)} message(s) at {datetime.now():%Y-%m-%d %H:%M} · {_calls['n']} GitHub searches · {status}")
    if _calls["limited"]:
        alert(f"⚠️ Project Scout hit GitHub's rate limit {_calls['limited']}× this run ({_calls['n']} searches). "
              f"It backed off and stopped early. If this repeats, lower SEARCH_BUDGET in project_scout.py. {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
