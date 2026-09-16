#!/usr/bin/env python3
"""
levels.py — undergraduate difficulty classification. stdlib only, deterministic, testable.

Sorts a *screened* repo into one of:
  beginner      guided exercises, basic Python/SQL/JavaScript, small notebooks, simple apps, clear setup
  intermediate  a manageable API, dashboard, database, tests, a small integration
  challenge     a bounded project combining familiar skills — NOT expert research or a large production system
  exclude       needs distributed infrastructure, graduate math, specialized/expensive hardware, or pro expertise
  unknown       not enough evidence to classify reliably (withhold from the leveled feed; offer a synthetic beginner)

It does NOT use stars or size alone. It weighs description/name wording plus code signals captured during the scan
(tests, Dockerfile, compose/k8s/terraform, dependency count, README length, top-level entries). Beginner is the
default; higher levels are an explicit opt-in. Effort figures are estimates and are labeled as such.
"""
import re

# ---- exclusion signals: beyond a supervised undergraduate feed ------------------------------------------------------
EXCLUDE_INFRA = re.compile(r"\b(kubernetes|k8s|service mesh|istio|distributed (training|system|systems|database)|"
                           r"petabyte|exabyte|high[- ]performance computing|\bhpc\b|spark cluster|kafka cluster|"
                           r"multi[- ]region|production[- ]scale|hyperscale|sharded cluster|terraform module)\b", re.I)
EXCLUDE_MATH = re.compile(r"\b(measure theory|stochastic (calculus|differential equation)|functional analysis|"
                          r"phd|graduate[- ]level|research[- ]grade|novel research|state[- ]of[- ]the[- ]art research|"
                          r"advanced (topology|algebraic))\b", re.I)
EXCLUDE_HW = re.compile(r"\b(fpga|verilog|vhdl|asic|oscilloscope|logic analyzer|gpu cluster|cuda toolkit required|"
                        r"requires? (a |an )?(gpu|tpu|fpga)|jtag|soldering|robot arm)\b", re.I)
# intermediate-signal wording
INT_WORDS = re.compile(r"\b(api|rest|graphql|dashboard|database|postgres|mysql|sqlite|mongodb|etl|pipeline|"
                       r"microservice|integration|web app|full[- ]stack|authentication|oauth)\b", re.I)
# beginner-signal wording
BEG_WORDS = re.compile(r"\b(tutorial|beginner|starter|example|examples|learn|learning|exercise|exercises|"
                       r"getting started|simple|basic|hello world|notebook|practice|first project|101|for beginners)\b", re.I)

BEGINNER_LANGS = {"Python", "JavaScript", "TypeScript", "SQL", "Jupyter Notebook", "HTML", "CSS", "R", None}


def _s(row: dict, rec: dict | None) -> dict:
    """The code signals captured during screening (scan.py), or {} if none were recorded."""
    return ((rec or {}).get("coverage") or {}).get("signals") or {}


def classify(row: dict, rec: dict | None = None) -> dict:
    """Return the level dict for a fresh repo row. Beginner by default; unknown when evidence is insufficient."""
    text = f"{row.get('full_name', '')} {row.get('description') or ''}"
    lang = row.get("language")
    sig = _s(row, rec)
    has_sig = bool(sig)

    if EXCLUDE_INFRA.search(text) or EXCLUDE_MATH.search(text) or EXCLUDE_HW.search(text) \
            or sig.get("has_k8s") or sig.get("has_terraform") or (sig.get("compose_services") or 0) >= 3:
        why = "needs distributed infrastructure, graduate math, or specialized hardware — beyond an undergrad project"
        return _pack("exclude", lang, [why], confidence="high")

    beg = bool(BEG_WORDS.search(text))
    intw = bool(INT_WORDS.search(text))
    tests = bool(sig.get("has_tests"))
    docker = bool(sig.get("has_dockerfile"))
    deps = sig.get("dep_count") or 0
    readme = sig.get("readme_bytes") or 0
    top = sig.get("top_level_entries") or 0

    # Not enough evidence to be reliable: no code signals AND nothing in the wording points either way.
    if not has_sig and not beg and not intw:
        return _pack("unknown", lang, ["insufficient evidence to classify difficulty reliably"], confidence="low")

    score = 0                       # higher = harder
    score += 2 if intw else 0
    score += 1 if tests else 0
    score += 2 if docker else 0
    score += 1 if deps >= 8 else 0
    score += 1 if top >= 25 else 0
    score += 1 if lang not in BEGINNER_LANGS else 0
    score -= 2 if beg else 0
    score -= 1 if (has_sig and readme >= 300) else 0   # a real README lowers setup burden

    if score <= 0:
        level, conf = "beginner", ("high" if (beg or (has_sig and readme >= 300)) else "medium")
    elif score <= 3:
        level, conf = "intermediate", ("high" if has_sig else "medium")
    else:
        level, conf = "challenge", ("high" if has_sig else "low")

    # Low confidence at the harder end is not reliable enough to recommend as that level -> step down / unknown.
    if level == "challenge" and conf == "low":
        return _pack("unknown", lang, ["difficulty looks high but evidence is thin"], confidence="low")
    return _pack(level, lang, [], confidence=conf)


