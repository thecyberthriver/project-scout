# Screening, publishing gate, and pilot readiness

This is the plain-language companion to `gate.py`, `scan.py`, `vet.py`, `links.py` and `pipeline.py`. It explains
what students see, what nontechnical staff have to do, what the automated checks do and do not establish, and what is
verified versus untested. It makes **no** promise of a numeric security score, malware-free repositories, or
guaranteed legal or privacy safety.

## What a student sees

Students never see raw search results. They see a **published snapshot** (`published.json`) that the feed rebuilds on
a schedule. Every repository in it has completed automated checks and is inside the freshness window. Every repository
message ends with the same line:

> ℹ️ Automated checks completed; not a safety guarantee.

If the checks are not current, the bots and slash commands **pause** and show "Recommendations are paused… staff have
been notified" instead of guessing. Nothing falls back to a live, unscreened search.

## The one gate (nothing student-visible skips it)

`gate.eligible(row, screening, quarantine, meta)` is the single decision. A repository is published only if **all** of:

1. It is **not quarantined** (`quarantine.json`).
2. It has a **passing screening record** whose reviewed commit SHA matches, under the current policy version.
3. The record is **not expired** (14 days for fresh repos, 30 for curated references).
4. For a fresh-repo row, it was **pushed within 30 days** (the freshness rule you chose: last push, not creation date).

Anything that fails, times out, is incomplete, or is in a language the scanner cannot parse is **withheld**. Checks are
never silently downgraded to make a repo pass. If nothing qualifies for a slot, the feed offers a **self-contained
project idea** with synthetic data and no external links instead of an unchecked repo.

## What a screening record contains

`screening.json` holds one record per repository: repository identity, the reviewed commit SHA, scan time, the Semgrep
version and rule-file SHA-256, coverage (which languages were parsed, how many files), the result (pass / withheld /
incomplete) and the reasons. A **changed commit** or an **expired record** forces a fresh screen before the repo can be
published again.

## What the checks are, in order

Discovery (the only stage that touches an untrusted repo) runs, per candidate:

1. **Quarantine** — two named incident repos and a clone-name pattern can never return.
2. **Content policy** (`gate.py`) — clearly-prohibited wording (wallet drainers, stealers, phishing kits, cracked
   software, account farms) fails any repo. Ambiguous **dual-use** offensive tooling (RATs, C2, keyloggers, booters) is
   kept out of the general feed. Curated, allow-listed security tools are **not** treated as malware.
3. **Deep vet** (`vet.py`) — binaries in the repo root, README-only shells, bought stars, brand-new owners, clone
   farms, OpenSSF Scorecard signals.
4. **Link + install screening** (`links.py`) — README links classified: file-sharing hosts, executable downloads from
   unrelated domains, credential-in-URL, and instructions to disable antivirus, use archive passwords, or pipe `curl`
   into a shell all block. URL shorteners warn. Repository text is treated as **data, never as instructions**. If a
   shortener is resolved, the resolver is **SSRF-guarded**: it refuses private, loopback, link-local, carrier-grade-NAT
   and cloud-metadata addresses, re-validates every redirect hop against the resolved IP, caps redirects and header
   size, and never downloads a body. Resolution is **off by default** (shorteners warn without a network call).
