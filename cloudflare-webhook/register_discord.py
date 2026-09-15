#!/usr/bin/env python3
"""
register_discord.py — register the /scout slash command with Discord (run once, and after edits).

  DISCORD_APP_ID=... DISCORD_BOT_TOKEN=... python register_discord.py

Also reads ../secrets_local.py if the env vars are missing. Global command:
propagates to every server the app is invited to within about an hour.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import secrets_local as s
except ImportError:  # env-only
    s = None

APP = os.environ.get("DISCORD_APP_ID") or getattr(s, "DISCORD_APP_ID", "")
TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or getattr(s, "DISCORD_BOT_TOKEN", "")

MAJORS = [("Quant", "quant"), ("Finance / FinTech", "fintech"), ("Software Engineering", "swe"),
          ("Cybersecurity", "cyber"), ("Data Analytics", "data")]
LANES = [("Build this (fresh repos)", "build"), ("Contribute (good first issues)", "oss"),
         ("Research (fresh paper code)", "research")]
COMMANDS = [{
    "name": "scout",
    "description": "GitHub project ideas, open-source issues and paper code by major",
    "options": [
        {"type": 3, "name": "major", "description": "Your major", "required": False,
         "choices": [{"name": n, "value": v} for n, v in MAJORS]},
        {"type": 3, "name": "lane", "description": "What kind of repos (default: fresh repos to build)", "required": False,
         "choices": [{"name": n, "value": v} for n, v in LANES]},
        {"type": 3, "name": "keywords", "description": "Narrow the search, e.g. honeypot", "required": False},
    ],
}]


def main() -> int:
    if not APP or not TOKEN:
        print(__doc__)
        return 1
    req = urllib.request.Request(f"https://discord.com/api/v10/applications/{APP}/commands", method="PUT",
                                 data=json.dumps(COMMANDS).encode(),
                                 headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json",
                                          "User-Agent": "project-scout (github.com/thecyberthriver/project-scout, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("registered:", [c["name"] for c in json.load(r)])
    except urllib.error.HTTPError as e:
        print("discord", e.code, e.read()[:300].decode(errors="replace"))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
