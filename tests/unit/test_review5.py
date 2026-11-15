# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Fifth review: re-pointed links, voided sets, relies_on with closes, the close CLI, derived manifests,
the lock re-check, the completion check, required assessments, and guards no test covered."""
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
import revise_diff  # noqa: E402
from check_hashes import owned_hash  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, run_close, run_create  # noqa: E402


def tracker_report(tr, plan, ov):
    fm = ov["skills"]["tracker"]["field_map"]
    m = latest_manifest(tr, plan["id"])
    w = {i["key"]: i for i in m["items"]}
    return [{"key": i["key"], "tracker_id": i["tracker_id"], "owned_hash": owned_hash(tr.normalize(i)),
             "updated_at": tr.updated_at(i["tracker_id"]),
             "status": create_steps.read_status(tr.raw(i["tracker_id"]), w.get(i["key"]), fm)["status"]}
            for i in tr.items.values()], m


def repoint_revision(plan):
    """Drop P1-T02 and re-point P1-T03 at P1-T01."""
    new = copy.deepcopy(plan)
    new["version"] += 1
    new["tasks"] = [t for t in new["tasks"] if t["id"] != "P1-T02"]
    ph = next(p for p in new["phases"] if p["id"] == "P1")
    ph["task_ids"] = [x for x in ph["task_ids"] if x != "P1-T02"]
    next(t for t in new["tasks"] if t["id"] == "P1-T03")["depends_on"][0]["task"] = "P1-T01"
    return new


class RepointedLinks(unittest.TestCase):
    """Finding 1: a revise removes the tracker link of a dependency it re-points."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")
        self.tr = FakeTracker()
        self.assertTrue(run_create(self.tr, self.plan, self.ov, ["P0", "P1"])["ok"])
        self.new = repoint_revision(self.plan)
        report, self.m = tracker_report(self.tr, self.plan, self.ov)
        self.d = revise_diff.diff(self.plan, self.new, report, self.ov, self.m)

    def links_of(self, tid):
        by = {i["key"]: i for i in self.tr.items.values()}
        name = {v["tracker_id"]: k.split(":")[-1] for k, v in by.items()}
        return sorted(name[x] for x in by[f"gw:{self.plan['id']}:{tid}"]["links"])

    def test_the_diff_lists_the_relink_and_the_write_list_unlinks(self):
        self.assertTrue(self.d["ok"], self.d["refused"])
        self.assertEqual(self.d["relinks"], [{"task": "P1-T03", "added": ["P1-T01"], "removed": ["P1-T02"]}])
        wl = render_proposal.write_list(self.new, self.ov, ["P1"], self.d["close_items"], None, self.d["edits"],
                                        self.d["relinks"], self.d["unblocks"])
        un = [w for w in wl["writes"] if w["kind"] == "unlink_dependency"]
        self.assertEqual([(w["key"].split(":")[-1], w["blocked_by"].split(":")[-1], w["scope"]) for w in un],
                         [("P1-T03", "P1-T02", "plan")])
        self.assertIn("no longer waits on", render_proposal.proposal(self.new, self.ov, ["P1"], wl))
        import check_hashes
        self.assertEqual(check_hashes.rebuilt_write_list_problems(self.new, self.ov, wl), [])
        bad = copy.deepcopy(wl)
        next(w for w in bad["writes"] if w["kind"] == "unlink_dependency")["blocked_by"] = f"gw:{self.plan['id']}:P1-T01"
        self.assertTrue(check_hashes.rebuilt_write_list_problems(self.new, self.ov, bad))

    def test_apply_leaves_no_link_to_the_dropped_task(self):
        wl = render_proposal.write_list(self.new, self.ov, ["P1"], self.d["close_items"], None, self.d["edits"],
                                        self.d["relinks"], self.d["unblocks"])
        ups = {w["key"]: w["owned_hash"] for w in wl["writes"] if w["kind"] == "update_item"}
        for attempt in range(2):  # the second run changes nothing
            pf = run_create(self.tr, self.new, self.ov, ["P1"], run=f"run-{2 + attempt}", updates=ups, write_list=wl)
            self.assertTrue(pf["ok"], pf)
            self.assertEqual(self.links_of("P1-T03"), ["P1-T01"])

    def test_a_relink_that_does_not_match_the_plan_is_refused(self):
        with self.assertRaises(ValueError):
            render_proposal.write_list(self.new, self.ov, ["P1"], None, None, None,
                                       [{"task": "P1-T03", "added": [], "removed": ["P1-T01"]}])


