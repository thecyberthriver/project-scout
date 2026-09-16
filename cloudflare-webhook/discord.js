/**
 * Project Scout — Discord Interactions endpoint (Cloudflare Worker).
 *
 * Serves `/scout` (register with register_discord.py) from published.json only — no live searches, no GitHub token.
 * Verifies Discord's Ed25519 signature, rejects stale/replayed/out-of-guild interactions, checks the caller's role,
 * validates every option, replies "thinking…" within Discord's 3 s limit, then edits the reply with the rendered snapshot.
 *
 * Secrets (wrangler secret put … -c wrangler.discord.toml): DISCORD_PUBLIC_KEY, DISCORD_APP_ID, DISCORD_GUILD_ID,
 *   STUDENT_ROLE_ID, STAFF_ROLE_ID. All five are required; a missing one fails closed.
 */
import { MAJORS, LANES, OTHER_LANES, PAUSE_MSG, loadPublished, answerFor, mdEsc } from "./worker.js";

const HELP =
  "**Project Scout** — GitHub project ideas by major, pre-screened.\n" +
  "**New here? Run `/scout lane:Learning path major:<yours>`** — your whole year in order, stage by stage.\n" +
  "`/scout major:Cyber` fresh repos to build · `lane:Contribute` open good-first-issues · `lane:Research` fresh paper code.\n" +
  "Add `keywords:` to narrow, e.g. `/scout major:Data keywords:nba`. Add `level:` for Beginner, Intermediate or Advanced.\n" +
  "*Results come from a snapshot rebuilt every 6 hours after automated screening. Automated checks completed; not a safety guarantee. " +
  "Read a project's install steps before running anything; report suspicious links to TLDP staff.*";

