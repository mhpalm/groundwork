# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Eighth review: the retire rebuild and recheck read the manifest, approvals require the derived
relinks and unblocks, a deleted dropped item is recorded as missing, and the diff's smaller guards."""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
sys.path.insert(0, os.path.dirname(__file__))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import create_steps  # noqa: E402
import render_proposal  # noqa: E402
import retire  # noqa: E402
import revise_diff  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, retire_items, run_close, run_create  # noqa: E402
from test_review5 import repoint_revision, tracker_report  # noqa: E402

PH = ["P0", "P1"]


def created():
    plan, ov, _e = fresh("G1")
    tr = FakeTracker()
    assert run_create(tr, plan, ov, PH)["ok"]
    return tr, plan, ov


def bump(p):
    n = copy.deepcopy(p)
    n["version"] += 1
    return n


class Base(unittest.TestCase):
    def setUp(self):
        self.tr, self.plan, self.ov = created()
        self.v2 = repoint_revision(self.plan)  # drops P1-T02, re-points P1-T03; stored, never applied
        next(t for t in self.v2["tasks"] if t["id"] == "P1-T03")["waits_on"] = []
        self.v3 = bump(self.v2)
        self.dropped = f"gw:{self.plan['id']}:P1-T02"
        self.m = latest_manifest(self.tr, self.plan["id"])

    def diff(self, report=None):
        rep, _m = tracker_report(self.tr, self.v2, self.ov)
        return revise_diff.diff(self.v2, self.v3, rep if report is None else report, self.ov, self.m)


class RetireReadsTheManifest(Base):
    """M1: the verifier's retire rebuild and the write-time recheck classify with the manifest."""

    def wl_for(self, rp):
        return retire.write_list(self.v3, self.ov, rp)

    def test_the_honest_retire_rebuilds_and_a_forged_one_is_refused(self):
        items = retire_items(self.tr, self.v3, self.ov, "VOL-1")
        ctx = render_proposal.proposal_context(self.v3, "retire", "Retire.", items=items)
        honest = self.wl_for(retire.plan_retire(items, {}, self.m))
        self.assertIn(self.dropped, [w["key"] for w in honest["writes"] if w["kind"] == "close_item"])
        self.assertEqual(check_hashes.rebuilt_plan_level_problems(self.v3, self.ov, honest, ctx, self.m), [])
        flagged = [dict(i, person_added=True) if i["key"] == self.dropped else i for i in items]
        forged = self.wl_for(retire.plan_retire(flagged, {}))  # built without the manifest: leaves it open
        self.assertNotIn(self.dropped, [w["key"] for w in forged["writes"] if w["kind"] == "close_item"])
        forged_ctx = render_proposal.proposal_context(self.v3, "retire", "Retire.", items=flagged)
        self.assertTrue(check_hashes.rebuilt_plan_level_problems(self.v3, self.ov, forged, ctx, self.m))
        self.assertTrue(check_hashes.rebuilt_plan_level_problems(self.v3, self.ov, forged, forged_ctx, self.m))
        # a context that flags a recorded key is refused even when the write list closes it
        self.assertTrue(check_hashes.rebuilt_plan_level_problems(self.v3, self.ov, honest, forged_ctx, self.m))
        # a recorded key the read missed is closed as missing, and only the manifest shows it
        absent = [i for i in items if i["key"] != self.dropped]
        actx = render_proposal.proposal_context(self.v3, "retire", "Retire.", items=absent)
        awl = self.wl_for(retire.plan_retire(absent, {}, self.m))
        self.assertEqual(check_hashes.rebuilt_plan_level_problems(self.v3, self.ov, awl, actx, self.m), [])

    def test_the_recheck_never_calls_a_recorded_key_a_persons(self):
        items = retire_items(self.tr, self.v3, self.ov, "VOL-1")
        rp = retire.plan_retire(items, {}, self.m)
        wl = self.wl_for(rp)
        seen = {i["key"]: i["status"] for i in rp["seen"]}
        flagged = [dict(i, person_added=True) if i["key"] == self.dropped else i for i in items]
        self.assertEqual(retire.recheck(wl, flagged, seen, self.m), [])
        self.assertTrue(retire.recheck(wl, flagged, seen))


class ApprovalsRequireDerivedWrites(Base):
    """M2: a write list must carry exactly the relinks and unblocks the manifest implies."""

    def test_missing_or_extra_relinks_and_unblocks_are_refused(self):
        d = self.diff()
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["unblocks"], ["P1-T03"])
        offer = sorted({t["phase"] for t in self.v3["tasks"] if t["id"] in d["edits"]})
        good = render_proposal.write_list(self.v3, self.ov, offer, d["close_items"], None, d["edits"], d["relinks"],
                                          d["unblocks"])
        self.assertEqual(check_hashes.rebuilt_write_list_problems(self.v3, self.ov, good, self.m), [])
        for name, rel, unb in (("no relink", [], d["unblocks"]), ("no unblock", d["relinks"], []), ("neither", [], [])):
            bad = render_proposal.write_list(self.v3, self.ov, offer, d["close_items"], None, d["edits"], rel, unb)
            with self.subTest(name):
                probs = check_hashes.rebuilt_write_list_problems(self.v3, self.ov, bad, self.m)
                self.assertTrue(probs and "relinks and unblocks" in probs[0], probs)