def _pack(level: str, lang: str | None, reasons: list[str], confidence: str) -> dict:
    lg = lang or "the project's language"
    tmpl = {
        "beginner": {
            "prereqs": f"Basic {lg}. No prior experience with the project needed.",
            "task": "Read the README, run it, then make one small change: fix a typo/docs issue or add a tiny feature.",
            "effort": "about 2 to 5 hours (estimate)",
            "success": "It runs from a clean clone, your small change works, and you committed no secrets.",
        },
        "intermediate": {
            "prereqs": f"{lg}, basic Git, and a little experience writing tests.",
            "task": "Build or extend one small feature end to end (an endpoint, a chart, a query) and add a test for it.",
            "effort": "about 1 to 2 days part-time (estimate)",
            "success": "The feature works, it has at least one test, and you documented it in the README.",
        },
        "challenge": {
            "prereqs": f"{lg}, Git, testing, and comfort reading unfamiliar docs.",
            "task": "Complete a bounded project combining a few familiar skills (e.g. a small API plus a database plus tests). A useful subset is enough.",
            "effort": "about 1 week part-time (estimate)",
            "success": "It runs, has tests, is documented, and a classmate could follow your README to reproduce it.",
        },
        "exclude": {"prereqs": "", "task": "", "effort": "", "success": ""},
        "unknown": {
            "prereqs": f"Basic {lg}.",
            "task": "Start with the README and run the simplest example; ask in the help channel if setup is unclear.",
            "effort": "unclear (estimate)",
            "success": "You got it running and understood one part of it.",
        },
    }[level]
    return {"level": level, "confidence": confidence, "reasons": reasons, **tmpl}


LABELS = {"beginner": "🟢 Beginner", "intermediate": "🟡 Intermediate", "challenge": "🟠 Undergraduate Challenge",
          "exclude": "⛔ Beyond undergrad", "unknown": "❔ Unclassified"}
# What a student sees in the feed by default (beginner) and can opt into.
FEED_LEVELS = ("beginner", "intermediate", "challenge")


def _demo() -> None:
    beg = {"full_name": "x/todo-tutorial", "description": "A beginner tutorial to build a to-do app", "language": "Python"}
    assert classify(beg)["level"] == "beginner"
    inf = {"full_name": "x/platform", "description": "distributed system on kubernetes at production-scale", "language": "Go"}
    assert classify(inf)["level"] == "exclude"
    hw = {"full_name": "x/fpga-dsp", "description": "Verilog FPGA signal processing", "language": "Verilog"}
    assert classify(hw)["level"] == "exclude"
    thin = {"full_name": "x/thing", "description": "a thing", "language": "Rust"}
    assert classify(thin)["level"] == "unknown"     # no signals, no wording -> not reliably classifiable
    api = {"full_name": "x/api", "description": "A REST API with a Postgres database", "language": "Python"}
    rec = {"coverage": {"signals": {"has_tests": True, "has_dockerfile": True, "dep_count": 10, "readme_bytes": 500, "top_level_entries": 12}}}
    assert classify(api, rec)["level"] in ("intermediate", "challenge")
    k8s = {"full_name": "x/svc", "description": "a service", "language": "Go"}
    assert classify(k8s, {"coverage": {"signals": {"has_terraform": True}}})["level"] == "exclude"
    for lv in FEED_LEVELS:
        assert "(estimate)" in _pack(lv, "Python", [], "high")["effort"]
    print("levels self-check ok")


if __name__ == "__main__":
    _demo()
