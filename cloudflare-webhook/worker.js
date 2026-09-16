/**
 * Project Scout — Cloudflare Worker (instant Telegram webhook).
 *
 * Answers instantly by hitting the GitHub Search API directly — no Actions round-trip:
 *   /quant /fintech /swe /cyber /data [keywords]   fresh repos to build (last 90 days)
 *   /oss <major> [keywords]                        active repos with open good-first-issues
 *   /research <major> [keywords]                   fresh repos citing arXiv (paper code)
 * The 2-hourly push alerts live in ../project_scout.py (GitHub Actions).
 *
 * Secrets: TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, OWNER_CHAT_ID (lock to one user; remove to open to students),
 *          optional GITHUB_TOKEN (30 searches/min instead of 10).
 */
export const MAJORS = {
  quant:   { label: "📈 Quant",                anchor: "trading",  terms: '"quantitative finance" OR backtesting OR "algorithmic trading" OR "options pricing" OR "portfolio optimization"' },
  fintech: { label: "💳 Finance / FinTech",    anchor: "finance",  terms: 'fintech OR payments OR "personal finance" OR "open banking" OR "stock market" OR "financial data"' },
  swe:     { label: "💻 Software Engineering", anchor: "software", terms: '"build your own" OR "from scratch" OR "project ideas" OR "portfolio project" OR "full stack"' },
  cyber:   { label: "🔐 Cybersecurity",        anchor: "security", terms: 'cybersecurity OR "penetration testing" OR "threat detection" OR "malware analysis" OR "security tool" OR CTF' },
  data:    { label: "📊 Data Analytics",       anchor: "data",     terms: '"data analytics" OR "data analysis" OR "exploratory data analysis" OR "data pipeline" OR "data visualization"' },
  pm:      { label: "📋 Project Management",   anchor: '"project management"', terms: '"project management" OR scrum OR kanban OR "task management" OR "agile" OR roadmap' },
  marketing: { label: "📣 Digital Marketing",  anchor: "marketing", terms: '"digital marketing" OR SEO OR "marketing analytics" OR "social media" OR "email marketing" OR "growth hacking"' },
};
const ALIAS = { finance: "fintech", software: "swe", security: "cyber", analytics: "data", project: "pm", projectmanagement: "pm", digitalmarketing: "marketing", seo: "marketing" };
const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
// GitHub search has no parentheses, so only the build lane uses the OR list; others use the anchor word.
export const LANES = {
  build:    { label: "🧪 Build this", sort: "stars",   q: (t) => `${t} created:>=${ago(90)} stars:>=10 archived:false` },
  oss:      { label: "🤝 Contribute", sort: "updated", q: (t) => `${t} good-first-issues:>0 stars:>=50 pushed:>=${ago(30)} archived:false` },
  research: { label: "🔬 Research",  sort: "stars",   q: (t) => `${t} arxiv in:readme,description created:>=${ago(90)} stars:>=20 archived:false` },
};
// a bare word + arxiv returns generic AI repos; a field phrase keeps research on-major
const RESEARCH_ANCHOR = { quant: '"quantitative finance"', fintech: '"financial"', swe: '"software engineering"', cyber: "cybersecurity", data: '"data analysis"', pm: '"project management"', marketing: '"digital marketing"' };
const LANE_ALIAS = { contribute: "oss", opensource: "oss", paper: "research", papers: "research", new: "build",
                     org: "orgs", nonprofit: "orgs", volunteer: "orgs", mission: "orgs",
                     basics: "start", starter: "start", starters: "start", learn: "start", ideas: "start", begin: "start",
                     hackathon: "hackathons", hack: "hackathons", hacks: "hackathons", events: "hackathons" };
