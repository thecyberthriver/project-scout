#!/usr/bin/env python3
"""
discord_setup.py — provision the private TLDP server in one run (rerunnable: skips what exists by name).
stdlib only (+ Pillow, optional, for the server icon).

  python discord_setup.py               # build / update everything, print secrets to set
  python discord_setup.py --invites 45  # print 45 single-use 7-day invite links (Discord max) (one per student, CSV)

Reads DISCORD_BOT_TOKEN / DISCORD_GUILD_ID from env or ../secrets_local.py. Needs the bot invited with
Manage Server, Manage Roles, Manage Channels, Manage Webhooks, Create Invite, Send/Manage Messages (805317681).

What it does:
  1. Server: verification Medium, notifications = mentions only, @everyone loses "Create Invite", TLDP icon.
  2. Roles: "TLDP Staff", "TLDP Student" (gate), one mentionable role per major.
  3. Categories + channels. Feed channels are FORUMS: every drop is its own post/thread, students discuss
     inside it and react 🙋 to claim it. Feed + Collaborate + Study Rooms are hidden until /verify grants
     "TLDP Student"; START HERE stays visible so newcomers can read #welcome and run /verify.
  4. One webhook per feed forum (+ #announcements) -> printed as the DISCORD_WEBHOOKS secret.
  5. A 45-use 7-day invite on #welcome + a pinned welcome post.
"""
import base64
import io
import json
import os
import sys
import urllib.parse
import urllib.request

try:
    import secrets_local as s
except ImportError:
    s = None
TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or getattr(s, "DISCORD_BOT_TOKEN", "")
GUILD = os.environ.get("DISCORD_GUILD_ID") or getattr(s, "DISCORD_GUILD_ID", "")
APP_ID = os.environ.get("DISCORD_APP_ID") or getattr(s, "DISCORD_APP_ID", "")
API = "https://discord.com/api/v10"
MAX_STUDENTS = 45

CREATE_INVITE, VIEW, SEND = 0x1, 0x400, 0x800
STAFF_PERMS = 805317681  # what the bot itself was invited with — a bot cannot grant more than it holds
TEXT, VOICE, CATEGORY, FORUM = 0, 2, 4, 15

MAJOR_ROLES = {"quant": ("Quant", 0x2ECC71), "fintech": ("Finance/FinTech", 0x1ABC9C), "swe": ("SWE", 0x3498DB),
               "cyber": ("Cybersecurity", 0xE74C3C), "data": ("Data Analytics", 0x9B59B6),
               "pm": ("Project Management", 0xF1C40F), "marketing": ("Digital Marketing", 0xE67E22)}

# category -> gated? , [(name, topic, type, feed key)]
LAYOUT = {
    "📌 START HERE": (False, [
        ("welcome", "Rules, how the bot works, and how to get your student role. Post in #introductions to unlock the server.", TEXT, None),
        ("announcements", "TLDP staff announcements + weekly hackathon list. Read-only.", TEXT, "announcements"),
        ("introductions", "Name · major · what you want to build this semester.", TEXT, None),
    ]),
    "🧰 SET UP YOUR SANDBOX (do this first)": (True, [
        ("🛠️│build-your-sandbox", "START HERE after you're verified: build your own reusable sandbox (Google Colab or a Codespaces dev container) so nothing you run can touch your laptop. Step-by-step inside; post when you've built it.", FORUM, None),
        ("🧰│safe-sandboxes", "Which free sandbox to use and the safety rules. Read the pinned post. Colab is completely free and the best default.", FORUM, None),
    ]),
    "🧪 PROJECT SCOUT FEED": (True, [
        ("📊│data-analytics", "Fresh data analytics repos, good-first-issues and paper code. One post per drop — react 🙋 to claim.", FORUM, "data"),
        ("💻│swe", "Fresh software projects, good-first-issues and paper code. React 🙋 to claim.", FORUM, "swe"),
        ("🔐│cybersecurity", "Fresh cybersecurity repos, good-first-issues and paper code. React 🙋 to claim.", FORUM, "cyber"),
        ("📈│quant", "Fresh quant repos, good-first-issues and paper code. React 🙋 to claim.", FORUM, "quant"),
        ("💳│finance-fintech", "Fresh finance/fintech repos, good-first-issues and paper code. React 🙋 to claim.", FORUM, "fintech"),
        ("📋│project-management", "Fresh project-management tools and good-first-issues. React 🙋 to claim.", FORUM, "pm"),
        ("📣│digital-marketing", "Fresh marketing/SEO/analytics repos and good-first-issues. React 🙋 to claim.", FORUM, "marketing"),
        ("🤝│open-source-orgs", "Non-profit, public-sector and company repos you can contribute to — resume-ready.", FORUM, "orgs"),
    ]),
    "🤝 COLLABORATE": (True, [
        ("scout-search", "Run /scout here: /scout major:Cybersecurity lane:Contribute keywords:honeypot", TEXT, None),
        ("find-a-team", "Post the project you picked and who you need. Weekly 'claimed this week' list lands here.", TEXT, None),
        ("show-your-work", "Merged PRs, demos, repos, resume lines. Friday leaderboard counts links posted here.", TEXT, None),
        ("help", "Stuck on git, a PR, an environment? Ask here.", TEXT, None),
        ("general-chat", "Everything else.", TEXT, None),
    ]),
    "🎯 SPRING REQUIREMENTS": (True, [
        ("🏁│nyc-hackathons", "In-person hackathons in the NYC area, city-wide + private + public sector, updated every 6 h from Devpost and MLH. Attend one by spring. Reply in a post to find teammates.", FORUM, "hackathons"),
        ("🎓│capstone", "Your capstone project, judged in spring. Post your idea, repo link, weekly progress, and questions for staff.", TEXT, None),
        ("📁│case-studies", "Contribute to real case-study collections, and add your own case to github.com/tldpprojectscout/tldp-case-studies. Every merged case is announced here with your name. Monday: case of the week.", TEXT, "cases"),
    ]),
    "🧑‍💻 PRACTICE & REVIEW": (True, [
        ("🧑‍💻│code-review-practice", "All tech majors: post code, a repo link or a short video walkthrough and get an interview-style code review from peers and staff. Read the pinned rubric first.", FORUM, None),
        ("🛡️│cyber-review-practice", "Cybersecurity: post lab write-ups, detection rules, scripts or video walkthroughs and get reviewed the way a security interview panel would. Read the pinned rubric first.", FORUM, None),
        ("🐙│github-academy", "Beginner GitHub videos and tutorials, in order. Start with 'Week 0'. Ask questions inside any post.", FORUM, None),
    ]),
    "🎧 STUDY ROOMS": (True, [("Study Room 1", "", VOICE, None), ("Study Room 2", "", VOICE, None)]),
}

