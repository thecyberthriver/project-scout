#!/usr/bin/env python3
"""
enroll.py — roster-gated Discord enrollment WITHOUT a self-typed-name oracle. stdlib only.

The roster (your list of student names) is the *distribution list*, never a thing a student types to prove identity.
Access is granted by two staff-run steps, each one command, no per-repo or per-student approval queue:

  python enroll.py --invites     # one UNIQUE, single-use, 7-day Discord invite per roster entry.
                                 #   Writes roster_invites_local.json (gitignored): name -> invite link. Staff DM each
                                 #   listed student their own link. Single-use = replay-proof; expiring = time-boxed;
                                 #   random code = unpredictable. Only people you invite can join.
  python enroll.py --grant       # give the TLDP Student role to every human member who joined and doesn't have it
                                 #   yet (skips bots and staff). Run it after invites go out; members == roster size.
  python enroll.py --sweep       # same grant, but enumerates members with the member-search endpoint instead of the
                                 #   member list, so it works WITHOUT the privileged Server Members Intent (which
                                 #   makes --grant/--reconcile fail 403 "Missing Access"). Slower; safe to re-run.
  python enroll.py --reconcile   # counts only: roster size vs current members vs students granted. No names printed.
  python enroll.py --self-check  # offline checks of the roster-loading and redaction logic (no network).

Security notes: the roster lives ONLY in roster_local.json (gitignored) and is never printed, logged, or sent to a
service. /verify does NOT check names (that oracle was removed). This is the low-maintenance option that needs no
external integration; the SSO / signed-token options are documented in docs/SCREENING.md and need your go-ahead.
Never run against a live server without approval.
"""
import json
import os
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://discord.com/api/v10"
UA = "project-scout-enroll (github.com/tldpprojectscout/project-scout, 1.0)"
ROSTER_FILE = "roster_local.json"          # gitignored; a JSON list of names, or [{"name": "...", "email": "..."}]
INVITES_FILE = "roster_invites_local.json"  # gitignored output; name -> invite; never committed, never printed
INVITE_MAX_AGE = 7 * 86400
STUDENT_ROLE = "TLDP Student"
STAFF_ROLE = "TLDP Staff"

try:
    import secrets_local as _s
except ImportError:
    _s = None
_env = lambda k: os.environ.get(k) or getattr(_s, k, "")  # noqa: E731


def api(method, path, body=None):
    token = _env("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN not set (secrets_local.py or env). Refusing to run.")
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bot {token}", "Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r) if r.status != 204 else None


