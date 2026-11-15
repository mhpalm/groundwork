# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Eleventh review: a retire resume is rebuilt from the manifest before its status intent, a resume's
recheck warns where proposing again is impossible, a revise resume accepts its own landed relinks and
clears, a found-again item closed with Groundwork's label is Groundwork's close, and an item a person
reopened after Groundwork closed it is left open and named."""
import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
sys.path.insert(0, os.path.dirname(__file__))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import create_steps  # noqa: E402
import render_proposal  # noqa: E402
import retire  # noqa: E402
import revise_diff  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, retire_items, run_create, run_retire  # noqa: E402
from test_review8 import Base  # noqa: E402

PH = ["P0", "P1"]


def created():
    plan, ov, _e = fresh("G1")
    tr = FakeTracker()
    assert run_create(tr, plan, ov, PH)["ok"]
    return tr, plan, ov


def manifest_paths(tr, plan_id):
    d = tempfile.mkdtemp()
    paths = []
    for k, v in sorted(tr.store.items()):
        if k.startswith(f"{plan_id}-manifest-"):
            paths.append(os.path.join(d, k + ".json"))
            with open(paths[-1], "w") as f:
                json.dump(v, f)
    return paths


def key(plan, tid):
    return f"gw:{plan['id']}:{tid}"


def with_close(tr, plan, k, close):
    """Record a close on k in a new manifest, as an earlier revise would have."""
    m = latest_manifest(tr, plan["id"])
    items = [dict(i, close=close) if i["key"] == k else i for i in m["items"]]
    m2 = create_steps.make_manifest(m, items, plan["id"], "r", m["seq"] + 1, tr.tick(), [])
    tr.put(f"{plan['id']}-manifest-{m2['seq']}", m2)
    return m2


class RetireResumeRebuildsFromBeforeTheIntent(unittest.TestCase):
    """M1: a retire that recorded its own closes (and a missing item) still verifies on a resume."""

    def test_a_resume_after_the_closes_verifies(self):
        tr, plan, ov = created()
        reopened = key(plan, "P1-T05")
        with_close(tr, plan, reopened, {"reason": "not_planned", "state": "closed"})  # a person reopened it
        gone = key(plan, "P0-T01")
        del tr.items[next(i["tracker_id"] for i in tr.items.values() if i["key"] == gone)]
        items = retire_items(tr, plan, ov, "VOL-1")
        ctx = render_proposal.proposal_context(plan, "retire", "Retire.", items=items)
        m = latest_manifest(tr, plan["id"])
        rp = retire.plan_retire(items, {}, m)
        self.assertEqual((rp["missing"], rp["reopened"]), ([gone], [reopened]))
        wl = retire.write_list(plan, ov, rp)
        self.assertEqual(check_hashes.rebuilt_plan_level_problems(plan, ov, wl, ctx, m), [])
        self.assertEqual(run_retire(tr, plan, ov, rp, "a" * 64, crash_after="closes").get("crashed"), "closes")
        paths = manifest_paths(tr, plan["id"])
        latest = check_hashes.latest_manifest_of(paths, plan["id"])
        self.assertEqual(next(i for i in latest["items"] if i["key"] == gone)["close"]["state"], "missing")
        basis = check_hashes.retire_basis_of(paths, plan["id"])
        self.assertIsNone(basis.get("status_file"))
        self.assertEqual(basis["seq"], m["seq"])  # the last one before the intent, not the first
        self.assertEqual(check_hashes.rebuilt_plan_level_problems(plan, ov, wl, ctx, basis), [])
        # the latest manifest shows the retire's own closes as earlier ones: rebuilt from it, the set differs
        self.assertTrue(check_hashes.rebuilt_plan_level_problems(plan, ov, wl, ctx, latest))
        state = {"manifest": latest, "retire_basis": basis}
        self.assertIs(check_hashes.plan_level_basis(state, wl), basis)
        self.assertIs(check_hashes.plan_level_basis(state, dict(wl, kind="change_request")), latest)
        self.assertIs(check_hashes.plan_level_basis({"manifest": latest}, wl), latest)

    def test_a_key_recorded_missing_before_is_not_listed_again(self):
        tr, plan, ov = created()
        gone = key(plan, "P0-T01")
        del tr.items[next(i["tracker_id"] for i in tr.items.values() if i["key"] == gone)]
        m = with_close(tr, plan, gone, {"reason": "not_planned", "state": "missing"})
        rp = retire.plan_retire(retire_items(tr, plan, ov, "VOL-1"), {}, m)
        self.assertEqual(rp["missing"], [])
        self.assertNotIn(gone, [c["key"] for c in rp["closes"]])

    def test_the_cli_state_carries_the_basis(self):
        tr, plan, ov = created()

        class A:
            manifests, status, epic = manifest_paths(tr, plan["id"]), "-", "open"
        st = check_hashes.cli_plan_state(A, plan["id"], plan)
        self.assertEqual(st["retire_basis"], st["manifest"])


class RecheckOnAResumeWarns(unittest.TestCase):
    """M2: after the status intent, a new person child or a newly started item is a warning, not a stop."""

    def test_warnings_only_once_the_intent_is_recorded(self):
        tr, plan, ov = created()
        m = latest_manifest(tr, plan["id"])
        items = retire_items(tr, plan, ov, "VOL-1")
        wl = retire.write_list(plan, ov, retire.plan_retire(items, {}, m))
        seen = {i["key"]: i["status"] for i in items}
        intent = dict(m, status_file={"state": "intent", "n": 1, "hash": "a" * 64, "at": "t",
                                      "set_by": {"plan_version": plan["version"], "proposal_hash": "b" * 64}})
        child = items + [{"key": "PERSON-1", "status": "todo", "person_added": True, "unrecorded": False}]
        started = [dict(i, status="in_progress") if i is items[0] else i for i in items]
        for now in (child, started):
            with self.subTest(n=len(now)):
                self.assertTrue(retire.recheck(wl, now, seen, m))
                warn = []
                self.assertEqual(retire.recheck(wl, now, seen, intent, warn), [])
                self.assertEqual(len(warn), 1)


class OpenAgainAfterTheIntent(unittest.TestCase):
    """Twelfth review, M1: an item finished at the proposal that is open again after the status intent
    (reopened, or a missing item found again) is left open with a warning, and the resume finishes."""

    def test_a_reopened_finished_item_does_not_block_the_resume(self):
        tr, plan, ov = created()
        k = key(plan, "P0-T01")
        tid = next(i["tracker_id"] for i in tr.items.values() if i["key"] == k)
        tr.close(tid, "Done")
        items = retire_items(tr, plan, ov, "VOL-1")
        m = latest_manifest(tr, plan["id"])
        rp = retire.plan_retire(items, {}, m)
        wl = retire.write_list(plan, ov, rp)
        seen = {i["key"]: i["status"] for i in items}
        self.assertEqual(run_retire(tr, plan, ov, rp, "a" * 64, crash_after="intent").get("crashed"), "intent")
        tr.reopen(tid)
        now = retire_items(tr, plan, ov, "VOL-1")
        self.assertTrue(retire.recheck(wl, now, seen, m))  # before the intent: propose again
        warn = []
        self.assertEqual(retire.recheck(wl, now, seen, latest_manifest(tr, plan["id"]), warn), [])
        self.assertEqual(len(warn), 1)
        sf = latest_manifest(tr, plan["id"])["status_file"]
        r = run_retire(tr, plan, ov, rp, "a" * 64, resuming=(sf["set_by"]["plan_version"], sf["set_by"]["proposal_hash"]))
        self.assertTrue(r["ok"], r)
        self.assertEqual(tr.items[tid]["state"], "open")


class ReviseResumeAcceptsItsLandedWrites(Base):
    """M3: relinks and clears the approved set already recorded are accepted on resume; a clear of a block
    Groundwork never recorded as cleared by this version is not."""

    def landed(self, d):
        m2 = copy.deepcopy(self.m)
        pre = f"gw:{self.v3['id']}:"
        items = {i["key"]: i for i in m2["items"]}
        for r in d["relinks"]:
            it = items[pre + r["task"]]
            it["links"] = [x for x in it["links"] if not (x["type"] == "blocked_by" and x["to_key"][len(pre):] in r["removed"])]
            it["links"] += [{"type": "blocked_by", "to_key": pre + x} for x in r["added"]]
        for t in d["unblocks"]:
            items[pre + t].update(create_steps.blocked_record(items[pre + t], "cleared", self.v3["version"]))
        return m2

    def test_resume_verifies_and_a_stray_clear_is_refused(self):
        d = self.diff()
        offer = sorted({t["phase"] for t in self.v3["tasks"] if t["id"] in d["edits"]})
        wl = render_proposal.write_list(self.v3, self.ov, offer, d["close_items"], None, d["edits"], d["relinks"], d["unblocks"])
        m2 = self.landed(d)
        self.assertEqual(revise_diff.derived_writes(self.v3, m2), {"relinks": [], "unblocks": []})
        self.assertEqual(check_hashes.rebuilt_write_list_problems(self.v3, self.ov, wl, m2), [])
        # a clear_blocked for a task this version never cleared is an extra write, refused
        other = render_proposal.write_list(self.v3, self.ov, offer, d["close_items"], None, d["edits"], d["relinks"],
                                           d["unblocks"] + ["P1-T01"])
        self.assertTrue(check_hashes.rebuilt_write_list_problems(self.v3, self.ov, other, m2))
        # a relink this set's manifest does not show as landed is an extra write, refused
        pre = f"gw:{self.v3['id']}:"
        for kind, dep in (("unlink_dependency", "P0-T02"), ("link_dependency", "P0-T01")):
            more = copy.deepcopy(wl)
            more["writes"].append({"kind": kind, "key": pre + "P1-T01", "blocked_by": pre + dep, "scope": "plan"})
            with self.subTest(kind=kind):
                self.assertTrue(check_hashes.rebuilt_write_list_problems(self.v3, self.ov, more, m2))
        # a clear recorded by an older version does not cover this version's write list
        old = copy.deepcopy(m2)
        k = f"gw:{self.v3['id']}:P1-T03"
        next(i for i in old["items"] if i["key"] == k)["blocked_changes"][-1]["plan_version"] = self.v3["version"] - 1
        self.assertTrue(check_hashes.rebuilt_write_list_problems(self.v3, self.ov, wl, old))


class FoundAgainClosedByGroundwork(unittest.TestCase):
    """m1: a missing item found closed with Groundwork's label is Groundwork's close, recorded closed."""

    def test_it_is_recorded_closed_not_finished(self):
        fm = {"statuses": {"closed_not_done": ["Won't Do"]}}
        w = {"key": "K", "tracker_id": "1", "close": {"reason": "not_planned", "state": "missing"}}
        raw = {"key": "K", "state": "closed", "closed_as": ["Done"], "labels": ["gw-closed:not_planned"]}
        st = create_steps.read_status(raw, w, fm)
        self.assertEqual(st["status"], "closed_not_done")
        steps = create_steps.close_steps([{"key": "K", "reason": "not_planned"}], {"items": [w]}, [dict(st, tracker_id="1")])
        self.assertEqual(steps["steps"][-1]["records"], [{"key": "K", "close": {"reason": "not_planned", "state": "closed"}}])
        # open again with the label: still drift with a close pending, never Groundwork's close
        st2 = create_steps.read_status(dict(raw, state="open", closed_as=[]), w, fm)
        self.assertTrue(st2["close_pending"])


class ReopenedIsLeftOpen(unittest.TestCase):
    """m2: an item Groundwork closed that a person reopened is left open and named, never a close."""

    def test_reopened_in_the_plan_the_write_list_and_the_proposal(self):
        tr, plan, ov = created()
        k = key(plan, "P1-T02")
        m = with_close(tr, plan, k, {"reason": "not_planned", "state": "closed"})
        items = retire_items(tr, plan, ov, "VOL-1")  # the item is open on the tracker: a person reopened it
        rp = retire.plan_retire(items, {}, m)
        self.assertEqual(rp["reopened"], [k])
        self.assertNotIn(k, [c["key"] for c in rp["closes"]])
        wl = retire.write_list(plan, ov, rp)
        self.assertEqual(wl["reopened"], [k])
        self.assertEqual(retire.recheck(wl, items, {i["key"]: i["status"] for i in items}, m), [])
        ctx = render_proposal.proposal_context(plan, "retire", "Retire.", items=items)
        text = render_proposal.plan_level_proposal(plan, ov, wl, ctx)
        text = text if isinstance(text, str) else json.dumps(text)
        self.assertIn("reopened after Groundwork closed them", text)
        self.assertIn(k, text)
        self.assertEqual(check_hashes.rebuilt_plan_level_problems(plan, ov, wl, ctx, m), [])


if __name__ == "__main__":
    unittest.main()
