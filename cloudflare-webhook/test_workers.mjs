// node --test cloudflare-webhook/test_workers.mjs — no network: fetch is stubbed and any real call fails the test.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as w from "./worker.js";
import discord, { validate, allowed, replay, rateLimited, verifySignature, verifyPlan,
  VERIFY_MSG, VERIFY_ALREADY, VERIFY_OK, VERIFY_FAIL } from "./discord.js";

const NOW = Date.parse("2026-10-01T12:00:00Z");
const iso = (ms) => new Date(ms).toISOString();
const day = (n) => iso(NOW - n * 864e5).slice(0, 10);
const SHA = "a".repeat(40);
const screened = (expDays = 10) => ({ sha: SHA, at: iso(NOW - 3600e3), expires: iso(NOW + expDays * 864e5) });
const row = (name, extra = {}) => ({ full_name: name, html_url: `https://github.com/${name}`, stargazers_count: 10, language: "Python",
  description: "a plain description", size: 500, pushed_at: day(5), created_at: day(20), screened: screened(), kind: "fresh", ...extra });
const meta = (extra = {}) => ({ generated_at: iso(NOW), status: "operational", last_screening_at: iso(NOW - 3600e3), fresh_field: "pushed_at",
  fresh_days: 30, label: "Automated checks completed; not a safety guarantee.", policy_version: 2, semgrep_version: "1.177.0", ruleset_sha256: "x", ...extra });
const pub = (rows, m = {}) => ({ meta: meta(m), feed: { "cyber|build|": rows }, evergreen: { starters: { cyber: rows }, cases: {}, paths: {}, stages: [] }, hackathons: { at: iso(NOW), items: [] } });

globalThis.fetch = async () => { throw new Error("network call attempted"); };

test("gate: expired, missing, bad-sha screening dropped; valid kept", () => {
  const m = meta();
  assert.equal(w.eligible(row("a/b"), m, NOW), true);
  assert.equal(w.eligible(row("a/b", { screened: screened(-1) }), m, NOW), false);
  assert.equal(w.eligible(row("a/b", { screened: undefined }), m, NOW), false);
  assert.equal(w.eligible(row("a/b", { screened: { ...screened(), sha: "notasha" } }), m, NOW), false);
  assert.equal(w.eligible(row("ElementTrail/Multichain-Drainer", { screened: undefined }), m, NOW), false);
});

test("gate: freshness boundary 30 passes, 31 fails; evergreen exempt; created_at honoured", () => {
  const m = meta();
  assert.equal(w.eligible(row("a/b", { pushed_at: day(30) }), m, NOW), true);
  assert.equal(w.eligible(row("a/b", { pushed_at: day(31) }), m, NOW), false);
  assert.equal(w.eligible(row("a/b", { pushed_at: day(300), kind: "evergreen" }), m, NOW), true);
  assert.equal(w.eligible(row("a/b", { pushed_at: day(300), kind: "evergreen", screened: screened(-1) }), m, NOW), false);
  assert.equal(w.eligible(row("a/b", { created_at: day(31), pushed_at: day(1) }), meta({ fresh_field: "created_at" }), NOW), false);
});

test("paused when snapshot missing, degraded, or stale", () => {
  assert.equal(w.answerFor(null, "build", "cyber", "", true, NOW), w.PAUSE_MSG);
  assert.equal(w.answerFor(pub([row("a/b")], { status: "degraded" }), "build", "cyber", "", true, NOW), w.PAUSE_MSG);
  assert.equal(w.answerFor(pub([row("a/b")], { last_screening_at: iso(NOW - 37 * 3600e3) }), "build", "cyber", "", true, NOW), w.PAUSE_MSG);
  assert.equal(w.answerFor(pub([row("a/b")], { last_screening_at: iso(NOW - 35 * 3600e3) }), "build", "cyber", "", true, NOW).includes("a/b"), true);
  assert.equal(w.answerFor(pub([row("a/b")]), "hackathons", null, "", true, NOW).includes("Nothing listed"), true);
});

