# Project Scout — security engineering write-up

Project Scout is a bot system that pulls GitHub project ideas, open-source issues and research code for undergraduate
students across seven majors, and delivers them through Telegram and a private Discord server. This document records
the security work done to make it safe enough for a **supervised student pilot**: the threat model, every control
built, how each was verified, and the honest limits. It makes no promise of a numeric security score, malware-free
repositories, or guaranteed legal or privacy safety.

## Reporting a problem

Found something the gate let through — a repository, model, dataset or Space that should not be in front of students —
or a weakness in the pipeline itself? Open a **private** security advisory on this repository
(Security → Advisories → Report a vulnerability), or tell TLDP staff directly in the Discord server. Please do not
open a public issue with a working exploit. Students are told the same thing: report anything suspicious rather than
running it.

## The problem

The bot's raw material is public GitHub search. GitHub search returns real malicious content: wallet drainers,
credential stealers, fake "download" repositories that point at password-protected archives, forex and account-farming
tooling, and star-farmed clone networks. A code review (using Codex) found a wallet drainer and a deceptive Ghostfolio
clone that had reached the catalogue. The risk is concrete: hand an 18-year-old a link, tell them it is a project
idea, and some of them will clone and run it on their laptop.

The design goal that followed: **students should only ever see repositories that have completed automated checks, and
even those should be run in a way that cannot infect a personal machine.** Risk is minimized, not eliminated.

## Threat model

- **Untrusted input:** every repository, README, description, issue title and hackathon listing is attacker-controlled
  data. It is never treated as instructions to the scanner or to an AI.
- **Adversaries:** repo authors seeding malware or scams into search results; someone trying to smuggle a malicious
  link or a fake mention into a Discord message; an outsider trying to join the private student server; a compromised
  or malicious dependency in an otherwise ordinary repo.
- **Assets to protect:** students' physical machines, the private roster, the bot's credentials, and the integrity of
  what students are told is "screened."
- **Explicitly out of scope of any guarantee:** perfect malware detection, and any claim about a project's legality.

## Controls, end to end

### 1. One publishing gate (`gate.py`)

Discovery is separated from what students see. `gate.eligible(row, screening, quarantine, meta)` is the single
decision every student-visible path calls. A repository is shown only if all hold: it is not quarantined; it has a
passing screening record whose reviewed commit SHA matches under the current policy version; the record has not
expired; and, for a fresh-repo row, it was pushed within 30 days. Anything that fails, times out, is incomplete, or is
in an unsupported language is **withheld**. Checks are never silently downgraded. If nothing qualifies, a self-contained
project idea with synthetic data and no external links is offered instead of an unchecked repo.

### 2. Isolated, no-execution code scanning (`scan.py`)

The only stage that touches an untrusted repo. It pins the commit with `git ls-remote`, shallow-clones it into a
throwaway directory with an **empty HOME**: no credential helpers, no git hooks, no LFS smudge, no submodules, blobs
over 2 MB skipped, non-https protocols disabled. **Nothing in the repository is ever executed** — no install scripts,
no build, no tests, no GitHub Actions workflows. Any `.semgrepignore` in the clone is deleted so a hostile repo cannot
hide files. Matched source text is discarded; only rule ids, paths and line numbers are kept, so a secret found in a
repo is never copied into a report or a message.

Four detection engines run over the clone, defence in depth:

- **Semgrep** (static analysis) with a custom malware-behaviour ruleset (`semgrep-rules/malware.yml`: decode-then-exec,
  download-and-run, credential and wallet theft, webhook and Telegram exfiltration, reverse shells, persistence,
  antivirus tampering, miners, keyloggers) plus `p/security-audit` and `p/secrets`.
- **YARA** (`yara-rules/malware.yar`) byte-signature scanning, which catches what language parsers skip: renamed
  executables, obfuscated payloads, and stealer strings in any file type.
- **ClamAV** signature scan for known malware.
- **osv-scanner** for **malicious and vulnerable dependencies**, where a large share of real GitHub malware lives.

**Blocking policy (conservative, documented):** any hit from the malware ruleset, any YARA match, any ClamAV signature,
any `p/secrets` finding, or a malicious-package advisory **withholds** the repo. Ordinary vulnerabilities and
`p/security-audit` findings are advisory only. Timeouts, parser errors, clone failures, or an unsupported primary
language make the result withheld or incomplete: the repo is not published. Findings are never suppressed to pass a
check; every engine's result and which engines actually ran are recorded.

### 3. Deep vetting and content policy (`vet.py`, `gate.py`)