def load_roster(path: str = ROSTER_FILE) -> list[str]:
    """A list of student names. Accepts ['A B', ...] or [{'name': 'A B'}, ...]. Never printed."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for e in data:
        name = e.get("name") if isinstance(e, dict) else e
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def redact(name: str) -> str:
    """A non-identifying tag for logs: initials + length, never the name. e.g. 'A—h·7'."""
    parts = [p for p in name.split() if p]
    initials = "".join(p[0].upper() for p in parts) or "?"
    return f"{initials}·{len(name)}"


def needs_grant(member: dict, student_id: str, staff_id: str | None) -> bool:
    """True for a human member who should get the Student role. Bots, staff and the already-granted are skipped."""
    if member.get("user", {}).get("bot"):
        return False
    roles = member.get("roles", [])
    if staff_id and staff_id in roles:
        return False
    return student_id not in roles


def _fail_closed_guild() -> str:
    g = _env("DISCORD_GUILD_ID")
    if not g:
        raise SystemExit("DISCORD_GUILD_ID not set. Refusing to run (fail closed).")
    return g


def make_invites() -> int:
    guild = _fail_closed_guild()
    roster = load_roster()
    welcome = next((c for c in api("GET", f"/guilds/{guild}/channels") if c["name"] == "welcome"), None)
    if not welcome:
        raise SystemExit("no #welcome channel; run discord_setup.py first")
    mapping = {}
    for name in roster:
        inv = api("POST", f"/channels/{welcome['id']}/invites",
                  {"max_age": INVITE_MAX_AGE, "max_uses": 1, "unique": True, "temporary": False})
        mapping[name] = {"invite": f"https://discord.gg/{inv['code']}", "code": inv["code"], "expires_in_days": 7}
    with open(INVITES_FILE, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)
    print(f"created {len(mapping)} single-use 7-day invites → {INVITES_FILE} (gitignored). "
          f"Distribute each student their own link privately. Names/links were not printed.")
    return 0


def grant_students() -> int:
    guild = _fail_closed_guild()
    roles = {r["name"]: r for r in api("GET", f"/guilds/{guild}/roles")}
    if STUDENT_ROLE not in roles:
        raise SystemExit(f"role {STUDENT_ROLE!r} missing; run discord_setup.py first")
    student_id, staff_id = roles[STUDENT_ROLE]["id"], roles.get(STAFF_ROLE, {}).get("id")
    granted = skipped = 0
    after = "0"
    while True:
        members = api("GET", f"/guilds/{guild}/members?limit=1000&after={after}")
        if not members:
            break
        for m in members:
            if not needs_grant(m, student_id, staff_id):
                skipped += 1
                continue
            api("PUT", f"/guilds/{guild}/members/{m['user']['id']}/roles/{student_id}")
            granted += 1
        after = members[-1]["user"]["id"]
        if len(members) < 1000:
            break
    print(f"granted {STUDENT_ROLE} to {granted} member(s); skipped {skipped} (bots/staff/already-granted). "
          f"Cross-check: member count should equal your roster size.")
    return 0


def _search(guild: str, query: str) -> list:
    """Member search — unlike the member list, it does NOT need the Server Members Intent. Backs off on 429."""
    for _ in range(6):
        try:
            return api("GET", f"/guilds/{guild}/members/search?query={urllib.parse.quote(query)}&limit=100")
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(float(json.loads(e.read()).get("retry_after", 2)) + 0.5)
    return []


def sweep_students() -> int:
    """--grant without the privileged intent: enumerate members by name prefix, grant whoever is missing the role."""
    guild = _fail_closed_guild()
    roles = {r["name"]: r for r in api("GET", f"/guilds/{guild}/roles")}
    if STUDENT_ROLE not in roles:
        raise SystemExit(f"role {STUDENT_ROLE!r} missing; run discord_setup.py first")
    student_id, staff_id = roles[STUDENT_ROLE]["id"], roles.get(STAFF_ROLE, {}).get("id")
    # ponytail: one search per leading character, 100 hits each — fine for a cohort server, misses anyone whose
    # username, nick and display name ALL start with a non-alphanumeric, and truncates a prefix with >100 members.
    # Upgrade path: enable the Server Members Intent and use --grant, which pages the real member list.
    found = {}
    for q in string.ascii_lowercase + string.digits:
        for m in _search(guild, q):
            found[m["user"]["id"]] = m
        time.sleep(1.2)
    granted = 0
    for uid, m in found.items():
        if needs_grant(m, student_id, staff_id):
            api("PUT", f"/guilds/{guild}/members/{uid}/roles/{student_id}")
            granted += 1
    print(f"swept {len(found)} member(s) found by search; granted {STUDENT_ROLE} to {granted}. "
          f"Re-runnable: already-granted members, bots and staff are skipped.")
    return 0


def reconcile() -> int:
    guild = _fail_closed_guild()
    roster_n = len(load_roster()) if os.path.exists(ROSTER_FILE) else 0
    roles = {r["name"]: r["id"] for r in api("GET", f"/guilds/{guild}/roles")}
    members, after = [], "0"
    while True:
        page = api("GET", f"/guilds/{guild}/members?limit=1000&after={after}")
        if not page:
            break
        members += page
        after = page[-1]["user"]["id"]
        if len(page) < 1000:
            break
    humans = [m for m in members if not m["user"].get("bot")]
    students = [m for m in humans if roles.get(STUDENT_ROLE) in m.get("roles", [])]
    print(f"roster: {roster_n} · human members: {len(humans)} · students granted: {len(students)}")
    if roster_n and len(humans) > roster_n:
        print(f"⚠️ {len(humans) - roster_n} more members than roster entries — review the member list.")
    return 0


def self_check() -> int:
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "r.json")
    json.dump(["Ada Lovelace", {"name": "Alan Turing", "email": "x@y"}, "", {"name": ""}, 5], open(p, "w"))
    r = load_roster(p)
    assert r == ["Ada Lovelace", "Alan Turing"], r
    assert redact("Ada Lovelace") == "AL·12", redact("Ada Lovelace")
    assert redact("") == "?·0"
    S, F = "role_student", "role_staff"
    assert needs_grant({"user": {"id": "1"}, "roles": []}, S, F)                      # plain member: grant
    assert not needs_grant({"user": {"id": "1"}, "roles": [S]}, S, F)                 # already a student
    assert not needs_grant({"user": {"id": "1"}, "roles": [F]}, S, F)                 # staff
    assert not needs_grant({"user": {"id": "1", "bot": True}, "roles": []}, S, F)     # bot
    assert needs_grant({"user": {"id": "1"}, "roles": []}, S, None)                   # server with no staff role
    print("enroll self-check ok")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        raise SystemExit(self_check())
    if "--invites" in sys.argv:
        raise SystemExit(make_invites())
    if "--grant" in sys.argv:
        raise SystemExit(grant_students())
    if "--sweep" in sys.argv:
        raise SystemExit(sweep_students())
    if "--reconcile" in sys.argv:
        raise SystemExit(reconcile())
    print(__doc__)