// SWE flavors: one language per GitHub query, so /swe runs Python + SQL + frontend in parallel by default;
// "/swe sql", "/swe frontend", "/swe java" … pick one. Mirrors BUILD_QUERIES in ../project_scout.py.
export const SWE_FLAVORS = {
  python:   '"backend" OR api OR "web app" OR cli OR automation language:Python',
  backend:  '"backend" OR api OR "web app" OR cli OR automation language:Python',
  sql:      'sql OR postgres OR sqlite OR "data model" OR analytics language:SQL',
  frontend: 'frontend OR react OR vue OR "web app" OR dashboard language:TypeScript',
  react: 'react language:TypeScript', vue: 'vue language:TypeScript', javascript: '"web app" OR frontend OR api language:JavaScript',
  typescript: '"web app" OR frontend OR api language:TypeScript', java: '"backend" OR api OR microservice language:Java',
  go: '"backend" OR api OR microservice OR cli language:Go', rust: 'cli OR "backend" OR api language:Rust',
  csharp: '"backend" OR api OR "web app" language:"C#"', "c#": '"backend" OR api OR "web app" language:"C#"', kotlin: 'android OR "backend" language:Kotlin',
  swift: 'ios OR app language:Swift', php: '"web app" OR api language:PHP', ruby: '"web app" OR api language:Ruby',
};
const SWE_DEFAULT = ["python", "sql", "frontend"];
// Data Analytics tool flavors: "/data powerbi", "/data tableau" (plain keywords also work).
export const DATA_FLAVORS = { powerbi: '"power bi" OR powerbi OR DAX OR "power query"', "power": '"power bi" OR powerbi OR DAX', tableau: 'tableau OR "tableau public" OR tabpy OR hyper' };
// Course-aligned searches (Baruch MFE + Zicklin finance core + PM tools). Mirrors COURSES in ../project_scout.py.
// Keys are what a student types: "/quant mth9821", "/fintech fin3710", "/fintech options", "/pm jira", "/courses quant".
export const COURSES = {
  quant: {
    mth9814: ["MTH 9814 Financial Markets & Securities", '"bond pricing" OR "yield curve" OR "financial instruments" OR "option payoff"'],
    mth9815: ["MTH 9815 Software Engineering for Finance", '"trading system" OR "order book" OR "market data" language:C++'],
    mth9816: ["MTH 9816 Fundamentals of Trading", '"algorithmic trading" OR "order execution" OR "order book" OR backtest'],
    mth9821: ["MTH 9821 Numerical Methods for Finance", '"finite difference" OR "monte carlo" OR "binomial tree" OR "option pricing"'],
    mth9831: ["MTH 9831 Probability & Stochastic Processes", '"stochastic calculus" OR "brownian motion" OR "stochastic process" OR "ito"'],
    mth9842: ["MTH 9842 Optimization Techniques in Finance", '"portfolio optimization" OR "mean-variance" OR "quadratic programming" OR "efficient frontier"'],
    mth9845: ["MTH 9845 Market & Credit Risk Management", '"value at risk" OR "expected shortfall" OR "credit risk" OR "risk model"'],
    mth9855: ["MTH 9855 Asset Allocation & Portfolio Management", '"asset allocation" OR "black-litterman" OR "risk parity" OR "portfolio construction"'],
    mth9863: ["MTH 9863 Volatility Filtering & Estimation", 'GARCH OR "realized volatility" OR "volatility estimation" OR "kalman filter"'],
    mth9866: ["MTH 9866 FX Modeling & Market Making", '"foreign exchange" OR "market making" OR "fx options" OR "currency pairs"'],
    mth9878: ["MTH 9873 / 9878 Interest Rate Models", '"interest rate model" OR "hull-white" OR "term structure" OR swaption'],
    mth9875: ["MTH 9875 The Volatility Surface", '"volatility surface" OR "implied volatility" OR "local volatility" OR heston OR SABR'],
    mth9876: ["MTH 9876 Credit Risk Models", '"credit default swap" OR "default probability" OR "merton model" OR "credit risk"'],
    mth9879: ["MTH 9879 Market Microstructure Models", '"market microstructure" OR "limit order book" OR "order flow" OR "high frequency"'],
    mth9882: ["MTH 9882 Fixed Income Risk Management", '"fixed income" OR duration OR convexity OR "bond portfolio"'],
    mth9887: ["MTH 9887 Blockchain Technologies in Finance", 'blockchain OR "smart contract" OR DeFi OR "on-chain"'],
    mth9893: ["MTH 9893 / 9867 Time Series & Algorithmic Trading", '"time series" OR ARIMA OR cointegration OR "pairs trading"'],
    mth9894: ["MTH 9894 / 9897 Algorithmic & Systematic Trading", '"systematic trading" OR "trading strategy" OR backtesting OR "momentum strategy"'],
    mth9896: ["MTH 9896 Behavioral Finance", '"behavioral finance" OR "investor sentiment" OR "sentiment analysis" stocks'],
    mth9899: ["MTH 9898 / 9899 Data Science & Machine Learning in Finance", '"machine learning" finance OR "stock prediction" OR "factor model" OR "financial data"'],
  },
  fintech: {
    fin3000: ["FIN 3000 Principles of Finance", '"time value of money" OR "capital budgeting" OR NPV OR IRR OR "financial calculator"'],
    fin3610: ["FIN 3610 Corporate Finance", '"corporate finance" OR WACC OR "capital structure" OR "dividend policy" OR DCF'],
    fin3710: ["FIN 3710 Investment Analysis", '"investment analysis" OR "portfolio theory" OR CAPM OR "security analysis" OR "efficient frontier"'],
    modeling: ["Financial modeling & valuation", '"financial modeling" OR "three statement" OR "DCF model" OR LBO OR "valuation model"'],
    statements: ["Financial statement analysis", '"financial statements" OR "ratio analysis" OR "10-K" OR "SEC EDGAR" OR XBRL'],
    options: ["Derivatives & options", '"black-scholes" OR "option pricing" OR "options strategy" OR greeks'],
    bonds: ["Fixed income", '"fixed income" OR "bond valuation" OR "yield curve" OR duration'],
    fx: ["International finance & FX", '"foreign exchange" OR "exchange rate" OR forex OR "currency hedging"'],
    markets: ["Financial markets & trading", '"stock market" OR "market data" OR "trading platform" OR brokerage'],
    personal: ["Personal finance & fintech apps", '"personal finance" OR budgeting OR "open banking" OR "robo-advisor" OR payments'],
    risk: ["Risk management & credit", '"risk management" OR "credit scoring" OR "fraud detection" OR "credit risk"'],
    realestate: ["Real estate finance", '"real estate" OR mortgage OR amortization OR REIT'],
  },
  pm: {
    scrum: ["Scrum", 'scrum OR sprint OR "scrum master" OR "sprint planning" OR retrospective'],
    jira: ["Jira", 'jira OR "jira api" OR "jira automation" OR "jira dashboard"'],
    confluence: ["Confluence", 'confluence OR "confluence api" OR atlassian OR "team wiki"'],
    kanban: ["Kanban", 'kanban OR "kanban board" OR "task board" OR "work in progress"'],
    metrics: ["Agile metrics & reporting", 'velocity OR burndown OR "agile metrics" OR "cycle time" OR "sprint report"'],
    roadmap: ["Roadmaps & OKRs", 'roadmap OR OKR OR "product roadmap" OR "release planning"'],
    stories: ["Requirements & user stories", '"user stories" OR "acceptance criteria" OR backlog OR "requirements management"'],
    risk: ["Risk, stakeholders & schedules", '"risk register" OR stakeholder OR "project charter" OR gantt'],
  },
};
export function coursesHelp(major) {
  const m = COURSES[major] ? major : null;
  if (!m) return "<b>🎓 Course-aligned searches</b>\n/courses quant · /courses fintech · /courses pm";
  const cmd = { quant: "/quant", fintech: "/fintech", pm: "/pm" }[m];
  return `<b>🎓 ${MAJORS[m].label} — course codes you can search</b>\n` +
    Object.entries(COURSES[m]).map(([k, [name]]) => `${cmd} ${k} — ${name}`).join("\n") +
    `\nAdd keywords after the code: <code>${cmd} ${Object.keys(COURSES[m])[0]} python</code>`;
}
// Cybersecurity by the 8 CISSP domains: "/cyber d7", "/cyber d7 sigma". Mirrors CYBER_DOMAINS in ../project_scout.py.
export const CYBER_DOMAINS = {
  d1: ["D1 Security & Risk Management (GRC)", 'grc OR "risk management" OR compliance OR "security policy" OR "nist csf"'],
  d2: ["D2 Asset Security", '"data loss prevention" OR "secrets detection" OR "data classification" OR "asset inventory" OR "pii detection"'],
  d3: ["D3 Security Architecture & Engineering", '"threat modeling" OR cryptography OR "zero trust" OR "secure design" OR "secrets management"'],
  d4: ["D4 Communication & Network Security", '"network security" OR firewall OR "intrusion detection" OR "packet capture" OR "network monitoring"'],
  d5: ["D5 Identity & Access Management", 'IAM OR authentication OR "single sign-on" OR OAuth OR passkeys OR "access control"'],
  d6: ["D6 Security Assessment & Testing", '"penetration testing" OR "vulnerability scanner" OR CTF OR fuzzing OR "security testing"'],
  d7: ["D7 Security Operations", 'SIEM OR "incident response" OR "threat hunting" OR "detection rules" OR "digital forensics" OR SOC'],
  d8: ["D8 Software Development Security", '"secure coding" OR SAST OR DevSecOps OR "dependency scanning" OR "supply chain security" OR sbom'],
};
export const DOMAINS_HELP = "<b>🔐 Cybersecurity — the 8 CISSP domains</b>\n" +
  Object.entries(CYBER_DOMAINS).map(([k, [l]]) => `/cyber ${k} — ${l}`).join("\n") +
  "\nAdd keywords: <code>/cyber d7 sigma</code>. Curated projects per domain are posted in the cyber channel.";
