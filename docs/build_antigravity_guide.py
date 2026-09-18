#!/usr/bin/env python3
"""
build_antigravity_guide.py — Generates a beautifully styled, readable 3-page PDF guide
for TLDP students on installing, configuring, and using Google Antigravity (IDE & CLI),
including the 1-year free Google AI Pro student offer, Windows execution policy troubleshooting,
and MCP server integration.
Outputs to docs/ and directly to the user's Desktop.
"""

import os
import shutil
import sys
from pathlib import Path
from xhtml2pdf import pisa

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DOCS_PDF = ROOT / "docs" / "TLDP_Antigravity_Guide.pdf"
OUTPUT_HTML = ROOT / "docs" / "TLDP_Antigravity_Guide.html"
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
OUTPUT_DESKTOP_PDF = DESKTOP_DIR / "TLDP_Antigravity_Guide.pdf"

HTML_CONTENT = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {
    size: letter;
    margin: 1.1cm 1.4cm;
  }

  body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 8.8pt;
    color: #333f48;
    line-height: 1.36;
  }

  h1 {
    color: #5865F2;
    font-size: 16pt;
    margin: 0 0 2pt 0;
    font-weight: bold;
  }

  .subtitle {
    color: #64748b;
    font-size: 9.5pt;
    margin-top: 0;
    margin-bottom: 7pt;
    border-bottom: 2px solid #5865F2;
    padding-bottom: 3pt;
  }

  h2 {
    color: #5865F2;
    font-size: 11pt;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 2pt;
    margin-top: 8pt;
    margin-bottom: 3pt;
    font-weight: bold;
  }

  h3 {
    color: #3b4252;
    font-size: 9.3pt;
    margin-top: 6pt;
    margin-bottom: 2pt;
    font-weight: bold;
  }

  p {
    margin: 2pt 0 4pt 0;
    color: #333f48;
  }

  ul, ol {
    margin-top: 2pt;
    margin-bottom: 4pt;
    padding-left: 15pt;
  }

  li {
    margin-bottom: 2pt;
    color: #333f48;
  }

  .label {
    color: #1e293b;
    font-weight: bold;
  }

  code {
    font-family: Courier, monospace;
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    padding: 0.5pt 2.5pt;
    font-size: 8.2pt;
    color: #b91c1c;
  }

  pre {
    font-family: Courier, monospace;
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    padding: 3.5pt 6pt;
    font-size: 7.8pt;
    line-height: 1.25;
    margin: 2pt 0 4pt 0;
    white-space: pre-wrap;
    color: #1e293b;
  }

  .box {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 3.5px solid #5865F2;
    padding: 4pt 7pt;
    margin: 4pt 0;
  }

  .warn {
    background-color: #fefce8;
    border: 1px solid #fef08a;
    border-left: 3.5px solid #ca8a04;
    padding: 4pt 7pt;
    margin: 4pt 0;
  }

  .offer {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-left: 3.5px solid #2563eb;
    padding: 4.5pt 7pt;
    margin: 4pt 0;
  }

  .success {
    background-color: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-left: 3.5px solid #16a34a;
    padding: 4pt 7pt;
    margin: 4pt 0;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    margin: 4pt 0;
  }

  th, td {
    border: 1px solid #e2e8f0;
    padding: 3pt 5pt;
    text-align: left;
    vertical-align: top;
    font-size: 8.2pt;
  }

  th {
    background-color: #f8fafc;
    font-weight: bold;
    color: #1e293b;
  }

  .page-break {
    page-break-before: always;
  }

  a {
    color: #2563eb;
    text-decoration: none;
    font-weight: bold;
  }

  .footer-note {
    margin-top: 7pt;
    padding-top: 3pt;
    border-top: 1px solid #e2e8f0;
    font-size: 7.5pt;
    color: #64748b;
    text-align: right;
  }
</style>
</head>
<body>