# Seed posts for the practice forums: created once (skipped when the forum already has a post with the same title).
SEED = {
    "🧑‍💻│code-review-practice": [
        ("📌 How code review practice works (read first)", """**Why:** most tech interviews include a code review or a live walkthrough of something you built. Practising it here, in front of peers, is how you stop freezing in the real one.

**How to post**
1. Title: `[language] what it does — what you want feedback on` (e.g. `[Python] CSV budget tracker — is my structure sane?`)
2. Body: link to the repo or file (GitHub, not a zip), OR a video walkthrough of 5 minutes or less (screen recording; explain the problem, your approach, one thing you're unsure about).
3. Tag your major role so the right people see it.

**How to review (anyone can review — reviewing teaches more than posting)**
Use the 3-2-1 format: **3** things that work, **2** things to change (say *why*), **1** question you'd ask in an interview.
Look at, in this order: does it run and do what it says · naming and readability · structure (functions, duplication) · error handling and edge cases · tests · anything a user could break or leak (inputs, secrets in code).

**Rules:** review the work, never the person. Reply within a week if you post. Staff sample threads for feedback quality; strong reviewers get called out on Fridays in #show-your-work."""),
        ("Example thread: what a good review looks like", """A worked example so nobody has to guess.

**Post:** `[Python] Weather CLI — first project, is my error handling ok?` + repo link + 3-min video.

**Review (3-2-1):**
✅ Runs from a clean clone with the README steps · clear function names (`fetch_forecast`, `render_table`) · you handled a missing API key with a real message instead of a stack trace.
🔧 `main()` is 80 lines; pull the argument parsing and the printing into their own functions so each does one thing. · The API key is read from a file committed to the repo — move it to an environment variable and add the file to `.gitignore` (interviewers will always ask about this).
❓ "What happens if the API returns 200 with an empty body?" — try it and tell us.

That's it. Specific, kind, and the poster knows exactly what to do next."""),
        ("Practice 1 (Beginner) — read this function and explain it", """**Teaching example.** Read it, then in your own words say what it does before scrolling.

```python
def dedupe(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
```

**What it does, line by line:** `seen` remembers what we've already met; `out` is the result. We walk `items` in order; the first time we see a value we record it and keep it, and skip any later copies. So it removes duplicates **while preserving the original order** (unlike `list(set(items))`, which loses order).

**Complexity (intro level):** **O(n) time** — one pass, and `x in seen` on a set is roughly constant. **O(n) space** — `seen` and `out` can each hold every item.

**One edge case it mishandles:** unhashable items. `dedupe([[1],[1]])` raises `TypeError: unhashable type: 'list'`, because sets need hashable elements. How would you handle that gracefully? Post your answer."""),
        ("Practice 2 (Intermediate) — find the bug and the security weakness (hints)", """**Teaching example — this code is intentionally flawed. Do NOT copy it into a real project.**

```python
import sqlite3

def top_customers(db, region, limit=10):
    con = sqlite3.connect(db)
    q = "SELECT name FROM customers WHERE region='" + region + "'"
    rows = con.execute(q).fetchall()
    names = []
    for i in range(1, limit):
        names.append(rows[i][0])
    return names
```

**Two flaws are hidden here — one bug, one security weakness.**

**Hints**
1. Loop bounds: how many names come back when you ask for `limit=10`? Print `len(names)` and compare. Count from where?
2. What happens if `region` is `"' OR '1'='1"`? Build the query string on paper.
3. Untrusted input should never be glued into SQL by hand.

**Your task:** name both flaws, propose the fix (a parameterized query with `?` placeholders, and correct loop bounds), and **write one small test** that fails on the current code and passes after your fix — include the empty-result case."""),
        ("Practice 3 (Undergraduate Challenge) — bounded task", """A real, finishable project that combines familiar skills. **Not** research, not a large system.

**Build:** a small command-line tool that reads a CSV of transactions (`date,amount,category`) and prints total spend per month.

**Requirements**
• Input validation: reject rows with a bad date or non-numeric amount, and report which row.
• Error handling: a missing file prints a clear message and exits, not a stack trace.
• 3 unit tests (`unittest` or `pytest`), including an **empty-file** edge case and a **malformed-row** case.
• A 5-line README: what it does, how to run it, example input.

**Prerequisites:** basic Python, file I/O, dictionaries. No external services.

**Effort:** roughly **2–4 hours** — an estimate; take longer if it's your first CLI.

**A successful submission:** runs from a clean clone with the README steps, all tests pass, handles empty and malformed input without crashing, and **no secrets or real personal data** are committed. Post the repo link here for a 3-2-1 review."""),
        ("Rubric & a sample constructive review", """**Review checklist** (use it when you review Practice 3 or any post):
☐ Readability — can you follow it without the author explaining?
☐ Naming — do names say what things are?
☐ Input validation — is untrusted input checked at the edge?
☐ Error handling — do failures give a clear message, not a stack trace?
☐ Secret handling — no passwords/keys/`.env` in the code or history?
☐ Tests & edge cases — empty, malformed, boundary inputs covered?
☐ Complexity — can the author explain the cost in one sentence?

**Sample review of a Practice 3 submission (3-2-1):**
✅ Runs from a clean clone; the empty-file test is there and passes; the month totals are correct on the sample.
🔧 A row like `2026-13-40,10,food` is accepted — validate the date with `datetime.strptime` and skip with a message, because one bad row shouldn't corrupt every total. · `amount` is summed as a string in one place, so `"10"+"5"` becomes `"105"` — convert to `float` once at parse time so the bug can't spread.
❓ "If the file were 10 GB, what would you change?" — a chance to mention streaming line by line instead of loading all rows.

Be specific and kind. Reviewing well is a skill interviewers watch for. Never post or ask for copied interview answers."""),
    ],
    "🛡️│cyber-review-practice": [
        ("📌 How security review practice works (read first)", """**Why:** security interviews ask you to walk through an investigation, defend a finding, or explain a detection. This forum is where you rehearse that with an audience.

**What to post (pick one)**
• A lab or CTF write-up (TryHackMe, HTB, Blue Team Labs, an Atomic Red Team test you ran, a Splunk/Sigma hunt).
• A detection rule, script or playbook (Sigma, YARA, Splunk SPL, KQL, a Python or PowerShell tool).
• A 5-minute-or-less video walkthrough of any of the above.
Title format: `[domain] what it is — what you want feedback on` using the CISSP domain names (e.g. `[D7 SecOps] Sigma rule for LSASS access — too noisy?`).

**How to review (3-2-1, same as code review)**
**3** things that are solid, **2** things to change with the reason, **1** question an interviewer would ask.
Check, in order: is the methodology clear and repeatable · is every claim backed by evidence (log line, screenshot, hash, CVE) · is the risk rated and justified (likelihood × impact, not vibes) · is the remediation specific and prioritized · could a non-technical manager follow the summary.

**Rules:** only targets you're authorized to test (labs, CTFs, your own machines). No live credentials, no real customer or personal data, ever. Review the work, never the person."""),
        ("Example thread: what a good security review looks like", """**Post:** `[D7 SecOps] Investigating a phishing alert in the Splunk lab — is my write-up interview-ready?` + PDF write-up + 4-min video.

**Review (3-2-1):**
✅ Timeline is exact (UTC timestamps, host, user) · you show the SPL query and the raw event, not just a conclusion · the executive summary is three sentences a manager can read.
🔧 The risk is called "High" without saying why — add one line: what the attacker could reach from that host, and how likely. · The remediation says "reset password"; add the containment step you'd do first (disable the account, block the sender domain) and the order.
❓ "How would you tell whether the attachment actually ran?" — name the log source you'd check (Sysmon event 1 / EDR process tree) and add it.

Specific, evidence-first, and it reads like a report a SOC lead would accept."""),
        ("Practice (Beginner→Intermediate) — spot the security weaknesses", """**Teaching example — intentionally insecure. Never ship code like this.**

```python
import os

API_KEY = "sk_live_9f3a2b7c1d8e"          # (1)

def backup(host):
    os.system("ping -c1 " + host)          # (2)
    os.system(f"scp data.db admin@{host}:/backups/")  # (3)
```

**Three flaws are hidden here. Find them.**

**Hints**
1. Line (1): where do secrets belong, and where do they *not*?
2. Lines (2)/(3): `host` comes from a user. What does `host = "x; rm -rf ~"` do when glued into a shell string?
3. Is `host` ever checked before use?

**Your task:** explain the risk of each (hardcoded secret in source and git history; OS command injection via unvalidated input), then propose the fix:
• Load the secret from an environment variable (`os.environ`), never commit it.
• Validate `host` against an allowlist / strict pattern before use.
• Replace `os.system(str)` with `subprocess.run([...], shell=False)` passing arguments as a list, so input can't become new commands.

Post your rewrite for review. Synthetic data only — no real hosts or keys."""),
        ("Reviewing security work — rubric", """Use this when you review a write-up, detection rule, or script:
☐ **Evidence** — is every claim backed by a log line, hash, screenshot, or CVE?
☐ **Risk rating** — is it justified as likelihood × impact, not a vibe?
☐ **Remediation** — specific and prioritized, with the first containment step named?
☐ **Reproducibility** — could someone repeat the steps from what's written?
☐ **Secrets & data** — no real credentials, tokens, or customer/personal data anywhere; secrets loaded from env, not code?
☐ **Scope** — only authorized targets (labs, CTFs, your own machines)?
☐ **Audience** — can a non-technical manager follow the summary?

Give feedback in the 3-2-1 format: 3 solid things, 2 to change with the reason, 1 question an interviewer would ask.

*These are practice exercises. Use synthetic data only, and treat every intentionally vulnerable example here as a learning artifact, never safe production code.*"""),
    ],
    "🛠️│build-your-sandbox": [
        ("📌 Build your sandbox — do this first", """You will build **one** reusable sandbox and use it all year. A sandbox is a throwaway computer for running code you did not write, so a bad project can't touch your real laptop. It **minimizes** risk — it does not remove it, and a passed check is not proof code is safe.

**Pick one and follow its post below:**
• **Build A — Google Colab.** Completely free, no bill possible, just a Google account. Best for Python and data. **Start here if unsure.**
• **Build B — Codespaces dev container.** More powerful (full apps), free within a monthly limit via the Student Pack. Best for SWE / web projects.

**The rules that matter more than the tool:**
1. **Public or synthetic data only.**
2. **Never** put a real password, API key, token or `.env` file in a sandbox. A sandbox holding your real login is not protecting you.
3. Treat it as **disposable** — delete the session when you're done.
4. **Read code before you run it.** If an install step says "disable your antivirus" or downloads from an odd site, stop and post it for staff.

Files and full instructions: https://github.com/tldpprojectscout/project-scout/tree/main/sandbox"""),
        ("🟢 Build A — your Google Colab sandbox (start here)", """Runs on Google's computers, so nothing touches your laptop. Completely free.

1. Go to **colab.research.google.com** and sign in with a Google account.
2. `File → Open notebook → GitHub`. Paste `tldpprojectscout/project-scout` and open **sandbox/colab_sandbox.ipynb**.
3. `File → Save a copy in Drive`. That copy is now **your** reusable sandbox — you built it.
4. Work through the numbered cells: it checks you're really in Colab, clones a repo you name, shows you the code to **read first**, then installs and runs it — all on Google's machine.
5. Finished? `Runtime → Disconnect and delete runtime`. Everything is destroyed.

Then post in this channel: "Built my Colab sandbox ✅". Stuck on a step? Reply on your post and tag a mentor."""),
        ("🟣 Build B — your Codespaces dev-container sandbox", """A full VS Code + Linux machine in your browser, tied to a repo. The code runs on GitHub's servers. Free up to a monthly limit; the Student Pack adds more.

1. Get the free **GitHub Student Developer Pack** with your Baruch email: **education.github.com/pack**
2. Copy the folder **sandbox/.devcontainer/** from `tldpprojectscout/project-scout` into the repo you want to try (or into your own template repo). It builds an Ubuntu container that runs as a **non-root** user with **capped CPU/memory** and **no-new-privileges** — a reproducible, least-privilege sandbox.
3. On that repo: green **Code** button → **Codespaces** tab → **Create codespace on main**.
4. VS Code opens in the browser with Python + Node ready. Run the project there.
5. Done? Go to **github.com/codespaces** and **delete** the codespace so it stops using your quota.

Prefer it on your own machine? Install **Podman Desktop** (free) + VS Code Dev Containers, open the repo, "Reopen in Container". A local container is weaker than the cloud (it shares your kernel) but still sealed and disposable.

Then post: "Built my Codespaces sandbox ✅"."""),
        ("✅ Post here once you've built it", """Reply to this thread (or start your own post) with:
• Which sandbox you built — **Colab** or **Codespaces**.
• One repo you ran inside it and what it did.

That's your proof you can run unfamiliar code safely — a real habit employers care about. Help a classmate who's stuck; walking someone through it counts too.""")],
    "🧰│safe-sandboxes": [
        ("📌 Read first — why a sandbox, and the rules", """A repo passing our automated checks is **not** proof it is safe to run. Checks reduce risk; they do not remove it. So before you run code you did not write, run it somewhere that is not your real laptop.

**The rules (they matter more than any tool):**
1. **Best option: keep the code off your machine entirely.** Use a browser sandbox — start with **Google Colab** (next post). Nothing installs, nothing can touch your files.
2. **Never put secrets in a sandbox.** No passwords, no API keys, no `.env` files, no personal data. A sandbox holding your real GitHub login is no longer protecting your GitHub.
3. **Use public or synthetic data only.**
4. **Treat it as disposable.** When you are done, delete the session. Do not save personal files inside it.
5. **A container or VM limits damage but is not a perfect wall.** The strongest rule is simply: do not run unfamiliar code on hardware you care about.
6. **See a suspicious link or install step?** Do not click or run it. Post it for staff instead.

**Which free tool?**
• **Google Colab** — completely free, no bill possible, just a Google account. Best for Python, data, notebooks. **Start here.**
• **Binder** — completely free, no account at all, fully disposable. Great for trying a public repo instantly; sessions are short.
• **GitHub Codespaces** — the most powerful, runs full apps in VS Code. Free up to a monthly limit, so not strictly "no cost," but you won't hit it easily and it won't surprise-bill you."""),
        ("🟢 Google Colab — completely free, start here", """**What it is:** a free notebook that runs on Google's computers, in your browser. Your laptop only shows the results, so bad code cannot touch your files. Best for anything Python, data, or machine learning.

**Set it up (2 minutes, no install):**
1. Go to **colab.research.google.com** and sign in with a Google account.
2. Click **New notebook**.
3. To run code from a repo, in a cell type a command starting with `!` to fetch it, then run the files. Example for a public repo:
```
!git clone https://github.com/OWNER/REPO
%cd REPO
!pip install -r requirements.txt
```
4. Run cells with **Shift+Enter**. Everything happens on Google's machine.
5. When you finish, close the tab or **Runtime → Disconnect and delete runtime**. Gone.

**Remember:** public/synthetic data only, and never paste a real password or API key into a cell. Post here if you get stuck."""),
        ("🔵 Binder — instant, no account, fully disposable", """**What it is:** launches any public GitHub repo in a free, throwaway Jupyter environment. No sign-up, nothing tied to you. Perfect for a quick, safe look at a repo. Sessions are short and low-powered, and they vanish when you close them.

**Use it (1 minute):**
1. Go to **mybinder.org**.
2. Paste the repo URL (for example `https://github.com/OWNER/REPO`) into the GitHub box.
3. Click **launch**. Wait for it to build, then it opens a notebook environment.
4. Explore and run. Close the tab when done — it is destroyed automatically.

**Note:** Binder works best on repos set up for it; some repos will open but not install everything. If it struggles, use Colab. Same rules: public/synthetic data only, no secrets."""),
        ("🟣 GitHub Codespaces — for full projects (free monthly quota)", """**What it is:** a full VS Code and Linux machine in your browser, tied to a repo. The most powerful option — it can run web apps, databases, and real projects — and the code still runs on GitHub's servers, not your laptop.

**Cost, honestly:** free up to a monthly amount of hours and storage on a personal account, and more through the **GitHub Student Developer Pack** (education.github.com/pack). Past the free amount it can bill, but GitHub stops you at the limit rather than surprising you, and beginners rarely hit it. If you want zero chance of a charge, use Colab or Binder.

**Set it up:**
1. Get the **Student Developer Pack** first (free, uses your Baruch email): education.github.com/pack
2. Open any repo on GitHub → green **Code** button → **Codespaces** tab → **Create codespace on main**.
3. It opens VS Code in the browser with the repo loaded. Run it there.
4. When done, go to **github.com/codespaces** and **delete** the codespace so it stops using your quota.

**Remember:** do not add real secrets; use the repo's example/sample env values. Ask here if you get stuck.""")],
    "🐙│github-academy": [
        ("Run it safely — sandbox before you run anyone's code", """Before Week 0, one habit that protects your laptop: **never run code you did not write on your real machine first.** A repo passing our checks is not proof it is safe.

**Do this instead:** open it in a free browser sandbox so bad code cannot touch your files.
• **Google Colab** (colab.research.google.com) — completely free, just a Google account. Best for Python and data. **Start here.**
• **Binder** (mybinder.org) — completely free, no account, disposable. Paste a repo URL and go.
• **GitHub Codespaces** — most powerful, free within a monthly limit via the Student Pack (education.github.com/pack).

Full step-by-step setup and the safety rules are pinned in **🧰│safe-sandboxes**. Two rules to remember everywhere: use **public or synthetic data only**, and **never put a password, API key or `.env` file** into a sandbox.

An automated check reduces risk; it does not make a project safe to run. Read code before you run it, and prefer a sandbox for anything unfamiliar."""),
        ("Week 0 — GitHub in one hour (start here)", """No installs needed for this one. Everything runs in the browser.

1. **Watch:** Git and GitHub for Beginners – Crash Course (freeCodeCamp, 1 h) — https://www.youtube.com/watch?v=RGOj5yH7evk
2. **Do:** GitHub's own interactive course, *Introduction to GitHub* (about 30 min, runs in your account) — https://github.com/skills/introduction-to-github
3. **Read:** the Hello World guide (repo → branch → commit → pull request → merge) — https://docs.github.com/en/get-started/start-your-journey/hello-world

**Done when:** you have a repo of your own with a README, one branch, one merged pull request. Post the link in this thread."""),
        ("Week 1 — Git on your laptop", """1. **Install:** GitHub Desktop (easiest) — https://desktop.github.com/ — or Git itself — https://git-scm.com/downloads
2. **Learn the moves visually:** Learn Git Branching (interactive, do the first two sections) — https://learngitbranching.js.org/
3. **Read:** Pro Git book, chapters 1–3 (free) — https://git-scm.com/book/en/v2
4. **Keep handy:** the official Git cheat sheet — https://education.github.com/git-cheat-sheet-education.pdf
5. **Write good commits:** How to Write a Git Commit Message — https://cbea.ms/git-commit/

**Done when:** you can clone, make a branch, commit, push and see it on GitHub — from your own laptop."""),
        ("Week 2 — Your first pull request to someone else's repo", """1. **Practice the whole flow safely:** First Contributions (a repo built for this; takes 15 min) — https://github.com/firstcontributions/first-contributions
2. **Learn to READ pull requests:** GitHub Skills *Review pull requests* — https://github.com/skills/review-pull-requests
3. **Fix the scary thing on purpose:** GitHub Skills *Resolve merge conflicts* — https://github.com/skills/resolve-merge-conflicts
4. **Find a real one:** the feed forums post repos with *good first issues* every 6 hours, or search /scout lane:Contribute in #scout-search.

**Etiquette:** comment on the issue before you start · one issue per PR · describe what and why · be patient with maintainers.
**Done when:** you have opened one pull request on a repo you don't own. Post the link here and in #show-your-work."""),
        ("Week 3 — Make your GitHub look employable", """1. **Profile README** (the page recruiters see): GitHub Skills *Communicate using Markdown* — https://github.com/skills/communicate-using-markdown — then create a repo named exactly like your username and put a README in it.
2. **A project page** for your best repo: GitHub Skills *GitHub Pages* — https://github.com/skills/github-pages
3. **Free tools as a student:** GitHub Student Developer Pack (Copilot, cloud credits, domains) — https://education.github.com/pack
4. **Every repo you show:** README with what it does + how to run it, a `.gitignore`, no secrets in the code, a license.
5. **More courses when you want them:** https://skills.github.com/

**Done when:** your profile has a README, at least three pinned repos with real READMEs, and your LinkedIn links to it."""),
    ],
}
OLD_FEED_NAMES = {"data-analytics", "swe", "cybersecurity", "quant", "finance-fintech", "project-management",
                  "digital-marketing", "open-source-orgs"}  # pre-forum text channels; replaced

