# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Seventh review: a version stored but never applied can't lose its closes, relinks or unblocks;
retire never names a Groundwork item as a person's; the draft label removal is recorded."""
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
from fake_tracker import FakeTracker, latest_manifest, retire_items, run_create  # noqa: E402
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


class StoredButNeverApplied(unittest.TestCase):
    """M1: the next version's diff works from the manifest, not only from the base plan."""

    def setUp(self):
        self.tr, self.plan, self.ov = created()
        self.v2 = repoint_revision(self.plan)  # drops P1-T02 and re-points P1-T03; stored, never applied
        self.v3 = bump(self.v2)
        report, self.m = tracker_report(self.tr, self.v2, self.ov)
        self.d = revise_diff.diff(self.v2, self.v3, report, self.ov, self.m)
        self.dropped = f"gw:{self.plan['id']}:P1-T02"

    def test_the_dropped_task_is_still_closed(self):
        self.assertTrue(self.d["ok"], self.d)
        self.assertEqual(self.d["close_items"], [{"key": self.dropped, "reason": "not_planned"}])

    def test_the_relink_is_still_made(self):
        self.assertEqual(self.d["relinks"], [{"task": "P1-T03", "added": ["P1-T01"], "removed": ["P1-T02"]}])

    def test_a_write_list_that_leaves_the_close_out_is_refused(self):
        wl = render_proposal.write_list(self.v3, self.ov, [], None, None, [], self.d["relinks"], self.d["unblocks"])
        probs = check_hashes.rebuilt_write_list_problems(self.v3, self.ov, wl, self.m)
        self.assertTrue(probs and "leaves open" in probs[0])
        wl = render_proposal.write_list(self.v3, self.ov, [], self.d["close_items"], None, [], self.d["relinks"],
                                        self.d["unblocks"])
        self.assertEqual(check_hashes.rebuilt_write_list_problems(self.v3, self.ov, wl, self.m), [])

    def test_a_recorded_close_is_not_asked_for_again(self):
        m = copy.deepcopy(self.m)
        next(i for i in m["items"] if i["key"] == self.dropped)["close"] = {"reason": "not_planned", "state": "closed"}
        self.assertEqual(revise_diff.required_closes(self.v3, m), [])

    def test_a_recorded_dropped_task_the_read_misses_is_refused(self):
        report, m = tracker_report(self.tr, self.v2, self.ov)
        report = [r for r in report if r["key"] != self.dropped]
        d = revise_diff.diff(self.v2, self.v3, report, self.ov, m)
        self.assertFalse(d["ok"])

    def test_retire_closes_it_instead_of_naming_it_a_persons(self):
        items = retire_items(self.tr, self.v3, self.ov, "VOL-1")
        r = retire.plan_retire(items, {}, self.m)
        self.assertNotIn(self.dropped, r["person_added"])
        self.assertIn(self.dropped, [c["key"] for c in r["closes"]])
        flagged = [dict(i, person_added=True) if i["key"] == self.dropped else i for i in items]
        self.assertIn(self.dropped, [c["key"] for c in retire.plan_retire(flagged, {}, self.m)["closes"]])
        missing = [i for i in items if i["key"] != self.dropped]
        self.assertFalse(retire.plan_retire(missing, {}, self.m)["ok"])

    def test_the_retire_cli_needs_the_manifests(self):
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)
        json.dump(retire_items(self.tr, self.v3, self.ov, "VOL-1"), open(P("items.json"), "w"))
        json.dump({}, open(P("choices.json"), "w"))
        paths = []
        for k, v in sorted(self.tr.store.items()):
            if k.startswith(f"{self.plan['id']}-manifest-"):
                paths.append(P(k + ".json"))
                json.dump(v, open(paths[-1], "w"))
        for argv, rc in ((["plan", P("items.json"), P("choices.json")], 1),
                         (["plan", P("items.json"), P("choices.json"), "--plan-id", self.plan["id"], "--manifests", *paths], 0)):
            buf = io.StringIO()
            with self.subTest(argv=len(argv)), redirect_stdout(buf):
                self.assertEqual(retire.main(argv), rc)
        self.assertIn(self.dropped, [c["key"] for c in json.loads(buf.getvalue())["closes"]])


