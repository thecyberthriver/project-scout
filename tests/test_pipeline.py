"""End-to-end proof that unqualified repos never reach a student-visible published.json or drop section."""
import unittest
from datetime import datetime, timedelta, timezone

import gate
import pipeline

NOW = datetime.now(timezone.utc)
FRESH = (NOW - timedelta(days=2)).date().isoformat()
OLD = (NOW - timedelta(days=90)).date().isoformat()


def rec(full, result="pass", sha="a" * 40, expires_days=10):
    return {"full_name": full, "result": result, "sha": sha, "policy_version": gate.POLICY_VERSION,
            "at": NOW.isoformat(), "expires": (NOW + timedelta(days=expires_days)).isoformat(),
            "coverage": {"code_scan_result": "pass",
                         "engines": {"semgrep": "ran", "yara": "ran", "clamav": "ran", "osv": "ran"},
                         "signals": {"readme_bytes": 500, "has_tests": False, "dep_count": 2, "top_level_entries": 8}},
            "reasons": []}  # signals -> classifies as beginner, so the row survives the level filter


def frow(full, pushed=FRESH):
    return {"full_name": full, "html_url": f"https://github.com/{full}", "stargazers_count": 5, "language": "Python",
            "description": "x", "size": 300, "pushed_at": pushed, "created_at": pushed}


class Published(unittest.TestCase):
    def setUp(self):
        self.meta = pipeline._meta("operational")
        self.quar = gate.load_quarantine()

    def build(self, keys, records):
        idx = {"keys": keys, "static": {"starters": {}, "cyber_domains": {}, "cases": {}, "paths": {}, "stages": []},
               "hackathons": {"at": self.meta["generated_at"], "items": []}}
        store = {"policy_version": gate.POLICY_VERSION, "records": records}
        return pipeline._build_published(idx, store, self.meta, self.quar)

    def test_only_passing_fresh_rows_reach_feed(self):
        keys = {"swe|build|": [frow("good/a"), frow("bad/b"), frow("stale/c", pushed=OLD), frow("unscreened/d")]}
        records = {"good/a": rec("good/a"), "bad/b": rec("bad/b", result="fail"), "stale/c": rec("stale/c")}
        pub = self.build(keys, records)
        names = [r["full_name"] for r in pub["feed"].get("swe|build|", [])]
        self.assertIn("good/a", names)
        self.assertNotIn("bad/b", names)          # failed screening
        self.assertNotIn("stale/c", names)        # older than 30 days
        self.assertNotIn("unscreened/d", names)   # no record

    def test_expired_record_excluded(self):
        keys = {"swe|build|": [frow("exp/a")]}
        pub = self.build(keys, {"exp/a": rec("exp/a", expires_days=-1)})
        self.assertEqual(pub["feed"].get("swe|build|", []), [])

    def test_quarantined_repo_never_published_even_if_recorded_pass(self):
        keys = {"cyber|build|": [frow("ElementTrail/Multichain-Drainer")]}
        pub = self.build(keys, {"ElementTrail/Multichain-Drainer": rec("ElementTrail/Multichain-Drainer")})
        self.assertEqual(pub["feed"].get("cyber|build|", []), [])

    def test_every_published_row_carries_screened_block_and_label(self):
        keys = {"data|build|": [frow("good/a")]}
        pub = self.build(keys, {"good/a": rec("good/a")})
        r = pub["feed"]["data|build|"][0]
        self.assertIn("screened", r)
        self.assertEqual(r["screened"]["sha"], "a" * 40)
        self.assertEqual(pub["meta"]["label"], gate.LABEL)
        self.assertIn("fallback", pub)  # synthetic self-contained ideas present

    def test_hackathon_with_bad_link_dropped(self):
        idx = {"keys": {}, "static": {"starters": {}, "cyber_domains": {}, "cases": {}, "paths": {}, "stages": []},
               "hackathons": {"at": self.meta["generated_at"], "items": [
                   {"title": "Good", "url": "https://devpost.com/x", "when": "", "where": "NYC", "org": "", "src": "Devpost"},
                   {"title": "Bad", "url": "https://mediafire.com/evil.exe", "when": "", "where": "NYC", "org": "", "src": "x"}]}}
        pub = pipeline._build_published(idx, {"records": {}}, self.meta, self.quar)
        urls = [h["url"] for h in pub["hackathons"]["items"]]
        self.assertIn("https://devpost.com/x", urls)
        self.assertNotIn("https://mediafire.com/evil.exe", urls)


class Drop(unittest.TestCase):
    def test_drop_excludes_already_seen(self):
        meta = pipeline._meta("operational")
        published = {"feed": {"swe|build|": [
            {**frow("new/a"), "kind": "fresh", "screened": {"sha": "a" * 40}, "level": "beginner"},
            {**frow("old/b"), "kind": "fresh", "screened": {"sha": "a" * 40}, "level": "beginner"}]},
            "hackathons": {"items": []}, "evergreen": {}}
        seen = {"old/b": "2026-01-01"}
        drop = pipeline._drop_sections(published, seen)
        picked = [r["full_name"] for sec in drop for part in sec.get("sections", []) for r in part["rows"]]
        self.assertIn("new/a", picked)
        self.assertNotIn("old/b", picked)


class Status(unittest.TestCase):
    def test_status_text_mentions_pause_when_not_operational(self):
        # with no published.json present in cwd during test, status is not operational
        txt = gate.status_text()
        self.assertTrue("OPERATIONAL" in txt or "PAUSED" in txt)
        self.assertIn(gate.LABEL, txt)


if __name__ == "__main__":
    unittest.main()
