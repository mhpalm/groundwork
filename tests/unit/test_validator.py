# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import NOW, fresh  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