// "Start here": curated evergreen repos with project IDEAS and the basics (mirrors STARTERS in ../project_scout.py).
export const STARTERS = {
  quant: ["wilsonfreitas/awesome-quant", "stefan-jansen/machine-learning-for-trading", "je-suis-tm/quant-trading", "microsoft/qlib", "QuantConnect/Lean", "ranaroussi/yfinance"],
  fintech: ["OpenBB-finance/OpenBB", "plaid/pattern", "stripe-samples/checkout-one-time-payments", "firefly-iii/firefly-iii", "actualbudget/actual", "ranaroussi/yfinance"],
  swe: ["practical-tutorials/project-based-learning", "codecrafters-io/build-your-own-x", "florinpop17/app-ideas", "karan/Projects", "nilbuild/developer-roadmap", "ossu/computer-science"],
  cyber: ["sbilly/awesome-security", "OWASP/CheatSheetSeries", "juice-shop/juice-shop", "OWASP/wstg", "swisskyrepo/PayloadsAllTheThings", "mitre-attack/attack-navigator"],
  data: ["microsoft/Data-Science-For-Beginners", "jakevdp/PythonDataScienceHandbook", "Yorko/mlcourse.ai", "awesomedata/awesome-public-datasets", "streamlit/streamlit", "academic/awesome-datascience", "microsoft/PowerBI-Developer-Samples", "microsoft/powerbi-desktop-samples", "tableau/TabPy", "tableau/server-client-python", "tableau/hyper-api-samples"],
  pm: ["dend/awesome-product-management", "opf/openproject", "makeplane/plane", "wekan/wekan", "mattermost-community/focalboard"],
  marketing: ["PostHog/posthog", "umami-software/umami", "matomo-org/matomo", "mautic/mautic", "knadh/listmonk", "n8n-io/n8n"],
};
// NYC in-person hackathons: Devpost listing JSON + MLH season page (embedded JSON). Mirrors hackathons_nyc() in ../project_scout.py.
// Commutable NYC area only: "<city>, New York" upstate (Ithaca, Troy, Rochester) is deliberately not matched.
const NYC_RE = /\b(new york, ?ny|new york, new york|nyc|brooklyn|manhattan|queens|bronx|staten island|flushing|jamaica, ny|jersey city|hoboken|newark, ?nj|long island city|columbia university|nyu|cornell tech|cuny|baruch|fordham|pace university|stevens|stony brook|hofstra)\b/i;
export const HACK_LINKS = [
  ["MLH season calendar", "https://mlh.io/seasons/2027/events"],
  ["Devpost in-person", "https://devpost.com/hackathons?challenge_type[]=in-person&order_by=deadline&search=new+york"],
  ["Eventbrite NYC", "https://www.eventbrite.com/d/ny--new-york/hackathon/"],
  ["Meetup NYC", "https://www.meetup.com/find/?keywords=hackathon&location=us--ny--New%20York&source=EVENTS"],
  ["Luma NYC", "https://lu.ma/nyc?q=hackathon"],
];
async function cachedText(url, accept) {
  const cache = caches.default, key = new Request(url, { method: "GET" });
  let r = await cache.match(key);
  if (!r) {
    r = await fetch(url, { headers: { "user-agent": "Mozilla/5.0 project-scout", accept } });
    if (!r.ok) throw new Error(`${new URL(url).host} HTTP ${r.status}`);
    r = new Response(await r.text(), { headers: { "cache-control": "s-maxage=1800" } });
    await cache.put(key, r.clone());
  }
  return r.text();
}
export async function hackathonsNyc() {
  const idx = await loadIndex().catch(() => null);
  if (idx?.hackathons?.items?.length && Date.now() - Date.parse(idx.hackathons.at) < 12 * 3600e3) return idx.hackathons.items;
  const out = [];
  try {
    for (let page = 1; page <= 4; page++) {
      const d = JSON.parse(await cachedText(`https://devpost.com/api/hackathons?status[]=open&status[]=upcoming&challenge_type[]=in-person&order_by=deadline&per_page=50&page=${page}`, "application/json"));
      if (!d.hackathons?.length) break;
      for (const h of d.hackathons) {
        const loc = h.displayed_location?.location || "";
        if (NYC_RE.test(loc) || NYC_RE.test(h.title))
          out.push({ title: h.title, url: h.url, when: h.submission_period_dates || "", where: loc, org: h.organization_name || "", src: "Devpost", prize: h.prize_amount || "" });
      }
    }
  } catch (e) { console.log("devpost", e.message); }
  try {
    const html = await cachedText("https://mlh.io/seasons/2027/events", "text/html");
    for (const m of html.matchAll(/\{"id":"[0-9a-f-]{36}","slug":.*?"venueAddress":\{[^}]*\}\}/g)) {
      let ev; try { ev = JSON.parse(m[0]); } catch { continue; }
      const va = ev.venueAddress || {}, where = ev.location || `${va.city || ""}, ${va.state || ""}`;
      if (["physical", "hybrid"].includes(ev.formatType) && NYC_RE.test(where))
        out.push({ title: ev.name, url: ev.websiteUrl || "https://mlh.io" + (ev.url || ""), when: ev.dateRange || "", where, org: "MLH", src: "MLH", prize: "" });
    }
  } catch (e) { console.log("mlh", e.message); }
  const seen = new Set();
  return out.filter((h) => !seen.has(h.url) && seen.add(h.url));
}
export function renderHacks(head, items, md = false) {
  const e = md ? (s) => String(s) : esc;
  const link = (t, u) => (md ? `[${t}](<${u}>)` : `<a href="${u}">${esc(t)}</a>`);
  const more = HACK_LINKS.map(([n, u]) => link(n, u)).join(" · ");
  if (!items.length) return `${head}\nNothing listed right now. Check: ${more}`;
  const rows = items.slice(0, 10).map((h) =>
    `• ${link(h.title, h.url)}${h.prize ? ` · 🏆 ${e(h.prize)}` : ""}\n  📅 ${e(h.when)} · 📍 ${e(h.where)}${h.org && h.org !== h.src ? ` · ${e(h.org)}` : ""} · via ${h.src}`);
  return `${head}\n${rows.join("\n")}\n\n🔎 More: ${more}`;
}