<!-- ================= PAGE 1 ================= -->
<h1>TLDP: Using Google Antigravity for Projects</h1>
<div class="subtitle">AI-Assisted Development Guide &middot; Requirements, Installation, Windows Bypass &middot; Cohort 2026&ndash;2027</div>

<div class="offer">
  <span style="color: #2563eb; font-weight: bold; font-size: 9.5pt;">Student Perk: Claim 1 Year Free of Google AI Pro (Gemini Advanced)</span><br/>
  College students can receive a <span class="label">free 12-month subscription</span> to Google's premium AI plan (Google AI Pro / Google One AI Premium). This unlocks advanced Gemini models, higher rate limits, and 2TB cloud storage.<br/>
  &middot; <span class="label">Direct Claim Portal:</span> <a href="https://one.google.com/ai-student">one.google.com/ai-student</a> (or <a href="https://gemini.google/students">gemini.google/students</a>)<br/>
  &middot; <span class="label">How to verify:</span> Sign in with your <span class="label">personal Google account</span> (campus-managed accounts often restrict developer tools). Complete verification via <span class="label">SheerID</span> with your Baruch / CUNY student credentials.<br/>
  &middot; <span class="label">Connect to Antigravity:</span> Log in to Antigravity with this verified personal Google account to immediately unlock high-tier model access for the entire academic year!
</div>

<h2>1. System Requirements & Machine Prerequisites</h2>
<p>Ensure your laptop or desktop meets these requirements before installing Antigravity:</p>

<table>
  <tr>
    <th style="width: 22%;">Component</th>
    <th style="width: 38%;">Minimum Requirement</th>
    <th style="width: 40%;">Recommended for TLDP</th>
  </tr>
  <tr>
    <td><span class="label">Operating System</span></td>
    <td>Windows 10 (64-bit), macOS 12+, or modern Linux</td>
    <td>Windows 11 (64-bit) or macOS Sonoma (Apple Silicon M1&ndash;M4)</td>
  </tr>
  <tr>
    <td><span class="label">Memory (RAM)</span></td>
    <td>8 GB RAM</td>
    <td>16 GB RAM (smooth multitasking with dev containers and IDEs)</td>
  </tr>
  <tr>
    <td><span class="label">Disk Storage</span></td>
    <td>4 GB free space</td>
    <td>10+ GB free space (for repos, packages, and Python environments)</td>
  </tr>
  <tr>
    <td><span class="label">Git</span></td>
    <td>Git 2.30+ installed (<code>git --version</code>)</td>
    <td>Latest Git (<a href="https://git-scm.com">git-scm.com</a>) + GitHub CLI (<code>gh</code>)</td>
  </tr>
  <tr>
    <td><span class="label">Node.js & npm</span></td>
    <td>Node.js v18+ LTS</td>
    <td>Node.js v20+ LTS (needed for <code>npx</code> and BetaNYC MCP tools)</td>
  </tr>
  <tr>
    <td><span class="label">Python</span></td>
    <td>Python 3.10+</td>
    <td>Python 3.11 or 3.12 (standard across TLDP analytics & cyber labs)</td>
  </tr>
  <tr>
    <td><span class="label">Google Account</span></td>
    <td>Standard Google account</td>
    <td>Account with Google AI Pro student benefit activated</td>
  </tr>
</table>

<h2>2. Installing Antigravity on Your Machine</h2>
<p>Antigravity offers two primary surfaces: the <span class="label">Antigravity IDE</span> (standalone code editor built on VS Code) and the <span class="label">Antigravity CLI (<code>agy</code>)</span> for terminal workflows.</p>

