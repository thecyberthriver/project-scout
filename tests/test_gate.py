"""Proof that no unqualified repository reaches students through the eligibility gate. Offline; no network, no sends."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import gate
import links

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def row(full="ok/repo", pushed=None, created=None, kind="fresh", sha="a" * 40):
    return {"full_name": full, "html_url": f"https://github.com/{full}", "stargazers_count": 10, "language": "Python",
            "description": "a repo", "size": 500, "pushed_at": (pushed or (NOW - DAY).date().isoformat()),
            "created_at": (created or (NOW - DAY).date().isoformat()), "kind": kind, "screened": {"sha": sha}}


def store_with(full="ok/repo", result="pass", sha="a" * 40, expires=None, policy=gate.POLICY_VERSION, coverage=None):
    return {"policy_version": gate.POLICY_VERSION, "records": {full: {
        "full_name": full, "result": result, "sha": sha, "at": iso(NOW - DAY),
        "expires": expires or iso(NOW + 10 * DAY), "policy_version": policy,
        "coverage": coverage or {"code_scan_result": "pass"}, "reasons": []}}}


META = {"status": "operational", "fresh_field": "pushed_at", "fresh_days": 30, "last_screening_at": iso(NOW)}
QUAR = {"names": set(), "reasons": {}, "patterns": []}


class Eligibility(unittest.TestCase):
    def test_clean_repo_passes(self):
        ok, why = gate.eligible(row(), store_with(), QUAR, META, NOW)
        self.assertTrue(ok, why)

    def test_missing_screening_record_withheld(self):
        ok, why = gate.eligible(row(), {"records": {}}, QUAR, META, NOW)
        self.assertFalse(ok)
        self.assertIn("no screening record", why[0])

    def test_failed_screening_withheld(self):
        ok, _ = gate.eligible(row(), store_with(result="fail"), QUAR, META, NOW)
        self.assertFalse(ok)

    def test_expired_screening_withheld(self):
        ok, why = gate.eligible(row(), store_with(expires=iso(NOW - DAY)), QUAR, META, NOW)
        self.assertFalse(ok)
        self.assertTrue(any("expired" in w for w in why))

    def test_changed_commit_withheld(self):
        r = row(sha="b" * 40)  # row's screened sha differs from the record's sha
        ok, why = gate.eligible(r, store_with(sha="a" * 40), QUAR, META, NOW)
        self.assertFalse(ok)
        self.assertTrue(any("commit changed" in w for w in why))

    def test_old_policy_version_withheld(self):
        ok, _ = gate.eligible(row(), store_with(policy=1), QUAR, META, NOW)
        self.assertFalse(ok)

    def test_freshness_boundary_30_days_passes_31_fails(self):
        ok30, _ = gate.eligible(row(pushed=(NOW - 30 * DAY).date().isoformat()), store_with(), QUAR, META, NOW)
        ok31, _ = gate.eligible(row(pushed=(NOW - 31 * DAY).date().isoformat()), store_with(), QUAR, META, NOW)
        self.assertTrue(ok30)
        self.assertFalse(ok31)

    def test_evergreen_exempt_from_freshness_but_not_screening(self):
        old = row(pushed=(NOW - 400 * DAY).date().isoformat(), kind="evergreen")
        self.assertTrue(gate.eligible(old, store_with(), QUAR, META, NOW)[0])
        self.assertFalse(gate.eligible(old, store_with(result="fail"), QUAR, META, NOW)[0])

    def test_quarantined_never_eligible_even_with_passing_record(self):
        q = {"names": {"elementtrail/multichain-drainer"}, "reasons": {"elementtrail/multichain-drainer": "wallet drainer"}, "patterns": []}
        r = row(full="ElementTrail/Multichain-Drainer")
        st = store_with(full="ElementTrail/Multichain-Drainer")  # even if something recorded a pass
        ok, why = gate.eligible(r, st, q, META, NOW)
        self.assertFalse(ok)
        self.assertIn("quarantined", why[0])


class Quarantine(unittest.TestCase):
    def test_loads_the_two_named_repos(self):
        q = gate.load_quarantine(os.path.join(os.path.dirname(__file__), "..", "quarantine.json"))
        self.assertIsNotNone(gate.is_quarantined("ElementTrail/Multichain-Drainer", q))
        self.assertIsNotNone(gate.is_quarantined("WildOctopusCrack/Ghostfolio-Privacy-First-Personal-Finance-Wealth-Tracker", q))

    def test_name_pattern_blocks_clones(self):
        q = gate.load_quarantine(os.path.join(os.path.dirname(__file__), "..", "quarantine.json"))
        self.assertIsNotNone(gate.is_quarantined("someone/Ghostfolio-Privacy-Wealth-Tracker", q))
        self.assertIsNone(gate.is_quarantined("torvalds/linux", q))


class ContentPolicy(unittest.TestCase):
    def test_prohibited_wording_blocks(self):
        self.assertTrue(gate.content_policy({"full_name": "x/y", "description": "a wallet drainer for MetaMask"}))
        self.assertTrue(gate.content_policy({"full_name": "x/cracked-idea", "description": "cracked software"}))

    def test_dual_use_kept_out_of_general_feed(self):
        self.assertTrue(gate.content_policy({"full_name": "x/y", "description": "a keylogger for testing"}))

    def test_curated_security_tool_not_flagged(self):
        # a curated legitimate security tool is not treated as malware
        self.assertEqual(gate.content_policy({"full_name": "OWASP/wstg", "description": "web security testing guide"}, curated=True), [])

    def test_ordinary_repo_clean(self):
        self.assertEqual(gate.content_policy({"full_name": "pandas-dev/pandas", "description": "data analysis"}), [])


class RecordCurrency(unittest.TestCase):
    def test_expired_not_current(self):
        rec = {"policy_version": gate.POLICY_VERSION, "expires": iso(NOW - DAY), "sha": "a" * 40}
        self.assertFalse(gate.record_is_current(rec, None, NOW))

    def test_changed_sha_not_current(self):
        rec = {"policy_version": gate.POLICY_VERSION, "expires": iso(NOW + DAY), "sha": "a" * 40}
        self.assertFalse(gate.record_is_current(rec, "b" * 40, NOW))
        self.assertTrue(gate.record_is_current(rec, "a" * 40, NOW))


class Freshness(unittest.TestCase):
    def test_uses_configured_field(self):
        r = {"pushed_at": (NOW - 5 * DAY).date().isoformat(), "created_at": (NOW - 500 * DAY).date().isoformat()}
        self.assertTrue(gate.fresh_enough(r, {"fresh_field": "pushed_at", "fresh_days": 30}, NOW))
        self.assertFalse(gate.fresh_enough(r, {"fresh_field": "created_at", "fresh_days": 30}, NOW))


if __name__ == "__main__":
    unittest.main()