export async function startItems(env, major) {
  const idx = await loadIndex().catch(() => null);
  const st = idx?.static?.starters;
  if (st && (major ? st[major]?.length : Object.keys(st).length)) {
    return ordered(major ? st[major] : dedupe(Object.values(st).flat()).slice(0, 14));
  }
  const majors = major ? [major] : Object.keys(STARTERS);
  const names = [...new Set(majors.flatMap((m) => STARTERS[m]))].slice(0, major ? 11 : 14);
  const items = await Promise.all(names.map((n) => ghJson(env, `https://api.github.com/repos/${n}`).catch(() => null)));
  return ordered(items.filter(Boolean));
}
// Mission-driven orgs whose repos welcome outside contributors (mirrors ORGS in ../project_scout.py).
// <= 12 orgs per sector: GitHub search queries max out at 256 chars.
export const ORGS = {
  nonprofit: { label: "🌱 Non-profit", orgs: { mozilla: "Mozilla", OWASP: "OWASP", wikimedia: "Wikimedia", EFForg: "EFF",
    datakind: "DataKind", ushahidi: "Ushahidi", hackforla: "Hack for LA", codeforamerica: "Code for America", torproject: "Tor Project", freeCodeCamp: "freeCodeCamp", BetaNYC: "BetaNYC (NYC civic tech)" } },
  public: { label: "🏛 Public sector", orgs: { cisagov: "CISA", GSA: "US GSA", "18F": "18F", usds: "US Digital Service",
    nasa: "NASA", usnistgov: "NIST", CDCgov: "CDC",
    CityOfNewYork: "City of New York", NYCPlanning: "NYC Dept of City Planning", alphagov: "UK GDS" } },
  private: { label: "🏢 Private sector", orgs: { microsoft: "Microsoft", google: "Google", aws: "AWS", IBM: "IBM",
    cloudflare: "Cloudflare", elastic: "Elastic", goldmansachs: "Goldman Sachs",
    "man-group": "Man Group", jpmorganchase: "JPMorgan Chase", bloomberg: "Bloomberg" } },
};
const ORG_SECTOR = {};
for (const [sector, { label, orgs }] of Object.entries(ORGS)) for (const [o, n] of Object.entries(orgs)) ORG_SECTOR[o.toLowerCase()] = { label, name: n };
const linkedin = (name) => "https://www.linkedin.com/search/results/companies/?keywords=" + encodeURIComponent(name);

