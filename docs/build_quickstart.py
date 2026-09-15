#!/usr/bin/env python3
"""
build_quickstart.py — ONE-PAGE Quick Start for TLDP students (goes out with the invite).

  python docs/build_quickstart.py [path/to/server_screenshot.png]

Writes docs/TLDP_Quick_Start.pdf (gitignored: it holds the invite link). The long reference guide is
docs/build_guide.py. Reads DISCORD_INVITE from ../secrets_local.py or env. Needs xhtml2pdf.
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
SHOT = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "docs" / "server.png")
shot_html = f'<img src="{SHOT}" style="width:17cm"/>' if Path(SHOT).exists() else ""

HTML = f"""
<html><head><style>
  @page {{ size: letter; margin: 1.4cm 1.6cm; }}
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; color: #1f2328; line-height: 1.35; }}
  h1 {{ color: #5865F2; font-size: 22pt; margin: 0 0 2pt 0; }}
  .sub {{ color: #57606a; margin: 0 0 8pt 0; }}
  h2 {{ color: #5865F2; font-size: 12.5pt; margin: 10pt 0 4pt 0; }}
  .step {{ margin: 0 0 5pt 0; }}
  .n {{ display: inline-block; background: #5865F2; color: white; font-weight: bold; padding: 1pt 6pt; margin-right: 6pt; }}
  code {{ font-family: Courier, monospace; background: #eef1f4; padding: 1pt 3pt; font-size: 10pt; }}
  .cmd {{ background: #f6f8fa; border: 1px solid #d0d7de; padding: 6pt 9pt; margin: 4pt 0; }}
  .cap {{ font-size: 9pt; color: #57606a; margin: 2pt 0 6pt 0; }}
  .gl td {{ font-size: 9.5pt; padding: 1pt 6pt 1pt 0; vertical-align: top; }}
  .warn {{ background: #fff8c5; border: 1px solid #d4a72c; padding: 4pt 8pt; font-size: 9.5pt; margin-top: 6pt; }}
</style></head><body>

<h1>TLDP_2026_2027 on Discord — Quick Start</h1>
<p class="sub">Five minutes to join. The bot finds real GitHub projects for your major so you can build, contribute, and put it on your resume.</p>

<h2>Join in 5 steps</h2>
<div class="step"><span class="n">1</span> Get a Discord account at <b>discord.com/register</b> (or the app). Use a display name with your real first name. <b>Verify your email</b> — click the link Discord sends you.</div>
<div class="step"><span class="n">2</span> Open your invite: <b>{INVITE}</b> → <b>Accept Invite</b>. The server appears in the left column.</div>
<div class="step"><span class="n">3</span> In any channel type <code>/verify name:Your Full Name major:Your Major</code> and press Enter. Use the name TLDP has on file. All channels unlock.</div>
<div class="step"><span class="n">4</span> Open the forum for your major (📊 data-analytics, 💻 swe, 🔐 cybersecurity, 📈 quant, 💳 finance-fintech, 📋 project-management, 📣 digital-marketing) and read the pinned <b>📚 Start here</b> post.</div>
<div class="step"><span class="n">5</span> Say hi in <b>#introductions</b>: name, major, what you want to build.</div>

{shot_html}
<p class="cap">Left: your servers. Middle: channels — START HERE, the PROJECT SCOUT FEED forums (one post per drop, every 6 h), COLLABORATE. Right: the posts. Tap a post to discuss it; react 🙋 to claim it.</p>

<h2>Three commands to know (type them in #scout-search)</h2>
<div class="cmd"><code>/scout lane:Start here major:Cybersecurity</code> — curated idea lists, roadmaps and beginner basics. <b>Use this first.</b></div>
<div class="cmd"><code>/scout major:Cybersecurity keywords:honeypot</code> — fresh repos matching a keyword (any major, any keyword).</div>
<div class="cmd"><code>/scout lane:Contribute major:Data Analytics</code> — active open-source projects with beginner-friendly issues, plus a resume line.</div>

<h2>Words you'll see</h2>
<table class="gl">
<tr><td><b>Repo</b></td><td>a project's folder on GitHub: code + README.</td><td><b>README</b></td><td>the front page of a repo. Read it first.</td></tr>
<tr><td><b>Good first issue</b></td><td>a small task the maintainers marked as beginner-friendly.</td><td><b>Fork</b></td><td>your own copy of a repo to work in.</td></tr>
<tr><td><b>Pull request (PR)</b></td><td>you sending your change back to the project. A merged PR = real experience.</td><td><b>🟢 🟡 🔴</b></td><td>starter / intermediate / advanced, by repo size and stars.</td></tr>
</table>

<div class="warn">Private server for TLDP students only — don't forward the invite. Stuck? Post in <b>#help</b>. Name not on the roster? Post in <b>#introductions</b> and staff will let you in.</div>
</body></html>
"""


def main() -> int:
    from xhtml2pdf import pisa
    out = ROOT / "docs" / "TLDP_Quick_Start.pdf"
    with open(out, "wb") as f:
        status = pisa.CreatePDF(HTML, dest=f, encoding="utf-8")
    print("error" if status.err else f"wrote {out} (screenshot: {'yes' if shot_html else 'MISSING'})")
    return 1 if status.err else 0


if __name__ == "__main__":
    raise SystemExit(main())