test("keyword filtering is local and never falls back to network", () => {
  const p = pub([row("x/honeypot", { description: "ssh honeypot" }), row("y/other")]);
  const out = w.lookup(p, "build", "cyber", "honeypot", NOW);
  assert.deepEqual(out.map((r) => r.full_name), ["x/honeypot"]);
  assert.deepEqual(w.lookup(p, "build", "cyber", "nothingmatches", NOW), []);
  assert.deepEqual(w.lookup(p, "build", "swe", "d7", NOW), []);  // unindexed sub-label → empty, no live search
  assert.equal(w.answerFor(p, "build", "cyber", "zzz", true, NOW).includes("Nothing matched"), true);
});

test("links: only https + allowlisted hosts become links; everything else is escaped text", () => {
  assert.equal(w.link("t", "https://github.com/a/b", true), "[t](<https://github.com/a/b>)");
  assert.equal(w.link("t", "http://github.com/a/b", true), "t");
  assert.equal(w.link("t", "https://evil.example/x", true), "t");
  assert.equal(w.link("t", "javascript:alert(1)", false), "t");
  assert.equal(w.link("t", "https://user:pw@github.com/a", true), "t");
  const out = w.answerFor(pub([row("a/b", { html_url: "https://evil.example/a/b" })]), "build", "cyber", "", true, NOW);
  assert.ok(!out.includes("evil.example") && out.includes("a/b"));
});

test("injection: description cannot mention or smuggle a masked link", () => {
  const evil = row("a/b", { description: "@everyone [click](https://evil.example) **bold** <@&1>" });
  const out = w.answerFor(pub([evil]), "build", "cyber", "", true, NOW);
  assert.ok(!/(^|[^​])@everyone/.test(out));
  assert.ok(!out.includes("[click](https://evil.example)"));
  assert.ok(!out.includes("<@&1>"));
  assert.ok(out.endsWith("*Automated checks completed; not a safety guarantee.*"));
  const tg = w.answerFor(pub([row("a/b", { description: "<b>x</b>" })]), "build", "cyber", "", false, NOW);
  assert.ok(tg.includes("&lt;b&gt;x&lt;/b&gt;"));
});

test("2000-char packing drops whole rows, keeps header and label, never cuts a link", () => {
  const rows = Array.from({ length: 40 }, (_, i) => row(`org${i}/repo-${"x".repeat(30)}-${i}`, { description: "d".repeat(140) }));
  const out = w.answerFor(pub(rows), "build", "cyber", "", true, NOW);
  assert.ok(out.length <= 2000);
  assert.ok(out.startsWith("**"));
  assert.ok(out.endsWith("*Automated checks completed; not a safety guarantee.*"));
  for (const m of out.matchAll(/\]\(<[^>]*/g)) assert.ok(m[0].endsWith(">") || out.slice(m.index).includes(">)"));
  assert.equal((out.match(/\]\(</g) || []).length, (out.match(/>\)/g) || []).length);
});

test("evergreen lists are labelled", () => {
  const out = w.answerFor(pub([row("a/b", { kind: "evergreen", pushed_at: day(400) })]), "start", "cyber", "", true, NOW);
  assert.ok(out.includes(w.EVERGREEN_HEAD) && out.includes("a/b"));
});

// ---- discord.js -------------------------------------------------------------------------------------------------------
const ENV = { DISCORD_GUILD_ID: "g1", STUDENT_ROLE_ID: "s1", STAFF_ROLE_ID: "st1" };
const inter = (over = {}) => ({ id: String(Math.random()), type: 2, guild_id: "g1", data: { name: "scout", options: [] }, member: { roles: ["s1"], user: { id: "u1" } }, token: "tok", ...over });

