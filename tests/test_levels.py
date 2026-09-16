"""Undergraduate level classification: default beginner, explicit choice, no harder-than-asked substitution."""
import unittest

import levels


def row(desc="a project", lang="Python", name="x/repo"):
    return {"full_name": name, "description": desc, "language": lang, "size": 500, "stargazers_count": 10}


def rec(**signals):
    return {"coverage": {"signals": signals}}


class Classify(unittest.TestCase):
    def test_beginner_default_wording(self):
        self.assertEqual(levels.classify(row("a beginner tutorial to learn Python"))["level"], "beginner")

    def test_intermediate_from_signals(self):
        r = levels.classify(row("A REST API with a database"), rec(has_tests=True, has_dockerfile=True, dep_count=10, readme_bytes=400, top_level_entries=12))
        self.assertIn(r["level"], ("intermediate", "challenge"))

    def test_excludes_distributed_infra(self):
        self.assertEqual(levels.classify(row("distributed training on a kubernetes cluster at production-scale", "Go"))["level"], "exclude")

    def test_excludes_grad_math(self):
        self.assertEqual(levels.classify(row("PhD-level measure theory and stochastic calculus"))["level"], "exclude")

    def test_excludes_specialized_hardware(self):
        self.assertEqual(levels.classify(row("Verilog FPGA project, requires a GPU cluster", "Verilog"))["level"], "exclude")

    def test_excludes_from_terraform_signal(self):
        self.assertEqual(levels.classify(row("a service", "Go"), rec(has_terraform=True))["level"], "exclude")

    def test_unknown_when_no_evidence(self):
        self.assertEqual(levels.classify(row("a thing", "Rust"))["level"], "unknown")

    def test_labels_present_and_effort_marked_estimate(self):
        for lv in levels.FEED_LEVELS:
            meta = levels._pack(lv, "Python", [], "high")
            self.assertTrue(meta["prereqs"] and meta["task"] and meta["success"])
            self.assertIn("(estimate)", meta["effort"])

    def test_feed_levels_exclude_advanced_and_unknown(self):
        self.assertNotIn("exclude", levels.FEED_LEVELS)
        self.assertNotIn("unknown", levels.FEED_LEVELS)


if __name__ == "__main__":
    unittest.main()
