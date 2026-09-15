#!/usr/bin/env python3
"""
build_guide.py — render the TLDP student Discord guide to PDF.

  python docs/build_guide.py            # writes docs/TLDP_Discord_Guide.pdf (gitignored: it holds the invite link)

Reads DISCORD_INVITE from ../secrets_local.py (or env). Uses xhtml2pdf (pip install xhtml2pdf).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    import secrets_local as s
except ImportError:
    s = None
INVITE = os.environ.get("DISCORD_INVITE") or getattr(s, "DISCORD_INVITE", "https://discord.gg/<ask-your-TLDP-lead>")

HTML = f"""
<html><head><style>
  @page {{ size: letter; margin: 2cm; }}
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #1f2328; line-height: 1.45; }}
  h1 {{ color: #5865F2; font-size: 24pt; margin-bottom: 4pt; }}
  h2 {{ color: #5865F2; font-size: 15pt; border-bottom: 1px solid #d0d7de; padding-bottom: 3pt; margin-top: 22pt; }}
  h3 {{ font-size: 12pt; margin-top: 14pt; }}
  .sub {{ color: #57606a; font-size: 11pt; margin-top: 0; }}
  .box {{ background: #f6f8fa; border: 1px solid #d0d7de; padding: 10pt 12pt; margin: 10pt 0; }}
  .warn {{ background: #fff8c5; border: 1px solid #d4a72c; padding: 8pt 12pt; margin: 10pt 0; }}
  code {{ font-family: Courier, monospace; background: #eef1f4; padding: 1pt 3pt; font-size: 10pt; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8pt 0; }}
  th, td {{ border: 1px solid #d0d7de; padding: 5pt 7pt; text-align: left; vertical-align: top; font-size: 10pt; }}
  th {{ background: #eef1f4; }}
  ol li, ul li {{ margin-bottom: 4pt; }}
  .small {{ font-size: 9pt; color: #57606a; }}
</style></head><body>

<h1>TLDP_2026_2027 on Discord</h1>
<p class="sub">Student guide: sign in, join, find your channels, and use the Project Scout bot to find real projects for your resume.</p>

<div class="warn"><b>Private server for TLDP students only.</b> Your invite link below works 45 times and expires 7 days after it was created. Do not forward it.</div>

<h2>1. Create a Discord account (skip if you have one)</h2>
<ol>
  <li>Go to <b>discord.com/register</b> (or install the Discord app from the App Store / Google Play / discord.com/download).</li>
  <li>Sign up with an email you check. Pick a display name that includes your real first name so classmates and staff recognize you.</li>
  <li><b>Verify your email.</b> Open the confirmation email from Discord and click the link. The server requires a verified email before you can post.</li>
  <li>Recommended: Settings &rarr; My Account &rarr; enable two-factor authentication.</li>
</ol>

<h2>2. Join the TLDP server and unlock it</h2>
<ol>
  <li>While signed in, open this link: <b>{INVITE}</b></li>
  <li>Click <b>Accept Invite</b>. The server "TLDP_2026_2027" appears in the left rail (the column of round icons). You will only see the START HERE channels at first.</li>
  <li>In any channel, type <code>/verify name:Your Full Name major:Your Major</code> and press Enter. Use the name TLDP has on file. The bot checks the TLDP roster and gives you the <b>TLDP Student</b> role plus your major role. All channels unlock immediately.</li>
  <li>If the bot says your name is not on the roster, post in <b>#introductions</b> and staff will let you in by hand.</li>
  <li>If Discord asks you to wait 10 minutes before posting, that is the server's verification level. Read #welcome meanwhile.</li>
  <li>Post one line in <b>#introductions</b>: name, major, and what you want to build this semester.</li>
</ol>

<h2>3. Finding your way around</h2>
<div class="box">
<b>Left rail</b> = your servers &nbsp;|&nbsp; <b>Channel list</b> = the rooms inside TLDP_2026_2027 &nbsp;|&nbsp; <b>Main pane</b> = messages &nbsp;|&nbsp; <b>Right pane</b> = member list.<br/>
Text channels start with <b>#</b>. Voice channels have a speaker icon: click to join, click "Disconnect" to leave.
</div>
<table>
<tr><th>Category</th><th>Channel</th><th>What it is for</th></tr>
<tr><td rowspan="3">START HERE</td><td>#welcome</td><td>Rules and how the bot works. Read first.</td></tr>
<tr><td>#announcements</td><td>Staff posts, the weekly "pick of the week", and hackathons closing soon (Fridays). Turn notifications on for this one.</td></tr>
<tr><td>#introductions</td><td>Say hi: name, major, goal.</td></tr>
<tr><td rowspan="8">PROJECT SCOUT FEED<br/><span class="small">(forums: each drop is its own post)</span></td><td>📊 data-analytics</td><td rowspan="7">Every 6 hours the bot opens a new post with fresh GitHub repos for that major: things to build, open-source repos with open <i>good first issue</i> tickets, and brand-new paper code. Each repo is tagged 🟢 starter, 🟡 intermediate or 🔴 advanced. Open the post to discuss it. <b>React 🙋 on a post to claim it</b>; every Friday the bot lists who claimed what in #find-a-team so you can team up.</td></tr>
<tr><td>💻 swe</td></tr>
<tr><td>🔐 cybersecurity</td></tr>
<tr><td>📈 quant</td></tr>
<tr><td>💳 finance-fintech</td></tr>
<tr><td>📋 project-management</td></tr>
<tr><td>📣 digital-marketing</td></tr>
<tr><td>🤝 open-source-orgs</td><td>Non-profit, public-sector and company repos that welcome contributors. Each post includes a LinkedIn link and a ready-to-paste resume line.</td></tr>
<tr><td rowspan="5">COLLABORATE</td><td>#scout-search</td><td>Search on demand with <code>/scout</code> (see section 4).</td></tr>
<tr><td>#find-a-team</td><td>Post the repo you picked and who you need. Teams of 2 to 4 work best.</td></tr>
<tr><td>#show-your-work</td><td>Merged pull requests, demos, and the resume line you earned. Every Friday the bot posts a leaderboard of who shared the most links here.</td></tr>
<tr><td>#help</td><td>Stuck on git, a pull request, or setup? Ask here.</td></tr>
<tr><td>#general-chat</td><td>Everything else.</td></tr>
<tr><td>STUDY ROOMS</td><td>Study Room 1 / 2</td><td>Voice rooms for co-working. Mute when you are not talking.</td></tr>
</table>

<h2>4. Using the Project Scout bot</h2>
<p>Type <code>/scout</code> in <b>#scout-search</b> and Discord shows a form with three optional fields:</p>
<table>
<tr><th>Field</th><th>Choices</th><th>Example</th></tr>
<tr><td><b>major</b></td><td>Quant, Finance / FinTech, Software Engineering, Cybersecurity, Data Analytics, Project Management, Digital Marketing</td><td><code>/scout major:Cybersecurity</code></td></tr>
<tr><td><b>lane</b></td><td>Build this (fresh repos, default) &middot; Contribute (good first issues) &middot; Research (fresh paper code) &middot; Orgs (non-profit / public / private sector)</td><td><code>/scout lane:Contribute major:Data Analytics</code></td></tr>
<tr><td><b>keywords</b></td><td>Anything: a tool, a topic, a dataset</td><td><code>/scout major:Quant keywords:options pricing</code></td></tr>
</table>
<p>Each result shows the repo name, stars, language, a one-line description and the link. Keyword searches pull from GitHub and GitLab (GitLab rows are tagged). Results are cached for 15 minutes, so if a search says "try again shortly", wait a minute.</p>

<h3>Suggested weekly loop</h3>
<ol>
  <li><b>Monday:</b> skim your major's feed channel. Pick one repo that excites you.</li>
  <li><b>Tuesday:</b> run <code>/scout lane:Contribute major:&lt;yours&gt;</code>, open the "good first issues" link, claim one issue by commenting on it.</li>
  <li><b>Wednesday to Friday:</b> fork, fix, open a pull request. Ask in #help if stuck.</li>
  <li><b>When it merges:</b> post the PR in #show-your-work and add the resume line from #open-source-orgs to your resume, for example "Open-Source Contributor, NASA (osal)".</li>
</ol>

<h2>5. Putting it on your resume and LinkedIn</h2>
<p>An open-source contribution counts as experience when it is specific and verifiable. Use this shape, one line per project, newest first, under a heading like <b>Open-Source Contributions</b> or inside <b>Projects</b>:</p>
<div class="box">
<b>Open-Source Contributor, OWASP (wstg)</b> &nbsp;·&nbsp; Sep 2026 – present<br/>
&bull; Fixed 3 documentation and test issues in the Web Security Testing Guide (Python, Markdown); 2 pull requests merged by maintainers.<br/>
&bull; github.com/OWASP/wstg/pulls?q=author:yourhandle
</div>
<div class="box">
<b>Open-Source Contributor, NASA (cFS)</b> &nbsp;·&nbsp; Oct 2026<br/>
&bull; Resolved a "good first issue" in the Core Flight System build scripts (C, CMake); added a regression test; merged after review.<br/>
&bull; Skills shown: reading a large C codebase, Git workflow, code review etiquette.
</div>
<ul>
  <li>Say what you did in numbers: pull requests merged, issues closed, tests added.</li>
  <li>Name the language and the tool. Recruiters search resumes for exact words like "Python", "Git", "CMake".</li>
  <li>Link the pull request list. That link is proof no interviewer can argue with.</li>
  <li>On LinkedIn: add the project under <b>Projects</b>, link the repo, and post a two-line update when a pull request merges. Follow the organization's LinkedIn page from the link in #open-source-orgs and mention them in the post.</li>
  <li>Never claim more than the merged work. One real merged pull request beats five "in progress".</li>
</ul>

<h2>6. House rules</h2>
<ul>
  <li>Be the colleague you would want. No harassment, no spam, no sharing of the invite link.</li>
  <li>Use real names or recognizable display names. Staff may remove unrecognized accounts.</li>
  <li>Respect each project's contribution guidelines. Read CONTRIBUTING.md before opening a pull request.</li>
  <li>Problems with the server or the bot: post in #help or message a member with the <b>TLDP Staff</b> role.</li>
</ul>

<h2>7. Quick fixes</h2>
<table>
<tr><th>Symptom</th><th>Fix</th></tr>
<tr><td>I only see #welcome, #announcements and #introductions</td><td>You have not verified yet. Run <code>/verify name:Your Full Name</code>. Still locked? Post in #introductions.</td></tr>
<tr><td>Invite says "invalid or expired"</td><td>The 7-day link expired or 45 uses were reached. Ask your TLDP lead for a fresh link.</td></tr>
<tr><td>Cannot post</td><td>Verify your email (Settings &rarr; My Account), then wait 10 minutes after joining.</td></tr>
<tr><td><code>/scout</code> does not appear when typing</td><td>Make sure you are typing in a text channel inside TLDP_2026_2027, then type the slash and wait a second for the menu.</td></tr>
<tr><td>Too many notifications</td><td>Right-click the server icon &rarr; Notification Settings &rarr; "Only @mentions". Then turn notifications on for #announcements and your major's channel only.</td></tr>
</table>

<p class="small">Project Scout is open source: github.com/thecyberthriver/project-scout. The bot only reads public GitHub and GitLab data; it never scrapes LinkedIn or stores anything about you.</p>
</body></html>
"""


def main() -> int:
    from xhtml2pdf import pisa
    out = ROOT / "docs" / "TLDP_Discord_Guide.pdf"
    (ROOT / "docs" / "TLDP_Discord_guide.html").write_text(HTML, encoding="utf-8")
    with open(out, "wb") as f:
        status = pisa.CreatePDF(HTML, dest=f, encoding="utf-8")
    print("error" if status.err else f"wrote {out}")
    return 1 if status.err else 0


if __name__ == "__main__":
    raise SystemExit(main())
