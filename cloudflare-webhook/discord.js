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
import { MAJORS, LANES, search, render, terms } from "./worker.js";

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

async function answer(env, interaction, lane, major, extra) {
  let content;
  if (lane === "build" && !major && !extra) content = HELP;
  else {
    const head = `**${LANES[lane].label} · ${major ? MAJORS[major].label : "🔎 All majors"}**${extra ? ` · *${extra}*` : ""}`;
    try {
      content = render(head, lane, await search(env, LANES[lane].q(terms(lane, major, extra)), LANES[lane].sort), true);
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
    const lane = LANES[o.lane] ? o.lane : "build";
    const major = MAJORS[o.major] ? o.major : null;
    ctx.waitUntil(answer(env, i, lane, major, (o.keywords || "").trim()).catch((e) => console.log("answer error", e)));
    return json({ type: 5 });                                          // deferred reply; edited by answer()
  },
};
