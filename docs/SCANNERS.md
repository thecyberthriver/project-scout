# Scanners: what runs, what it covers, what it does not

**SQL repositories** (`SQL`, `TSQL`, `PLpgSQL`, `PLSQL`, `MySQL`, `SQLPL`): Semgrep ships no SQL parser, so these are
screened the way a documentation repo is — generic (regex) malware and secrets rules — while **YARA, ClamAV and
osv-scanner still run over the whole checkout**. The coverage note on the record says exactly that. Before this, every
SQL teaching repo was withheld as "unsupported language", which is why the feed carried no SQL projects at all.

Two different things get scanned, by the same tool, in different trust zones:

| Target | Where | Trust zone |
|---|---|---|
| Third-party repositories a student might be shown | `screen` job of `digest.yml`, `screen-index` job of `weekly.yml` (via `project_scout.py --discover` / `--index-discover`, which call `scan.py`) | **Untrusted.** No Discord/Telegram secrets, no git credential (`persist-credentials: false`), `contents: read`, 45-minute job timeout, only the no-permission machine-account search token. Repositories are shallow-cloned at a pinned commit and read by Semgrep; nothing in them is ever executed (no install scripts, no build, no tests, no workflows). |
| This project's own code | `security.yml` | `contents: read`, no secrets. |

**MCP servers are not part of enforcement.** The `semgrep` and `socket-mcp` servers connected to Claude Code are
interactive helpers for the maintainer. The only checks that gate what students see are the ones the workflows
above run deterministically. If a workflow does not run, nothing is published (the `publish` job needs the
`screen` artifact).

## Tools selected

| Tool | Version | Used on | Covers | Does not cover | Data leaves the runner? | Account / cost |
|---|---|---|---|---|---|---|
| **Semgrep OSS CLI** | 1.177.0 (pinned with `pip install semgrep==1.177.0`) | both targets | Pattern-based static analysis. Registry rulesets `p/security-audit`, `p/secrets`, `p/python`, `p/javascript`, `p/github-actions` on this repo; `p/security-audit` at ERROR plus the custom `semgrep-rules/malware.yml` (decode-then-exec, download-and-run, credential-store access, webhook/Telegram exfiltration, reverse shells, persistence, AV tampering, miners, keyloggers) on third-party repos. | Obfuscation beyond its patterns, binaries, minified bundles over the size cap, languages Semgrep has no parser for (those repos are withheld as *unsupported*, not passed), logic bugs, licence/legal questions. Semgrep Pro rules and cross-file taint are **not** enabled (need an account). | Rules are downloaded from `semgrep.dev`. `--metrics=off` is set everywhere, so no code, paths or findings are sent. | Free, no account. |
| **osv-scanner** | `google/osv-scanner-action` v2.6.0 | this repo | Known CVEs in declared dependencies (lockfiles/manifests for 11+ ecosystems). | Anything without a manifest. This repo is stdlib-only Python and dependency-free Workers, so today there is nothing to scan and the step is `continue-on-error: true` (documented limitation; flip to `false` when a lockfile appears). Not run on third-party repos (would need their manifests and adds network calls per repo). | Sends package names and versions to `api.osv.dev`. | Free, no account. |
| **gitleaks** | `gitleaks/gitleaks-action` v3.0.0 | this repo (full history) | Committed secrets, tokens, keys. | Secrets in third-party repos (those are covered by `p/secrets` inside the untrusted scan, and findings are reported as rule id + location only, never the matched text). | Nothing. | Free for personal-account repositories (README: licence key only required for organisations). |
| Semgrep `p/secrets` | as above | both | Fallback secret detection if gitleaks is removed. | | as Semgrep | free |

**Not enabled, ask before adding:** Semgrep Pro / Supply Chain (account, paid tiers, sends code to Semgrep cloud),
Socket.dev (account + API key; sends package metadata), pip-audit (nothing to audit — no Python dependencies).

## Pinned action SHAs (resolved read-only with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` on 2026-09-16)

| Action | Tag | Commit |
|---|---|---|
| actions/checkout | v4 | `11d5960a326750d5838078e36cf38b85af677262` |
| actions/setup-python | v5 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| actions/upload-artifact | v4 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| actions/download-artifact | v4 | `d3f86a106a0bac45b974a628896c90dbdf5c8093` |
| google/osv-scanner-action/osv-scanner-action | v2.6.0 | `a345acffa64b0eaede81a3d9aae6141214d9c8fc` |
| gitleaks/gitleaks-action | v3.0.0 | `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` |

## Local self-scan of this repository (2026-09-16, Semgrep 1.177.0, before the workflow rewrite)

Command: `semgrep scan --config p/security-audit --config p/secrets --config p/python --config p/javascript --config p/github-actions --metrics=off --json --exclude docs --exclude __pycache__ .` — 330 rules, 21 files.

| Severity | Rule | Location | Status |
|---|---|---|---|
| ERROR | `github-actions.security.run-shell-injection` | `.github/workflows/weekly.yml:31` (`${{ inputs.day }}` inside `run:`) | **Fixed** in this change: `day` is a `type: choice` input passed via `env: DAY` and quoted `"${DAY:-…}"`; re-scan of the new workflows: 0 findings. |
| WARNING ×19 | `python.lang.security.audit.dynamic-urllib-use-detected` | `project_scout.py` (482, 544, 592, 601, 613, 936, 1008, 1054, 1060, 1071), `vet.py` (53, 141), `discord_weekly.py` (32, 85, 95, 103), `discord_setup.py:197`, `purge_posts.py:36`, `cloudflare-webhook/register_discord.py:66` | Audit-level note that `urllib.request.urlopen` is called with a non-literal URL (it accepts `file://` etc. if the scheme were attacker-controlled). Every call site builds the URL from a hard-coded `https://` host plus encoded parameters; the link-checker being added by the gate work validates schemes/hosts explicitly. Left open as a documented WARNING, not suppressed. |
| — | 4 parser errors (`PartialParsing`) | old `digest.yml:47`, `weekly.yml:31` | Semgrep could not parse the old `${{ }}`-in-shell lines as Bash; gone after the rewrite. |

Custom ruleset on this repo (`--config semgrep-rules/malware.yml`): 9 findings, all in `semgrep-rules/malware.yml`
itself (the rules' own regex strings match themselves: `credential-store-access` ×5, `cryptominer` ×4). No findings
in any code file. `security.yml` therefore scans the custom ruleset with `--exclude semgrep-rules`.

Dependencies: `grep` of imports confirms the Python is stdlib-only (`json, os, re, shutil, subprocess, sys, tempfile,
time, urllib, datetime, collections, pathlib, base64, io`); the one `import requests` is in a one-off helper script
with a comment saying so. `cloudflare-webhook/` has no `package.json` or lockfile. pip-audit / osv-scanner have
nothing to audit today.

Could not run locally: osv-scanner and gitleaks are not installed on this machine and were not installed (no new
tools/accounts); they run in `security.yml` on GitHub. The gitleaks step could not be exercised before push.

## Limits to keep in mind

- Static heuristics miss malicious projects that hide behind obfuscation, binaries, or behaviour the rules don't
  describe, and they reject legitimate projects that happen to match (security tooling especially). A scan result
  says "these checks completed", not "safe", and says nothing about legality or licensing.
- Findings are reported by rule id and file:line only. Matched text is never written to Discord, Telegram, or the
  public report, so a discovered secret is not re-exposed by the scanner.
- A withheld repository stays withheld; nothing is suppressed to make a check pass. Unresolved findings are kept in
  the screening record with the rule ids that caused them.