// One query per sector (3 calls, each cached 15 min), merged and sorted by recent activity.
export async function orgSearch(env, text) {
  const idx = await loadIndex().catch(() => null);
  if (idx?.keys && !text) {  // plain /orgs comes straight from the snapshot
    const rows = dedupe(Object.keys(idx.keys).filter((k) => k.startsWith("orgs|")).flatMap((k) => idx.keys[k]));
    if (rows.length) return rows.sort((a, b) => (a.pushed_at < b.pushed_at ? 1 : -1)).slice(0, MAX);
  }
  const results = [];
  for (const { orgs } of Object.values(ORGS))  // sequential, see lookup()
    results.push(await search(env, `${text} ${Object.keys(orgs).map((o) => "org:" + o).join(" ")} good-first-issues:>0 archived:false pushed:>=${ago(90)}`.trim(), "updated"));
  return results.flat().filter(english).sort((a, b) => (a.pushed_at < b.pushed_at ? 1 : -1)).slice(0, MAX);
}

export function renderOrgs(head, items, md = false) {
  if (!items.length) return `${head}\nNothing matched. Try fewer keywords.`;
  const e = md ? (s) => String(s) : esc;
  const link = (t, u) => (md ? `[${t}](<${u}>)` : `<a href="${u}">${esc(t)}</a>`);
  const rows = items.map((it) => {
    const [org, repo] = it.full_name.split("/");
    const s = ORG_SECTOR[org.toLowerCase()] || { label: "🏢", name: org };
    return render("", "oss", [it], md).trimStart() +
      `\n  🏷 ${s.label} · ${e(s.name)} · ${link("LinkedIn", linkedin(s.name))}` +
      `\n  📝 Resume: Open-Source Contributor, ${e(s.name)} (${e(repo)})`;
  });
  return `${head}\n${rows.join("\n")}`;
}
const MAX = 6;
const GFI = "/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const HELP =
  "<b>Project Scout</b> — GitHub project ideas by major.\n\n" +
  "/quant · /fintech · /swe · /cyber · /data · /pm · /marketing — fresh repos to build\n" +
  "  /swe = Python + SQL + frontend mixed · /swe sql · /swe frontend · /swe java (any language)\n" +
  "  /data powerbi · /data tableau · /cyber d1…d8 (CISSP domains, /domains lists them)\n" +
  "  /quant mth9821 · /fintech fin3710 · /pm jira — Baruch course-aligned searches (/courses quant lists codes)\n" +
  "/oss &lt;major&gt; — open-source repos with open <i>good first issue</i> tickets\n" +
  "/research &lt;major&gt; — fresh paper code (cites arXiv) to reproduce or join\n" +
  "/orgs [major] — non-profit, public-sector and company repos that welcome contributors (resume-ready, with LinkedIn links)\n" +
  "/basics &lt;major&gt; — start here: curated idea lists, roadmaps, beginner courses and sample apps\n" +
  "/hackathons — NYC in-person hackathons, live from Devpost + MLH\n\n" +
  "Add keywords to narrow: <code>/cyber honeypot</code>, <code>/oss data pandas</code>, <code>/research quant</code>.\n" +
  "Any other text = keyword search across all majors.\n\n" +
  "<i>New repos are pushed here automatically as they appear (checked every 2 h).</i>";