test("validate: guild, command, options, keywords", () => {
  assert.equal(validate(inter(), ENV).ok, true);
  assert.equal(validate(inter({ guild_id: "g2" }), ENV).ok, false);
  assert.equal(validate(inter(), { ...ENV, DISCORD_GUILD_ID: "" }).ok, false);
  assert.equal(validate(inter({ guild_id: undefined }), ENV).ok, false);
  assert.equal(validate(inter({ data: { name: "evil", options: [] } }), ENV).ok, false);
  assert.equal(validate(inter({ data: { name: "scout", options: [{ name: "x", value: "y" }] } }), ENV).ok, false);
  assert.equal(validate(inter({ data: { name: "scout", options: [{ name: "keywords", value: "k".repeat(61) }] } }), ENV).ok, false);
  assert.equal(validate(inter({ data: { name: "scout", options: [{ name: "keywords", value: "@everyone" }] } }), ENV).ok, false);
  assert.equal(validate(inter({ data: { name: "scout", options: [{ name: "keywords", value: "nba stats" }] } }), ENV).ok, true);
  assert.equal(validate(inter({ data: { name: "scout", options: [{ name: "major", value: "nope" }] } }), ENV).ok, false);
  assert.equal(validate(inter({ data: { name: "scout", options: [{ name: "level", value: "god" }] } }), ENV).ok, false);
  assert.equal(validate(inter({ data: { name: "scout", options: [{ name: "lane", value: 5 }] } }), ENV).ok, false);
});

test("allowed: fails closed without role config; non-student rejected", () => {
  assert.equal(allowed(inter(), ENV), true);
  assert.equal(allowed(inter({ member: { roles: ["st1"], user: { id: "u" } } }), ENV), true);
  assert.equal(allowed(inter({ member: { roles: ["other"], user: { id: "u" } } }), ENV), false);
  assert.equal(allowed(inter(), { ...ENV, STUDENT_ROLE_ID: "" }), false);
  assert.equal(allowed(inter(), { ...ENV, STAFF_ROLE_ID: undefined }), false);
});

test("replay and rate limit", () => {
  assert.equal(replay("id-1", NOW), false);
  assert.equal(replay("id-1", NOW + 1000), true);
  assert.equal(replay("id-1", NOW + 700e3), false);  // expired from the set
  for (let i = 0; i < 6; i++) assert.equal(rateLimited("rl-user", NOW + i), false);
  assert.equal(rateLimited("rl-user", NOW + 10), true);
  assert.equal(rateLimited("rl-user", NOW + 61e3), false);
});

// Signed requests: generate an Ed25519 key in-test and sign exactly as Discord does (timestamp + body).
const kp = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
const pubHex = Buffer.from(await crypto.subtle.exportKey("raw", kp.publicKey)).toString("hex");
const SENV = { ...ENV, DISCORD_PUBLIC_KEY: pubHex, DISCORD_APP_ID: "app" };
async function signed(bodyObj, tsOffset = 0, badSig = false) {
  const body = JSON.stringify(bodyObj), ts = String(Math.floor(Date.now() / 1000) + tsOffset);
  let sig = Buffer.from(await crypto.subtle.sign("Ed25519", kp.privateKey, new TextEncoder().encode(ts + body))).toString("hex");
  if (badSig) sig = sig.replace(/^../, "00");
  return new Request("https://x/", { method: "POST", body, headers: { "x-signature-ed25519": sig, "x-signature-timestamp": ts } });
}
const ctx = { waitUntil: (p) => p.catch(() => {}) };

test("signature required, skewed timestamp rejected, ping answered", async () => {
  assert.equal((await discord.fetch(await signed({ type: 1 }, 0, true), SENV, ctx)).status, 401);
  assert.equal((await discord.fetch(await signed({ type: 1 }, 400), SENV, ctx)).status, 401);
  assert.equal((await discord.fetch(await signed({ type: 1 }), SENV, ctx)).status, 200);
  assert.equal(await verifySignature(await signed({ type: 1 }), "{}", SENV), false);  // body mismatch
});

