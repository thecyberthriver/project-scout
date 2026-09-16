#!/usr/bin/env python3
"""
purge_posts.py — remove repos that failed vetting from messages the bot ALREADY posted.

  python purge_posts.py            # dry run: list what would change
  python purge_posts.py --apply    # edit the Discord posts (via each channel's webhook) and warn on Telegram

Discord: forum starter posts and later replies were sent by the channel webhooks, so the webhook can edit them
(no Manage Threads needed). Every line block mentioning a failed repo is replaced with one "removed" note.
Telegram: bots can't read or edit their own history without message ids, so both bots get a warning that lists the
repos to ignore. Reads failures from vet_cache.json; needs DISCORD_BOT_TOKEN / DISCORD_GUILD_ID / DISCORD_WEBHOOKS
and the Telegram secrets from secrets_local.py or the environment.
"""
import json
import os
import re
import sys
import urllib.request

try:
    import secrets_local as s
except ImportError:
    s = None
env = lambda k: os.environ.get(k) or getattr(s, k, "")  # noqa: E731
TOKEN, GUILD = env("DISCORD_BOT_TOKEN"), env("DISCORD_GUILD_ID")
HOOKS = json.loads(env("DISCORD_WEBHOOKS") or "{}")
UA = "project-scout (github.com/thecyberthriver/project-scout, 1.0)"
APPLY = "--apply" in sys.argv


def api(method, path, body=None, base="https://discord.com/api/v10", auth=True):
    h = {"Content-Type": "application/json", "User-Agent": UA}
    if auth:
        h["Authorization"] = f"Bot {TOKEN}"
    req = urllib.request.Request(f"{base}{path}", method=method, data=json.dumps(body).encode() if body is not None else None, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r) if r.status != 204 else None


def scrub(content: str, bad: set[str]) -> tuple[str, list[str]]:
    """Drop every bullet block (a '•' line plus its indented continuation lines) that names a failed repo."""
    lines, out, hit, i = content.split("\n"), [], [], 0
    while i < len(lines):
        block = [lines[i]]
        j = i + 1
        while j < len(lines) and (lines[j].startswith("  ") or lines[j].startswith("　")) and not lines[j].lstrip().startswith("•"):
            block.append(lines[j]); j += 1
        text = "\n".join(block)
        names = [b for b in bad if b.lower() in text.lower()]
        if names:
            hit += names
            out.append("• ~~removed~~ — this repo failed the TLDP safety vetting (download trap / scam pattern). Do not use it.")
        else:
            out += block
        i = j
    return "\n".join(out), hit


def main() -> int:
    cache = json.load(open("vet_cache.json", encoding="utf-8"))
    bad = {n for n, v in cache.items() if not v.get("ok")}
    print(f"{len(bad)} failed repos in vet_cache.json")
    hook_by_channel = {}
    for key, url in HOOKS.items():
        wid = url.split("/")[-2]
        try:
            hook_by_channel[api("GET", f"/webhooks/{wid}")["channel_id"]] = url
        except Exception as e:
            print(f"webhook {key}: {e}", file=sys.stderr)
    channels = api("GET", f"/guilds/{GUILD}/channels")
    threads = api("GET", f"/guilds/{GUILD}/threads/active")["threads"]
    edits = 0
    targets = []  # (message channel id for reading, webhook url, thread_id or None)
    for t in threads:
        if t["parent_id"] in hook_by_channel:
            targets.append((t["id"], hook_by_channel[t["parent_id"]], t["id"]))
    for c in channels:
        if c["type"] == 0 and c["id"] in hook_by_channel:
            targets.append((c["id"], hook_by_channel[c["id"]], None))
    for chan_id, hook, thread_id in targets:
        try:
            msgs = api("GET", f"/channels/{chan_id}/messages?limit=100")
        except Exception as e:
            print(f"read {chan_id}: {e}", file=sys.stderr); continue
        for m in msgs:
            if not m.get("webhook_id") or not m.get("content"):
                continue
            new, hit = scrub(m["content"], bad)
            if hit:
                print(f"{'EDIT' if APPLY else 'would edit'} message {m['id']} in {chan_id}: removes {sorted(set(hit))}")
                if APPLY:
                    q = f"?thread_id={thread_id}" if thread_id else ""
                    api("PATCH", f"/webhooks/{hook.split('/')[-2]}/{hook.split('/')[-1]}/messages/{m['id']}{q}", {"content": new[:2000]}, auth=False)
                    edits += 1
    print(f"discord: {edits} messages edited" if APPLY else "discord: dry run")
    if APPLY and bad:
        names = sorted(bad)
        text = ("⚠️ Safety notice from Project Scout\n\nThe repos below appeared in earlier drops and have since FAILED our vetting "
                "(README-only shells pointing to downloads, archive passwords, Telegram links, bought stars or wallet-drainer code). "
                "Do not download or run anything from them:\n\n" + "\n".join(f"• {n}" for n in names[:60]) +
                (f"\n…and {len(names) - 60} more" if len(names) > 60 else "") +
                "\n\nEvery repo the bot shows is now checked for these signals before it is posted.")
        for tok, chat in ((env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")), (env("CAMPUS_BOT_TOKEN"), env("CAMPUS_CHAT_ID"))):
            if tok and chat:
                for part in [text[i:i + 3900] for i in range(0, len(text), 3900)]:
                    api("POST", "/sendMessage", {"chat_id": chat, "text": part}, base=f"https://api.telegram.org/bot{tok}", auth=False)
        if HOOKS.get("announcements"):
            api("POST", "", {"content": text[:2000]}, base=HOOKS["announcements"], auth=False)
        print("warnings sent to both Telegram bots and #announcements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
