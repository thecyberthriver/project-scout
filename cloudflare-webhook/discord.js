/**
 * Project Scout — Discord Interactions endpoint (Cloudflare Worker).
 *
 * Serves the `/scout` slash command (register it with ../register_discord.py).
 * Verifies Discord's Ed25519 signature, replies "thinking…" within Discord's 3 s
 * limit, then edits the reply with the GitHub search result. Reuses the search,
 * query tables and 15-min cache from worker.js.
 *
 * Secrets (wrangler secret put … -c wrangler.discord.toml):
 *   DISCORD_PUBLIC_KEY   General Information → Public Key
 *   DISCORD_APP_ID       General Information → Application ID
 *   optional GITHUB_TOKEN
 */
import { MAJORS, LANES, lookup, render, terms, orgSearch, renderOrgs, startItems } from "./worker.js";

const HELP =
  "**Project Scout** — GitHub project ideas by major.\n" +
  "`/scout major:Cyber` fresh repos to build · `lane:Contribute` open good-first-issues · `lane:Research` fresh paper code.\n" +
  "Add `keywords:` to narrow, e.g. `/scout major:Data keywords:nba`.";

const hex = (h) => Uint8Array.from(h.match(/../g), (b) => parseInt(b, 16));

async function verify(request, body, env) {
  const sig = request.headers.get("x-signature-ed25519");
  const ts = request.headers.get("x-signature-timestamp");
  if (!sig || !ts || !env.DISCORD_PUBLIC_KEY) return false;
  const key = await crypto.subtle.importKey("raw", hex(env.DISCORD_PUBLIC_KEY), { name: "Ed25519" }, false, ["verify"]);
  return crypto.subtle.verify("Ed25519", key, hex(sig), new TextEncoder().encode(ts + body));
}

const json = (o) => new Response(JSON.stringify(o), { headers: { "content-type": "application/json" } });

/**
 * /verify name:<full name> major:<choice> — second gate after the invite link.
 * Secrets: ROSTER (JSON array of the 45 student names), DISCORD_BOT_TOKEN, DISCORD_GUILD_ID,
 *          STUDENT_ROLE_ID, MAJOR_ROLES (JSON {quant: roleId, ...}). Matching is case/punctuation-insensitive
 *          and accepts "First Last" against roster entries like "First M. Last".
 */
const norm = (s) => String(s).toLowerCase().replace(/[^a-z ]/g, "").replace(/\s+/g, " ").trim();
function rosterMatch(name, roster) {
  const n = norm(name).split(" ");
  if (n.length < 2) return null;
  return roster.find((r) => { const p = norm(r).split(" "); return p[0] === n[0] && p[p.length - 1] === n[n.length - 1]; }) || null;
}
async function verifyStudent(env, i, o) {
  const roster = JSON.parse(env.ROSTER || "[]");
  const userId = i.member?.user?.id;
  if (!userId || !env.STUDENT_ROLE_ID) return "Verification isn't set up yet — ask TLDP staff.";
  const hit = rosterMatch(o.name || "", roster);
  if (!hit) return `❌ "${o.name}" isn't on the TLDP roster. Use the name TLDP has on file, or ask staff in #introductions.`;
  const roles = [env.STUDENT_ROLE_ID];
  const majorRoles = JSON.parse(env.MAJOR_ROLES || "{}");
  if (o.major && majorRoles[o.major]) roles.push(majorRoles[o.major]);
  for (const r of roles) {
    const res = await fetch(`https://discord.com/api/v10/guilds/${env.DISCORD_GUILD_ID}/members/${userId}/roles/${r}`, {
      method: "PUT", headers: { authorization: `Bot ${env.DISCORD_BOT_TOKEN}`, "user-agent": "project-scout-bot" } });
    if (!res.ok) return `⚠️ Matched ${hit} but Discord refused the role (HTTP ${res.status}). Ask staff.`;
  }
  return `✅ Welcome, ${hit}! You now have the TLDP Student role${o.major ? ` and the ${MAJORS[o.major]?.label || o.major} role` : ""}. The feed and collaboration channels are unlocked.`;
}

async function answer(env, interaction, lane, major, extra) {
  let content;
  if (lane === "build" && !major && !extra) content = HELP;
  else {
    const laneLabel = { orgs: "🤝 Mission-driven orgs", start: "📚 Start here — ideas & basics" }[lane] || LANES[lane].label;
    const head = `**${laneLabel} · ${major ? MAJORS[major].label : "🔎 All majors"}**${extra ? ` · *${extra}*` : ""}`;
    try {
      content = lane === "orgs"
        ? renderOrgs(head, await orgSearch(env, terms(lane, major, extra)), true)
        : lane === "start"
          ? render(head, "build", await startItems(env, major), true) + "\n\n💡 Pick one, read its README, then run `/scout` for something fresh to build on top of it."
          : render(head, lane, await lookup(env, lane, major, extra), true);
    } catch (e) {
      content = `⚠️ ${e.message} — GitHub search is rate-limited; try again in a minute.`;
    }
  }
  await fetch(`https://discord.com/api/v10/webhooks/${env.DISCORD_APP_ID}/${interaction.token}/messages/@original`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content: content.slice(0, 2000) }),
  });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("Project Scout Discord endpoint is up.", { status: 200 });
    const body = await request.text();
    if (!(await verify(request, body, env))) return new Response("bad signature", { status: 401 });
    const i = JSON.parse(body);
    if (i.type === 1) return json({ type: 1 });                       // PING → PONG (endpoint verification)
    if (i.type !== 2) return json({ type: 4, data: { content: "Unsupported interaction." } });
    const o = Object.fromEntries((i.data.options || []).map((x) => [x.name, x.value]));
    if (i.data.name === "verify") return json({ type: 4, data: { content: await verifyStudent(env, i, o), flags: 64 } });
    const lane = LANES[o.lane] || o.lane === "orgs" || o.lane === "start" ? o.lane : "build";
    const major = MAJORS[o.major] ? o.major : null;
    ctx.waitUntil(answer(env, i, lane, major, (o.keywords || "").trim()).catch((e) => console.log("answer error", e)));
    return json({ type: 5 });                                          // deferred reply; edited by answer()
  },
};