WELCOME = """**Welcome to TLDP_2026_2027** 🎓

Private server for the 45 TLDP students. Please don't share the invite link.

**Step 1 — unlock the server:** you joined with a personal, single-use invite from TLDP staff, so you're on the list. Post in #introductions with your name and major; a staff member gives you the **TLDP Student** role and your major role. (Typing a name proves nothing, so the bot never grants access by name.)

**Step 2 — build your sandbox BEFORE you run any project.** This is the most important habit: a repo passing our automated checks is *not* proof it is safe to run. So run other people's code in a free, disposable sandbox, never on your real laptop. Go to **🛠️ build-your-sandbox** and follow the "do this first" post. **Google Colab** is completely free and the best place to start. Do this once and reuse it all year.

**What's here once you're in**
• **🛠️ build-your-sandbox / 🧰 safe-sandboxes** — set up a free sandbox first (Colab, Binder or Codespaces) so nothing you run can touch your machine. Do this before browsing the feed.
• **Feed forums** (📊 data-analytics · 💻 swe · 🔐 cybersecurity · 📈 quant · 💳 finance-fintech · 📋 project-management · 📣 digital-marketing) — every 6 hours the Project Scout bot opens a post with fresh GitHub repos for that major: things to build, open-source repos with *good first issues*, and new paper code. Each row shows 🟢 starter / 🟡 intermediate / 🔴 advanced.
• **React 🙋 on a post to claim it.** Every Friday the bot lists who claimed what in #find-a-team so you can team up.
• **🤝 open-source-orgs** — non-profit, public-sector and company repos that welcome contributors, with a LinkedIn link and a ready-to-paste resume line.
• **#scout-search** — search on demand: `/scout major:Cybersecurity`, `/scout lane:Contribute major:Data Analytics`, `/scout lane:Orgs keywords:python`.
• **#show-your-work** — post merged PRs and demos. Friday leaderboard lives here.
• **#announcements** — staff posts.
• **🧑‍💻 code-review-practice / 🛡️ cyber-review-practice** — post code, write-ups or a short video and get an interview-style review (3-2-1 format, rubric pinned). Reviewing others counts too.
• **🐙 github-academy** — new to GitHub? Four short weekly lessons, videos and tutorials, in order. Start at Week 0.

**Spring requirements (both graded)**
• **🏁 nyc-hackathons** — attend one in-person hackathon in the NYC area. New listings from Devpost and MLH land here automatically; reply in a post to find teammates.
• **🎓 capstone** — your capstone project, judged in spring. Post your idea, your repo, and weekly progress there.
• **📁 case-studies** — contribute to real case collections (Tidy Tuesday, Atomic Red Team, Sigma, OWASP, Open Case Studies…) and write one case of your own in the TLDP case library on GitHub. Merged cases are announced here with your name.

**Start now:** introduce yourself in #introductions, **build your sandbox in 🛠️ build-your-sandbox**, then pick one repo this week and open one good-first-issue PR.

**A note on safety:** every repo the feed shows has completed automated checks, but *automated checks are not a safety guarantee.* Use public or synthetic data only — never put passwords, API keys, `.env` files or personal data in a repo or message. Report suspicious links to staff instead of clicking. **Read code before you run it, and run anything unfamiliar in a free browser sandbox — see 🧰 safe-sandboxes (start with Google Colab, completely free).**
"""


