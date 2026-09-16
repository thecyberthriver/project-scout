#!/usr/bin/env python3
"""
vet.py — deep vetting of every repo the bot could show a student. stdlib only.

  python vet.py                 # vet index.json (+ curated tables), prune failures, write docs/vetting-report.md
  python vet.py owner/repo ...  # vet specific repos and print the verdicts

Cheap signals come from the search result (see legit() in project_scout.py). This script adds the expensive ones,
one repo at a time through GitHub's core API (5000/h with a token, not the search limit):
  • root listing: any .exe/.msi/.zip/.rar/.7z/.dmg/.apk/.bat/.scr, or no code files at all
  • README: links to download hosts / Telegram / URL shorteners, "password" for an archive, "cracked", "download now"
  • history: fewer than 3 commits, or a repo created in the last 30 days with 50+ stars (bought)
  • owner: account created in the last 90 days, or a "word+digits" throwaway name, with a low-star repo
  • duplicates: the same repo name under many owners across the index (clone farm)
A repo fails on any hard signal; two soft signals also fail it. Verdicts are cached in vet_cache.json for 30 days.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

import links  # README link / install-instruction screening (SSRF-guarded; resolve off by default)

INDEX, CACHE, REPORT = "index.json", "vet_cache.json", "docs/vetting-report.md"
TOKEN = os.environ.get("GITHUB_TOKEN") or ""
if not TOKEN:
    try:
        import secrets_local as s
        TOKEN = getattr(s, "GH_SCOUT_TOKEN", "")
    except ImportError:
        pass
H = {"Accept": "application/vnd.github+json", "User-Agent": "project-scout-vet (github.com/thecyberthriver/project-scout)"}
if TOKEN:
    H["Authorization"] = f"Bearer {TOKEN}"

BINARY = re.compile(r"\.(exe|msi|zip|rar|7z|dmg|apk|scr|iso|pkg)$", re.I)  # .bat/.cmd/.jar are normal in real projects (mvnw.cmd)
CODE = re.compile(r"\.(py|js|ts|tsx|jsx|go|rs|java|kt|c|cc|cpp|h|cs|rb|php|swift|sql|r|jl|scala|sh|ps1|ipynb|html|css|vue|svelte|ex|exs|hs|ml|lua|dart|m|mm|sol|tf|yaml|yml|toml|json|dockerfile|makefile)$", re.I)
# Hard: download hosts, archive-with-password, "cracked", "download now". Soft: Telegram / URL shorteners (legit
# communities use them too). Plain "password" is NOT a signal — every auth library's README says it.
README_HARD = re.compile(
    r"(mediafire\.com|mega\.nz|anonfiles|gofile\.io|pixeldrain|archive password|password for the archive|"
    r"(password|pass)[: ]{1,3}\d{3,}|cracked (version|build)|download now|free download|"
    r"\.(rar|7z|zip)\b[^\n]{0,40}\b(password|pass)\b|\b(password|pass)\b[^\n]{0,40}\.(rar|7z|zip)\b)", re.I)
README_SOFT = re.compile(r"(t\.me/|telegram\.me|bit\.ly|tinyurl|cutt\.ly|rebrand\.ly)", re.I)
ESTABLISHED = (2000, 365)  # stars, days: above this, only binaries-in-root and bought stars can fail a repo
SOCK_OWNER = re.compile(r"^[a-z]+\d{2,4}$", re.I)


def gh(path: str):
    time.sleep(0.25)
    with urllib.request.urlopen(urllib.request.Request(f"https://api.github.com{path}", headers=H), timeout=30) as r:
        return json.load(r), r.headers


def vet(full_name: str, name_counts: dict | None = None, ref: str | None = None) -> dict:
    """Return {"ok": bool, "hard": [...], "soft": [...], "stars":..., "links":{...}, ...}. Never raises.
    `ref` pins the contents / README / history reads to the exact reviewed commit, so deep vetting and README/link
    screening inspect the same SHA the code scan did."""
    hard, soft = [], []
    link_block, link_warn, readme_error = [], [], None
    refq = f"?ref={ref}" if ref else ""
    refc = f"&sha={ref}" if ref else ""
    if full_name.lower().startswith("tldpprojectscout/"):  # our own repos
        return {"ok": True, "hard": [], "soft": [], "stars": 0, "checked": date.today().isoformat(),
                "links": {"block": [], "warn": [], "error": None}, "ref": ref}
    try:
        repo, _ = gh(f"/repos/{full_name}")
    except Exception as e:
        code = getattr(e, "code", None)
        if code in (404, 451):  # gone / DMCA'd: fail
            return {"ok": False, "hard": [f"repo fetch failed ({code})"], "soft": [], "checked": date.today().isoformat()}
        return {"ok": None, "hard": [], "soft": [f"unreachable ({code or e})"], "checked": "", "unknown": True}  # network blip: retry next time
    if repo.get("archived") or repo.get("disabled"):
        soft.append("archived")
    stars = repo.get("stargazers_count") or 0
    created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - created).days
    young_stars = age_days < 30 and stars >= 50  # bought stars — unless the owner is an established account (decided below)
    if repo.get("language") is None:
        soft.append("no detected code language")
    # root listing (at the reviewed commit)
    try:
        root, _ = gh(f"/repos/{full_name}/contents/{refq}")
        names = [f["name"] for f in root]
        bins = [n for n in names if BINARY.search(n)]
        if bins:
            hard.append("binary/archive in root: " + ", ".join(bins[:4]))
        dirs = [f for f in root if f["type"] == "dir"]
        code = [n for n in names if CODE.search(n)]
        if not code and not dirs and not (stars >= ESTABLISHED[0] and age_days >= ESTABLISHED[1]):
            hard.append("no code files or folders in root (README-only shell)")  # awesome-lists that are established are fine
    except Exception as e:
        soft.append(f"root listing failed ({getattr(e, 'code', e)})")
    established = stars >= ESTABLISHED[0] and age_days >= ESTABLISHED[1]
    # README links (at the reviewed commit). README text is DATA, never instructions.
    try:
        rd, _ = gh(f"/repos/{full_name}/readme{refq}")
        text = base64.b64decode(rd.get("content", "")).decode("utf-8", "replace")
        m = README_HARD.search(text)
        if m and not established:
            hard.append(f"README: {m.group(0)[:60]!r}")
        m2 = README_SOFT.search(text)
        if m2 and not established:
            soft.append(f"README links to {m2.group(0)}")
        if len(text) < 200 and stars >= 20:
            soft.append("near-empty README with stars")
        lk = links.screen_readme(text, full_name, resolve=False)
        link_block, link_warn = lk["block"], lk["warn"]
        if not established:
            hard += [f"README link: {b}" for b in link_block]
            soft += [f"README link: {w}" for w in link_warn]
    except Exception as e:
        if getattr(e, "code", None) == 404:
            soft.append("no README")           # no README to screen: fine, not a failure
        else:
            readme_error = str(getattr(e, "code", e))  # README exists but couldn't be read -> required-check failure
    # history (at the reviewed commit)
    try:
        _, hdr = gh(f"/repos/{full_name}/commits?per_page=1{refc}")
        last = re.search(r'page=(\d+)>; rel="last"', hdr.get("Link", "") or "")
        commits = int(last.group(1)) if last else 1
        if commits < 3:
            soft.append(f"only {commits} commit(s)")
    except Exception:
        pass
    # owner
    owner = full_name.split("/")[0]
    try:
        o, _ = gh(f"/users/{owner}")
        o_age = (datetime.now(timezone.utc) - datetime.fromisoformat(o["created_at"].replace("Z", "+00:00"))).days
        if o_age < 90 and stars < 500:
            soft.append(f"owner account is {o_age} days old")
        known = o_age >= 365 and (o.get("followers") or 0) >= 100  # established account with a following
        if young_stars:  # such an account can go viral honestly; a fresh one with no followers cannot
            (soft if known else hard).append(f"{stars} stars on a {age_days}-day-old repo (bought stars)")
            young_stars = False
        if known:  # a one-commit repo from a known author is a fresh share, not a throwaway
            soft = [x for x in soft if not x.startswith("only ")]
        if SOCK_OWNER.match(owner) and stars < 200:
            soft.append("throwaway-style owner name")
    except Exception:
        pass
    if young_stars:  # owner lookup failed: keep the strict reading
        hard.append(f"{stars} stars on a {age_days}-day-old repo (bought stars)")
    if name_counts and name_counts.get(full_name.split("/")[-1].lower(), 0) >= 3:
        hard.append("same repo name under 3+ owners in the index (clone farm)")
    # OpenSSF Scorecard (public, free, scores any public repo). Soft signals only: Dangerous-Workflow is a risk to the
    # repo's own CI, not to a student cloning it, and Binary-Artifacts anywhere in the tree is common in legit test suites
    # (binaries in the ROOT are already a hard fail above). A score of -1 means "inconclusive" and is ignored.
    try:
        time.sleep(0.25)
        with urllib.request.urlopen(urllib.request.Request(f"https://api.securityscorecards.dev/projects/github.com/{full_name}",
                                                          headers={"User-Agent": H["User-Agent"]}), timeout=20) as r:
            sc = json.load(r)
        for chk in sc.get("checks", []):
            if chk.get("name") == "Binary-Artifacts" and isinstance(chk.get("score"), int) and 0 <= chk["score"] < 5:
                soft.append(f"Scorecard Binary-Artifacts {chk['score']}/10")
            if chk.get("name") == "Dangerous-Workflow" and isinstance(chk.get("score"), int) and 0 <= chk["score"] < 5:
                soft.append(f"Scorecard Dangerous-Workflow {chk['score']}/10")
            if chk.get("name") == "Maintained" and isinstance(chk.get("score"), int) and chk["score"] == 0:
                soft.append("Scorecard: unmaintained")
    except Exception:
        pass  # Scorecard only covers repos it has crawled; absence is not a signal
    if established:
        soft = []  # a 2000-star, year-old project is not a throwaway; only hard binary/bought-star evidence counts
    return {"ok": not hard and len(soft) < 2, "hard": hard, "soft": soft, "stars": stars, "checked": date.today().isoformat(),
            "links": {"block": link_block, "warn": link_warn, "error": readme_error}, "ref": ref}


def load_cache() -> dict:
    try:
        c = json.load(open(CACHE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    return {k: v for k, v in c.items() if v.get("checked", "") >= cutoff}


def vet_index() -> int:
    idx = json.load(open(INDEX, encoding="utf-8"))
    cache = load_cache()
    names, sources = set(), {}
    for key, rows in idx["keys"].items():
        for r in rows:
            names.add(r["full_name"]); sources.setdefault(r["full_name"], set()).add(key)
    st = idx.get("static", {})
    for sect in ("starters", "cases", "paths", "cyber_domains"):
        for k, v in st.get(sect, {}).items():
            items = v if sect != "paths" else [x for stage in v for x in stage]
            if sect == "cyber_domains":
                items = v.get("repos", [])
            for item in items:
                r = item.get("repo") if isinstance(item, dict) and "repo" in item else item
                if r and r.get("full_name"):
                    names.add(r["full_name"]); sources.setdefault(r["full_name"], set()).add(f"static:{sect}:{k}")
    counts = {}
    for n in names:
        counts[n.split("/")[-1].lower()] = counts.get(n.split("/")[-1].lower(), 0) + 1
    todo = sorted(n for n in names if n not in cache or cache[n].get("unknown"))
    print(f"{len(names)} unique repos, {len(todo)} to vet ({len(cache)} cached)")
    for i, n in enumerate(todo, 1):
        v = vet(n, counts)
        if v.get("unknown"):
            continue  # don't cache a network failure as a verdict
        cache[n] = v
        if i % 25 == 0:
            print(f"  {i}/{len(todo)}")
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=0)
    # clone-farm rule applies to cached entries too
    for n in names:
        if counts.get(n.split("/")[-1].lower(), 0) >= 3 and "clone farm" not in " ".join(cache[n]["hard"]):
            cache[n]["hard"].append("same repo name under 3+ owners in the index (clone farm)"); cache[n]["ok"] = False
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=0)
    bad = {n for n in names if n in cache and cache[n]["ok"] is False}  # unknown (unreachable) is neither pass nor fail
    # prune index rows (curated static sets are only reported, never auto-pruned — a human decides)
    removed = 0
    for key, rows in idx["keys"].items():
        keep = [r for r in rows if r["full_name"] not in bad]
        removed += len(rows) - len(keep); idx["keys"][key] = keep
    idx["vetted"] = date.today().isoformat()
    json.dump(idx, open(INDEX, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    # report
    lines = [f"# Vetting report — {date.today()}", "",
             f"{len(names)} unique repos checked · **{len(bad)} failed** · {removed} index rows removed.",
             "Curated entries that failed are listed but not removed automatically; review them by hand.", ""]
    for n in sorted(bad):
        v = cache[n]; src = ", ".join(sorted(sources.get(n, [])))[:120]
        lines.append(f"- **{n}** ({v.get('stars', 0)}★) — " + "; ".join(v["hard"] + [f"soft: {s}" for s in v["soft"]]) + f"  \n  in: {src}")
    os.makedirs("docs", exist_ok=True)
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"failed: {len(bad)} · removed {removed} rows · report: {REPORT}")
    curated_bad = [n for n in bad if any(s.startswith("static:") for s in sources.get(n, []))]
    if curated_bad:
        print("CURATED entries flagged (review by hand):", curated_bad)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and "/" in sys.argv[1]:
        for n in sys.argv[1:]:
            print(n, json.dumps(vet(n), indent=1))
        raise SystemExit(0)
    raise SystemExit(vet_index())