class ReliesOnWithCloses(unittest.TestCase):
    """Finding 3: the first preflight of a revise that closes a task passes its own relies_on."""

    def test_a_revise_with_a_close_passes_relies_on_and_still_catches_a_move(self):
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()
        self.assertTrue(run_create(tr, plan, ov, ["P0", "P1"])["ok"])
        new = repoint_revision(plan)
        report, m = tracker_report(tr, plan, ov)
        d = revise_diff.diff(plan, new, report, ov, m)
        self.assertIn(f"gw:{plan['id']}:P1-T02", [r["key"] for r in d["relies_on"]])
        wl = render_proposal.write_list(new, ov, ["P1"], d["close_items"], None, d["edits"], d["relinks"], d["unblocks"])
        ups = {w["key"]: w["owned_hash"] for w in wl["writes"] if w["kind"] == "update_item"}
        moved = copy.deepcopy(tr)
        next(i for i in moved.items.values() if i["key"].endswith(":P1-T02"))["category"] = "in_progress"
        pf = run_create(moved, new, ov, ["P1"], run="run-2", updates=ups, relies_on=d["relies_on"], write_list=wl)
        self.assertFalse(pf["ok"])
        self.assertIn("diff again", pf["stops"][0]["why"])
        pf = run_create(tr, new, ov, ["P1"], run="run-2", updates=ups, relies_on=d["relies_on"], write_list=wl)
        self.assertTrue(pf["ok"], pf)
        self.assertTrue(run_close(tr, new, ov, d["close_items"])["ok"])


class CompletionCheck(unittest.TestCase):
    """Finding 7: before the lock release, every approved write must show as done."""

    def test_create_then_revise_with_closes_relinks_and_a_decision(self):
        import change_request as cr
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()
        wl0 = render_proposal.write_list(plan, ov, ["P0", "P1"])
        self.assertTrue(run_create(tr, plan, ov, ["P0", "P1"], write_list=wl0)["ok"])
        self.assertEqual(create_steps.unfinished(wl0, latest_manifest(tr, plan["id"])), [])
        new = repoint_revision(plan)
        report, m = tracker_report(tr, plan, ov)
        d = revise_diff.diff(plan, new, report, ov, m)
        log, _ = cr.allocate(cr.empty_log(plan["id"]), "Drop the second export step", "runner", "business_user", 1, m["seq"])
        entry = cr.to_bind(log, "CR-1", "added", "Simpler")
        wl = render_proposal.write_list(new, ov, ["P1"], d["close_items"], entry, d["edits"], d["relinks"], d["unblocks"])
        self.assertEqual(wl["writes"][1]["kind"], "cr_log_put")  # the decision is written first
        ups = {w["key"]: w["owned_hash"] for w in wl["writes"] if w["kind"] == "update_item"}
        self.assertTrue(run_create(tr, new, ov, ["P1"], run="run-2", updates=ups, write_list=wl)["ok"])
        left = {x["kind"] for x in create_steps.unfinished(wl, latest_manifest(tr, plan["id"]), log)}
        self.assertEqual(left, {"close_item", "cr_log_put"})  # the closes and the decision are still to do
        self.assertTrue(run_close(tr, new, ov, d["close_items"])["ok"])
        log2, _ = cr.decide_bound(log, wl, "d" * 64)
        self.assertEqual(create_steps.unfinished(wl, latest_manifest(tr, plan["id"]), log2), [])
        self.assertTrue(create_steps.unfinished(wl, latest_manifest(tr, plan["id"])))  # no log given

    def test_a_skipped_update_or_block_is_listed(self):
        wl = {"plan_version": 2, "writes": [{"no": 1, "kind": "update_item", "key": "k", "owned_hash": "b" * 64},
                                            {"no": 2, "kind": "set_blocked", "key": "k"},
                                            {"no": 3, "kind": "unlink_dependency", "key": "k", "blocked_by": "j"}]}
        m = {"items": [{"key": "k", "tracker_id": "T", "owned_hash": "a" * 64, "not_ready": False,
                        "links": [{"type": "blocked_by", "to_key": "j"}]}]}
        self.assertEqual([x["no"] for x in create_steps.unfinished(wl, m)], [1, 2, 3])