const bodyOf = async (r) => JSON.parse(await r.text());
test("wrong guild / missing config / non-student / replay via the handler", async () => {
  let b = await bodyOf(await discord.fetch(await signed(inter({ guild_id: "other" })), SENV, ctx));
  assert.equal(b.type, 4); assert.ok(b.data.content.includes("only works inside")); assert.equal(b.data.flags, 64);
  b = await bodyOf(await discord.fetch(await signed(inter()), { ...SENV, STUDENT_ROLE_ID: "" }, ctx));
  assert.ok(b.data.content.includes("isn't configured"));
  b = await bodyOf(await discord.fetch(await signed(inter({ member: { roles: [], user: { id: "u9" } } })), SENV, ctx));
  assert.ok(b.data.content.includes("isn't configured"));
  const same = inter({ id: "replay-1" });
  await discord.fetch(await signed(same), SENV, ctx);
  b = await bodyOf(await discord.fetch(await signed(same), SENV, ctx));
  assert.ok(b.data.content.includes("Duplicate"));
});

// /verify grants the TLDP Student role (the staff-issued invite is the gate). It matches NO names: a ROSTER env var
// must never turn it into a name oracle, and it must stay ephemeral and fail closed when it is not configured.
test("/verify: unconfigured and already-verified answer without any network call, and ignore ROSTER", async () => {
  const calls = [];
  globalThis.fetch = async (url) => { calls.push(String(url)); throw new Error("no network"); };
  const verify = (over = {}) => inter({ data: { name: "verify", options: [] }, ...over });
  // no bot token -> "ask staff", ephemeral, nothing called
  let b = await bodyOf(await discord.fetch(await signed(verify()), { ...SENV, ROSTER: '["Some Name"]' }, ctx));
  assert.equal(b.data.content, VERIFY_MSG); assert.equal(b.data.flags, 64);
  // already holds the Student role -> told so, still nothing called
  b = await bodyOf(await discord.fetch(await signed(verify()), { ...SENV, DISCORD_BOT_TOKEN: "t", ROSTER: '["Some Name"]' }, ctx));
  assert.equal(b.data.content, VERIFY_ALREADY); assert.equal(b.data.flags, 64);
  assert.deepEqual(calls, []);
  globalThis.fetch = async () => { throw new Error("network call attempted"); };
});

test("/verify: a member without the role gets it granted by id, never by name", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), method: init?.method, auth: init?.headers?.authorization }); return new Response(null, { status: 204 }); };
  const env = { ...SENV, DISCORD_BOT_TOKEN: "t", ROSTER: '["Some Name"]' };
  const newcomer = inter({ data: { name: "verify", options: [] }, member: { roles: [], user: { id: "123456789" } } });
  const b = await bodyOf(await discord.fetch(await signed(newcomer), env, ctx));
  assert.equal(b.data.content, VERIFY_OK); assert.equal(b.data.flags, 64);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "PUT");
  assert.equal(calls[0].url, "https://discord.com/api/v10/guilds/g1/members/123456789/roles/s1");
  assert.equal(calls[0].auth, "Bot t");
  assert.ok(!JSON.stringify(calls).includes("Some Name"));      // no roster, no name matching
  globalThis.fetch = async () => { throw new Error("network call attempted"); };
});

test("/verify: a refused grant fails closed, and a malformed caller is never granted", async () => {
  globalThis.fetch = async () => new Response("nope", { status: 403 });
  const env = { ...SENV, DISCORD_BOT_TOKEN: "t" };
  const b = await bodyOf(await discord.fetch(await signed(inter({ data: { name: "verify", options: [] }, member: { roles: [], user: { id: "987654321" } } })), env, ctx));
  assert.equal(b.data.content, VERIFY_FAIL); assert.equal(b.data.flags, 64);
  globalThis.fetch = async () => { throw new Error("network call attempted"); };
  assert.equal(verifyPlan({ member: { roles: [], user: { id: "nope" } } }, env).action, "unconfigured");
  assert.equal(verifyPlan({ member: { roles: [], user: { id: "123456789" } } }, { ...env, DISCORD_BOT_TOKEN: "" }).action, "unconfigured");
  assert.equal(verifyPlan({ member: { roles: ["st1"], user: { id: "123456789" } } }, env).action, "already");
});