async function tgSend(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true }),
  });
}

// GitHub GET with a 15-min edge cache so a room full of students tapping /cyber costs one call, not one per tap.
// Circuit breaker: after one 403/429 from GitHub, every search short-circuits for 2 minutes instead of retrying
// (a room full of students retrying is exactly how an IP gets blocked). Cached results keep serving meanwhile.
const BACKOFF_KEY = new Request("https://project-scout.local/github-backoff", { method: "GET" });
async function ghJson(env, url) {
  const headers = { accept: "application/vnd.github+json", "user-agent": "project-scout-bot (github.com/thecyberthriver/project-scout)" };
  if (env.GITHUB_TOKEN) headers.authorization = `Bearer ${env.GITHUB_TOKEN}`;
  const cache = caches.default;
  const key = new Request(url, { method: "GET" });
  let r = await cache.match(key);
  if (!r) {
    if (await cache.match(BACKOFF_KEY)) throw new Error("GitHub is rate-limiting searches right now — try again in 2 minutes");
    r = await fetch(url, { headers });
    if (r.status === 403 || r.status === 429) {
      const retry = Number(r.headers.get("retry-after")) || 120;
      await cache.put(BACKOFF_KEY, new Response("1", { headers: { "cache-control": `s-maxage=${Math.min(retry, 300)}` } }));
      throw new Error("GitHub is rate-limiting searches right now — try again in 2 minutes");
    }
    if (!r.ok) throw new Error(`GitHub HTTP ${r.status}`);
    r = new Response(await r.text(), { headers: { "content-type": "application/json", "cache-control": "s-maxage=900" } });
    await cache.put(key, r.clone());
  }
  return r.json();
}

export async function search(env, q, sort) {
  const url = "https://api.github.com/search/repositories?" +
    new URLSearchParams({ q, sort, order: "desc", per_page: String(MAX) });
  return (await ghJson(env, url)).items || [];
}

// Second source for keyword searches: GitLab's public projects API (no auth). Rows are tagged "(GitLab)".
async function gitlab(kw) {
  const url = "https://gitlab.com/api/v4/projects?" + new URLSearchParams({
    search: kw, order_by: "last_activity_at", sort: "desc", per_page: "3", simple: "true", archived: "false" });
  try {
    const r = await fetch(url, { headers: { "user-agent": "project-scout-bot" } });
    if (!r.ok) return [];
    return (await r.json()).filter((p) => p.description && (p.star_count || 0) >= 5).map((p) => ({
      full_name: `${p.path_with_namespace} (GitLab)`, html_url: p.web_url, stargazers_count: p.star_count || 0,
      description: p.description, language: null }));
  } catch { return []; }
}

// ---- index.json first: the feed's snapshot, served from GitHub's CDN (no API calls, no rate limits) --------------
const INDEX_URL = "https://raw.githubusercontent.com/thecyberthriver/project-scout/main/index.json";
export async function loadIndex() {
  const cache = caches.default, key = new Request(INDEX_URL, { method: "GET" });
  let r = await cache.match(key);
  if (!r) {
    r = await fetch(INDEX_URL, { headers: { "user-agent": "project-scout-bot" } });
    if (!r.ok) return null;
    r = new Response(await r.text(), { headers: { "content-type": "application/json", "cache-control": "s-maxage=1800" } });
    await cache.put(key, r.clone());
  }
  return r.json();
}
// What a first keyword selects inside the index (by the sub-label the feed stored the rows under).
const SWE_LABEL = { python: "Python backend", backend: "Python backend", sql: "SQL", frontend: "Frontend", go: "Other languages" };
const DATA_LABEL = { powerbi: "Power BI", power: "Power BI", tableau: "Tableau" };
const dedupe = (rows) => { const s = new Set(); return rows.filter((r) => !s.has(r.full_name) && s.add(r.full_name)); };
export function fromIndex(idx, lane, major, extra) {
  if (!idx?.keys) return null;
  const tokens = (extra || "").toLowerCase().split(/\s+/).filter((t) => t && !/^(advanced|any|all)$/.test(t));
  let keys = Object.keys(idx.keys).filter((k) => (!major || k.startsWith(`${major}|`)) && k.includes(`|${lane}|`));
  const first = tokens[0];
  const label = first && ((major === "swe" && SWE_LABEL[first]) || (major === "data" && DATA_LABEL[first]) ||
    (major === "cyber" && CYBER_DOMAINS[first]?.[0]) || COURSES[major]?.[first]?.[0]);
  if (label) {
    const kk = keys.filter((k) => k.toLowerCase().includes(label.toLowerCase()));
    if (!kk.length) return null;          // that course/domain hasn't been indexed yet → live search
    keys = kk; tokens.shift();
  }
  let rows = dedupe(keys.flatMap((k) => idx.keys[k]));
  if (tokens.length) rows = rows.filter((r) => tokens.every((t) => `${r.full_name} ${r.description || ""}`.toLowerCase().includes(t)));
  return rows.length >= (tokens.length ? 3 : 1) ? rows : null;
}