class LockRecheck(unittest.TestCase):
    """Finding 6: after each renew the run reads the lock again and stops unless it still holds it."""

    def test_a_run_that_stalled_past_expiry_stops_at_its_next_checkpoint(self):
        import datetime as dt
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()

        def stall(t):
            t.clock += dt.timedelta(minutes=31)
            t.comment("acct-other", create_steps.lock_line("claim", "run-b", "acct-other", t.clock))
            t.tick()

        pf = run_create(tr, plan, ov, ["P0", "P1"], on_checkpoint=stall)
        self.assertFalse(pf["ok"])
        self.assertEqual(pf["lock_lost"]["decision"], "lost")
        self.assertEqual(create_steps.lock_decision(tr.comments, "run-b", "acct-other", tr.clock)["decision"], "held")
        written = len(tr.items)
        self.assertLessEqual(written, create_steps.BATCH)  # nothing after the checkpoint

    def test_a_run_that_keeps_its_lock_is_unaffected(self):
        plan, ov, _e = fresh("G1")
        self.assertTrue(run_create(FakeTracker(), plan, ov, ["P0", "P1"])["ok"])


class RetireVoidsFromItsFirstWrite(unittest.TestCase):
    """Finding 2: once a retire starts, the pending sets it voids can't be created, even after a crash mid-close."""

    def test_a_crash_during_the_closes_blocks_every_other_create(self):
        from test_retire import PH_HASH, approve, created, gate
        from fake_tracker import run_retire
        tr, plan, ov = created()
        rp = approve(tr, plan, ov)
        tr.fail_at = tr.writes + 4  # inside the close procedure
        try:
            run_retire(tr, plan, ov, rp, PH_HASH)
        except Exception:
            pass
        tr.fail_at = None
        self.assertIsNotNone(latest_manifest(tr, plan["id"]).get("status_file"))
        for op in ("create", "release", "revise", "freeze"):
            self.assertFalse(gate(tr, plan, op)["ok"], op)
        self.assertTrue(gate(tr, plan, "resume", (plan["version"], PH_HASH))["ok"])


