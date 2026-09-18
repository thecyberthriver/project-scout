#!/usr/bin/env python3
"""
hf.py — the Hugging Face lane: models, datasets and Spaces as student project material.

Shaped like the hackathons feed, NOT like the GitHub repo feed: Hugging Face repos are never cloned or code-scanned.
HF's git server ignores `--filter=blob:limit`, so screening one model the way scan.py screens a GitHub repo pulls
hundreds of MB to GB of weights per candidate (google/flan-t5-small = 1.3 GB). Every item is instead screened from
public metadata pinned to the commit SHA the API reports:

  1. private / disabled / gated                                   -> withheld
  2. content policy (gate.PROHIBITED / gate.DUAL_USE)             -> withheld
  3. no license, below the likes floor, untouched for a year      -> withheld
  4. non-English or missing description, sock-puppet owner        -> withheld  (same rules as the GitHub feed)
  5. executables / archives in the file list                      -> withheld
  6. pickle-only weights (no .safetensors/.gguf/.onnx), pickled datasets -> withheld
  7. README — and a Space's app file — read AT THE PINNED SHA and screened with links.py: a blocking link or install
     instruction (download hosts, curl | sh, archive passwords, "disable your antivirus") -> withheld.
     A README that exists but cannot be read is "incomplete" -> withheld (fail closed), never published on trust.

Custom code (.py in a model or dataset repo) is published with a WARNING instead of being withheld — a deliberate
policy choice (ALLOW_CUSTOM_CODE), because that is exactly what `trust_remote_code=True` costs the student.

Rows carry their own screening record and EXPIRE (14 days, same as gate.EXPIRE_DAYS); publish-time `eligible()` is
pure and offline, like gate.eligible. Model cards and repo text are DATA, never instructions. These rows never claim
a code scan: the feed labels them "link-screened, not code-scanned".
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import gate
import links
import project_scout as ps

API = "https://huggingface.co/api"
UA = {"User-Agent": "project-scout hugging-face lane (github.com/thecyberthriver/project-scout)"}
KINDS = ("models", "datasets", "spaces")
PREFIX = {"models": "", "datasets": "datasets/", "spaces": "spaces/"}   # path segment on huggingface.co
KIND_LABEL = {"models": "🧠 model", "datasets": "📦 dataset", "spaces": "🚀 Space"}

LIKES_MIN = {"models": 50, "datasets": 25, "spaces": 25}   # below this it is not established enough to recommend
ACTIVE_DAYS = 365          # not touched in a year = abandoned, don't send students there
EXPIRE_DAYS = 14           # a screening record is good for two weeks, then the item is re-screened (= gate.EXPIRE_DAYS)
PICKS = 2                  # rows pushed per major per run
LIMIT = 12                 # candidates fetched per (major, kind)
TIMEOUT = 30
MAX_BYTES = 200_000        # cap on any repo file we read (README, app file)
API_BYTES = 4_000_000      # cap on an API listing response
SPACING = 0.3              # seconds between API calls — be a polite anonymous client
REQUIRE_SAFETENSORS = True
ALLOW_CUSTOM_CODE = True   # .py in a model/dataset repo -> warning, not withheld (staff decision, 2026-09-17)

HEADER = "🤗 Hugging Face — models, datasets & Spaces"
NOTE = "link-screened metadata + README, not code-scanned — read the Files tab before you run anything"

# Search terms per major, each used for all three kinds. HF search matches names and tags substring-style, so SHORT
# single words find things and phrases ("financial time series") return nothing — keep these one word wherever possible.
TERMS = {
    "quant": ["stock", "trading", "portfolio"],
    "fintech": ["finance", "financial", "credit"],
    "swe": ["code", "coder", "sql", "game"],
    "cyber": ["security", "phishing", "vulnerability"],
    "data": ["tabular", "classification", "forecasting"],
    "pm": ["summarization", "meeting"],
    "marketing": ["sentiment", "marketing", "reviews", "twitter"],
}

# Industry axis. Free: it is read off text we already have, so it costs no extra API call. First match wins; an item
# that matches nothing is "general" and is simply not labelled.
INDUSTRY = [
    ("healthcare", "🩺", r"health|medical|clinical|patient|hospital|biomed|radiolog|\behr\b|hipaa|diagnos|drug|disease|cancer"),
    ("finance", "🏦", r"financ|bank|credit|loan|invest|stock|trading|portfolio|insur|fraud|payment|accounting|earnings"),
    ("retail", "🛒", r"retail|e-?commerce|shopping|product review|inventory|supply chain|customer review|amazon review|sales forecast"),
    ("hospitality", "🏨", r"hotel|restaurant|travel|tourism|booking|airline|flight|hospitality|menu|recipe|yelp"),
    ("gaming", "🎮", r"\bgam(e|es|ing)\b|video ?game|esports|minecraft|roblox|twitch|nintendo|steam review|npc dialogue"),
    ("social media", "📱", r"social media|twitter|\btweets?\b|reddit|instagram|tiktok|facebook|hashtag|influencer|toxic comment|youtube comment|\bmemes?\b"),
    ("education", "🎓", r"education|student|course|classroom|school|exam|tutor|essay scoring"),
    ("public sector", "🏛", r"government|public sector|civic|municipal|census|regulation|legal|court|policy document"),
]
INDUSTRY_RX = [(name, emoji, re.compile(rx, re.I)) for name, emoji, rx in INDUSTRY]


def industry_of(text: str) -> tuple[str, str]:
    """(name, emoji) for the first industry this item's own text matches; ("", "") when it is general-purpose."""
    for name, emoji, rx in INDUSTRY_RX:
        if rx.search(text or ""):
            return name, emoji
    return "", ""