export const COMMANDS = { scout: ["major", "lane", "keywords", "level"], verify: [] };
export const LEVELS = ["beginner", "intermediate", "advanced"];
export const KEYWORDS_RE = /^[\w .,&+#-]*$/;
export const KEYWORDS_MAX = 60;
const SKEW_S = 300;

const hex = (h) => Uint8Array.from(String(h).match(/../g) || [], (b) => parseInt(b, 16));
export async function verifySignature(request, body, env) {
  const sig = request.headers.get("x-signature-ed25519"), ts = request.headers.get("x-signature-timestamp");
  if (!sig || !ts || !env.DISCORD_PUBLIC_KEY || !/^[0-9a-f]{64}$/i.test(env.DISCORD_PUBLIC_KEY) || !/^[0-9a-f]{128}$/i.test(sig)) return false;
  if (!/^\d{1,12}$/.test(ts) || Math.abs(Date.now() / 1000 - Number(ts)) > SKEW_S) return false;
  try {
    const key = await crypto.subtle.importKey("raw", hex(env.DISCORD_PUBLIC_KEY), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify("Ed25519", key, hex(sig), new TextEncoder().encode(ts + body));
  } catch { return false; }
}

// ponytail: replay set and rate limiter live in this isolate only — best effort, resets on redeploy and differs per
// edge location. Upgrade to a KV namespace or a Durable Object if abuse is ever observed.
const seenIds = new Map();
const buckets = new Map();
const REPLAY_TTL = 600e3, REPLAY_CAP = 5000, RATE_N = 6, RATE_WINDOW = 60e3;
export function replay(id, now = Date.now()) {
  for (const [k, t] of seenIds) if (now - t > REPLAY_TTL) seenIds.delete(k);
  if (seenIds.has(id)) return true;
  if (seenIds.size >= REPLAY_CAP) seenIds.delete(seenIds.keys().next().value);
  seenIds.set(id, now);
  return false;
}
export function rateLimited(userId, now = Date.now()) {
  const hits = (buckets.get(userId) || []).filter((t) => now - t < RATE_WINDOW);
  if (hits.length >= RATE_N) { buckets.set(userId, hits); return true; }
  hits.push(now); buckets.set(userId, hits);
  if (buckets.size > REPLAY_CAP) buckets.delete(buckets.keys().next().value);
  return false;
}

// Returns {ok:true, o} with validated options, or {ok:false, msg}. Everything in `i` is untrusted.
export function validate(i, env) {
  if (!env.DISCORD_GUILD_ID || !i?.guild_id || String(i.guild_id) !== String(env.DISCORD_GUILD_ID)) return { ok: false, msg: "This command only works inside the TLDP server." };
  const name = i.data?.name;
  if (!COMMANDS[name]) return { ok: false, msg: "Unknown command." };
  const o = {};
  for (const opt of Array.isArray(i.data.options) ? i.data.options : []) {
    if (!COMMANDS[name].includes(opt?.name) || typeof opt.value !== "string") return { ok: false, msg: "Unknown option." };
    o[opt.name] = opt.value;
  }
  if (name === "scout") {
    if (o.major !== undefined && !MAJORS[o.major]) return { ok: false, msg: "Pick a major from the list." };
    if (o.lane !== undefined && !LANES[o.lane] && !OTHER_LANES.includes(o.lane)) return { ok: false, msg: "Pick a lane from the list." };
    if (o.level !== undefined && !LEVELS.includes(o.level)) return { ok: false, msg: "Pick a level from the list." };
    if (o.keywords !== undefined && (o.keywords.length > KEYWORDS_MAX || !KEYWORDS_RE.test(o.keywords)))
      return { ok: false, msg: `Keywords: up to ${KEYWORDS_MAX} letters, digits, spaces or . , & + # - only.` };
  }
  return { ok: true, name, o };
}
export function allowed(i, env) {
  if (!env.STUDENT_ROLE_ID || !env.STAFF_ROLE_ID) return false;  // fail closed when roles aren't configured
  const roles = Array.isArray(i.member?.roles) ? i.member.roles.map(String) : [];
  return roles.includes(String(env.STUDENT_ROLE_ID)) || roles.includes(String(env.STAFF_ROLE_ID));
}

const json = (o) => new Response(JSON.stringify(o), { headers: { "content-type": "application/json" } });
const ephemeral = (content) => json({ type: 4, data: { content, flags: 64, allowed_mentions: { parse: [] } } });
export const VERIFY_MSG = "Verification is handled by TLDP staff. Post in #introductions and a staff member will enroll you.";

async function answer(env, interaction, lane, major, extra) {
  let content;
  try {
    content = lane === "build" && !major && !extra ? HELP : answerFor(await loadPublished().catch(() => null), lane, major, extra, true);
  } catch (e) {
    console.log("answer error", e?.message);
    content = "Something went wrong on our side. Try again in a minute.";
  }
  await fetch(`https://discord.com/api/v10/webhooks/${env.DISCORD_APP_ID}/${interaction.token}/messages/@original`, {
    method: "PATCH", headers: { "content-type": "application/json" },
    body: JSON.stringify({ content: content.slice(0, 2000), allowed_mentions: { parse: [] } }),
  });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("Project Scout Discord endpoint is up.", { status: 200 });
    const body = await request.text();
    if (body.length > 65536 || !(await verifySignature(request, body, env))) return new Response("bad signature", { status: 401 });
    let i;
    try { i = JSON.parse(body); } catch { return new Response("bad request", { status: 400 }); }
    if (i.type === 1) return json({ type: 1 });                       // PING → PONG (endpoint verification)
    if (i.type !== 2) return ephemeral("Unsupported interaction.");
    if (typeof i.id !== "string" || replay(i.id)) return ephemeral("Duplicate request ignored.");
    const v = validate(i, env);
    if (!v.ok) return ephemeral(v.msg);
    if (v.name === "verify") return ephemeral(VERIFY_MSG);           // never assigns roles, no roster, no name matching
    const userId = String(i.member?.user?.id || "");
    if (!userId || !allowed(i, env)) return ephemeral("Project Scout isn't configured for you yet. Ask TLDP staff to enroll you.");
    if (rateLimited(userId)) return ephemeral("Slow down — try again in a minute.");
    const lane = v.o.lane || "build", major = v.o.major || null;
    const extra = [v.o.keywords || "", v.o.level || ""].join(" ").trim();  // level choice rides along as a keyword
    ctx.waitUntil(answer(env, i, lane, major, extra).catch((e) => console.log("answer error", e?.message)));
    return json({ type: 5, data: { allowed_mentions: { parse: [] } } });  // deferred reply; edited by answer()
  },
};
export { PAUSE_MSG, HELP, mdEsc };
