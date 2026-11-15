# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Ninth review: a deleted task dropped from the plan of record, a landed update on finished work,
an item recorded missing that is found again, and the smaller guards."""
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
import create_steps  # noqa: E402
import render_proposal  # noqa: E402
import retire  # noqa: E402
import revise_diff  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, planned_items, retire_items, run_close, run_create  # noqa: E402
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


def key(plan, tid):
    return f"gw:{plan['id']}:{tid}"


def tid_of(tr, k):
    return next(i["tracker_id"] for i in tr.items.values() if i["key"] == k)


class DeletedTaskDroppedFromThePlanOfRecord(unittest.TestCase):
    """M1: a written task a person deleted can be dropped by the very next revise."""

    def test_the_drop_is_a_missing_close(self):
        tr, plan, ov = created()
        k = key(plan, "P1-T02")
        del tr.items[tid_of(tr, k)]
        v2 = repoint_revision(plan)  # drops P1-T02 from the plan of record
        rep, m = tracker_report(tr, plan, ov)
        d = revise_diff.diff(plan, v2, rep, ov, m)
        self.assertTrue(d["ok"], d["refused"])
        self.assertEqual(d["missing"], [k])
        self.assertEqual([c["key"] for c in d["close_items"]], [k])
        self.assertTrue(run_close(tr, v2, ov, d["close_items"])["ok"])
        w = next(i for i in latest_manifest(tr, plan["id"])["items"] if i["key"] == k)
        self.assertEqual(w["close"]["state"], "missing")


class LandedUpdateOnFinishedWork(unittest.TestCase):
    """M2: an approved update that landed before a crash is recorded even if the task is finished since."""

    def test_resume_records_it_and_done_passes(self):
        tr, plan, ov = created()
        new = bump(plan)
        t = next(x for x in new["tasks"] if x["id"] == "P1-T02")
        t["title"] += " (with an empty-file check)"
        m = {i["key"]: i["owned_hash"] for i in latest_manifest(tr, new["id"])["items"]}
        ups = {p["key"]: p["owned_hash"] for p in planned_items(new, ov, PH) if p["key"] in m and m[p["key"]] != p["owned_hash"]}
        self.assertEqual(run_create(tr, new, ov, PH, run="run-2", updates=ups, crash_after_update=True).get("crashed"), "update")
        tr.close(tid_of(tr, t["key"]), "Done")
        r = run_create(tr, new, ov, PH, run="run-2", updates=ups)
        self.assertTrue(r["ok"], r.get("stops"))
        w = next(i for i in latest_manifest(tr, new["id"])["items"] if i["key"] == t["key"])
        self.assertEqual(w["owned_hash"], ups[t["key"]])

    def test_an_unapproved_text_on_finished_work_still_stops(self):
        tr, plan, ov = created()
        k = key(plan, "P1-T02")
        p = next(x for x in planned_items(plan, ov, PH) if x["key"] == k)
        w = next(i for i in latest_manifest(tr, plan["id"])["items"] if i["key"] == k)
        f = {"key": k, "tracker_id": w["tracker_id"], "owned_hash": p["owned_hash"], "status": "done", "points": 1}
        old = dict(w, owned_hash="b" * 64)
        out = create_steps.preflight([p], [f], {"items": [old]}, ["P1"], {})
        self.assertFalse(out["ok"])


    def test_a_tracker_text_no_update_approves_stops(self):
        tr, plan, ov = created()
        k = key(plan, "P1-T02")
        p = next(x for x in planned_items(plan, ov, PH) if x["key"] == k)
        w = next(i for i in latest_manifest(tr, plan["id"])["items"] if i["key"] == k)
        f = {"key": k, "tracker_id": w["tracker_id"], "owned_hash": p["owned_hash"], "status": "todo", "points": 1}
        old = dict(w, owned_hash="b" * 64)
        p = dict(p, depends_on=[])
        self.assertFalse(create_steps.preflight([p], [f], {"items": [old]}, ["P1"], {})["ok"])
        self.assertTrue(create_steps.preflight([p], [f], {"items": [old]}, ["P1"], {k: p["owned_hash"]})["ok"])


class FoundAgainAfterMissing(unittest.TestCase):
    """M3: a wrong missing record is noticed and the item is closed after all."""

    def setUp(self):
        self.tr, self.plan, self.ov = created()
        self.k = key(self.plan, "P1-T02")
        m = latest_manifest(self.tr, self.plan["id"])
        found = [{"key": i["key"], "tracker_id": i["tracker_id"], "status": "todo"} for i in m["items"] if i["key"] != self.k]
        steps = create_steps.close_steps([{"key": self.k, "reason": "not_planned"}], m, found, [self.k])
        rec = steps["steps"][-1]["records"][0]["close"]
        self.assertEqual(rec["state"], "missing")
        items = copy.deepcopy(m["items"])
        next(i for i in items if i["key"] == self.k)["close"] = rec
        self.m2 = create_steps.make_manifest(m, items, self.plan["id"], "r", m["seq"] + 1, self.tr.tick(), [])
        self.tr.put(f"{self.plan['id']}-manifest-{self.m2['seq']}", self.m2)

    def test_it_reads_as_drift_and_the_close_procedure_closes_it(self):
        fm = self.ov["skills"]["tracker"]["field_map"]
        w = next(i for i in self.m2["items"] if i["key"] == self.k)
        st = create_steps.read_status(self.tr.raw(w["tracker_id"]), w, fm)
        self.assertTrue(st["drift"] and st["close_pending"])
        r = run_close(self.tr, self.plan, self.ov, [{"key": self.k, "reason": "not_planned"}])
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.tr.items[w["tracker_id"]]["state"], "closed")
        w2 = next(i for i in latest_manifest(self.tr, self.plan["id"])["items"] if i["key"] == self.k)
        self.assertEqual(w2["close"]["state"], "closed")

    def test_a_revise_closes_it_and_a_retire_closes_it(self):
        v2 = repoint_revision(self.plan)
        rep, m = tracker_report(self.tr, self.plan, self.ov)
        d = revise_diff.diff(v2, bump(v2), rep, self.ov, m)
        self.assertIn(self.k, [c["key"] for c in d["close_items"]])
        rp = retire.plan_retire(retire_items(self.tr, v2, self.ov, "VOL-1"), {}, m)
        self.assertIn(self.k, [c["key"] for c in rp["closes"]])

    def test_a_person_s_close_of_a_found_item_reads_by_the_tracker(self):
        fm = self.ov["skills"]["tracker"]["field_map"]
        w = next(i for i in self.m2["items"] if i["key"] == self.k)
        raw = dict(self.tr.raw(w["tracker_id"]), state="closed", closed_as=["Done"], labels=["gw-closed:not_planned"])
        self.assertEqual(create_steps.read_status(raw, w, fm)["status"], "done")

    def test_missing_moves_only_forward_with_the_same_reason(self):
        mk = lambda c: create_steps.make_manifest(self.m2, [dict(i, close=c) if i["key"] == self.k else i
                                                             for i in self.m2["items"]],
                                                  self.plan["id"], "r", self.m2["seq"] + 1, self.tr.tick(), [])
        self.assertEqual(next(i for i in mk({"reason": "not_planned", "state": "intent"})["items"]
                              if i["key"] == self.k)["close"]["state"], "intent")  # tenth review, m1
        for bad in ({"reason": "duplicate", "state": "intent"}, {"reason": "duplicate", "state": "closed"}, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mk(bad)

    def test_a_found_again_close_writes_its_intent_first(self):
        found = [{"key": self.k, "tracker_id": "x", "status": "todo", "close_pending": True}]
        out = create_steps.close_steps([{"key": self.k, "reason": "not_planned"}], self.m2, found)
        self.assertEqual(out["steps"][0], {"step": "manifest_intent", "items": [{"key": self.k, "reason": "not_planned"}]})


class SmallerGuards(unittest.TestCase):
    def test_retire_keeps_a_recorded_close_reason(self):
        tr, plan, ov = created()
        k = key(plan, "P1-T02")
        m = latest_manifest(tr, plan["id"])
        items = [dict(i, close={"reason": "superseded", "state": "intent"}) if i["key"] == k else i for i in m["items"]]
        m2 = create_steps.make_manifest(m, items, plan["id"], "r", m["seq"] + 1, tr.tick(), [])
        rp = retire.plan_retire(retire_items(tr, plan, ov, "VOL-1"), {}, m2)
        self.assertIn({"key": k, "reason": "superseded"}, rp["closes"])  # tenth review, M1

    def test_a_missing_close_keeps_the_approved_reason(self):
        tr, plan, ov = created()
        k = key(plan, "P1-T02")
        m = latest_manifest(tr, plan["id"])
        items = copy.deepcopy(m["items"])
        next(i for i in items if i["key"] == k)["close"] = {"reason": "superseded", "state": "intent"}
        m2 = create_steps.make_manifest(m, items, plan["id"], "r", m["seq"] + 1, tr.tick(), [])
        out = create_steps.close_steps([{"key": k, "reason": "duplicate"}], m2, [], [k])
        self.assertFalse(out["ok"])

    def test_the_retire_proposal_names_missing_items(self):
        tr, plan, ov = created()
        k = key(plan, "P1-T02")
        del tr.items[tid_of(tr, k)]
        rp = retire.plan_retire(retire_items(tr, plan, ov, "VOL-1"), {}, latest_manifest(tr, plan["id"]))
        wl = retire.write_list(plan, ov, rp)
        self.assertEqual(wl["missing"], [k])
        ctx = render_proposal.proposal_context(plan, "retire", "Retire.", items=rp["seen"])
        text = "\n".join(render_proposal.plan_level_proposal(plan, ov, wl, ctx).splitlines()) \
            if isinstance(render_proposal.plan_level_proposal(plan, ov, wl, ctx), str) else ""
        self.assertIn("no longer on the tracker", text)
        self.assertIn(k, text)

    def test_preflight_and_close_refuse_an_empty_manifest_set_on_a_written_plan(self):
        tr, plan, ov = created()
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)
        wl = render_proposal.write_list(bump(plan), ov, ["P1"])
        wl["writes"] = [w for w in wl["writes"] if w["kind"] != "remove_label"]
        json.dump(wl, open(P("wl.json"), "w"))
        json.dump([], open(P("a.json"), "w"))
        ovp = os.path.join(os.path.dirname(__file__), "..", "golden", "G1", "overlay", "overlay.yaml")
        for argv in (["preflight", P("a.json"), P("a.json"), "--phases", "P1", "--write-list", P("wl.json")],
                     ["close", P("wl.json"), P("a.json"), "--overlay", ovp]):
            with self.subTest(argv[0]), redirect_stdout(io.StringIO()) as buf:
                self.assertEqual(create_steps.main(argv + ["--plan-id", plan["id"], "--manifests"]), 1)
            self.assertIn("already written", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
