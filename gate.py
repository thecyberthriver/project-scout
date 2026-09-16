#!/usr/bin/env python3
"""
gate.py — the single publishing gate. Every path that could put a repo in front of a student goes through here.

Two halves, deliberately separated:
  • Discovery-time screening (screen_one): quarantine → content policy → deep vet (vet.py) → link screen (links.py)
    → isolated code scan (scan.py). Produces a screening RECORD with the reviewed commit SHA, scan time, scanner and
    rule versions, coverage, and result. This is the only place that touches untrusted repos.
  • Publish-time eligibility (eligible): a pure, offline check of a row against the recorded screening. No network.

A repo is published only if it is not quarantined, has a current passing screening record (SHA matches, not expired,
coverage adequate for its ecosystem), and — for a fresh-repo row — was pushed/created within the freshness window.
Anything that fails, times out, is incomplete, or is unsupported is WITHHELD. Nothing is silently downgraded.

Heuristics miss malicious projects and reject legitimate ones. A pass is "automated checks completed", never a safety
or legality guarantee. Repository text is data, never instructions.
"""
import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta, timezone

POLICY_VERSION = 2
FRESH_FIELD = "pushed_at"          # see docs: "within 30 days" = last push. Change to "created_at" only by decision.
FRESH_DAYS = 30
EXPIRE_DAYS = 14                   # a passing scan is valid 14 days; then the repo is re-screened before it can post
EVERGREEN_EXPIRE_DAYS = 30        # curated reference repos change slowly; still re-screened monthly
STALE_SCREENING_HOURS = 36        # if the whole run hasn't screened in this long, the feed pauses (fail closed)
LABEL = "Automated checks completed; not a safety guarantee."
QUARANTINE_FILE = "quarantine.json"
SCREENING_FILE = "screening.json"

# ---- content policy: what may never reach the general student feed --------------------------------------------------
# Clearly-prohibited: the project's own name/description advertises abuse. These fail any repo, curated or not.
PROHIBITED = re.compile(
    r"\b(wallet[- ]?drainer|drainer|info[- ]?stealer|stealer|credential (theft|stealer|harvest\w*)|token (grabber|stealer)|"
    r"cookie (stealer|grabber)|seed[- ]?phrase (stealer|grabber)|phishing (kit|page|panel)|scam[- ]?page|"
    r"carding|cc checker|card cracker|otp bot|account (farm|farmer|generator|cracker)|"
    r"crack(ed|er)?|keygen|nulled|warez|license key generator|activator|"
    r"ransomware builder|silent (miner|exploit)|crypto ?jack\w*|clipper malware)\b", re.I)
