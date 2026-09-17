// Self-check for /verify's decision logic: node test_verify.mjs
import assert from "node:assert/strict";
import { verifyPlan } from "./discord.js";

const ENV = { DISCORD_BOT_TOKEN: "t", DISCORD_GUILD_ID: "1", STUDENT_ROLE_ID: "100", STAFF_ROLE_ID: "200" };
const who = (roles) => ({ member: { user: { id: "123456789012345678" }, roles } });

assert.deepEqual(verifyPlan(who([]), ENV), { action: "grant", userId: "123456789012345678" });
assert.equal(verifyPlan(who(["100"]), ENV).action, "already");
assert.equal(verifyPlan(who(["200"]), ENV).action, "already");
assert.equal(verifyPlan(who([]), { ...ENV, DISCORD_BOT_TOKEN: "" }).action, "unconfigured");  // fails closed
assert.equal(verifyPlan(who([]), { ...ENV, STUDENT_ROLE_ID: "" }).action, "unconfigured");
assert.equal(verifyPlan({ member: { roles: [] } }, ENV).action, "unconfigured");              // no user id
assert.equal(verifyPlan({}, ENV).action, "unconfigured");                                     // DM, no member

console.log("verifyPlan: 7 checks passed");