// Items for a non-orgs lane: index first; GitHub (cached, sequential) only when the index has nothing for the request.
export async function lookup(env, lane, major, extra) {
  const idx = await loadIndex().catch(() => null);
  const hit = fromIndex(idx, lane, major, extra);
  if (hit) return ordered(hit, ceilingFor(extra)).slice(0, MAX + 3);
  if (lane === "build") {  // major-specific build searches: SWE languages, Data tools, cyber domains
    const first = (extra || "").split(/\s+/)[0].toLowerCase(), rest = (extra || "").split(/\s+/).slice(1).join(" ");
    let queries = null;
    if (major === "swe") {
      const flavors = SWE_FLAVORS[first] ? [[SWE_FLAVORS[first], rest]] : extra ? null : SWE_DEFAULT.map((f) => [SWE_FLAVORS[f], ""]);
      if (flavors) queries = flavors;
    } else if (major === "data" && DATA_FLAVORS[first]) {
      queries = [[DATA_FLAVORS[first], rest]];
    } else if (major === "cyber" && CYBER_DOMAINS[first]) {
      queries = [[CYBER_DOMAINS[first][1], rest]];
    } else if (COURSES[major] && COURSES[major][first.replace(/\s+/g, "")]) {
      queries = [[COURSES[major][first.replace(/\s+/g, "")][1], rest]];
    }
    if (queries) {
      const lists = [];  // sequential on purpose: GitHub's secondary limit dislikes concurrent requests from one source
      for (const [q, kw] of queries)
        lists.push(await search(env, LANES.build.q(kw ? `${kw} in:name,description,readme ${q.match(/language:\S+/)?.[0] || ""}` : q), "stars"));
      const out = [];  // interleave so /swe shows Python, SQL, frontend, Python, SQL, …
      for (let i = 0; out.length < MAX + 3 && lists.some((l) => l[i]); i++) for (const l of lists) if (l[i]) out.push(l[i]);
      return ordered(out.filter(english), ceilingFor(extra)).slice(0, MAX + 3);
    }
  }
  const a = await search(env, LANES[lane].q(terms(lane, major, extra)), LANES[lane].sort);
  const b = lane === "build" && extra ? await gitlab(extra) : [];
  const spamFree = AI_OK.has(major) || extra ? a : a.filter((it) => !AI_SPAM.test(`${it.full_name} ${it.description || ""}`));
  return ordered(spamFree.concat(b).filter(english), ceilingFor(extra)).slice(0, MAX + 3);
}
const ceilingFor = (extra) => (/\b(advanced|any|all)\b/i.test(extra || "") ? null : phase()[0]);
// English-only: drop repos whose name+description is mostly non-ASCII (CJK, Cyrillic, ...) or has no description.
export function english(it) {
  const s = `${it.full_name} ${it.description || ""}`;
  if (!(it.description || "").trim()) return false;
  let ascii = 0;
  for (const ch of s) if (ch.charCodeAt(0) < 128) ascii++;
  return ascii / s.length >= 0.9;
}
// Most new GitHub repos right now are LLM wrappers; keep them out of the non-software majors (typed keywords override).
const AI_SPAM = /\b(agents?|llms?|gpt|chatgpt|copilot|claude|openai|langchain|rag)\b/i;
const AI_OK = new Set(["swe", "data"]);
// Difficulty ceiling rises through the school year (mirrors phase() in ../project_scout.py): 0 starter, 1 intermediate, 2 advanced.
const RANK = { "🟢 starter": 0, "🟡 intermediate": 1, "🔴 advanced": 2 };
export function phase(d = new Date()) {
  const m = d.getMonth() + 1;
  return [9, 10].includes(m) ? [0, "Phase 1 · Sep–Oct · starter"] : [11, 12, 1].includes(m) ? [1, "Phase 2 · Nov–Jan · up to intermediate"] : [2, "Phase 3 · Feb–May · all levels"];
}
// Easiest first, then stars; with a ceiling, harder repos sink to the bottom. "advanced"/"any" in keywords lifts the ceiling.
export function ordered(items, ceiling = null) {
  const ranked = [...items].sort((a, b) => RANK[difficulty(a)] - RANK[difficulty(b)] || (b.stargazers_count || 0) - (a.stargazers_count || 0));
  if (ceiling === null) return ranked;
  return ranked.filter((it) => RANK[difficulty(it)] <= ceiling).concat(ranked.filter((it) => RANK[difficulty(it)] > ceiling));
}
// Rough on-ramp hint from repo size (KB) and stars — so freshmen don't pick a 20k-star monorepo.
export function difficulty(it) {
  const size = it.size || 0, stars = it.stargazers_count || 0;
  if (size < 5000 && stars < 500) return "🟢 starter";
  if (size < 50000 && stars < 5000) return "🟡 intermediate";
  return "🔴 advanced";
}