<h3>Option A: Antigravity IDE (Full Editor Experience)</h3>
<ol>
  <li>Navigate to <code>https://antigravity.google</code> and download the installer (<code>.exe</code> for Windows, <code>.dmg</code> for macOS).</li>
  <li>Run the installer and follow the standard on-screen setup prompts.</li>
  <li>Launch the application and sign in with your Google account.</li>
  <li><span class="label">Core Modalities:</span>
    <ul>
      <li><span class="label">Inline Code Edits:</span> Highlight any code and press <code>Ctrl+I</code> (Windows) or <code>Cmd+I</code> (macOS) to refactor or explain.</li>
      <li><span class="label">Tab Autocomplete:</span> Press <code>Tab</code> to accept smart insertions, import completions, and function blocks.</li>
      <li><span class="label">Sidebar Agent:</span> Ask questions, plan features, and instruct the agent to build and test code across multiple files.</li>
    </ul>
  </li>
</ol>

<h3>Option B: Antigravity CLI (<code>agy</code>)</h3>
<p>For students who prefer working inside their existing terminal, PowerShell, or VS Code integrated terminal:</p>
<ol>
  <li><span class="label">Windows (PowerShell):</span>
    <pre>iwr -useb https://antigravity.google/install.ps1 | iex</pre>
    <i>(If PowerShell blocks this script, see Section 3 on the next page to bypass the restriction!)</i>
  </li>
  <li><span class="label">macOS / Linux (Terminal):</span>
    <pre>curl -fsSL https://antigravity.google/install.sh | bash</pre>
  </li>
  <li><span class="label">Configure Shell & PATH:</span> Run <code>agy install</code> to set up environment variables and shell completions.</li>
  <li><span class="label">Verify Setup:</span> Run <code>agy --version</code>. Then type <code>agy</code> to launch and complete browser login.</li>
</ol>

<div class="footer-note">TLDP 2026&ndash;2027 &middot; Page 1 of 3 &middot; Continue to Page 2 for Windows Troubleshooting</div>

<!-- ================= PAGE 2 ================= -->
<div class="page-break"></div>

<h2>3. Windows Troubleshooting: Bypassing PowerShell Script Execution Errors</h2>

<div class="warn">
  <span class="label" style="color: #854d0e;">The Common Windows Error:</span> When running installation scripts (such as <code>install.ps1</code>), activating Python virtual environments (<code>venv\Scripts\Activate.ps1</code>), or executing developer tools, Windows PowerShell often blocks execution with:
  <pre>File C:\...\install.ps1 cannot be loaded because running scripts is disabled on this system.
+ CategoryInfo          : SecurityError: (:) [], PSSecurityException
+ FullyQualifiedErrorId : UnauthorizedAccess</pre>
</div>

<p>By default, Windows sets PowerShell's execution policy to <code>Restricted</code>, preventing all <code>.ps1</code> scripts from running. This is a built-in operating system precaution, not a broken install. Below are four safe ways to bypass or resolve this issue:</p>

<h3>Method 1: Permanent User Fix (Recommended &mdash; No Administrator Rights Required)</h3>
<p>You can set the execution policy <span class="label">specifically for your current Windows user account</span>. This does not require Administrator permissions and will not affect any other accounts or system-level security:</p>
<ol>
  <li>Open a standard PowerShell window (press <b>Windows Key + X</b> &rarr; select <b>Terminal</b> or <b>PowerShell</b>).</li>
  <li>Run the following command:
    <pre>Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser</pre>
  </li>
  <li>When prompted: <i>"Do you want to change the execution policy?"</i>, type <b><code>Y</code></b> and press <b>Enter</b>.</li>
  <li><span class="label">Why this is safe:</span> <code>RemoteSigned</code> allows locally created scripts (such as your Python virtual environments or local build scripts) to execute freely, while requiring scripts downloaded from the internet to be digitally signed by a trusted publisher.</li>
</ol>

<h3>Method 2: One-Time Execution Bypass (No Configuration Changes)</h3>
<p>If you prefer not to change any persistent settings, run PowerShell with the <code>-ExecutionPolicy Bypass</code> flag for that specific script or command:</p>
<ul>
  <li><span class="label">To execute the Antigravity web installer directly:</span>
    <pre>powershell -ExecutionPolicy Bypass -Command "iwr -useb https://antigravity.google/install.ps1 | iex"</pre>
  </li>
  <li><span class="label">To run a downloaded .ps1 script file:</span>
    <pre>powershell -ExecutionPolicy Bypass -File .\install.ps1</pre>
  </li>
  <li><span class="label">To activate a Python virtual environment:</span>
    <pre>powershell -ExecutionPolicy Bypass -File .\venv\Scripts\Activate.ps1</pre>
  </li>