class RecordGuards(unittest.TestCase):
    """Finding 9: guards no test covered."""

    def setUp(self):
        from test_approval_sets import base, phase_case
        self.plan, self.ov, self.anchor, self.rev = base()
        self.wl, self.prop = phase_case(self.plan, self.ov)

    def verify(self, recs, anchor=None, view=None, plan=None, prop=None):
        import check_hashes
        from test_approval_sets import NOW
        return check_hashes.verify_approvals(plan or self.plan, self.ov, anchor or self.anchor, recs, prop or self.prop,
                                             self.wl, self.rev, ["P1"], NOW, False, None, None, None, view)

    def test_an_edited_comment_in_this_set_is_refused(self):
        from test_approval_sets import comment, record
        rec = record(self.plan, self.prop, self.wl, self.rev, ["P1"])
        ok, probs, _ = self.verify([comment(rec, updated="2026-11-15T11:00:00Z")])
        self.assertFalse(ok)
        self.assertTrue(any("edited after it was posted" in p for p in probs), probs)

    def test_an_overlay_that_is_not_the_anchored_one_is_refused(self):
        from test_approval_sets import comment, record
        recs = [comment(record(self.plan, self.prop, self.wl, self.rev, ["P1"]))]
        for k, v in (("hash", "e" * 64), ("version", 99), ("overlay_id", "other")):
            with self.subTest(field=k):
                ok, probs, _ = self.verify(recs, dict(self.anchor, **{k: v}))
                self.assertFalse(ok)
                self.assertTrue(any("CR-12" in p for p in probs), probs)

    def test_a_review_copied_onto_a_newer_plan_is_refused(self):
        import check_hashes
        from gw_hash import view_bundle, view_hash
        from test_approval_sets import comment, phase_case, record
        view = {"evidence": [], "rules": []}
        good = dict(self.rev, view_hash=view_hash(view_bundle(self.plan, [], check_hashes.CHECKLIST_VERSION, [])))
        newer = copy.deepcopy(self.plan)
        newer["version"] += 1
        newer["tasks"][0]["title"] += " (changed)"
        newer["review"]["reviewer"] = good  # the old review, copied: review sits outside plan_hash
        self.rev = good
        self.wl, prop = phase_case(newer, self.ov)
        recs = [comment(record(newer, prop, self.wl, good, ["P1"]))]
        ok, probs, _ = self.verify(recs, view=view, plan=newer, prop=prop)
        self.assertFalse(ok)
        self.assertTrue(any("reviewer view" in p for p in probs), probs)

    def test_the_plan_level_proposal_shows_the_restatement(self):
        import change_request as cr
        log, _ = cr.allocate(cr.empty_log(self.plan["id"]), "Also send a reminder email", "runner", "business_user", 1, 2)
        wl = render_proposal.plan_write_list(self.plan, self.ov, "decline", cr.to_bind(log, "CR-1", "declined", "No"))
        ctx = render_proposal.proposal_context(self.plan, "decline", "Decline CR-1.")
        md = render_proposal.plan_level_proposal(self.plan, self.ov, wl, ctx)
        self.assertIn("The request, as the runner confirmed it: Also send a reminder email", md.split("## Write list")[0])


class LogChainGuards(unittest.TestCase):
    def setUp(self):
        import change_request as cr
        self.cr = cr
        self.plan, self.ov, _e = fresh("G1")
        self.l1, _ = cr.allocate(cr.empty_log(self.plan["id"]), "Export the list", "runner", "business_user", 1, 2)
        self.l2, _ = cr.allocate(self.l1, "Add a report", "runner", "business_user", 1, 2)

    def test_two_files_with_one_number_stop(self):
        fork, _ = self.cr.allocate(self.l1, "Something else", "runner", "business_user", 1, 2)
        _l, probs = self.cr.verify_log_chain([self.l1, self.l2, fork], self.plan["id"])
        self.assertTrue(any("two files with one number" in p for p in probs), probs)

    def test_a_later_file_rewriting_a_pending_request_stops(self):
        bad = copy.deepcopy(self.l2)
        bad["entries"][0]["restatement"] = "Export everything"
        bad.pop("hash")
        bad["hash"] = self.cr.item_hash(bad)
        _l, probs = self.cr.verify_log_chain([self.l1, bad], self.plan["id"])
        self.assertTrue(any("changes the request CR-1 itself" in p for p in probs), probs)


