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
                     org: "orgs", nonprofit: "orgs", volunteer: "orgs", mission: "orgs" };
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
  "/orgs [major] — non-profit, public-sector and company repos that welcome contributors (resume-ready, with LinkedIn links)\n\n" +
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

export async function search(env, q, sort) {
  const url = "https://api.github.com/search/repositories?" +
    new URLSearchParams({ q, sort, order: "desc", per_page: String(MAX) });
  const headers = { accept: "application/vnd.github+json", "user-agent": "project-scout-bot" };
  if (env.GITHUB_TOKEN) headers.authorization = `Bearer ${env.GITHUB_TOKEN}`;
  // Cache each query 15 min so a room full of students tapping /cyber costs one GitHub call, not one per tap.
  const cache = caches.default;
  const key = new Request(url, { method: "GET" });
  let r = await cache.match(key);
  if (!r) {
    r = await fetch(url, { headers });
    if (!r.ok) throw new Error(`GitHub HTTP ${r.status}`);
    r = new Response(await r.text(), { headers: { "content-type": "application/json", "cache-control": "s-maxage=900" } });
    await cache.put(key, r.clone());
  }
  return (await r.json()).items || [];
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
  lane = LANES[lane] || lane === "orgs" ? lane : LANE_ALIAS[lane];
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
  const laneLabel = lane === "orgs" ? "🤝 Mission-driven orgs" : LANES[lane].label;
  const head = `<b>${laneLabel} · ${major ? MAJORS[major].label : "🔎 All majors"}</b>${extra ? ` · <i>${esc(extra)}</i>` : ""}`;
  try {
    if (lane === "orgs") {
      await tgSend(env, chatId, renderOrgs(head, await orgSearch(env, terms(lane, major, extra))));
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
