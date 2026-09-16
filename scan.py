#!/usr/bin/env python3
"""
scan.py — layer 2: does the repo's CODE do what malware does? Shallow-clones a repo and runs Semgrep with the
malware-behavior ruleset (semgrep-rules/malware.yml) plus the public p/security-audit rules at ERROR severity.

  python scan.py owner/repo [...]   # scan and print verdicts
  python scan.py --index            # scan every index repo not yet scanned (cache 30 days), mark failures in vet_cache

A hit on any malware rule fails the repo (recorded in vet_cache.json as {"ok": false, "hard": ["semgrep: …"]}) so
project_scout.py's post-time gate and the weekly prune both honor it. Repos over MAX_KB are skipped (not failed).
Needs: git, semgrep (pip install semgrep), GITHUB_TOKEN optional. Clones go to a temp dir and are deleted.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

CACHE, VET_CACHE, INDEX = "scan_cache.json", "vet_cache.json", "index.json"
RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "semgrep-rules", "malware.yml")
MAX_KB = 60_000           # skip huge repos (they are established projects anyway; the vetter handles them)
TIMEOUT = 240             # seconds per repo, clone + scan
MALWARE_PREFIX = "tldp."  # rule ids from our own ruleset; a hit here is a hard fail


def scan_repo(full_name: str, size_kb: int | None = None) -> dict:
    """Return {"ok": bool|None, "hits": [rule ids], "findings": int, "checked": date}. None = skipped/unknown."""
    if size_kb and size_kb > MAX_KB:
        return {"ok": None, "hits": [], "findings": 0, "note": f"skipped: {size_kb} KB > {MAX_KB} KB", "checked": date.today().isoformat()}
    tmp = tempfile.mkdtemp(prefix="scout-scan-")
    try:
        clone = subprocess.run(["git", "clone", "--depth", "1", "--quiet", "--config", "core.longpaths=true",
                                f"https://github.com/{full_name}.git", tmp], capture_output=True, text=True, timeout=120)
        if clone.returncode != 0:
            return {"ok": None, "hits": [], "findings": 0, "note": "clone failed: " + clone.stderr.strip()[-120:], "checked": ""}
        shutil.rmtree(os.path.join(tmp, ".git"), ignore_errors=True)
        r = subprocess.run(["semgrep", "scan", "--config", RULES, "--config", "p/security-audit", "--severity", "ERROR",
                            "--json", "--quiet", "--timeout", "30", "--max-target-bytes", "1000000", "--metrics", "off", tmp],
                           capture_output=True, text=True, timeout=TIMEOUT, encoding="utf-8", errors="replace")
        try:
            out = json.loads(r.stdout or "{}")
        except ValueError:
            return {"ok": None, "hits": [], "findings": 0, "note": "semgrep output unreadable", "checked": ""}
        results = out.get("results", [])
        hits = sorted({x["check_id"].split(".")[-1] if MALWARE_PREFIX not in x["check_id"] else x["check_id"][x["check_id"].index(MALWARE_PREFIX):]
                       for x in results if MALWARE_PREFIX in x["check_id"]})
        return {"ok": not hits, "hits": hits, "findings": len(results), "checked": date.today().isoformat(),
                "sample": [f"{os.path.relpath(x['path'], tmp)}:{x['start']['line']} {x['check_id'].split('.')[-1]}" for x in results[:5]]}
    except subprocess.TimeoutExpired:
        return {"ok": None, "hits": [], "findings": 0, "note": "timeout", "checked": ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load(path: str) -> dict:
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def scan_index() -> int:
    idx, cache, vet = load(INDEX), load(CACHE), load(VET_CACHE)
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    cache = {k: v for k, v in cache.items() if v.get("checked", "") >= cutoff}
    rows = {r["full_name"]: r for rows in idx.get("keys", {}).values() for r in rows}
    todo = [n for n in rows if n not in cache and vet.get(n, {}).get("ok") is not False]  # don't waste clones on vet failures
    print(f"{len(rows)} index repos · {len(todo)} to scan · {len(cache)} cached")
    failed = 0
    for i, n in enumerate(todo, 1):
        v = scan_repo(n, rows[n].get("size"))
        if v.get("ok") is None and not v.get("checked"):
            continue  # transient: retry next time
        cache[n] = v
        if v["ok"] is False:
            failed += 1
            print(f"  FAIL {n}: {', '.join(v['hits'])}")
            vet[n] = {"ok": False, "hard": ["semgrep: " + ", ".join(v["hits"])], "soft": [], "stars": rows[n].get("stargazers_count", 0), "checked": date.today().isoformat()}
        if i % 10 == 0:
            print(f"  {i}/{len(todo)}")
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=0)
            json.dump(vet, open(VET_CACHE, "w", encoding="utf-8"), indent=0)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=0)
    json.dump(vet, open(VET_CACHE, "w", encoding="utf-8"), indent=0)
    bad = {n for n, v in vet.items() if v.get("ok") is False}
    removed = 0
    for key, rs in idx.get("keys", {}).items():
        keep = [r for r in rs if r["full_name"] not in bad]
        removed += len(rs) - len(keep); idx["keys"][key] = keep
    json.dump(idx, open(INDEX, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    print(f"semgrep: {failed} new failures · {removed} index rows removed")
    return 0


if __name__ == "__main__":
    if "--index" in sys.argv:
        raise SystemExit(scan_index())
    for n in sys.argv[1:]:
        print(n, json.dumps(scan_repo(n), indent=1))