// md=true renders Discord markdown (<url> suppresses link embeds) instead of Telegram HTML.
export function render(head, lane, items, md = false) {
  if (!items.length) return `${head}\nNothing matched. Try fewer keywords.`;
  head += md ? `\n*${phase()[1]} · easiest first*` : `\n<i>📶 ${phase()[1]} · easiest first</i>`;
  const e = md ? (s) => String(s) : esc;
  const link = (t, u) => (md ? `[${t}](<${u}>)` : `<a href="${u}">${esc(t)}</a>`);
  const rows = items.map((it) => {
    let d = (it.description || "").trim();
    if (d.length > 140) d = d.slice(0, 140) + "…";
    const lang = it.language ? ` · ${e(it.language)}` : "";
    const tail = lane === "oss" ? `\n  👉 ${link("open good-first-issues", it.html_url + GFI)}` : "";
    return `• ${link(it.full_name, it.html_url)} ⭐${it.stargazers_count}${lang} · ${difficulty(it)}\n  ${e(d) || "(no description)"}${tail}`;
  });
  return `${head}\n${rows.join("\n")}`;
}

// "/oss cyber honeypot" -> {lane:"oss", major:"cyber", extra:"honeypot"}; "nba stats" -> {lane:"build", major:null, extra:"nba stats"}
export function parse(text) {
  // in groups Telegram sends "/oss@BotName cyber" — drop the @mention
  const words = text.trim().replace(/^\/(\w+)@\w+/, "$1").replace(/^\//, "").split(/\s+/);
  let lane = words[0].toLowerCase();
  lane = LANES[lane] || ["orgs", "start", "hackathons"].includes(lane) ? lane : LANE_ALIAS[lane];
  if (lane) words.shift(); else lane = "build";
  let major = (words[0] || "").toLowerCase();
  major = MAJORS[major] ? major : ALIAS[major] || null;
  const extra = (major ? words.slice(1) : words).join(" ").trim();
  return { lane, major, extra };
}

// Text terms for the query: OR list only for a plain major build search; anchor + keywords otherwise.
export function terms(lane, major, extra) {
  if (lane === "build" && major && !extra) return MAJORS[major].terms;
  const kw = extra ? `${extra} in:name,description,readme` : "";
  const anchor = major ? (lane === "research" ? `${RESEARCH_ANCHOR[major]} ${MAJORS[major].anchor}` : MAJORS[major].anchor) : "";
  return `${anchor} ${kw}`.trim();
}

async function handleUpdate(env, update) {
  const msg = update.message || update.edited_message;
  if (!msg || !msg.chat) return;
  const chatId = String(msg.chat.id);
  if (env.OWNER_CHAT_ID && chatId !== String(env.OWNER_CHAT_ID)) return;

  const t = (msg.text || "").trim();
  if (!t || /^\/?(start|help)$/i.test(t)) return tgSend(env, chatId, HELP);
  if (/^\/?domains$/i.test(t)) return tgSend(env, chatId, DOMAINS_HELP);
  const cm = t.match(/^\/?courses(?:\s+(\w+))?$/i);
  if (cm) return tgSend(env, chatId, coursesHelp(ALIAS[(cm[1] || "").toLowerCase()] || (cm[1] || "").toLowerCase()));

  const { lane, major, extra } = parse(t);
  if (lane === "build" && !major && !extra) return tgSend(env, chatId, HELP);
  if (lane === "hackathons") {
    try { await tgSend(env, chatId, renderHacks("<b>🏁 NYC in-person hackathons (Devpost + MLH, live)</b>", await hackathonsNyc())); }
    catch (e) { await tgSend(env, chatId, `⚠️ ${esc(e.message)}`); }
    return;
  }
  const laneLabel = { orgs: "🤝 Mission-driven orgs", start: "📚 Start here — ideas & basics" }[lane] || LANES[lane].label;
  const head = `<b>${laneLabel} · ${major ? MAJORS[major].label : "🔎 All majors"}</b>${extra ? ` · <i>${esc(extra)}</i>` : ""}`;
  try {
    if (lane === "orgs") {
      await tgSend(env, chatId, renderOrgs(head, await orgSearch(env, terms(lane, major, extra))));
      return;
    }
    if (lane === "start") {
      await tgSend(env, chatId, render(head, "build", await startItems(env, major)) +
        "\n\n💡 Pick one, read its README, then run a major command for something fresh to build on top of it.");
      return;
    }
    await tgSend(env, chatId, render(head, lane, await lookup(env, lane, major, extra)));
  } catch (e) {
    await tgSend(env, chatId, `⚠️ ${esc(e.message)} — GitHub search is rate-limited to 10/min; try again shortly.`);
  }
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") return new Response("Project Scout webhook is up.", { status: 200 });
    if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
    if (env.WEBHOOK_SECRET && request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 401 });
    }
    let update;
    try { update = await request.json(); } catch { return new Response("bad request", { status: 400 }); }
    ctx.waitUntil(handleUpdate(env, update).catch((e) => console.log("handle error", e)));
    return new Response("ok", { status: 200 });
  },
};
