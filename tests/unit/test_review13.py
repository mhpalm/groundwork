# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Thirteenth review: once a retire's status intent is recorded, nothing a person does on the tracker or in
the approval comments, and no overlay update, can leave the resume with no legal way forward."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
sys.path.insert(0, os.path.dirname(__file__))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import render_proposal  # noqa: E402
import retire  # noqa: E402
from gw_canon import sha256_hex  # noqa: E402
from gw_hash import plan_level_bundle, view_hash  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, planned_items, retire_items, run_create, run_retire  # noqa: E402
from test_approval_sets import NOW, base, comment, record  # noqa: E402


def own(tr, plan):
    sf = latest_manifest(tr, plan["id"])["status_file"]
    return sf["set_by"]["plan_version"], sf["set_by"]["proposal_hash"]


class UnrecordedItemAfterTheIntent(unittest.TestCase):
    """M1: a plan-owned item no manifest records, seen only after the intent, is left open with a warning."""

    def test_the_resume_finishes(self):
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()
        assert run_create(tr, plan, ov, ["P0"])["ok"]
        p = next(x for x in planned_items(plan, ov, ["P1"]) if x["phase"] == "P1")
        tid = tr.create_item(p["key"], p["task"]["title"], p["body"], p["task"]["role_key"], p["task"]["phase"])
        stash = tr.items.pop(tid)  # moved out of the project before the proposal
        tr.tick(60 * 31)
        items = retire_items(tr, plan, ov, "VOL-1")
        m = latest_manifest(tr, plan["id"])
        rp = retire.plan_retire(items, {}, m)
        self.assertTrue(rp["ok"], rp)
        wl = retire.write_list(plan, ov, rp)
        seen = {i["key"]: i["status"] for i in items}
        self.assertEqual(run_retire(tr, plan, ov, rp, "a" * 64, crash_after="intent").get("crashed"), "intent")
        tr.items[tid] = stash  # moved back
        now = retire_items(tr, plan, ov, "VOL-1")
        self.assertTrue(retire.recheck(wl, now, seen, m))  # before the intent it stops
        warn = []
        self.assertEqual(retire.recheck(wl, now, seen, latest_manifest(tr, plan["id"]), warn), [])
        self.assertTrue(any("never recorded" in w for w in warn), warn)
        self.assertTrue(run_retire(tr, plan, ov, rp, "a" * 64, resuming=own(tr, plan))["ok"])


class ReopenedAfterThisRetireClosedIt(unittest.TestCase):
    """m1: an item this retire closed that a person reopens and starts is reported as left open, not closed."""

    def test_the_warning_tells_the_truth(self):
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()
        assert run_create(tr, plan, ov, ["P0", "P1"])["ok"]
        items = retire_items(tr, plan, ov, "VOL-1")
        rp = retire.plan_retire(items, {}, latest_manifest(tr, plan["id"]))
        wl = retire.write_list(plan, ov, rp)
        seen = {i["key"]: i["status"] for i in items}
        self.assertEqual(run_retire(tr, plan, ov, rp, "a" * 64, crash_after="closes").get("crashed"), "closes")
        k = rp["closes"][0]["key"]
        tid = next(i["tracker_id"] for i in tr.items.values() if i["key"] == k)
        tr.reopen(tid)
        now = [dict(i, status="in_progress") if i["key"] == k else i for i in retire_items(tr, plan, ov, "VOL-1")]
        warn = []
        self.assertEqual(retire.recheck(wl, now, seen, latest_manifest(tr, plan["id"]), warn), [])
        self.assertEqual(warn, [f"{k} was reopened after this retire closed it; it is left open"])


class ResumeApprovals(unittest.TestCase):
    """M2 and M3: on the retire's own resume, a bad record in the set is not counted and doesn't stop it, and
    the overlay the plan binds is accepted after an admin publishes a new one; quorum still holds."""

    def setUp(self):
        self.plan, self.ov, self.anchor, _r = base()
        plan, ov = self.plan, self.ov
        plan["overlay"]["hash"] = ov["hash"]  # the plan was drafted with the loaded overlay
        self.tr = FakeTracker()
        assert run_create(self.tr, plan, ov, ["P0", "P1"])["ok"]
        items = retire_items(self.tr, plan, ov, "VOL-1")
        self.m = latest_manifest(self.tr, plan["id"])
        self.rp = retire.plan_retire(items, {}, self.m)
        self.wl = retire.write_list(plan, ov, self.rp)
        ctx = render_proposal.proposal_context(plan, "retire", "Retire.", items=items)
        self.prop = render_proposal.plan_level_proposal(plan, ov, self.wl, ctx, None)
        self.rev = {"view_hash": view_hash(plan_level_bundle(plan, self.wl, ctx, check_hashes.CHECKLIST_VERSION, [], None)),
                    "findings": []}
        self.stored = {"context": ctx, "assessment": None, "rules": []}
        self.good = comment(record(plan, self.prop, self.wl, self.rev, [], kind="retire", scope="plan_level"))

    def v(self, recs, ov=None, anchor=None):
        state = {"manifest": latest_manifest(self.tr, self.plan["id"]), "retire_basis": self.m, "status": None, "epic": "open"}
        return check_hashes.verify_plan_level(self.plan, ov or self.ov, anchor or self.anchor, recs, self.prop, self.wl,
                                              self.rev, NOW, False, [], self.plan["version"], state, self.stored)[:2]

    def crash(self):
        ph = sha256_hex(self.prop.encode())
        self.assertEqual(run_retire(self.tr, self.plan, self.ov, self.rp, ph, crash_after="intent").get("crashed"), "intent")

    def test_a_bad_record_stops_before_the_intent_and_not_after(self):
        copied = dict(self.good, ref="c-copy", author_account_id="acct-someone")
        edited = dict(self.good, updated_at="2026-11-15T11:30:00Z")
        fresh_rec = dict(self.good, ref="c-fresh", created_at="2026-11-15T11:40:00Z", updated_at="2026-11-15T11:40:00Z")
        self.assertFalse(self.v([self.good, copied])[0])
        self.crash()
        self.assertEqual(self.v([self.good, copied]), (True, []))
        self.assertFalse(self.v([edited])[0])  # not counted: no quorum without a fresh record
        self.assertEqual(self.v([edited, fresh_rec]), (True, []))

    def test_the_bound_overlay_after_an_overlay_update(self):
        anchor2 = dict(self.anchor, version=self.anchor["version"] + 1, hash="e" * 64)
        self.assertFalse(self.v([self.good], anchor=anchor2)[0])  # before the intent: CR-12
        self.crash()
        self.assertEqual(self.v([self.good], anchor=anchor2), (True, []))
        other = copy.deepcopy(self.ov)
        other["hash"] = "d" * 64  # neither the anchored overlay nor the one the plan binds
        self.assertFalse(self.v([self.good], ov=other, anchor=anchor2)[0])


if __name__ == "__main__":
    unittest.main()
