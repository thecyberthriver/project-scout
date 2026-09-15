/**
 * Project Scout — Cloudflare Worker (instant Telegram webhook).
 *
 * Answers /quant /fintech /swe /cyber /data (optionally + keywords, e.g.
 * "/cyber honeypot") by hitting the GitHub Search API directly — no Actions
 * round-trip. The weekly digest lives in ../project_scout.py (GitHub Actions).
 *
 * Secrets: TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, OWNER_CHAT_ID (lock to one user),
 *          optional GITHUB_TOKEN (30 searches/min instead of 10).
 */
const MAJORS = {
  quant:   { label: "📈 Quant",                terms: '"quantitative finance" OR backtesting OR "algorithmic trading" OR "options pricing" OR "portfolio optimization"' },
  fintech: { label: "💳 Finance / FinTech",    terms: 'fintech OR payments OR "personal finance" OR "open banking" OR budgeting OR "stock market"' },
  swe:     { label: "💻 Software Engineering", terms: '"build your own" OR "from scratch" OR "project ideas" OR "portfolio project" OR "full stack"' },
  cyber:   { label: "🔐 Cybersecurity",        terms: 'cybersecurity OR "penetration testing" OR "threat detection" OR "malware analysis" OR "security tool" OR CTF' },
  data:    { label: "📊 Data Analytics",       terms: '"data analytics" OR "data analysis" OR "exploratory data analysis" OR "data pipeline" OR "data visualization"' },
};
const ALIAS = { finance: "fintech", software: "swe", security: "cyber", analytics: "data" };
const DAYS = 90;      // interactive window (digest uses 14)
const MIN_STARS = 10;
const MAX = 6;

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const HELP =
  "<b>Project Scout</b> — GitHub project ideas by major.\n\n" +
  "/quant · /fintech · /swe · /cyber · /data\n" +
  "Add keywords to narrow: <code>/cyber honeypot</code>, <code>/data nba</code>.\n" +
  "Any other text = keyword search across all majors.\n\n" +
  `<i>Shows repos created in the last ${DAYS} days with ⭐${MIN_STARS}+. New repos are pushed here automatically as they appear (checked every 2 h).</i>`;

async function tgSend(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true }),
  });
}

async function search(env, terms) {
  const since = new Date(Date.now() - DAYS * 864e5).toISOString().slice(0, 10);
  const q = `${terms} created:>=${since} stars:>=${MIN_STARS} archived:false`;
  const url = "https://api.github.com/search/repositories?" +
    new URLSearchParams({ q, sort: "stars", order: "desc", per_page: String(MAX) });
  const headers = { accept: "application/vnd.github+json", "user-agent": "project-scout-bot" };
  if (env.GITHUB_TOKEN) headers.authorization = `Bearer ${env.GITHUB_TOKEN}`;
  const r = await fetch(url, { headers });
  if (!r.ok) throw new Error(`GitHub HTTP ${r.status}`);
  return (await r.json()).items || [];
}

function render(label, items, extra) {
  const head = `<b>${label}</b>${extra ? ` · <i>${esc(extra)}</i>` : ""}`;
  if (!items.length) return `${head}\nNothing new matched. Try fewer keywords.`;
  const rows = items.map((it) => {
    let d = (it.description || "").trim();
    if (d.length > 140) d = d.slice(0, 140) + "…";
    const lang = it.language ? ` · ${esc(it.language)}` : "";
    return `• <a href="${it.html_url}">${esc(it.full_name)}</a> ⭐${it.stargazers_count}${lang}\n  ${esc(d) || "(no description)"}`;
  });
  return `${head}\n${rows.join("\n")}`;
}

// "/cyber honeypot" -> {major:"cyber", extra:"honeypot"}; "nba stats" -> {major:null, extra:"nba stats"}
export function parse(text) {
  const words = text.trim().replace(/^\//, "").split(/\s+/);
  let major = words[0].toLowerCase();
  major = MAJORS[major] ? major : ALIAS[major] || null;
  const extra = (major ? words.slice(1) : words).join(" ").trim();
  return { major, extra };
}

async function handleUpdate(env, update) {
  const msg = update.message || update.edited_message;
  if (!msg || !msg.chat) return;
  const chatId = String(msg.chat.id);
  if (env.OWNER_CHAT_ID && chatId !== String(env.OWNER_CHAT_ID)) return;

  const t = (msg.text || "").trim();
  if (!t || /^\/?(start|help)$/i.test(t)) return tgSend(env, chatId, HELP);

  const { major, extra } = parse(t);
  if (!major && !extra) return tgSend(env, chatId, HELP);
  const label = major ? MAJORS[major].label : "🔎 All majors";
  // GitHub search has no parentheses, so keywords + major use a single anchor word instead of the OR list.
  const ANCHOR = { quant: "quant", fintech: "finance", swe: "", cyber: "security", data: "data" };
  const terms = major && !extra ? MAJORS[major].terms : `${major ? ANCHOR[major] : ""} ${extra} in:name,description,readme`.trim();
  try {
    const items = await search(env, terms);
    await tgSend(env, chatId, render(label, items, extra));
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