class MoreGuards(unittest.TestCase):
    """Mutation survivors of the fifth-review fixes."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")

    def test_a_removed_wait_clears_the_blocked_state_end_to_end(self):
        tr = FakeTracker()
        self.assertTrue(run_create(tr, self.plan, self.ov, ["P0", "P1"])["ok"])
        t = next(i for i in tr.items.values() if i["key"].endswith(":P1-T03"))
        self.assertTrue(t["blocked"])
        new = copy.deepcopy(self.plan)
        new["version"] += 1
        next(x for x in new["tasks"] if x["id"] == "P1-T03")["waits_on"] = []
        report, m = tracker_report(tr, self.plan, self.ov)
        d = revise_diff.diff(self.plan, new, report, self.ov, m)
        self.assertEqual(d["unblocks"], ["P1-T03"])
        with self.assertRaises(ValueError):  # a task that still waits keeps its block
            render_proposal.write_list(new, self.ov, ["P1"], None, None, d["edits"], None, ["P1-T02"])
        wl = render_proposal.write_list(new, self.ov, ["P1"], None, None, d["edits"], d["relinks"], d["unblocks"])
        ups = {w["key"]: w["owned_hash"] for w in wl["writes"] if w["kind"] == "update_item"}
        self.assertTrue(run_create(tr, new, self.ov, ["P1"], run="run-2", updates=ups, write_list=wl)["ok"])
        self.assertFalse(t["blocked"])

    def test_the_close_procedure_never_closes_as_completed(self):
        m = {"items": [{"key": "k", "tracker_id": "T1", "owned_hash": "a" * 64, "links": [], "not_ready": False}]}
        out = create_steps.close_steps([{"key": "k", "reason": "completed"}], m, [{"key": "k", "tracker_id": "T1", "status": "todo"}])
        self.assertFalse(out["ok"])

    def test_the_latest_manifest_is_derived_and_a_bad_chain_raises(self):
        import check_hashes
        d = tempfile.mkdtemp()
        pid = self.plan["id"]
        m1 = create_steps.make_manifest(None, [], pid, "r", 1, create_steps.ts("2026-11-15T10:00:00Z"), [])
        m2 = create_steps.make_manifest(m1, [], pid, "r", 2, create_steps.ts("2026-11-15T10:01:00Z"), [])
        m3 = create_steps.make_manifest(m2, [], pid, "r", 3, create_steps.ts("2026-11-15T10:02:00Z"), [])
        paths = []
        for m in (m1, m2, m3):
            paths.append(os.path.join(d, f"m{m['seq']}.json"))
            json.dump(m, open(paths[-1], "w"))
        self.assertEqual(check_hashes.latest_manifest_of(paths, pid)["seq"], 3)
        self.assertIsNone(check_hashes.latest_manifest_of([], pid))
        for name, ps in (("seq 2 missing", [paths[0], paths[2]]), ("no seq 1", paths[1:])):
            with self.subTest(name), self.assertRaises(ValueError):
                check_hashes.latest_manifest_of(ps, pid)
        bad = dict(m3, run_id="edited")
        json.dump(bad, open(paths[2], "w"))
        with self.assertRaises(ValueError):
            check_hashes.latest_manifest_of(paths, pid)
        with self.assertRaises(ValueError):
            check_hashes.latest_manifest_of(None, pid)

    def test_done_lists_a_missing_create_and_a_decision_by_another_set(self):
        wl = {"plan_version": 2, "writes": [{"no": 1, "kind": "create_item", "key": "k"},
                                            {"no": 2, "kind": "cr_log_put", "entry": {"id": "CR-1", "outcome": "added"}}]}
        log = {"entries": [{"id": "CR-1", "outcome": "declined", "decided_by": {"plan_version": 2}}]}
        self.assertEqual([x["no"] for x in create_steps.unfinished(wl, {"items": []}, log)], [1, 2])
        log = {"entries": [{"id": "CR-1", "outcome": "added", "decided_by": {"plan_version": 1}}]}
        self.assertEqual([x["no"] for x in create_steps.unfinished(wl, {"items": []}, log)], [1, 2])

    def test_a_set_deciding_a_request_needs_its_assessment(self):
        import check_hashes
        from test_approval_sets import NOW, base, comment, dassess, decline_case, drev, dstored, record
        plan, ov, anchor, _r = base()
        wl, _c, prop = decline_case(plan, ov)
        rev = drev(plan, wl)
        recs = [comment(record(plan, prop, wl, rev, [], kind="decline", scope="plan_level", rid="A-2"))]
        stored = dstored(plan, wl)
        self.assertTrue(check_hashes.verify_plan_level(plan, ov, anchor, recs, prop, wl, rev, NOW, False, None, None,
                                                       None, stored)[0])
        for a in (None, dict(dassess(plan, wl), cr="CR-7")):
            with self.subTest(assessment=a and a["cr"]):
                ok, probs, _ = check_hashes.verify_plan_level(plan, ov, anchor, recs, prop, wl, rev, NOW, False, None,
                                                              None, None, dict(stored, assessment=a))
                self.assertFalse(ok)
                self.assertTrue(any("stored assessment" in p for p in probs), probs)


if __name__ == "__main__":
    unittest.main()
