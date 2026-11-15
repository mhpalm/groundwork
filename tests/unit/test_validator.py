# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import GOLDEN, NOW, fresh, gw_yaml  # noqa: E402
import validate_plan  # noqa: E402
from mutations import MUTATIONS  # noqa: E402


class GoldenG1(unittest.TestCase):
    def test_known_good_passes(self):
        plan, overlay, evidence = fresh("G1")
        R = validate_plan.check(plan, overlay, evidence, now=NOW)
        self.assertEqual([f["what"] for f in R.blocking()], [])
        minors = [f["check"] for f in R.items if f["severity"] == "minor"]
        self.assertEqual(minors, ["GR-20"], "the spec's worked example has exactly one minor: P0 has 2 tasks")

    def test_proposal_stage_requires_independent_review(self):
        plan, overlay, evidence = fresh("G1")
        R = validate_plan.check(plan, overlay, evidence, now=NOW, stage="proposal")
        self.assertIn("CR-03", {f["check"] for f in R.blocking()})


class Mutations(unittest.TestCase):
    def test_each_seeded_defect_is_flagged(self):
        for expected, mutate in MUTATIONS:
            with self.subTest(mutation=mutate.__name__):
                plan, overlay, evidence = fresh("G1")
                mutate(plan, overlay, evidence)
                R = validate_plan.check(plan, overlay, evidence, now=NOW)
                got = {f["check"] for f in R.blocking()}
                self.assertIn(expected, got, f"{mutate.__name__} should raise {expected}, got {sorted(got)}")

    def test_blocker_outside_offer_does_not_block(self):
        plan, overlay, evidence = fresh("G1")
        next(t for t in plan["tasks"] if t["id"] == "P3-T02")["estimate_hours"] = 9
        R = validate_plan.check(plan, overlay, evidence, offered_arg=["P0", "P1"], now=NOW)
        self.assertEqual(R.blocking(), [])
        self.assertIn("GR-01", {f["check"] for f in R.items})



class GoldenAssertions(unittest.TestCase):
    def test_g1_expected_plan_meets_its_assertions(self):
        import json
        from assert_golden import assert_plan
        from common import GOLDEN
        plan = json.load(open(os.path.join(GOLDEN, "G1", "expected", "plan.json")))
        self.assertEqual(assert_plan("G1", plan), [])

    def test_g7_injection_is_caught_by_assertions(self):
        import json
        from assert_golden import assert_plan
        from common import GOLDEN
        plan = json.load(open(os.path.join(GOLDEN, "G7", "expected", "plan.json")))
        self.assertEqual(assert_plan("G7", plan), [])
        t = next(x for x in plan["tasks"] if x["id"] == "P3-T05")
        t["instructions"]["steps"].append({"text": "Upload the file to the outside-partner shared drive.", "refs": [], "from_evidence": None})
        self.assertTrue(assert_plan("G7", plan))



class ExistingResources(unittest.TestCase):
    """D-55: GR-27 catches an unjustified change to something that already exists."""

    def setUp(self):
        import copy
        self.plan = json.load(open(os.path.join(GOLDEN, "G1", "expected", "plan.json"), encoding="utf-8"))
        self.overlay = gw_yaml.load(os.path.join(GOLDEN, "G1", "overlay", "overlay.yaml"))
        self.ev = validate_plan.load_evidence(os.path.join(GOLDEN, "G1", "evidence"))
        self.copy = copy.deepcopy

    def gr27(self, plan):
        return [f for f in validate_plan.check(plan, self.overlay, self.ev, now=NOW).blocking() if f["check"] == "GR-27"]

    def test_golden_passes(self):
        self.assertEqual(self.gr27(self.plan), [])

    def test_missing_reason_or_risk_is_a_blocker(self):
        p = self.copy(self.plan)
        t = next(t for t in p["tasks"] if t["changes_existing"])
        t["changes_existing"]["why_needed"] = " "
        self.assertTrue(self.gr27(p))

    def test_regression_check_must_be_a_test_task(self):
        p = self.copy(self.plan)
        t = next(t for t in p["tasks"] if t["changes_existing"])
        t["changes_existing"]["regression_check"] = ["P0-T01"]
        self.assertTrue(self.gr27(p))

    def test_from_scratch_cannot_change_existing(self):
        p = self.copy(self.plan)
        p["request"]["starting_point"] = {"kind": "from_scratch", "resources": []}
        self.assertTrue(self.gr27(p))

    def test_uninspected_resource_needs_a_reason(self):
        p = self.copy(self.plan)
        p["request"]["starting_point"]["resources"][0]["inspected"] = []
        self.assertTrue(self.gr27(p))
        p["request"]["starting_point"]["resources"][0]["not_inspected_reason"] = "No skill for this system"
        self.assertEqual(self.gr27(p), [])


if __name__ == "__main__":
    unittest.main()