test("/scout deferred reply carries allowed_mentions and the edit is mention-safe and published-only", async () => {
  const patches = [];
  globalThis.fetch = async (url, init) => {
    if (String(url) === w.PUBLISHED_URL) return new Response(JSON.stringify(pub([row("a/b", { description: "@everyone hi" })])));
    if (String(url).includes("discord.com/api/v10/webhooks/")) { patches.push(JSON.parse(init.body)); return new Response("{}"); }
    throw new Error("unexpected network call " + url);
  };
  let done; const c2 = { waitUntil: (p) => { done = p; } };
  const realNow = Date.now; Date.now = () => NOW;
  try {
    const b = await bodyOf(await discord.fetch(await signed(inter({ data: { name: "scout", options: [{ name: "major", value: "cyber" }] } }), 0), SENV, c2));
    assert.equal(b.type, 5); assert.deepEqual(b.data.allowed_mentions, { parse: [] });
  } finally { Date.now = realNow; }
  await done;
  assert.equal(patches.length, 1);
  assert.deepEqual(patches[0].allowed_mentions, { parse: [] });
  assert.ok(patches[0].content.includes("a/b") && !/(^|[^​])@everyone/.test(patches[0].content));
  globalThis.fetch = async () => { throw new Error("network call attempted"); };
});

test("telegram worker: missing secret fails closed; owner lock; text capped", async () => {
  const r = await w.default.fetch(new Request("https://x/", { method: "POST", body: "{}" }), {}, ctx);
  assert.equal(r.status, 401);
  assert.deepEqual(w.parse("/oss cyber " + "k".repeat(500)), { lane: "oss", major: "cyber", extra: "k".repeat(60) });
});

test("levels: beginner is the default; harder is an explicit choice, simpler-only fallback", () => {
  const rows = [
    { full_name: "x/beg", level: "beginner" },
    { full_name: "x/int", level: "intermediate" },
    { full_name: "x/chal", level: "challenge" },
  ];
  assert.equal(w.wantedLevel(""), "beginner");
  assert.equal(w.wantedLevel("intermediate"), "intermediate");
  assert.equal(w.wantedLevel("advanced"), "challenge");
  // default returns only beginner
  assert.deepEqual(w.byLevel(rows, "").rows.map((r) => r.full_name), ["x/beg"]);
  // intermediate returns intermediate
  assert.deepEqual(w.byLevel(rows, "intermediate").rows.map((r) => r.full_name), ["x/int"]);
  // a row with no level is treated as beginner
  assert.deepEqual(w.byLevel([{ full_name: "x/none" }], "").rows.map((r) => r.full_name), ["x/none"]);
});

test("levels: no harder substitution — beginner request with none available shows nothing harder", () => {
  const onlyHard = [{ full_name: "x/int", level: "intermediate" }, { full_name: "x/chal", level: "challenge" }];
  assert.deepEqual(w.byLevel(onlyHard, "").rows, []);                       // beginner asked, none -> empty, not harder
  assert.deepEqual(w.byLevel(onlyHard, "intermediate").rows.map((r) => r.full_name), ["x/int"]);  // exact match
  // challenge asked, only intermediate present -> steps DOWN to intermediate (simpler), never up
  assert.deepEqual(w.byLevel([{ full_name: "x/int", level: "intermediate" }], "challenge").rows.map((r) => r.full_name), ["x/int"]);
});