</ul>

<h3>Method 3: Unblock a Downloaded Script File</h3>
<p>When you download a <code>.ps1</code> file via a web browser, Windows attaches an "untrusted web zone" identifier to it. You can strip this identifier and allow the script to execute by running:</p>
<pre>Unblock-File -Path .\install.ps1</pre>

<h3>Method 4: Switch to Command Prompt (cmd.exe) or Git Bash</h3>
<p>PowerShell execution policies are exclusive to PowerShell. Neither <span class="label">Command Prompt</span> nor <span class="label">Git Bash</span> enforce them:</p>
<ul>
  <li><span class="label">Inside VS Code or Antigravity IDE:</span> Open the terminal (<code>Ctrl+`</code>), click the dropdown arrow next to the <b>+</b> button in the terminal panel, and select <b>Command Prompt</b> or <b>Git Bash</b>.</li>
  <li><span class="label">Activating Python Environments by Terminal:</span>
    <table>
      <tr>
        <th style="width: 32%;">Shell / Terminal</th>
        <th style="width: 68%;">Activation Command</th>
      </tr>
      <tr>
        <td>Command Prompt (cmd.exe)</td>
        <td><code>venv\Scripts\activate.bat</code></td>
      </tr>
      <tr>
        <td>Git Bash / macOS / Linux</td>
        <td><code>source venv/Scripts/activate</code> &nbsp;(or <code>source venv/bin/activate</code>)</td>
      </tr>
      <tr>
        <td>PowerShell (after Method 1)</td>
        <td><code>.\venv\Scripts\Activate.ps1</code></td>
      </tr>
    </table>
  </li>
</ul>

<div class="footer-note">TLDP 2026&ndash;2027 &middot; Page 2 of 3 &middot; Continue to Page 3 for MCP Servers & Safety Rules</div>

<!-- ================= PAGE 3 ================= -->
<div class="page-break"></div>

<h2>4. Connecting Model Context Protocol (MCP) Servers</h2>
<p>Antigravity natively supports the open Model Context Protocol (MCP) &mdash; the exact same tool standard used in Codex. You can connect live New York City public datasets (BetaNYC) and external developer tools with single commands:</p>

<table>
  <tr>
    <th style="width: 32%;">Tool / Dataset</th>
    <th style="width: 68%;">Antigravity CLI Command</th>
  </tr>
  <tr>
    <td><span class="label">Checkbook NYC</span><br/>(City budget, vendor contracts, payroll)</td>
    <td><code>agy mcp add nyc-checkbook -- npx -y @betanyc/nyc-checkbook-mcp</code></td>
  </tr>
  <tr>
    <td><span class="label">City Record</span><br/>(Procurement notices, RFPs, public hearings)</td>
    <td><code>agy mcp add nyc-record -- npx -y @betanyc/nyc-record-mcp</code></td>
  </tr>
  <tr>
    <td><span class="label">NYC 311 Service Requests</span><br/>(Requires free key from api-portal.nyc.gov)</td>
    <td><code>agy mcp add nyc-311 --env NYC_311_API_KEY=&lt;key&gt; -- npx -y @betanyc/nyc-311-mcp</code></td>
  </tr>
  <tr>
    <td><span class="label">Web Fetch</span><br/>(Extracts clean text from documentation pages)</td>
    <td><code>agy mcp add fetch -- uvx mcp-server-fetch</code></td>
  </tr>
  <tr>
    <td><span class="label">Firecrawl</span><br/>(Web crawler for marketing & SEO audits)</td>
    <td><code>agy mcp add firecrawl --env FIRECRAWL_API_KEY=&lt;key&gt; -- npx -y firecrawl-mcp</code></td>
  </tr>
</table>

<h2>5. Daily Agentic Workflow for TLDP Projects</h2>
<ol>
  <li><span class="label">Navigate to Your Project:</span> Open your terminal in your repository:
    <pre>cd C:\Users\&lt;username&gt;\tldp-case-studies</pre>
  </li>
  <li><span class="label">Launch Antigravity:</span> Type <code>agy</code> to start an interactive pair-programming session. Antigravity automatically indexes your repository structure and files.</li>
  <li><span class="label">Planning Mode (<code>/plan</code>):</span> For capstone milestones or complex features, type <code>/plan</code> before writing code. Review the proposed steps and refine them before execution.</li>
  <li><span class="label">Automated Testing & Linting:</span> Have Antigravity run your test suite directly (e.g., <code>pytest</code>, <code>npm test</code>) and fix any diagnostic errors interactively.</li>
  <li><span class="label">Exiting Antigravity:</span> Press <code>Ctrl+D</code> or type <code>/exit</code> to return to your normal terminal shell.</li>
</ol>

<h2>6. Safety, Sandboxes & No-Secrets Policy (TLDP Standard)</h2>
<div class="warn">
  <span class="label" style="color: #854d0e;">Critical Safety Rules for All TLDP Students:</span>
  <ul>
    <li><span class="label">Use Sandboxes for Unfamiliar Code:</span> Passing automated checks does not guarantee a project is safe. Run unfamiliar code inside a free browser sandbox (Google Colab or Codespaces) or launch Antigravity with <code>agy --sandbox</code> to enforce terminal restrictions.</li>
    <li><span class="label">Never Expose Credentials:</span> Never commit passwords, API keys, private tokens, or <code>.env</code> files to Git repositories or paste them into AI chat prompts. Add <code>.env</code> to your <code>.gitignore</code> before writing any code.</li>
    <li><span class="label">Synthetic / Public Data Only:</span> When working on finance, data, or cybersecurity case studies, use public datasets or synthetic test data only.</li>
  </ul>
</div>

<div class="success">
  <span class="label" style="color: #15803d;">Need Help or Have Questions?</span><br/>
  &middot; Post questions in <span class="label">#help</span> on the TLDP Discord server.<br/>
  &middot; Share your project walkthroughs and PRs in <span class="label">🧑‍💻│code-review-practice</span>.<br/>
  &middot; Check out <span class="label">🔌│mcp-servers-for-codex</span> for more copy-paste MCP configuration recipes!
</div>

<div class="footer-note">TLDP 2026&ndash;2027 &middot; Page 3 of 3 &middot; Document generated for TLDP Technology Leadership & Development Program</div>

</body>
</html>
"""


def main() -> int:
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(HTML_CONTENT)
    print(f"Wrote HTML preview: {OUTPUT_HTML}")

    with open(OUTPUT_DOCS_PDF, "wb") as f:
        pisa_status = pisa.CreatePDF(HTML_CONTENT, dest=f, encoding="utf-8")

    if pisa_status.err:
        print(f"Error compiling PDF: {pisa_status.err}", file=sys.stderr)
        return 1
    print(f"Successfully generated PDF: {OUTPUT_DOCS_PDF}")

    try:
        shutil.copy2(OUTPUT_DOCS_PDF, OUTPUT_DESKTOP_PDF)
        print(f"Successfully placed PDF on Desktop: {OUTPUT_DESKTOP_PDF}")
    except PermissionError:
        alt_desktop = DESKTOP_DIR / "TLDP_Antigravity_Guide_Light.pdf"
        shutil.copy2(OUTPUT_DOCS_PDF, alt_desktop)
        print(f"Original Desktop file is open in a viewer. Saved updated version to: {alt_desktop}")
    except Exception as e:
        print(f"Could not copy to Desktop: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