def api(method, path, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json",
                                          "User-Agent": "project-scout (github.com/tldpprojectscout/project-scout, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r) if r.status != 204 else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}")


def icon_png() -> str | None:
    """512x512 'TLDP' icon as a data URI (needs Pillow); None if Pillow is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    im = Image.new("RGB", (512, 512), (88, 101, 242))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arialbd.ttf", 150)
    except OSError:
        font = ImageFont.load_default()
    d.text((256, 230), "TLDP", fill="white", font=font, anchor="mm")
    d.text((256, 350), "2026–27", fill=(220, 224, 255), font=ImageFont.truetype("arial.ttf", 60) if font else font, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def staff(names: list[str]) -> int:
    """--staff "Nii Ato" "Cristina": give the TLDP Staff role to members whose username/display name matches."""
    role = next(r for r in api("GET", f"/guilds/{GUILD}/roles") if r["name"] == "TLDP Staff")
    for name in names:
        q = name.split()[0]
        hits = api("GET", f"/guilds/{GUILD}/members/search?query={urllib.parse.quote(q)}&limit=10")
        low = name.lower()
        hit = next((m for m in hits if low in " ".join(filter(None, [m["user"]["username"], m["user"].get("global_name"), m.get("nick")])).lower()), None) \
            or (hits[0] if len(hits) == 1 else None)
        if not hit:
            print(f"{name}: not in the server yet (send them an invite, then rerun)")
            continue
        api("PUT", f"/guilds/{GUILD}/members/{hit['user']['id']}/roles/{role['id']}")
        print(f"{name}: TLDP Staff granted to @{hit['user']['username']}")
    return 0


def invites(n: int) -> int:
    chans = {c["name"]: c for c in api("GET", f"/guilds/{GUILD}/channels")}
    print("student_number,invite_url")
    for i in range(1, n + 1):
        inv = api("POST", f"/channels/{chans['welcome']['id']}/invites", {"max_age": 7 * 86400, "max_uses": 1, "unique": True})
        print(f"{i},https://discord.gg/{inv['code']}")
    return 0


def main() -> int:
    if not TOKEN or not GUILD:
        print(__doc__)
        return 1
    if "--invites" in sys.argv:
        return invites(int(sys.argv[sys.argv.index("--invites") + 1]))
    if "--staff" in sys.argv:
        return staff(sys.argv[sys.argv.index("--staff") + 1:])
    print("guild:", api("GET", f"/guilds/{GUILD}")["name"])

    # 1. server hardening + icon
    patch = {"verification_level": 2, "default_message_notifications": 1}
    icon = icon_png()
    if icon:
        patch["icon"] = icon
    api("PATCH", f"/guilds/{GUILD}", patch)
    roles = {r["name"]: r for r in api("GET", f"/guilds/{GUILD}/roles")}
    everyone = roles["@everyone"]
    api("PATCH", f"/guilds/{GUILD}/roles/{everyone['id']}", {"permissions": str(int(everyone["permissions"]) & ~CREATE_INVITE)})
    bot_role = next((r for r in roles.values() if r.get("tags", {}).get("bot_id") == APP_ID), None)
    print("server: verification=medium, invites staff-only, icon", "set" if icon else "skipped (no Pillow)")

    # 2. roles
    def role(name, perms, color, hoist=False):
        if name not in roles:
            roles[name] = api("POST", f"/guilds/{GUILD}/roles", {"name": name, "permissions": str(perms), "color": color,
                                                                 "hoist": hoist, "mentionable": True})
            print("role:", name)
        return roles[name]
    staff = role("TLDP Staff", STAFF_PERMS, 0x5865F2, hoist=True)
    student = role("TLDP Student", 0, 0x57F287, hoist=True)
    major_ids = {k: role(n, 0, c)["id"] for k, (n, c) in MAJOR_ROLES.items()}

    # 3. channels
    gate = [{"id": everyone["id"], "type": 0, "deny": str(VIEW)},
            {"id": student["id"], "type": 0, "allow": str(VIEW)},
            {"id": staff["id"], "type": 0, "allow": str(VIEW)}]
    if bot_role:
        gate.append({"id": bot_role["id"], "type": 0, "allow": str(VIEW)})
    existing = {c["name"]: c for c in api("GET", f"/guilds/{GUILD}/channels")}
    for old in OLD_FEED_NAMES | {"general", "General"}:
        if old in existing and existing[old]["type"] in (TEXT, VOICE):
            api("DELETE", f"/channels/{existing.pop(old)['id']}")
            print("replaced old channel:", old)
    webhooks = {}
    for idx, (cat, (gated, chans)) in enumerate(LAYOUT.items()):
        parent = existing.get(cat) or api("POST", f"/guilds/{GUILD}/channels", {"name": cat, "type": CATEGORY, "position": idx})
        existing[cat] = parent
        api("PATCH", f"/channels/{parent['id']}", {"permission_overwrites": gate if gated else [], "position": idx})
        for name, topic, ctype, key in chans:
            ch = existing.get(name)
            body = {"name": name, "type": ctype, "parent_id": parent["id"]}
            if ctype != VOICE:
                body["topic"] = topic
            body["permission_overwrites"] = list(gate) if gated else []
            if name == "announcements":
                body["permission_overwrites"] = [{"id": everyone["id"], "type": 0, "deny": str(SEND)}]
            if not ch:
                ch = existing[name] = api("POST", f"/guilds/{GUILD}/channels", body)
                print("channel:", name)
            else:
                api("PATCH", f"/channels/{ch['id']}", {k: v for k, v in body.items() if k != "type"})
            if key:  # 4. webhooks
                hooks = api("GET", f"/channels/{ch['id']}/webhooks")
                hook = next((h for h in hooks if h["name"] == "Project Scout"), None) or \
                    api("POST", f"/channels/{ch['id']}/webhooks", {"name": "Project Scout"})
                webhooks[key] = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"

    # 4b. seed posts in the practice forums (once)
    for name, posts in SEED.items():
        ch = existing[name]
        have = {t["name"] for t in api("GET", f"/channels/{ch['id']}/threads/archived/public").get("threads", [])} | \
               {t["name"] for t in api("GET", f"/guilds/{GUILD}/threads/active").get("threads", []) if t.get("parent_id") == ch["id"]}
        for title, body in posts:
            if title in have:
                continue
            api("POST", f"/channels/{ch['id']}/threads", {"name": title[:100], "message": {"content": body}, "auto_archive_duration": 10080})
            print("seed post:", title)

    # 5. invite + welcome (reused on rerun)
    welcome = existing["welcome"]
    inv = next((i for i in api("GET", f"/guilds/{GUILD}/invites") if i.get("max_uses") == MAX_STUDENTS), None) or \
        api("POST", f"/channels/{welcome['id']}/invites", {"max_age": 7 * 86400, "max_uses": MAX_STUDENTS, "unique": True})
    old_msgs = api("GET", f"/channels/{welcome['id']}/messages?limit=5")
    for m in old_msgs:  # refresh the welcome text on rerun
        if m.get("author", {}).get("id") == APP_ID:
            api("DELETE", f"/channels/{welcome['id']}/messages/{m['id']}")
    parts, cur = [], ""  # Discord caps a message at 2000 chars: split on paragraphs, pin the first
    for para in WELCOME.split("\n\n"):
        if len(cur) + len(para) + 2 > 1900:
            parts.append(cur); cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    parts.append(cur)
    msg = api("POST", f"/channels/{welcome['id']}/messages", {"content": parts[0]})
    for part in parts[1:]:
        api("POST", f"/channels/{welcome['id']}/messages", {"content": part})
    try:
        api("PUT", f"/channels/{welcome['id']}/messages/pins/{msg['id']}")
    except SystemExit as e:
        print("pin skipped:", e)

    print(f"\nINVITE (45 uses, 7 days): https://discord.gg/{inv['code']}")
    print("\nRepo secret (feed -> per-channel):")
    print("gh secret set DISCORD_WEBHOOKS -R tldpprojectscout/project-scout -b '" + json.dumps(webhooks) + "'")
    print("\nWorker secrets for /verify (wrangler secret bulk -c wrangler.discord.toml):")
    print(json.dumps({"STUDENT_ROLE_ID": student["id"], "MAJOR_ROLES": json.dumps(major_ids),
                      "SHOW_YOUR_WORK_ID": existing["show-your-work"]["id"], "FIND_A_TEAM_ID": existing["find-a-team"]["id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