test("levels: lookup defaults to beginner rows from the published feed", () => {
  const p = pub([row("x/beg", { level: "beginner" }), row("x/chal", { level: "challenge" })]);
  const names = w.lookup(p, "build", "cyber", "", NOW).map((r) => r.full_name);
  assert.deepEqual(names, ["x/beg"]);
  const hard = w.lookup(p, "build", "cyber", "challenge", NOW).map((r) => r.full_name);
  assert.deepEqual(hard, ["x/chal"]);
});

// ---- Hugging Face lane ------------------------------------------------------------------------------------------
const hrow = (id = "acme/demo", extra = {}) => ({
  full_name: `hf:models/${id}`, id, hf_kind: "model", html_url: `https://huggingface.co/${id}`, likes: 42,
  description: "a plain description", license: "apache-2.0", task: "text-classification",
  industry: "healthcare", industry_emoji: "\u{1FA7A}", warnings: [],
  screened: { result: "pass", sha: SHA, at: iso(NOW - 3600e3), expires: iso(NOW + 10 * 864e5) }, ...extra });
const hpub = (rows, m = {}) => ({ ...pub([], m), huggingface: { at: iso(NOW), items: { cyber: rows } } });

test("hf: only a passing, pinned, unexpired record renders", () => {
  assert.equal(w.hfEligible(hrow(), NOW), true);
  assert.equal(w.hfEligible(hrow("a/b", { screened: { result: "incomplete", sha: SHA, expires: iso(NOW + 864e5) } }), NOW), false);
  assert.equal(w.hfEligible(hrow("a/b", { screened: { result: "pass", sha: SHA, expires: iso(NOW - 864e5) } }), NOW), false);
  assert.equal(w.hfEligible(hrow("a/b", { screened: { result: "pass", sha: "notasha", expires: iso(NOW + 864e5) } }), NOW), false);
  assert.equal(w.hfEligible(row("a/b"), NOW), false);              // a GitHub repo row never rides this lane
});

test("hf: answers are gated, labelled, and never claim a code scan", () => {
  const out = w.answerFor(hpub([hrow(), hrow("bad/one", { screened: { result: "fail", sha: SHA, expires: iso(NOW + 864e5) } })]),
                          "hf", "cyber", "", true, NOW);
  assert.match(out, /huggingface\.co\/acme\/demo/);
  assert.ok(!out.includes("bad/one"));
  assert.ok(out.includes(w.HF_NOTE));
  assert.equal(w.answerFor(hpub([hrow()], { status: "degraded" }), "hf", "cyber", "", true, NOW), w.PAUSE_MSG);
  assert.match(w.answerFor(hpub([]), "hf", "cyber", "", true, NOW), /Nothing matched/);
});

test("hf: links render (huggingface.co is allow-listed), keywords filter, aliases parse", () => {
  assert.equal(w.safeUrl("https://huggingface.co/acme/demo"), "https://huggingface.co/acme/demo");
  assert.equal(w.safeUrl("https://evil.tld/acme/demo"), null);
  assert.equal(w.hfItems(hpub([hrow()]), "cyber", "nomatchhere", NOW).length, 0);
  assert.equal(w.hfItems(hpub([hrow()]), "cyber", "demo", NOW).length, 1);
  assert.equal(w.parse("/hf cyber").lane, "hf");
  assert.equal(w.parse("/huggingface cyber").lane, "hf");
  assert.equal(w.parse("/datasets cyber").lane, "hf");
});

test("hf: warnings reach the student, and untrusted text is escaped", () => {
  const out = w.answerFor(hpub([hrow("acme/demo", { warnings: ["custom code — needs trust_remote_code=True"] })]), "hf", "cyber", "", true, NOW);
  assert.match(out, /trust..?_remote..?_code/);      // present, with Discord markdown escaping
  const nasty = w.answerFor(hpub([hrow("acme/demo", { description: "[click](https://evil.tld) **bold** @everyone" })]), "hf", "cyber", "", true, NOW);
  assert.ok(!nasty.includes("[click](https://evil.tld)"));
  assert.ok(!nasty.includes("@everyone"));           // mdEsc puts a zero-width space after the @
});