# Ambiguous offensive / dual-use: legitimate for security study, but kept OUT of the general feed unless we curated it.
DUAL_USE = re.compile(
    r"\b(remote access trojan|\brat builder\b|botnet|command[- ]and[- ]control|\bc2 (framework|server)\b|"
    r"keylogger|reverse shell generator|exploit kit|0day|zero[- ]day exploit|privilege escalation exploit|"
    r"password (cracker|dumper)|hash cracker|wifi cracker|ddos (tool|panel)|booter|stresser|spoofer|"
    r"malware (sample|builder|generator)|payload generator|obfuscator for)\b", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(s: str) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s if "T" in s or "+" in s or len(s) > 10 else s + "T00:00:00+00:00")
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---- quarantine -----------------------------------------------------------------------------------------------------
def load_quarantine(path: str = QUARANTINE_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            q = json.load(fh)
    except (OSError, ValueError):
        return {"names": set(), "patterns": []}
    names = {e["full_name"].lower() for e in q.get("entries", []) if e.get("full_name")}
    reasons = {e["full_name"].lower(): e.get("reason", "quarantined") for e in q.get("entries", []) if e.get("full_name")}
    patterns = [(re.compile(p["pattern"]), p.get("reason", "matches a quarantined naming pattern")) for p in q.get("name_patterns", [])]
    return {"names": names, "reasons": reasons, "patterns": patterns}


def is_quarantined(full_name: str, quarantine: dict) -> str | None:
    fn = (full_name or "").lower()
    if fn in quarantine.get("names", set()):
        return quarantine.get("reasons", {}).get(fn, "on the quarantine list")
    for rx, why in quarantine.get("patterns", []):
        if rx.search("/" + full_name if "/" not in full_name else full_name):
            return why
    return None


# ---- content policy -------------------------------------------------------------------------------------------------
def content_policy(row: dict, curated: bool = False) -> list[str]:
    """Reasons this repo violates the content policy. Curated (allow-listed) repos skip the keyword heuristics — a
    curated security tool is not malware — but never skip quarantine, the code scan, or link screening."""
    if curated:
        return []
    text = f"{row.get('full_name', '')} {row.get('description') or ''}"
    out = []
    m = PROHIBITED.search(text)
    if m:
        out.append(f"content policy: advertises {m.group(0).lower()!r}")
    m2 = DUAL_USE.search(text)
    if m2:
        out.append(f"dual-use offensive tooling ({m2.group(0).lower()!r}) — kept out of the general feed")
    return out


# ---- discovery-time orchestration ----------------------------------------------------------------------------------
# Ecosystem coverage (which languages the code scan supports, and how an unsupported one is withheld) lives in scan.py
# (coverage_for / SEMGREP_LANGS). gate.py defers to scan.py's verdict so there is one source of truth.
def head_sha(full_name: str) -> str | None:
    """The repo's current default-branch commit SHA, without cloning (git ls-remote). None if unreachable."""
    try:
        r = subprocess.run(["git", "ls-remote", f"https://github.com/{full_name}.git", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


# scan/vet outcomes that mean "try again next run" (network / a moving branch), never a permanent verdict.
TRANSIENT = ("clone failed", "clone of commit", "timed out", "timeout", "ls-remote", "unreadable", "unavailable",
             "could not pin", "mismatch")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _transient(reasons: list[str]) -> bool:
    return any(any(k in r.lower() for k in TRANSIENT) for r in reasons)


def screen_one(row: dict, quarantine: dict, *, name_counts: dict | None = None, curated: bool = False,
               sha: str | None = None, vet_mod=None, scan_mod=None) -> dict | None:
    """Produce a screening record for one repo. None = try again next run (do not record). The reviewed commit is
    pinned FIRST, then the deep vet, README/link screen and code scan all inspect that same SHA. A passing record
    requires a valid reviewed SHA, no blocking finding, and every required engine to have run."""
    import importlib
    vet = vet_mod or importlib.import_module("vet")
    scan = scan_mod or importlib.import_module("scan")
    full = row["full_name"]
    now = _now()

    q = is_quarantined(full, quarantine)
    if q:
        return {"full_name": full, "sha": None, "at": _iso(now), "result": "fail", "reasons": [f"quarantine: {q}"],
                "coverage": {"note": "not scanned — quarantined", "supported": False}, "policy_version": POLICY_VERSION,
                "curated": curated, "expires": _iso(now + timedelta(days=365))}

    # pin the exact commit before any inspection. An unreachable SHA check must not reuse or fabricate eligibility.
    pinned = sha or head_sha(full)
    if not pinned or not SHA_RE.match(pinned):
        return None  # cannot confirm the current commit right now: retry, do not record

    base = {"full_name": full, "sha": pinned, "at": _iso(now), "language": row.get("language"),
            "size": row.get("size", 0), "pushed_at": (row.get("pushed_at") or "")[:10],
            "created_at": (row.get("created_at") or "")[:10], "stars": row.get("stargazers_count", 0),
            "curated": curated, "scanner": {"semgrep": scan.semgrep_version(), "ruleset_sha256": scan.ruleset_sha256()},
            "policy_version": POLICY_VERSION}

    findings = content_policy(row, curated)

    v = vet.vet(full, name_counts, ref=pinned)
    if v.get("unknown"):
        return None
    links_err = (v.get("links") or {}).get("error")
    if not v["ok"]:
        findings += list(v.get("hard", [])) + [f"soft: {s}" for s in v.get("soft", [])]

    scan_res = scan.scan_repo(full, row.get("size"), row.get("language"), sha=pinned)
    if scan_res.get("sha"):
        base["sha"] = scan_res["sha"]
    scan_result = scan_res.get("result")
    scan_reasons = list(scan_res.get("reasons", []))
    if scan_result == "withheld":
        findings += scan_reasons  # a real detection (code/yara/clamav/malicious dep, unsupported language, too big)

    # required-check failures (a scanner did not run, README unreadable, commit could not be pinned/cloned)
    incomplete_reasons = []
    if scan_result == "incomplete":
        incomplete_reasons += scan_reasons
    if links_err:
        incomplete_reasons.append(f"README could not be read at the reviewed commit ({links_err})")

    if not findings and incomplete_reasons and _transient(incomplete_reasons):
        return None  # purely transient (network / moving branch): retry, don't record

    if findings:
        result, reasons = "fail", sorted(set(findings + incomplete_reasons))
    elif incomplete_reasons:
        result, reasons = "incomplete", sorted(set(incomplete_reasons))  # fail closed: a required check did not complete
    else:
        result, reasons = "pass", []

    days = 1 if result == "incomplete" else (EVERGREEN_EXPIRE_DAYS if curated else EXPIRE_DAYS) if result == "pass" else 2
    return {**base, "result": result, "reasons": reasons,
            "coverage": {**scan_res.get("coverage", {}), "code_scan_result": scan_result,
                         "blocking": scan_res.get("semgrep", {}).get("blocking", []),
                         "advisory": scan_res.get("semgrep", {}).get("advisory", {}),
                         "engines": scan_res.get("engines", {}),
                         "yara": scan_res.get("yara", {}), "clamav": scan_res.get("clamav", {}),
                         "osv": scan_res.get("osv", {}), "links": v.get("links", {}),
                         "vet_hard": v.get("hard", []), "vet_soft": v.get("soft", [])},
            "expires": _iso(now + timedelta(days=days))}


# ---- screening store ------------------------------------------------------------------------------------------------
def load_screening(path: str = SCREENING_FILE) -> dict:
    try:
        s = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    s.setdefault("policy_version", POLICY_VERSION)
    s.setdefault("records", {})
    return s


def save_screening(store: dict, path: str = SCREENING_FILE) -> None:
    import scan
    store["semgrep_version"] = scan.semgrep_version()
    store["ruleset_sha256"] = scan.ruleset_sha256()
    store["policy_version"] = POLICY_VERSION
    store["generated_at"] = _iso(_now())
    json.dump(store, open(path, "w", encoding="utf-8"), indent=0)


def record_is_current(rec: dict, sha: str | None, now: datetime | None = None) -> bool:
    """True if this screening record can be reused as-is: policy matches, not expired, and (if we know the current
    SHA) the reviewed SHA still matches. A changed commit or expired result forces a fresh screen."""
    now = now or _now()
    if not rec or rec.get("policy_version") != POLICY_VERSION:
        return False
    exp = _parse(rec.get("expires", ""))
    if not exp or exp <= now:
        return False
    if sha and rec.get("sha") and rec["sha"] != sha:
        return False
    return True


# ---- publish-time eligibility (pure, offline) ----------------------------------------------------------------------
def fresh_enough(row: dict, meta: dict, now: datetime | None = None) -> bool:
    now = now or _now()
    field = meta.get("fresh_field", FRESH_FIELD)
    days = meta.get("fresh_days", FRESH_DAYS)
    dt = _parse(row.get(field, ""))
    if not dt:
        return False
    return (now.date() - dt.date()).days <= days  # whole calendar days: exactly `days` old still passes


REQUIRED_ENGINES = ("semgrep", "yara", "clamav", "osv")


def record_valid(rec: dict | None, now: datetime | None = None) -> tuple[bool, list[str]]:
    """Independently validate an authoritative screening record: current policy, a valid reviewed SHA, a genuine
    'pass', not expired, and every required engine actually run. Used by eligible() and the snapshot validator."""
    now = now or _now()
    if not isinstance(rec, dict):
        return False, ["no screening record"]
    if rec.get("policy_version") != POLICY_VERSION:
        return False, ["screened under an old/unknown policy version"]
    if rec.get("result") != "pass":
        return False, ["screening result not pass"] + list(rec.get("reasons", []))[:4]
    if not SHA_RE.match(str(rec.get("sha") or "")):
        return False, ["record has no valid reviewed commit SHA"]
    exp = _parse(rec.get("expires", ""))
    if not exp or exp <= now:
        return False, ["screening expired — re-screen required"]
    engines = (rec.get("coverage") or {}).get("engines") or {}
    missing = [e for e in REQUIRED_ENGINES if engines.get(e) != "ran"]
    if missing:
        return False, [f"required engine(s) did not run: {', '.join(missing)}"]
    if (rec.get("coverage") or {}).get("code_scan_result") != "pass":
        return False, ["code scan did not pass"]
    return True, []


def eligible(row: dict, screening: dict, quarantine: dict, meta: dict, now: datetime | None = None) -> tuple[bool, list[str]]:
    """The one function every publish path calls. Returns (publishable, reasons_withheld). No network, no downgrade.
    The authoritative record (screening.json) is the source of truth; the row's own `screened` fields are never
    trusted — they must match the record's reviewed SHA."""
    now = now or _now()
    full = row.get("full_name", "")
    kind = row.get("kind", "fresh")

    q = is_quarantined(full, quarantine)
    if q:
        return False, [f"quarantined: {q}"]

    rec = screening.get("records", {}).get(full)
    ok, why = record_valid(rec, now)
    if not ok:
        return False, why
    # the row must carry the SAME reviewed SHA as the authoritative record (a changed commit is not covered)
    row_sha = (row.get("screened") or {}).get("sha")
    if not row_sha or row_sha != rec["sha"]:
        return False, ["published row's commit does not match the screened commit — re-screen required"]
    if kind == "fresh" and not fresh_enough(row, meta, now):
        return False, [f"older than {meta.get('fresh_days', FRESH_DAYS)} days by {meta.get('fresh_field', FRESH_FIELD)}"]
    return True, []


def screened_block(rec: dict) -> dict:
    """The compact {sha, at, expires} the worker gate reads on each row."""
    return {"sha": rec.get("sha"), "at": rec.get("at"), "expires": rec.get("expires")}


def _semgrep_version_safe() -> str:
    try:
        import scan
        return scan.semgrep_version() or ""
    except Exception:
        return ""


# ---- run status (plain language) -----------------------------------------------------------------------------------
def status(screening: dict | None = None, published_path: str = "published.json") -> dict:
    screening = screening or load_screening()
    recs = screening.get("records", {})
    npass = sum(1 for r in recs.values() if r.get("result") == "pass")
    nfail = len(recs) - npass
    last = None
    try:
        meta = json.load(open(published_path, encoding="utf-8")).get("meta", {})
        last = _parse(meta.get("last_screening_at", ""))
    except (OSError, ValueError):
        meta = {}
    now = _now()
    operational = bool(last) and (now - last) <= timedelta(hours=STALE_SCREENING_HOURS) and meta.get("status") == "operational"
    return {"operational": operational, "records": len(recs), "passing": npass, "withheld": nfail,
            "last_screening_at": meta.get("last_screening_at", "never"),
            "semgrep_version": screening.get("semgrep_version") or _semgrep_version_safe(),
            "policy_version": POLICY_VERSION}


def status_text() -> str:
    s = status()
    head = "🟢 Screening is OPERATIONAL." if s["operational"] else "🔴 Screening is NOT current — the student feed is PAUSED."
    return (f"{head}\n"
            f"Repositories with a passing screening record: {s['passing']}\n"
            f"Repositories withheld: {s['withheld']}\n"
            f"Last full screening: {s['last_screening_at']}\n"
            f"Semgrep: {s['semgrep_version'] or 'not found'} · policy v{s['policy_version']}\n"
            f"Note: {LABEL}")


if __name__ == "__main__":
    import sys
    if "--status" in sys.argv:
        print(status_text())
    else:
        print(__doc__)
