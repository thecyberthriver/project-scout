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
// "Start here": curated evergreen repos with project IDEAS and the basics (mirrors STARTERS in ../project_scout.py).
export const STARTERS = {
  quant: ["wilsonfreitas/awesome-quant", "stefan-jansen/machine-learning-for-trading", "je-suis-tm/quant-trading", "microsoft/qlib", "QuantConnect/Lean", "ranaroussi/yfinance"],
  fintech: ["OpenBB-finance/OpenBB", "plaid/pattern", "stripe-samples/checkout-one-time-payments", "firefly-iii/firefly-iii", "actualbudget/actual", "ranaroussi/yfinance"],
  swe: ["practical-tutorials/project-based-learning", "codecrafters-io/build-your-own-x", "florinpop17/app-ideas", "karan/Projects", "nilbuild/developer-roadmap", "ossu/computer-science"],
  cyber: ["sbilly/awesome-security", "OWASP/CheatSheetSeries", "juice-shop/juice-shop", "OWASP/wstg", "swisskyrepo/PayloadsAllTheThings", "mitre-attack/attack-navigator"],
  data: ["microsoft/Data-Science-For-Beginners", "jakevdp/PythonDataScienceHandbook", "Yorko/mlcourse.ai", "awesomedata/awesome-public-datasets", "streamlit/streamlit", "academic/awesome-datascience"],
  pm: ["dend/awesome-product-management", "opf/openproject", "makeplane/plane", "wekan/wekan", "mattermost-community/focalboard"],
  marketing: ["PostHog/posthog", "umami-software/umami", "matomo-org/matomo", "mautic/mautic", "knadh/listmonk", "n8n-io/n8n"],
};
// NYC in-person hackathons: Devpost listing JSON + MLH season page (embedded JSON). Mirrors hackathons_nyc() in ../project_scout.py.
// Commutable NYC area only: "<city>, New York" upstate (Ithaca, Troy, Rochester) is deliberately not matched.
const NYC_RE = /\b(new york, ?ny|new york, new york|nyc|brooklyn|manhattan|queens|bronx|staten island|flushing|jamaica, ny|jersey city|hoboken|newark|long island city|columbia university|nyu|cornell tech|cuny|baruch|fordham|pace university|stevens|stony brook|hofstra)\b/i;
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
  const majors = major ? [major] : Object.keys(STARTERS);
  const names = [...new Set(majors.flatMap((m) => STARTERS[m]))].slice(0, major ? 6 : 14);
  const items = await Promise.all(names.map((n) => ghJson(env, `https://api.github.com/repos/${n}`).catch(() => null)));
  return items.filter(Boolean);
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
  const qs = Object.values(ORGS).map(({ orgs }) =>
    `${text} ${Object.keys(orgs).map((o) => "org:" + o).join(" ")} good-first-issues:>0 archived:false pushed:>=${ago(90)}`.trim());
  const results = await Promise.all(qs.map((q) => search(env, q, "updated")));
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
  "/quant · /fintech · /swe · /cyber · /data — fresh repos to build\n" +
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
async function ghJson(env, url) {
  const headers = { accept: "application/vnd.github+json", "user-agent": "project-scout-bot" };
  if (env.GITHUB_TOKEN) headers.authorization = `Bearer ${env.GITHUB_TOKEN}`;
  const cache = caches.default;
  const key = new Request(url, { method: "GET" });
  let r = await cache.match(key);
  if (!r) {
    r = await fetch(url, { headers });
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

// Items for a non-orgs lane: GitHub (cached), plus GitLab when the student typed keywords.
export async function lookup(env, lane, major, extra) {
  const gh = search(env, LANES[lane].q(terms(lane, major, extra)), LANES[lane].sort);
  const gl = lane === "build" && extra ? gitlab(extra) : Promise.resolve([]);
  const [a, b] = await Promise.all([gh, gl]);
  const spamFree = AI_OK.has(major) || extra ? a : a.filter((it) => !AI_SPAM.test(`${it.full_name} ${it.description || ""}`));
  return spamFree.concat(b).filter(english).slice(0, MAX + 3);
}
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
