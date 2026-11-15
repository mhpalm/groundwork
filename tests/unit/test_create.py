# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Create-step tests on the fake tracker (spec section 10)."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import create_steps  # noqa: E402
from fake_tracker import FakeTracker, run_create  # noqa: E402

PH = ["P0", "P1"]


def g1():
    plan, overlay, _e = fresh("G1")
    return plan, overlay


class Idempotency(unittest.TestCase):
    def test_second_run_makes_no_item_writes(self):
        plan, ov = g1()
        tr = FakeTracker()
        self.assertTrue(run_create(tr, plan, ov, PH)["ok"])
        n_items = len(tr.items)
        self.assertEqual(n_items, 7)
        self.assertTrue(all(not i["not_ready"] for i in tr.items.values()))
        before = tr.writes
        pf = run_create(tr, plan, ov, PH, run="run-2")
        self.assertTrue(pf["ok"])
        self.assertEqual(len(tr.items), n_items)
        self.assertTrue(all(a["action"] == "skip" for a in pf["actions"]))
        # only housekeeping writes: lock claim, two manifests each followed by a renew, lock release
        self.assertEqual(tr.writes - before, 6)

    def test_partial_failure_then_resume_has_no_duplicates(self):
        plan, ov = g1()
        for k in range(2, 30, 3):
            tr = FakeTracker()
            tr.fail_at = k
            r = run_create(tr, plan, ov, PH)
            with self.subTest(fail_at=k):
                if r.get("ok") is False and "failed" in r:
                    self.assertTrue(any(i["not_ready"] for i in tr.items.values()) or not tr.items)
                pf = run_create(tr, plan, ov, PH, run="run-2")
                self.assertTrue(pf["ok"], pf)
                keys = [i["key"] for i in tr.items.values()]
                self.assertEqual(len(keys), len(set(keys)))
                self.assertEqual(len(keys), 7)
                self.assertTrue(all(not i["not_ready"] for i in tr.items.values()))

    def test_crash_before_manifest_is_adopted_not_duplicated(self):
        plan, ov = g1()
        tr = FakeTracker()
        tr.fail_at = 5  # lock claim is write 1; creates 2..4 succeed, then the session dies
        r = run_create(tr, plan, ov, PH, hard_crash=True)
        self.assertTrue(r.get("crashed"))
        self.assertEqual(len(tr.items), 3)
        tr.tick(31 * 60)  # the dead run's lock expires
        pf = run_create(tr, plan, ov, PH, run="run-2")
        self.assertTrue(pf["ok"], pf)
        self.assertEqual(sum(1 for a in pf["actions"] if a["action"] == "adopt"), 3)
        self.assertEqual(len(tr.items), 7)

    def test_search_lag_is_covered_by_manifest(self):
        plan, ov = g1()
        tr = FakeTracker(search_lag_writes=3)
        self.assertTrue(run_create(tr, plan, ov, PH)["ok"])
        pf = run_create(tr, plan, ov, PH, run="run-2")
        # lagging items look missing to search but the manifest says written: stop, never recreate
        self.assertFalse(pf["ok"])
        self.assertEqual(len(tr.items), 7)
        tr.settle()
        self.assertTrue(run_create(tr, plan, ov, PH, run="run-3")["ok"])