EXEC_FILE = re.compile(r"\.(exe|msi|dll|apk|scr|bat|cmd|vbs|vbe|jse|hta|jar|iso|img|dmg|pkg|lnk|zip|rar|7z)$", re.I)
CODE_FILE = re.compile(r"\.(py|sh|ipynb)$", re.I)
PICKLE_FILE = re.compile(r"\.(bin|pt|pth|ckpt|pkl|pickle|joblib|h5|msgpack)$", re.I)
SAFE_WEIGHTS = re.compile(r"\.(safetensors|gguf|onnx)$", re.I)
PICKLED_DATA = re.compile(r"\.(pkl|pickle|joblib|pt|pth)$", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _get(url: str, accept_404: bool = False, cap: int = MAX_BYTES) -> bytes | None:
    """GET at most `cap` bytes. None = a 404 the caller said is acceptable. Raises on anything else (fail closed)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=TIMEOUT) as r:
            return r.read(cap)
    except urllib.error.HTTPError as e:
        if accept_404 and e.code == 404:
            return None
        raise


def url_for(kind: str, item_id: str) -> str:
    return "https://huggingface.co/" + PREFIX[kind] + urllib.parse.quote(item_id)


def raw_url(kind: str, item_id: str, sha: str, path: str) -> str:
    return f"https://huggingface.co/{PREFIX[kind]}{urllib.parse.quote(item_id)}/raw/{sha}/{urllib.parse.quote(path)}"


def search(kind: str, terms: str, limit: int = LIMIT) -> list[dict]:
    q = urllib.parse.urlencode({"search": terms, "sort": "likes", "direction": -1, "limit": limit, "full": "true"})
    time.sleep(SPACING)
    data = json.loads(_get(f"{API}/{kind}?{q}", cap=API_BYTES) or b"[]")
    return data if isinstance(data, list) else []


def license_of(item: dict) -> str:
    lic = (item.get("cardData") or {}).get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    if not lic:
        for t in item.get("tags") or []:
            if isinstance(t, str) and t.startswith("license:"):
                lic = t.split(":", 1)[1]
                break
    return str(lic or "")


def describe(item: dict, kind: str) -> str:
    """A model has no description field — build one from what the card does carry."""
    d = (item.get("description") or "").strip()
    if d:
        return re.sub(r"\s+", " ", d)[:200]
    card = item.get("cardData") or {}
    bits = [card.get("title"), item.get("pipeline_tag"), item.get("library_name") or item.get("sdk")]
    bits += [t for t in (item.get("tags") or []) if isinstance(t, str) and ":" not in t]
    out: list[str] = []
    for b in bits:                                    # the same word arrives as library_name AND as a tag
        if b and str(b).lower() not in [x.lower() for x in out]:
            out.append(str(b))
    return re.sub(r"\s+", " ", " · ".join(out[:6]))[:200]


def files_of(item: dict) -> list[str]:
    return [s.get("rfilename", "") for s in (item.get("siblings") or []) if isinstance(s, dict)]


def app_file(item: dict) -> str:
    """The file a Space actually runs. cardData.app_file when declared, else the conventional entry point."""
    named = (item.get("cardData") or {}).get("app_file")
    if isinstance(named, str) and named.strip():
        return named.strip()
    names = files_of(item)
    for candidate in ("app.py", "streamlit_app.py", "main.py", "index.html", "Dockerfile"):
        if candidate in names:
            return candidate
    return ""


def screen(item: dict, kind: str, fetch=None) -> dict:
    """Screen one HF item from metadata + its README (+ a Space's app file) at the pinned SHA.
    Returns a record: result pass | fail | incomplete, with reasons and warnings. Never raises.
    `fetch` overrides the HTTP reader (tests pass a stub; nothing else should)."""
    fetch = fetch or _get
    now = _now()
    item_id = str(item.get("id") or "")
    owner = item_id.split("/")[0] if "/" in item_id else ""
    sha = str(item.get("sha") or "")
    rec = {"at": _iso(now), "sha": sha, "kind": kind, "result": "fail", "reasons": [], "warnings": [],
           "checks": ["metadata", "content-policy", "license", "files", "readme-links"],
           "expires": _iso(now + timedelta(days=EXPIRE_DAYS))}
    reasons, warn = rec["reasons"], rec["warnings"]
    desc = describe(item, kind)
    likes = int(item.get("likes") or 0)

    if not item_id or "/" not in item_id:
        reasons.append("no owner/name id")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        reasons.append("no pinned commit SHA from the API")
    if item.get("private") or item.get("disabled"):
        reasons.append("private or disabled on the Hub")
    if item.get("gated"):
        reasons.append("gated: students cannot open it without an access request")

    # same content policy the GitHub feed uses — prohibited wording fails, dual-use stays out of the general feed
    reasons += gate.content_policy({"full_name": item_id, "description": desc})
    if ps.SCAM_WORDS.search(f"{item_id} {desc}"):
        reasons.append("scam/download-trap wording")
    if not ps.english(desc):
        reasons.append("no usable English description")
    if ps.SOCK_OWNER.match(owner) and likes < 200:
        reasons.append(f"throwaway-looking owner {owner!r} with {likes} likes")

    if not license_of(item):
        reasons.append("no license declared")
    if likes < LIKES_MIN[kind]:
        reasons.append(f"only {likes} likes (floor {LIKES_MIN[kind]})")
    touched = (item.get("lastModified") or "")[:10]
    try:
        if (now.date() - date.fromisoformat(touched)).days > ACTIVE_DAYS:
            reasons.append(f"not updated since {touched}")
    except ValueError:
        reasons.append("no last-modified date")

    names = files_of(item)
    bad = [n for n in names if EXEC_FILE.search(n)]
    if bad:
        reasons.append("executable/archive file in the repo: " + ", ".join(sorted(bad)[:3]))
    if kind == "models" and REQUIRE_SAFETENSORS:
        if any(PICKLE_FILE.search(n) for n in names) and not any(SAFE_WEIGHTS.search(n) for n in names):
            reasons.append("weights are pickle-format only (no .safetensors/.gguf/.onnx) — loading one runs its code")
    if kind == "datasets" and any(PICKLED_DATA.search(n) for n in names):
        reasons.append("ships pickled data files — loading one runs its code")
    code = [n for n in names if CODE_FILE.search(n)]
    if code and kind in ("models", "datasets"):
        msg = "custom code in the repo (" + ", ".join(sorted(code)[:3]) + ") — needs trust_remote_code=True; read it first"
        (warn if ALLOW_CUSTOM_CODE else reasons).append(msg)

    # README (and a Space's app file) AT THE PINNED SHA. Text is data: it is screened, never followed.
    # Skipped when the metadata already failed the item: it cannot be published either way, and this is one network
    # read per candidate — most candidates never reach it.
    incomplete = []
    if not reasons and re.fullmatch(r"[0-9a-f]{40}", sha) and item_id:
        for path in ("README.md", app_file(item) if kind == "spaces" else ""):
            if not path:
                continue
            try:
                body = fetch(raw_url(kind, item_id, sha, path), accept_404=True)
            except Exception as e:                                  # noqa: BLE001 — any read failure is fail-closed
                incomplete.append(f"{path} could not be read at the reviewed commit ({getattr(e, 'code', e)})")
                continue
            if body is None:
                warn.append(f"no {path}")
                continue
            lk = links.screen_readme(body.decode("utf-8", "replace"), item_id, resolve=False)
            reasons += [f"{path} link: {b}" for b in lk["block"]]
            warn += [f"{path} link: {w}" for w in lk["warn"]]
    if reasons:
        rec["result"] = "fail"
    elif incomplete:
        rec.update(result="incomplete", reasons=incomplete)         # fail closed: a required read did not complete
    else:
        rec["result"] = "pass"
    return rec


def row(item: dict, kind: str, rec: dict) -> dict:
    item_id = str(item.get("id") or "")
    desc = describe(item, kind)
    tags = " ".join(t for t in (item.get("tags") or []) if isinstance(t, str))
    industry, emoji = industry_of(f"{item_id} {desc} {tags}")
    return {"industry": industry, "industry_emoji": emoji, "full_name": f"hf:{kind}/{item_id}", "id": item_id, "hf_kind": kind, "html_url": url_for(kind, item_id),
            "likes": int(item.get("likes") or 0), "downloads": int(item.get("downloads") or 0),
            "task": item.get("pipeline_tag") or item.get("sdk") or "", "library": item.get("library_name") or "",
            "license": license_of(item), "description": desc,
            "updated": (item.get("lastModified") or "")[:10], "warnings": rec.get("warnings", []), "screened": rec}


def discover(terms: dict | None = None, run_no: int | None = None) -> dict:
    """{major: [screened rows]} — the only stage that talks to huggingface.co. Never raises for one bad item.
    An item is claimed by the first major that takes it (no duplicate across majors), so the major order ROTATES each
    run the way pipeline._searches rotates the GitHub majors — otherwise the same major always starves last."""
    out, taken = {}, set()
    src = terms or TERMS
    if run_no is None:
        now = datetime.now()
        run_no = now.timetuple().tm_yday * 4 + now.hour // 6
    order = list(src)
    order = order[run_no % len(order):] + order[:run_no % len(order)]
    for major, qs in ((m, src[m]) for m in order):
        rows = []
        for q, kind in ((q, k) for q in ([qs] if isinstance(qs, str) else qs) for k in KINDS):
            try:
                found = search(kind, q)
            except Exception as e:                                   # noqa: BLE001 — one kind failing is not fatal
                print(f"hf {major}/{kind}: {e}", file=sys.stderr)
                continue
            for item in found:
                key = f"hf:{kind}/{item.get('id')}"
                if key in taken:
                    continue
                try:
                    rec = screen(item, kind)
                except Exception as e:                               # noqa: BLE001
                    print(f"hf screen {key}: {e}", file=sys.stderr)
                    continue
                if rec["result"] != "pass":
                    continue
                taken.add(key)
                rows.append(row(item, kind, rec))
        # industry first so the section reads grouped, most-liked first inside each industry ("" = general, last)
        out[major] = sorted(rows, key=lambda r: ((r["industry"] or "zz"), -r["likes"]))[:LIMIT]
    return out


def eligible(r: dict, now: datetime | None = None) -> bool:
    """Pure, offline publish-time check — the hackathon-lane equivalent of gate.eligible. No network."""
    now = now or _now()
    rec = (r or {}).get("screened") or {}
    if rec.get("result") != "pass" or not re.fullmatch(r"[0-9a-f]{40}", str(rec.get("sha") or "")):
        return False
    try:
        if datetime.fromisoformat(rec["expires"]) <= now:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    if not str(r.get("full_name", "")).startswith("hf:"):
        return False
    c = links.classify(r.get("html_url", ""))
    return not (c and c[0] == "block")


def render(r: dict) -> str:
    """One feed line, same shape as ps.render_repo. Warnings are shown to the student, not hidden."""
    kind = KIND_LABEL.get(r.get("hf_kind"), "🤗")
    ind = f'{r.get("industry_emoji", "")} {r.get("industry", "")}'.strip()
    meta = " · ".join(x for x in (ind, kind, r.get("task") or "", r.get("license") or "") if x)
    line = (f'• <a href="{r["html_url"]}">{ps.esc(r["id"])}</a> ❤{r.get("likes", 0)} · {ps.esc(meta)}\n'
            f'  {ps.esc(r.get("description") or "(no description)")}')
    for w in r.get("warnings", [])[:2]:
        line += f"\n  ⚠️ {ps.esc(w)}"
    return line


def _demo() -> None:
    """Offline self-check: the screening rules, on fixtures. No network."""
    sha = "a" * 40
    base = {"id": "acme/good-model", "sha": sha, "likes": 500, "downloads": 10, "lastModified": date.today().isoformat(),
            "cardData": {"license": "apache-2.0"}, "pipeline_tag": "text-classification",
            "siblings": [{"rfilename": "README.md"}, {"rfilename": "model.safetensors"}]}

    def rec(item, kind="models"):                      # offline: the file reader is stubbed to "no such file"
        return screen(dict(base, **item), kind, fetch=lambda url, accept_404=False: None)

    assert "no license declared" in rec({"cardData": {}, "tags": []})["reasons"]
    assert any("only 3 likes" in x for x in rec({"likes": 3})["reasons"])
    assert any("gated" in x for x in rec({"gated": True})["reasons"])
    assert any("private or disabled" in x for x in rec({"disabled": True})["reasons"])
    assert any("not updated since" in x for x in rec({"lastModified": "2019-01-01"})["reasons"])
    assert any("pickle-format only" in x for x in
               rec({"siblings": [{"rfilename": "pytorch_model.bin"}]})["reasons"])
    assert not any("pickle" in x for x in rec({"siblings": [{"rfilename": "pytorch_model.bin"},
                                                            {"rfilename": "model.safetensors"}]})["reasons"])
    assert any("executable/archive" in x for x in rec({"siblings": [{"rfilename": "setup.exe"}]})["reasons"])
    assert any("pickled data" in x for x in
               rec({"siblings": [{"rfilename": "train.pkl"}]}, "datasets")["reasons"])
    assert any("content policy" in x for x in rec({"description": "a wallet drainer for testing"})["reasons"])
    assert any("throwaway-looking owner" in x for x in rec({"id": "elenahao66/thing", "likes": 60})["reasons"])
    # custom code is a warning, not a block (ALLOW_CUSTOM_CODE)
    custom = rec({"siblings": [{"rfilename": "model.safetensors"}, {"rfilename": "modeling_acme.py"}]})
    assert not custom["reasons"] and any("trust_remote_code" in w for w in custom["warnings"]), custom

    passing = {"full_name": "hf:models/acme/good", "html_url": "https://huggingface.co/acme/good",
               "screened": {"result": "pass", "sha": sha, "expires": _iso(_now() + timedelta(days=1))}}
    assert eligible(passing)
    assert not eligible({**passing, "screened": {**passing["screened"], "expires": _iso(_now() - timedelta(days=1))}})
    assert not eligible({**passing, "screened": {**passing["screened"], "result": "incomplete"}})
    assert not eligible({**passing, "screened": {**passing["screened"], "sha": "short"}})
    assert not eligible({**passing, "full_name": "acme/good"})   # a GitHub-shaped name never rides this lane
    assert app_file({"cardData": {"app_file": "run.py"}}) == "run.py"
    assert app_file({"siblings": [{"rfilename": "app.py"}]}) == "app.py"
    assert license_of({"tags": ["license:mit"]}) == "mit"
    assert industry_of("patient triage notes")[0] == "healthcare"
    assert industry_of("hotel booking reviews")[0] == "hospitality"
    assert industry_of("npc dialogue for a video game")[0] == "gaming"
    assert industry_of("toxic comment detection on reddit")[0] == "social media"
    assert industry_of("a general text model")[0] == ""
    assert row({"id": "a/b", "description": "hospital readmission"}, "datasets", {})["industry"] == "healthcare"
    assert "❤500" in render(row(dict(base), "models", {"result": "pass", "sha": sha, "warnings": ["x"]}))
    print("hf self-check ok")


if __name__ == "__main__":
    if "--preview" in sys.argv:
        sys.stdout.reconfigure(errors="replace")   # Windows consoles are cp1252; the feed itself is UTF-8 over HTTP
        for major, rows in discover().items():
            print(f"\n== {major} ==")
            for r in rows[:PICKS]:
                print(render(r))
    else:
        _demo()
