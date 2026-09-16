#!/usr/bin/env python3
"""
scan.py — static code screening of a third-party repository at a pinned commit. stdlib + git + semgrep.

  python scan.py owner/repo [...]      # scan and print the record (no cache writes)

What it does, in order — and what it never does:
  1. `git ls-remote` pins the default-branch commit SHA (no clone yet).
  2. Shallow clone of that commit into a temp dir with an EMPTY HOME/config: no credential helpers, no hooks
     (core.hooksPath -> empty dir), no LFS smudge, no submodules, blobs over 2 MB skipped, protocol.allow=never
     for anything but https. Nothing in the repository is executed: no install scripts, no build, no tests,
     no workflows. Semgrep is a static parser; --config only, no Pro engine, no autofix.
  3. Notebooks (.ipynb) have their code cells COPIED into sibling .py files so Python rules can read them (no kernel).
  4. Any .semgrepignore in the clone is deleted (a hostile repo must not be able to hide files from the scan).
  5. Semgrep runs with our malware-behaviour rules + p/security-audit + p/secrets, metrics off, per-file timeout,
     total timeout, memory cap, target-size cap. Output is parsed as JSON; matched source text is discarded — only
     rule ids, paths and line numbers are kept, so a committed secret is never copied into a report or a message.
  6. The clone is deleted.

Blocking (documented in docs/SCREENING.md): any hit from semgrep-rules/malware.yml (ids tldp.*) or any p/secrets
finding blocks. p/security-audit findings are advisory counts (vulnerable code is a learning topic, not a student-
safety issue). Timeouts, parse-engine errors, clone failures or an unsupported primary language make the result
"incomplete"/"withheld": the repository is NOT published. Heuristics can miss malicious code and flag benign code.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "semgrep-rules", "malware.yml")
YARA_RULES = os.path.join(HERE, "yara-rules", "malware.yar")
CONFIGS = ["p/security-audit", "p/secrets"]          # registry rulesets (downloaded from semgrep.dev; no code leaves the runner)
MALWARE_PREFIX = "tldp."
YARA_MAX_FILE = 8 * 1024 * 1024                       # skip files bigger than this for the byte-signature scan
ENGINE_TIMEOUT = 180                                  # per-engine wall clock (clamav / osv)
MAX_KB = 60_000                                       # repo size cap (GitHub's size field, KB) — bigger = withheld, not scanned
MAX_CLONE_BYTES = 200 * 1024 * 1024
CLONE_TIMEOUT, SCAN_TIMEOUT, FILE_TIMEOUT = 120, 300, 30
BLOB_LIMIT = "2m"
# Semgrep-parsed languages (GitHub "language" names). Doc-only languages are scanned by the generic (regex) rules only.
SEMGREP_LANGS = {"Python", "JavaScript", "TypeScript", "Java", "Go", "Ruby", "PHP", "C", "C++", "C#", "Kotlin", "Rust", "Scala",
                 "Swift", "Shell", "Dockerfile", "HCL", "Solidity", "Elixir", "Lua", "OCaml", "Dart", "Clojure", "Julia", "R",
                 "JSON", "YAML", "HTML", "Vue", "Jupyter Notebook", "Jsonnet", "Apex", "Cairo", "Lisp", "Scheme", "XML"}
DOC_LANGS = {"Markdown", "TeX", "CSS", "SCSS", "Less", "Makefile", "Batchfile", "Roff", "AsciiDoc", "reStructuredText"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_version = None


def semgrep_version() -> str | None:
    global _version
    if _version is None and shutil.which("semgrep"):
        try:
            _version = subprocess.run(["semgrep", "--version"], capture_output=True, text=True, timeout=60).stdout.strip() or "?"
        except (OSError, subprocess.SubprocessError):
            _version = None
    return _version


def ruleset_sha256() -> str:
    h = hashlib.sha256()
    with open(RULES, "rb") as f:
        h.update(f.read())
    h.update(("|" + ",".join(CONFIGS)).encode())
    return h.hexdigest()


def coverage_for(language: str | None) -> tuple[bool, str]:
    if language in SEMGREP_LANGS:
        return True, "generic + language rules" if language != "Jupyter Notebook" else "notebook code cells extracted to Python"
    if language in DOC_LANGS:
        return True, "documentation repo: generic (regex) rules only"
    return False, f"primary language {language or 'unknown'} is not parsed by Semgrep"


def _iso_env(home: str) -> dict:
    """Minimal environment for git/semgrep: no user config, no credential helpers, no inherited tokens."""
    keep = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "PATHEXT", "LANG", "LC_ALL") if k in os.environ}
    keep.update({"HOME": home, "USERPROFILE": home, "XDG_CONFIG_HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                 "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_ASKPASS": "", "SSH_ASKPASS": "",
                 "SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0", "PYTHONIOENCODING": "utf-8"})
    return keep


def pin_sha(full_name: str, env: dict) -> str | None:
    try:
        r = subprocess.run(["git", "ls-remote", f"https://github.com/{full_name}.git", "HEAD"], capture_output=True, text=True,
                           timeout=45, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (r.stdout.split() or [""])[0]
    return sha if r.returncode == 0 and len(sha) == 40 else None


def clone(full_name: str, tmp: str, env: dict) -> str | None:
    hooks = os.path.join(tmp, "_nohooks"); os.makedirs(hooks, exist_ok=True)
    dest = os.path.join(tmp, "repo")
    args = ["git", "-c", f"core.hooksPath={hooks}", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.required=false", "-c", "filter.lfs.clean=",
            "-c", "core.symlinks=false", "-c", "core.longpaths=true", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
            "-c", "submodule.recurse=false", "-c", "core.fsmonitor=false",
            "clone", "--depth", "1", "--no-tags", "--single-branch", "--no-recurse-submodules", f"--filter=blob:limit={BLOB_LIMIT}", "--quiet",
            f"https://github.com/{full_name}.git", dest]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=CLONE_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return dest


def head_sha(dest: str, env: dict) -> str | None:
    try:
        r = subprocess.run(["git", "-C", dest, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, env=env)
        sha = r.stdout.strip()
        return sha if r.returncode == 0 and len(sha) == 40 else None
    except (OSError, subprocess.SubprocessError):
        return None


def prepare_tree(dest: str) -> dict:
    """Remove .git and .semgrepignore, extract notebook code cells, measure size. Pure file operations."""
    shutil.rmtree(os.path.join(dest, ".git"), ignore_errors=True)
    total, files, notebooks, ignored = 0, 0, 0, 0
    for root, dirs, names in os.walk(dest):
        for n in names:
            p = os.path.join(root, n)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            total += sz; files += 1
            if n == ".semgrepignore":
                try:
                    os.remove(p); ignored += 1
                except OSError:
                    pass
            elif n.lower().endswith(".ipynb") and sz <= 1_000_000:
                try:
                    nb = json.load(open(p, encoding="utf-8"))
                    cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
                    src = "\n\n".join("".join(c.get("source") or []) for c in cells)
                    if src.strip():
                        with open(p + ".py", "w", encoding="utf-8") as f:
                            f.write(src)
                        notebooks += 1
                except (ValueError, OSError, TypeError, UnicodeDecodeError):
                    pass
    return {"bytes": total, "files": files, "notebooks_extracted": notebooks, "semgrepignore_removed": ignored}


def run_semgrep(dest: str, env: dict) -> tuple[dict | None, str | None]:
    cmd = ["semgrep", "scan", "--config", RULES] + [x for c in CONFIGS for x in ("--config", c)] + [
        "--metrics=off", "--disable-version-check", "--json", "--quiet", "--no-git-ignore",
        "--timeout", str(FILE_TIMEOUT), "--timeout-threshold", "3", "--max-target-bytes", "1000000", "--max-memory", "2000",
        "--jobs", "2", "--exclude", "*.min.js", "--exclude", "*.map", dest]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=SCAN_TIMEOUT, env=env, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as e:
        return None, f"semgrep not runnable: {e.__class__.__name__}"
    try:
        return json.loads(r.stdout or "{}"), None
    except ValueError:
        return None, "semgrep output unreadable"


# ---- extra detection engines (defence in depth on top of Semgrep) --------------------------------------------------
# yara: byte-signature scan (catches renamed executables, obfuscated payloads, stealer strings Semgrep's parsers skip).
# clamav: known-malware signatures. osv-scanner: malicious / vulnerable dependencies (where much GitHub malware lives).
# Each runs only if its tool is present; a HIT blocks the repo; absence is recorded (never a silent downgrade). CI
# installs all three (see the workflows), so the authoritative screening always runs every engine.
_yara_rules = None
_yara_err = None


def yara_compiled():
    global _yara_rules, _yara_err
    if _yara_rules is None and _yara_err is None:
        try:
            import yara
            _yara_rules = yara.compile(filepath=YARA_RULES)
        except Exception as e:  # yara-python not installed, or rule error
            _yara_err = str(e)
    return _yara_rules


def yara_available() -> bool:
    return yara_compiled() is not None


def run_yara(dest: str) -> list[str] | None:
    """['rule@relpath', ...] of byte-signature matches, or None if yara-python is unavailable."""
    rules = yara_compiled()
    if rules is None:
        return None
    hits = []
    for root, dirs, names in os.walk(dest):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in names:
            p = os.path.join(root, n)
            try:
                if os.path.getsize(p) > YARA_MAX_FILE:
                    continue
                for m in rules.match(filepath=p, timeout=60):
                    hits.append(f"{m.rule}@{os.path.relpath(p, dest)}")
            except Exception:
                continue  # unreadable file / match error: skip, don't fail the whole scan
            if len(hits) >= 50:
                return sorted(set(hits))
    return sorted(set(hits))


def run_clamav(dest: str, env: dict) -> list[str] | None:
    """['Signature@relpath', ...] from clamscan, or None if clamav is unavailable or its database is missing."""
    if not shutil.which("clamscan"):
        return None
    try:
        r = subprocess.run(["clamscan", "-r", "-i", "--no-summary", "--stdout", "--max-filesize=25M",
                            "--max-scansize=200M", dest], capture_output=True, text=True, timeout=ENGINE_TIMEOUT, env=env)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode == 2:  # 2 = error (e.g. no signature database loaded); treat as "did not run"
        return None
    return parse_clamav(r.stdout or "", dest)


def parse_clamav(stdout: str, dest: str) -> list[str]:
    """['Signature@relpath', ...] from clamscan '<path>: <Signature> FOUND' lines."""
    hits = []
    for line in stdout.splitlines():
        if line.rstrip().endswith("FOUND"):
            path, _, sig = line.rpartition(":")
            sig = sig.strip().removesuffix("FOUND").strip()
            try:
                rel = os.path.relpath(path.strip(), dest)
            except ValueError:
                rel = os.path.basename(path.strip())
            hits.append(f"{sig}@{rel}")
    return sorted(set(hits))


def run_osv(dest: str, env: dict) -> tuple[list[str], int] | None:
    """(malicious_package_ids, vulnerable_count) from osv-scanner, or None if unavailable. Malicious advisories block;
    ordinary vulnerabilities are advisory (vulnerable code is a learning topic, not a student-safety issue)."""
    if not shutil.which("osv-scanner"):
        return None
    try:
        r = subprocess.run(["osv-scanner", "--format", "json", "--recursive", dest],
                           capture_output=True, text=True, timeout=ENGINE_TIMEOUT, env=env)
    except (subprocess.TimeoutExpired, OSError):
        return None
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        return None
    return parse_osv(data)


def parse_osv(data: dict) -> tuple[list[str], int]:
    """Split OSV findings into malicious-package advisories (block) and ordinary vulnerabilities (advisory count)."""
    malicious, vulns = [], 0
    for res in data.get("results", []):
        for pkg in res.get("packages", []):
            name = (pkg.get("package") or {}).get("name", "?")
            for v in pkg.get("vulnerabilities", []):
                ids = [v.get("id", "")] + list(v.get("aliases", []))
                is_mal = any(i.startswith(("MAL-", "GHSA-MAL", "OSV-MAL")) for i in ids) \
                    or (v.get("database_specific") or {}).get("malicious") is True \
                    or "malicious" in " ".join(ids + [v.get("summary", "")]).lower()
                if is_mal:
                    malicious.append(f"{name}:{ids[0]}")
                else:
                    vulns += 1
    return sorted(set(malicious)), vulns


def scan_repo(full_name: str, size_kb: int | None = None, language: str | None = None) -> dict:
    """Return the code-screening part of a record. result: "pass" | "withheld" | "incomplete". Never raises."""
    out = {"sha": None, "scanned_at": now_iso(), "semgrep_version": semgrep_version(), "ruleset_sha256": ruleset_sha256(),
           "configs": [os.path.basename(RULES)] + CONFIGS, "coverage": {"primary_language": language, "supported": False, "note": ""},
           "semgrep": {"blocking": [], "advisory": {}, "errors": []}, "result": "incomplete", "reasons": []}
    supported, note = coverage_for(language)
    out["coverage"].update(supported=supported, note=note)
    if not supported:
        out.update(result="withheld", reasons=[f"scanner coverage: {note}"])
        return out
    if size_kb and size_kb > MAX_KB:
        out.update(result="withheld", reasons=[f"repository too large to scan ({size_kb} KB > {MAX_KB} KB)"])
        return out
    if not shutil.which("git") or not shutil.which("semgrep") or not semgrep_version():
        out["reasons"] = ["scanner unavailable on this machine (git/semgrep missing)"]
        return out
    tmp = tempfile.mkdtemp(prefix="scout-scan-")
    env = _iso_env(os.path.join(tmp, "home"))
    os.makedirs(env["HOME"], exist_ok=True)
    try:
        sha = pin_sha(full_name, env)
        if not sha:
            out["reasons"] = ["could not pin commit (ls-remote failed)"]
            return out
        dest = clone(full_name, tmp, env)
        if not dest:
            out["reasons"] = ["clone failed or timed out"]
            return out
        got = head_sha(dest, env)
        out["sha"] = got or sha
        tree = prepare_tree(dest)
        out["coverage"].update(tree)
        if tree["bytes"] > MAX_CLONE_BYTES:
            out.update(result="withheld", reasons=[f"checkout too large to scan ({tree['bytes'] // 1024} KB)"])
            return out
        data, err = run_semgrep(dest, env)
        if err:
            out["reasons"] = [f"scan {err}"]
            return out
        results = data.get("results", [])
        errs = data.get("errors", [])
        fatal = sorted({e.get("type", "error") for e in errs if str(e.get("type", "")).lower() in ("timeout", "outofmemory", "out of memory", "semgrepcoreerror", "fatal")})
        out["semgrep"]["errors"] = fatal
        blocking = []
        adv: dict[str, int] = {}
        for x in results:
            cid = x.get("check_id", "")
            sev = (x.get("extra") or {}).get("severity", "")
            if MALWARE_PREFIX in cid:
                blocking.append(cid[cid.index(MALWARE_PREFIX):])
            elif ".secrets." in cid or cid.startswith("secrets."):
                blocking.append("secrets:" + cid.split(".")[-1])
            else:
                adv[sev] = adv.get(sev, 0) + 1
        out["semgrep"].update(blocking=sorted(set(blocking)), advisory=adv,
                              files_scanned=len((data.get("paths") or {}).get("scanned", [])), files_skipped=len((data.get("paths") or {}).get("skipped", [])))
        # sample locations only (rule + path + line); the matched text is intentionally not kept
        out["semgrep"]["sample"] = [f"{os.path.relpath(x['path'], dest)}:{x['start']['line']} {x['check_id'].split('.')[-1]}"
                                    for x in results if MALWARE_PREFIX in x.get("check_id", "")][:5]

        # ---- defence-in-depth engines (each blocks on a hit; absence recorded, never a silent pass) ----
        yara_hits = run_yara(dest)
        clam_hits = run_clamav(dest, env)
        osv = run_osv(dest, env)
        osv_mal, osv_vulns = osv if osv is not None else ([], 0)
        out["yara"] = {"ran": yara_hits is not None, "hits": yara_hits or []}
        out["clamav"] = {"ran": clam_hits is not None, "hits": clam_hits or []}
        out["osv"] = {"ran": osv is not None, "malicious": osv_mal, "vulnerable": osv_vulns}
        out["engines"] = {"semgrep": bool(semgrep_version()), "yara": yara_hits is not None,
                          "clamav": clam_hits is not None, "osv": osv is not None}
        out["semgrep"]["advisory"]["osv_vulnerabilities"] = osv_vulns

        reasons = []
        if blocking:
            reasons.append(f"code scan: {', '.join(sorted(set(blocking)))}")
        if yara_hits:
            reasons.append(f"yara: {', '.join(sorted({h.split('@')[0] for h in yara_hits}))}")
        if clam_hits:
            reasons.append(f"clamav: {', '.join(sorted({h.split('@')[0] for h in clam_hits}))}")
        if osv_mal:
            reasons.append(f"malicious dependency: {', '.join(osv_mal)}")

        if fatal:
            out.update(result="incomplete", reasons=[f"scan incomplete: {', '.join(fatal)}"])
        elif reasons:
            out.update(result="withheld", reasons=reasons)
        else:
            out["result"] = "pass"
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for n in sys.argv[1:]:
        print(n, json.dumps(scan_repo(n), indent=1))