class Drift(unittest.TestCase):
    def test_human_edit_of_owned_field_stops(self):
        plan, ov = g1()
        tr = FakeTracker()
        run_create(tr, plan, ov, PH)
        item = next(i for i in tr.items.values() if i["key"].endswith("P1-T02"))
        item["body"] = item["body"].replace("Purpose.", "Purpose (edited).")
        pf = run_create(tr, plan, ov, PH, run="run-2")
        self.assertFalse(pf["ok"])
        self.assertIn("drift", pf["stops"][0]["why"])

    def test_notes_outside_owned_section_are_not_drift(self):
        plan, ov = g1()
        tr = FakeTracker()
        run_create(tr, plan, ov, PH)
        item = next(i for i in tr.items.values() if i["key"].endswith("P1-T02"))
        item["body"] += "\n\nNote from the team: pair with Sam."
        item["title"] = "  " + item["title"] + "  "
        self.assertTrue(run_create(tr, plan, ov, PH, run="run-2")["ok"])

    def test_ticked_steps_are_not_drift(self):
        plan, ov = g1()
        tr = FakeTracker()
        run_create(tr, plan, ov, PH)
        item = next(i for i in tr.items.values() if i["key"].endswith("P1-T02"))
        item["body"] = item["body"].replace("- [ ] 1.", "- [x] 1.").replace("- [ ] 2.", "- [X] 2.")
        self.assertTrue(run_create(tr, plan, ov, PH, run="run-2")["ok"])

    def test_deleted_item_stops_and_is_not_recreated(self):
        plan, ov = g1()
        tr = FakeTracker()
        run_create(tr, plan, ov, PH)
        tid = next(t for t, i in tr.items.items() if i["key"].endswith("P1-T03"))
        del tr.items[tid]
        pf = run_create(tr, plan, ov, PH, run="run-2")
        self.assertFalse(pf["ok"])
        self.assertEqual(len(tr.items), 6)

    def test_drift_in_other_phase_is_a_warning(self):
        plan, ov = g1()
        tr = FakeTracker()
        run_create(tr, plan, ov, PH)
        item = next(i for i in tr.items.values() if i["key"].endswith("P0-T01"))
        item["body"] = item["body"].replace("Purpose.", "Purpose (edited).")
        pf = run_create(tr, plan, ov, ["P2"], run="run-2")
        self.assertTrue(pf["ok"], pf)
        self.assertTrue(pf["warnings"])

    def test_larger_points_kept_with_split_comment(self):
        plan, ov = g1()
        tr = FakeTracker()
        run_create(tr, plan, ov, PH)
        item = next(i for i in tr.items.values() if i["key"].endswith("P1-T02"))
        item["points"] = 3
        pf = run_create(tr, plan, ov, PH, run="run-2")
        self.assertTrue(pf["ok"])
        self.assertIn("comment_split", [a["action"] for a in pf["actions"]])
        self.assertEqual(item["points"], 3)


class Lock(unittest.TestCase):
    def test_same_second_claims_one_winner(self):
        t = create_steps.ts("2026-11-15T12:00:00Z")
        c = lambda ref, acct, run: {"ref": ref, "author_account_id": acct, "created_at": "2026-11-15T12:00:00Z",
                                    "body": create_steps.lock_line("claim", run, acct, t)}
        comments = [c("c2", "acct-b", "run-b"), c("c1", "acct-a", "run-a")]
        a = create_steps.lock_decision(comments, "run-a", "acct-a", t)
        b = create_steps.lock_decision(comments, "run-b", "acct-b", t)
        self.assertEqual({a["decision"], b["decision"]}, {"held", "lost"})

    def test_expired_claim_is_ignored_and_forged_claim_rejected(self):
        t = create_steps.ts("2026-11-15T12:00:00Z")
        old = {"ref": "c1", "author_account_id": "acct-a", "created_at": "2026-11-15T11:00:00Z",
               "body": create_steps.lock_line("claim", "run-a", "acct-a", t - dt.timedelta(hours=1))}
        forged = {"ref": "c2", "author_account_id": "acct-x", "created_at": "2026-11-15T11:59:00Z",
                  "body": create_steps.lock_line("claim", "run-z", "acct-z", t)}
        self.assertEqual(create_steps.lock_decision([old, forged], "run-b", "acct-b", t)["decision"], "claim")

    def test_contention_on_tracker_only_one_writes(self):
        plan, ov = g1()
        tr = FakeTracker()
        tr.comment("acct-other", create_steps.lock_line("claim", "run-x", "acct-other", tr.clock))
        r = run_create(tr, plan, ov, PH)
        self.assertFalse(r["ok"])
        self.assertEqual(r["lock"]["decision"], "lost")
        self.assertEqual(len(tr.items), 0)


class Manifest(unittest.TestCase):
    def test_broken_chain_stops(self):
        from check_hashes import verify_chain
        now = create_steps.ts("2026-11-15T12:00:00Z")
        m1 = create_steps.make_manifest(None, [], "gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC", "r", 1, now, [])
        m2 = create_steps.make_manifest(m1, [], "gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC", "r", 2, now, [])
        latest, probs = verify_chain([m1, m2])
        self.assertEqual(latest["seq"], 2)
        self.assertEqual(probs, [])
        m2b = dict(m2, prev_hash="0" * 64)
        from gw_hash import item_hash
        m2b["hash"] = item_hash(m2b)
        latest, probs = verify_chain([m1, m2b])
        self.assertEqual(latest["seq"], 1)
        self.assertTrue(probs)

    def test_plan_store_never_overwrites(self):
        from fake_tracker import WriteFailed
        tr = FakeTracker()
        tr.put("x-plan-v1", {})
        with self.assertRaises(WriteFailed):
            tr.put("x-plan-v1", {})


if __name__ == "__main__":
    unittest.main()