5. **Isolated code scan** (`scan.py`) — the repo is cloned at the pinned commit into a throwaway directory with an
   **empty HOME**: no credential helpers, no git hooks (`core.hooksPath` → empty), no LFS smudge, no submodules, blobs
   over 2 MB skipped, non-https protocols disabled. **Nothing in the repo is executed** — no install scripts, no build,
   no tests, no GitHub Actions workflows. Semgrep runs static-only (`--config` only, no Pro engine, no autofix) with
   our malware-behaviour rules plus `p/security-audit` and `p/secrets`, metrics off, per-file and total timeouts, a
   memory cap and a target-size cap. Any `.semgrepignore` in the clone is deleted so a hostile repo cannot hide files.
   Matched source text is discarded — only rule ids, paths and line numbers are kept, so a **discovered secret is never
   copied into a report or a Discord message**.

   Three more engines run over the same clone, defence in depth: **YARA** byte-signatures (`yara-rules/malware.yar`,
   catches renamed executables, obfuscated payloads and stealer strings in any file type), **ClamAV** known-malware
   signatures, and **osv-scanner** for malicious and vulnerable dependencies. Each blocks on a hit. If an engine cannot
   run (for example ClamAV's signature database failed to download), that is recorded as "not run" — never a silent
   pass. CI installs all four so the authoritative screening always runs every engine.

**Blocking thresholds (documented, conservative):** any hit from our malware rules (`tldp.*`), any YARA match, any
ClamAV signature, a malicious-package advisory, or any `p/secrets` finding **withholds** the repo. Ordinary
vulnerabilities and `p/security-audit` findings are advisory counts only (vulnerable code is a learning
topic, not a student-safety issue) and do not block. Timeouts, parser errors, clone failures, or an unsupported primary
language make the result withheld/incomplete — the repo is **not** published. Findings are never suppressed to make a
check pass; unresolved findings are preserved in the record.

## Untrusted vs. trusted stages (GitHub Actions)

- The **screen** job clones and scans untrusted repos. It has `contents: read`, `persist-credentials: false`, **no
  Discord/Telegram secrets**, and only a no-permission GitHub token. It uploads `build/` as an artifact.
- The **publish** job downloads that artifact, re-validates every row **offline** through `gate.eligible`, sends
  messages, and commits state. It never clones or executes anything.
- Third-party Actions are pinned to commit SHAs (see `docs/SCANNERS.md`). `contents: write` remains only so the bot can
  commit `seen.json`, `published.json`, `screening.json`, `index.json` (the alternative is a scoped deploy key or
  GitHub App — see the workflow header comments).

## Student identity (your decision: roster controls access)

Name-on-roster matching was removed: typing a name is not proof of identity, and `/verify` no longer answers name
queries (no roster oracle). Your roster of student names is the **distribution list**:

1. `python enroll.py --invites` mints one **unique, single-use, 7-day** Discord invite per roster entry into
   `roster_invites_local.json` (gitignored, never printed). Staff DM each listed student their own link. Single-use =
   replay-proof; expiring = time-boxed; random code = unpredictable; only people you invite can join.
2. `python enroll.py --grant` gives the Student role to every human member who joined (skips bots and staff). Members
   should equal your roster size; `--reconcile` prints those counts (never names).

The roster lives only in `roster_local.json` (gitignored) and is never printed, logged, or sent to a service.
**Stronger options, not built (they need your go-ahead and an integration):** school SSO/OAuth binding to a
`@baruch.cuny.edu` identity, or per-student signed single-use tokens redeemed at `/verify` (needs Cloudflare KV for
replay state). Both are documented; neither is enabled.

## Low-maintenance operation

No routine staff approvals and no per-repository review queue. Withheld repositories and their reasons go to a private
diagnostic report (`docs/vetting-report.md`), not to students. Staff are alerted only on **actionable system failures**
(a run failed, or nothing has posted in 48 h) — never on individual rejections. `python gate.py --status` prints a
plain-language status: whether screening is operational, how many repos are passing versus withheld, and when screening
last ran.

## Student guidance (posted in the server; see `github-academy` and `#welcome`)

- Use **public or synthetic data only**. Never put personal data, passwords, API keys, `.env` files, or anything under
  NDA into a repo, a case study, or a message.
- **Report suspicious links** to staff instead of clicking them.
- **A scanned project is not proven safe to run.** Read code before you run it; prefer running unfamiliar code in a
  sandbox or a throwaway environment.
- Automated checks reduce risk; they do not remove it, and they say nothing about a project's licence or legality.

## Honest limits

Heuristics miss malicious projects and reject legitimate ones. Static analysis and link checks can be evaded. A repo
can change after it was screened (records expire in 14 days). Replay and rate-limit state on the Cloudflare Workers is
best-effort per isolate (a KV/Durable Object upgrade is noted in the code). This system is built for a **supervised**
pilot with staff in the loop; it is not an unattended safe-by-default guarantee.
