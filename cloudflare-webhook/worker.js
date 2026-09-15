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
  fintech: { label: "💳 Finance / FinTech",    anchor: "finance",  terms: 'fintech OR payments OR "personal finance" OR "open banking" OR budgeting OR "stock market"' },
  swe:     { label: "💻 Software Engineering", anchor: "software", terms: '"build your own" OR "from scratch" OR "project ideas" OR "portfolio project" OR "full stack"' },
  cyber:   { label: "🔐 Cybersecurity",        anchor: "security", terms: 'cybersecurity OR "penetration testing" OR "threat detection" OR "malware analysis" OR "security tool" OR CTF' },
  data:    { label: "📊 Data Analytics",       anchor: "data",     terms: '"data analytics" OR "data analysis" OR "exploratory data analysis" OR "data pipeline" OR "data visualization"' },
};
const ALIAS = { finance: "fintech", software: "swe", security: "cyber", analytics: "data" };
const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
// GitHub search has no parentheses, so only the build lane uses the OR list; others use the anchor word.
export const LANES = {
  build:    { label: "🧪 Build this", sort: "stars",   q: (t) => `${t} created:>=${ago(90)} stars:>=10 archived:false` },
  oss:      { label: "🤝 Contribute", sort: "updated", q: (t) => `${t} good-first-issues:>0 stars:>=50 pushed:>=${ago(30)} archived:false` },
  research: { label: "🔬 Research",  sort: "stars",   q: (t) => `${t} arxiv in:readme,description created:>=${ago(90)} stars:>=5 archived:false` },
};
// a bare word + arxiv returns generic AI repos; a field phrase keeps research on-major
const RESEARCH_ANCHOR = { quant: '"quantitative finance"', fintech: '"financial"', swe: '"software engineering"', cyber: "cybersecurity", data: '"data analysis"' };
const LANE_ALIAS = { contribute: "oss", opensource: "oss", paper: "research", papers: "research", new: "build" };
const MAX = 6;
const GFI = "/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const HELP =
  "<b>Project Scout</b> — GitHub project ideas by major.\n\n" +
  "/quant · /fintech · /swe · /cyber · /data — fresh repos to build\n" +
  "/oss &lt;major&gt; — open-source repos with open <i>good first issue</i> tickets\n" +
  "/research &lt;major&gt; — fresh paper code (cites arXiv) to reproduce or join\n\n" +
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
    return `• ${link(it.full_name, it.html_url)} ⭐${it.stargazers_count}${lang}\n  ${e(d) || "(no description)"}${tail}`;
  });
  return `${head}\n${rows.join("\n")}`;
}

// "/oss cyber honeypot" -> {lane:"oss", major:"cyber", extra:"honeypot"}; "nba stats" -> {lane:"build", major:null, extra:"nba stats"}
export function parse(text) {
  // in groups Telegram sends "/oss@BotName cyber" — drop the @mention
  const words = text.trim().replace(/^\/(\w+)@\w+/, "$1").replace(/^\//, "").split(/\s+/);
  let lane = words[0].toLowerCase();
  lane = LANES[lane] ? lane : LANE_ALIAS[lane];
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
  const anchor = major ? (lane === "research" ? RESEARCH_ANCHOR[major] : MAJORS[major].anchor) : "";
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
  const head = `<b>${LANES[lane].label} · ${major ? MAJORS[major].label : "🔎 All majors"}</b>${extra ? ` · <i>${esc(extra)}</i>` : ""}`;
  try {
    const items = await search(env, LANES[lane].q(terms(lane, major, extra)), LANES[lane].sort);
    await tgSend(env, chatId, render(head, lane, items));
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