class ApprovalsReadTheManifest(unittest.TestCase):
    """M1: approvals refuse a phase write list that leaves a recorded, dropped task open."""

    def test_verify_approvals_uses_the_latest_manifest(self):
        from test_approval_sets import NOW, base, comment, phase_case, record
        plan, ov, anchor, rev = base()
        wl, prop = phase_case(plan, ov)
        recs = [comment(record(plan, prop, wl, rev, ["P1"]))]
        item = {"key": f"gw:{plan['id']}:P9-T99", "tracker_id": "T9", "owned_hash": "a" * 64, "links": [], "not_ready": False}
        foreign = dict(item, key="gw:gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ:P1-T01", tracker_id="T8")
        t = create_steps.ts("2026-11-15T10:00:00Z")
        for items, bad in (([item], True), ([foreign], False)):
            m = create_steps.make_manifest(None, items, plan["id"], "r", 1, t, [])
            state = {"manifest": m, "status": None, "epic": "open"}
            _ok, probs, _ = check_hashes.verify_approvals(plan, ov, anchor, recs, prop, wl, rev, ["P1"], NOW, False,
                                                          None, None, state)
            with self.subTest(bad=bad):
                self.assertEqual(any("leaves open" in p for p in probs), bad, probs)


class UnblockOnlyWhatGroundworkSet(unittest.TestCase):
    """m1: an unblock follows the manifest's blocked state, and a clear of a block never set is satisfied."""

    def test_no_unblock_when_the_block_never_landed(self):
        tr, plan, ov = created()
        k = f"gw:{plan['id']}:P1-T03"
        m = latest_manifest(tr, plan["id"])
        items = [dict({x: v for x, v in i.items() if x != "blocked_set"}) if i["key"] == k else i for i in m["items"]]
        m = dict(m, items=items)
        new = bump(plan)
        next(t for t in new["tasks"] if t["id"] == "P1-T03")["waits_on"] = []
        report, _m = tracker_report(tr, plan, ov)
        self.assertEqual(revise_diff.diff(plan, new, report, ov, m)["unblocks"], [])
        self.assertEqual(revise_diff.diff(plan, new, report, ov, _m)["unblocks"], ["P1-T03"])

    def test_a_clear_of_a_block_never_set_is_done(self):
        w = {"key": "k", "tracker_id": "T", "owned_hash": "a" * 64, "links": [], "not_ready": False}
        self.assertEqual(create_steps.blocked_record(w, "cleared", 2), w)
        wl = {"plan_version": 2, "writes": [{"no": 1, "kind": "clear_blocked", "key": "k"}]}
        self.assertEqual(create_steps.unfinished(wl, {"items": [w]}), [])
        self.assertEqual(len(create_steps.unfinished(wl, {"items": [dict(w, blocked_set=True)]})), 1)


class DraftLabelRemovalIsRecorded(unittest.TestCase):
    """m5: done checks the epic's draft label removal, and the record is never cleared."""

    def test_done_waits_for_the_record_and_it_is_append_only(self):
        pid = fresh("G1")[0]["id"]
        t = create_steps.ts("2026-11-15T10:00:00Z")
        wl = {"plan_version": 1, "writes": [{"no": 1, "kind": "remove_label", "on": "epic", "label": "gw-draft"}]}
        m1 = create_steps.make_manifest(None, [], pid, "r", 1, t, [])
        self.assertEqual(len(create_steps.unfinished(wl, m1)), 1)
        m2 = create_steps.make_manifest(m1, [], pid, "r", 2, t, [], draft_label_removed=True)
        self.assertEqual(create_steps.unfinished(wl, m2), [])
        m3 = create_steps.make_manifest(m2, [], pid, "r", 3, t, [])
        self.assertTrue(m3["draft_label_removed"])  # carried forward
        bad = dict(m3)
        bad.pop("draft_label_removed")
        self.assertTrue(create_steps.successor_problems(m2, bad))

    def test_a_first_create_records_it(self):
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()
        tr.epic_labels["VOL-1"] = {"gw-draft"}
        wl = render_proposal.write_list(plan, ov, PH)
        self.assertTrue(run_create(tr, plan, ov, PH, write_list=wl)["ok"])
        self.assertNotIn("gw-draft", tr.epic_labels["VOL-1"])
        self.assertEqual(create_steps.unfinished(wl, latest_manifest(tr, plan["id"])), [])


if __name__ == "__main__":
    unittest.main()