class DeletedDroppedItem(Base):
    """M3: a dropped item a person deleted is closed as missing, and the plan moves on."""

    def setUp(self):
        super().setUp()
        tid = next(i["tracker_id"] for i in self.tr.items.values() if i["key"] == self.dropped)
        del self.tr.items[tid]

    def test_revise_close_and_retire_all_move_on(self):
        d = self.diff()
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["missing"], [self.dropped])
        r = run_close(self.tr, self.v3, self.ov, d["close_items"])
        self.assertTrue(r["ok"], r)
        m = latest_manifest(self.tr, self.plan["id"])
        self.assertEqual(next(i for i in m["items"] if i["key"] == self.dropped)["close"]["state"], "missing")
        self.assertEqual(revise_diff.required_closes(self.v3, m), [])
        wl = {"plan_version": 3, "writes": [{"no": 1, "kind": "close_item", "key": self.dropped, "reason": "not_planned"}]}
        self.assertEqual(create_steps.unfinished(wl, m), [])
        self.assertTrue(retire.plan_retire(retire_items(self.tr, self.v3, self.ov, "VOL-1"), {}, m)["ok"])

    def test_a_key_named_missing_that_exists_stops(self):
        k = f"gw:{self.plan['id']}:P1-T01"
        m = latest_manifest(self.tr, self.plan["id"])
        found = [{"key": k, "tracker_id": "x", "status": "todo"}]
        out = create_steps.close_steps([{"key": k, "reason": "not_planned"}], m, found, [k])
        self.assertFalse(out["ok"])
        out = create_steps.close_steps([{"key": "gw:other:P1-T01", "reason": "not_planned"}], m, [], ["gw:other:P1-T01"])
        self.assertFalse(out["ok"])


class SmallerGuards(Base):
    def test_a_dropped_written_key_is_never_reused(self):
        v3 = bump(self.v2)
        t = copy.deepcopy(next(x for x in self.plan["tasks"] if x["id"] == "P1-T02"))
        v3["tasks"].append(t)
        next(p for p in v3["phases"] if p["id"] == "P1")["task_ids"].append("P1-T02")
        rep, _m = tracker_report(self.tr, self.v2, self.ov)
        d = revise_diff.diff(self.v2, v3, rep, self.ov, self.m)
        self.assertFalse(d["ok"])
        self.assertTrue(any("dropped" in r["why"] for r in d["refused"]))

    def test_a_crashed_approved_update_is_adopted_not_drift(self):
        k = f"gw:{self.plan['id']}:P1-T01"
        t2 = bump(self.plan)
        task = next(x for x in t2["tasks"] if x["key"] == k)
        task["title"] += " (approved)"
        body = render_proposal.task_body(t2, self.ov, task)
        tid = next(i["tracker_id"] for i in self.tr.items.values() if i["key"] == k)
        self.tr.update_owned(tid, task["title"], body)  # the update landed; the manifest was never written
        rep, m = tracker_report(self.tr, t2, self.ov)
        d = revise_diff.diff(t2, bump(t2), rep, self.ov, m)
        self.assertTrue(d["ok"], d)
        self.assertEqual((d["adopted"], d["drift"]), (["P1-T01"], []))
        t4 = bump(t2)
        next(x for x in t4["tasks"] if x["key"] == k)["title"] += " again"
        self.assertFalse(revise_diff.diff(t2, t4, rep, self.ov, m)["ok"])

    def test_no_manifest_while_the_plan_is_written_is_refused(self):
        dd = tempfile.mkdtemp()
        P = lambda n: os.path.join(dd, n)
        rep, _m = tracker_report(self.tr, self.v2, self.ov)
        rep, _m = tracker_report(self.tr, self.plan, self.ov)
        json.dump(self.plan, open(P("base.json"), "w"))
        json.dump(bump(self.plan), open(P("new.json"), "w"))
        json.dump(rep, open(P("tracker.json"), "w"))
        ovp = os.path.join(os.path.dirname(__file__), "..", "golden", "G1", "overlay", "overlay.yaml")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(revise_diff.main([P("base.json"), P("new.json"), P("tracker.json"), "--overlay", ovp,
                                               "--manifests"]), 1)

        class A:
            manifests, status, epic = [], "-", "open"
        written = copy.deepcopy(self.plan)
        written["phases"][0]["state"] = "released"
        with self.assertRaises(ValueError):
            check_hashes.cli_plan_state(A, written["id"], written)
        self.assertIsNone(check_hashes.cli_plan_state(A, self.plan["id"], fresh("G1")[0])["manifest"])


if __name__ == "__main__":
    unittest.main()
