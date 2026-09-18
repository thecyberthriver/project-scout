#!/usr/bin/env python3
"""
dedupe_posts.py — delete duplicate forum threads the bot posted twice.

  python dedupe_posts.py            # dry run: list what would be deleted
  python dedupe_posts.py --apply    # delete them

Two kinds of duplicate, both from a post type being run more than once (the one-time --paths/--starters/--courses
flags have no seen-check, and a digest re-run before seen.json was committed re-picks the same repos):
  * identical content — two threads in one channel linking the exact same set of repos
  * repeat evergreen  — the same one-time post (🗺 roadmap / 📚 start-here / 🎓 course map) posted again

The NEWEST thread of each group is kept. A thread is never deleted if a student posted in it or reacted to it.
Deleting a forum thread's starter message deletes the thread, and the webhook that posted it can delete it — so this
needs no Manage Threads on the bot role, same trick purge_posts.py uses to edit posts.
Needs DISCORD_BOT_TOKEN / DISCORD_GUILD_ID / DISCORD_WEBHOOKS (secrets_local.py or env).
"""
import collections
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request

import enroll

REPO = re.compile(r"(github\.com|huggingface\.co)/((?:datasets/|spaces/)?[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)")
EVERGREEN = ("🗺", "📚", "🎓")  # one-time posts; the feed drops are seen-gated and are left alone
APPLY = "--apply" in sys.argv


def api(method, path):
    """enroll.api with 429 backoff — a sweep makes enough calls to hit the bucket."""
    for _ in range(6):
        try:
            return enroll.api(method, path)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(float(json.loads(e.read()).get("retry_after", 2)) + 0.5)
    raise SystemExit("rate limited six times in a row; try again later")


def hooks_by_channel() -> dict[str, str]:
    """parent channel id -> webhook url, from the DISCORD_WEBHOOKS map purge_posts.py also reads."""
    out = {}
    for key, url in json.loads(enroll._env("DISCORD_WEBHOOKS") or "{}").items():
        try:
            out[api("GET", f"/webhooks/{url.split('/')[-2]}")["channel_id"]] = url
        except urllib.error.HTTPError as e:
            print(f"webhook {key}: {e}", file=sys.stderr)
    return out


def delete_thread(hook: str | None, thread_id: str) -> None:
    """Delete the thread with the bot (needs Manage Threads); fall back to the webhook that posted the starter."""
    try:
        api("DELETE", f"/channels/{thread_id}")
        return
    except urllib.error.HTTPError as e:
        if e.code != 403 or not hook:
            raise
    # Manage Threads not granted: a webhook may delete its OWN starter message, which deletes the post.
    wid, token = hook.split("/")[-2], hook.split("/")[-1]
    req = urllib.request.Request(
        f"https://discord.com/api/v10/webhooks/{wid}/{token}/messages/{thread_id}?thread_id={thread_id}",
        method="DELETE", headers={"User-Agent": "project-scout-dedupe (github.com/tldpprojectscout/project-scout, 1.0)"})
    urllib.request.urlopen(req, timeout=30).close()


def feed_threads(guild: str) -> list[dict]:
    """Every thread in every forum channel, active and archived."""
    forums = [c for c in api("GET", f"/guilds/{guild}/channels") if c["type"] == 15]
    names = {c["id"]: c["name"] for c in forums}
    out = [t for t in api("GET", f"/guilds/{guild}/threads/active")["threads"] if t["parent_id"] in names]
    for f in forums:
        before = ""  # archived threads page 100 at a time; without this the oldest posts are never scanned
        while True:
            page = api("GET", f"/channels/{f['id']}/threads/archived/public?limit=100{before}")
            out += page["threads"]
            time.sleep(0.3)
            if not page.get("has_more") or not page["threads"]:
                break
            before = "&before=" + page["threads"][-1]["thread_metadata"]["archive_timestamp"]
    return [dict(t, channel=names[t["parent_id"]]) for t in out]


def duplicates(threads: list[dict]) -> dict[str, str]:
    """thread id -> why it is redundant. Keeps the newest of each group (ids are snowflakes: bigger == newer)."""
    bodies, drop = {}, {}
    for t in threads:
        msgs = api("GET", f"/channels/{t['id']}/messages?limit=100")
        text = "\n".join(m.get("content", "") for m in msgs)
        bodies[t["id"]] = {
            # hash the whole post, not just its repo links: a drop whose only content is the canned
            # "build-it-yourself idea" has no links at all, and those were the ones repeating.
            "text": hashlib.sha1(" ".join(text.split()).encode()).hexdigest(),
            "repos": sorted({f"{h}/{p}".rstrip(".").lower() for h, p in REPO.findall(text)}),
            "msgs": len(msgs),
            "human": [m for m in msgs if not m["author"].get("bot")],
            "reacts": sum(sum(r["count"] for r in m.get("reactions", [])) for m in msgs),
        }
        time.sleep(0.3)
    same_content, same_title = collections.defaultdict(list), collections.defaultdict(list)
    for t in threads:
        b = bodies[t["id"]]
        if not b["msgs"]:  # empty husk: starter message already gone, nothing left for students to read
            drop[t["id"]] = "empty post"
        if b["msgs"]:
            same_content[(t["channel"], b["text"] if not b["repos"] else
                          hashlib.sha1(",".join(b["repos"]).encode()).hexdigest())].append(t["id"])
        if t["name"].startswith(EVERGREEN):
            same_title[(t["channel"], re.sub(r"·.*$", "", t["name"]).strip())].append(t["id"])
    for groups, why in ((same_content, "identical content"), (same_title, "repeat of a one-time post")):
        for ids in groups.values():
            for tid in sorted(ids, key=int)[:-1]:  # keep the newest
                drop.setdefault(tid, why)
    return {tid: why for tid, why in drop.items() if not (bodies[tid]["human"] or bodies[tid]["reacts"])}


def main() -> int:
    guild = enroll._fail_closed_guild()
    threads = feed_threads(guild)
    by_id = {t["id"]: t for t in threads}
    drop = duplicates(threads)
    for tid, why in sorted(drop.items(), key=lambda kv: int(kv[0])):
        t = by_id[tid]
        print(f"  {'delete' if APPLY else 'would delete'}  {t['channel']:<26} {why:<26} {t['name'][:56]}")
    if not APPLY:
        print(f"{len(drop)} duplicate thread(s) of {len(threads)} — dry run, nothing deleted. Re-run with --apply.")
        return 0
    hooks, gone, failed = hooks_by_channel(), 0, []
    for tid in drop:
        try:
            delete_thread(hooks.get(by_id[tid]["parent_id"]), tid)
            gone += 1
        except urllib.error.HTTPError as e:
            failed.append((by_id[tid]["channel"], by_id[tid]["name"][:40], e.code))
        time.sleep(0.6)
    print(f"deleted {gone} duplicate thread(s); {len(threads) - gone} kept. "
          f"Threads with student replies or reactions are never deleted.")
    for ch, name, code in failed:
        print(f"  could not delete ({code}): {ch} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