Before the clone: a quarantine list (`quarantine.json`) that named incident repos and clone-name patterns can never
escape; a content policy that fails repos advertising drainers, stealers, phishing kits or cracked software, and keeps
ambiguous dual-use offensive tooling out of the general feed without flagging legitimate curated security tools; and a
deep vet for root binaries, README-only shells, bought stars, brand-new owners, clone farms, and OpenSSF Scorecard
signals.

### 4. Link and install-instruction screening with an SSRF guard (`links.py`)

README links are classified: file-sharing hosts, executable downloads from unrelated domains, credentials embedded in
a URL, and instructions to disable antivirus, use archive passwords, or pipe `curl` into a shell all block. URL
shorteners warn. If a shortener is ever resolved, the resolver is SSRF-guarded: it refuses private, loopback,
link-local, carrier-grade-NAT and cloud-metadata addresses, re-validates every redirect hop against the resolved IP,
caps redirects and header size, and never downloads a body.

### 5. Screening records and expiry (`screening.json`)

Each record holds repository identity, the reviewed commit SHA, scan time, scanner and rule versions, coverage, which
engines ran, the result and the reasons. Records expire (14 days for fresh repos, 30 for curated references); a changed
commit or an expired record forces a fresh screen before the repo can be published again.

### 6. Student-side containment: sandboxes (`sandbox/`, Discord)

The most reliable control for "won't infect their machine" is that students never run untrusted code on the laptop.
The server ships a build-your-sandbox channel and a reusable template: a hardened dev container (non-root user, capped
CPU and memory, `no-new-privileges`) for GitHub Codespaces or local Docker/Podman, and a Google Colab starter
notebook. Colab and Binder run the code off the machine entirely. Every repo message and the welcome guidance tell
students to use public or synthetic data only, never commit secrets, report suspicious links, and read code before
running it.

### 7. Identity and privacy (`enroll.py`, Discord Worker)

Name-on-roster matching was removed: a typed name is not proof of identity, and `/verify` exposes no roster oracle.
The roster is the distribution list for unique, single-use, expiring Discord invites (replay-proof, unpredictable,
time-boxed); staff grant the student role to the members who joined. The roster lives only in a gitignored file and is
never printed, logged, or sent to a service. Stronger SSO or signed-token binding is documented but intentionally not
enabled without a decision.

### 8. Safe delivery (Cloudflare Workers, feed, weekly posts)

The Telegram and Discord Workers render only the pre-screened `published.json` snapshot; they make no live GitHub or
GitLab search, and they fail closed (pause with a notice) if screening is stale, degraded, or missing. Third-party text
is escaped consistently; automatic mentions are disabled on every posting path; masked links are neutralized; link
destinations are checked against an allowlist; messages are trimmed without cutting a link or the safety label. The
Discord command endpoint keeps Ed25519 signature verification and adds guild and role enforcement, command and input
validation, a timestamp skew check, and best-effort replay and rate limiting.

### 9. Least-privilege CI (`.github/workflows/`)

Two jobs. The **screen** job does the untrusted cloning and scanning with `contents: read`, `persist-credentials:
false`, no Discord or Telegram secrets, and only a no-permission machine-account search token; it installs Semgrep,
YARA, ClamAV and osv-scanner and uploads its results as an artifact. The **publish** job re-validates every row
offline, sends messages, and commits state; it never clones or executes anything. Third-party actions are pinned to
commit SHAs. A separate `security.yml` scans this repository itself.

## Verification

- **68 automated tests pass** (60 Python across `tests/` plus 8 for the new engines, and 16 Cloudflare Worker tests).
  They prove that failed, stale, quarantined, unscreened, and out-of-freshness repositories never reach the published
  feed or a message through any path, that the YARA rules catch malicious samples and leave benign ones clean, that the
  ClamAV and OSV parsers split malicious from ordinary findings, that the SSRF guard refuses private and metadata
  addresses and re-validates redirects, and that mention and masked-link injection is neutralized.
- **Semgrep 1.177.0** run over this project reports zero ERROR findings in code.
- A **real end-to-end screen** of a live repository produced a passing record with a genuine reviewed commit SHA,
  engine coverage, and an expiry; a quarantined repository was failed without being scanned.
- **Not verified here:** the full discovery-and-publish run at scale, and ClamAV and osv-scanner end to end, which run
  only in CI on GitHub. Those are described honestly as untested until they run there.

## Honest limits

Heuristics miss malicious projects and reject legitimate ones. Static analysis, signature scanning and link checks are
all evadable. A repository can change after it was screened; records expire in 14 days. Worker replay and rate-limit
state is best-effort per isolate. This system is built for a supervised pilot with staff in the loop. It reduces risk
substantially; it does not remove it, and it makes no claim about any project's licence or legality. The student
sandbox is what makes the residual risk acceptable: a missed repository runs in a disposable environment, not on a
personal machine.
