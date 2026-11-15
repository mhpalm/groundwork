# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Approval verification across plan versions, gates and empty offers."""
import copy
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import render_proposal  # noqa: E402
import validate_plan  # noqa: E402
from gw_canon import sha256_hex  # noqa: E402
from gw_hash import phase_hashes, plan_hash, review_hash, write_list_hash  # noqa: E402

NOW = dt.datetime(2026, 11, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
CREATED = "2026-11-15T10:00:00Z"
PD = "acct-program-director"


def setup_case():
    plan, overlay, _e = fresh("G1")
    overlay = copy.deepcopy(overlay)
    overlay["hash"] = "f" * 64
    anchor = {"overlay_id": overlay["id"], "version": overlay["version"], "hash": overlay["hash"],
              "gates": {g["id"]: [a["account_id"] for a in g["approvers"]] for g in overlay["approval_gates"]},
              "author_account_id": PD}
    wl = render_proposal.write_list(plan, overlay, ["P0"])
    review = {"surface": "claude-code-cloud", "model": "test-model", "view_hash": "a" * 64, "independent": True,
              "mode": "subagent", "findings": [], "not_performed": []}
    plan["review"]["reviewer"] = dict(plan["review"]["reviewer"] or {}, **review)
    proposal = render_proposal.proposal(plan, overlay, wl["phases"], wl)
    return plan, overlay, anchor, proposal, wl, review


def record(plan, proposal, wl, review, phases, version=None, gate="phase-release", who=PD, rid="A-1", phash=None):
    rec = {"schema_version": "1.0", "id": rid, "kind": "initial", "plan_id": plan["id"],
           "plan_version": plan["version"] if version is None else version,
           "plan_hash": phash or plan_hash(plan), "plan_store_ref": "plan-v1.json", "phases": phases,
           "phase_hashes": {p: phase_hashes(plan)[p] for p in phases},
           "write_list_hash": write_list_hash(wl), "proposal_hash": sha256_hex(proposal.encode("utf-8")),
           "review_hash": review_hash(review), "view_hash": review["view_hash"], "accept_unverified_writer": False,
           "gate": gate, "approver": {"account_id": who, "name": "Program Director"},
           "minors_accepted": [], "exceptions_accepted": [], "artifact": None}
    return {"ref": f"c-{rid}", "author_account_id": who, "created_at": CREATED, "updated_at": CREATED,
            "body": "Approved.\n```json\n" + json.dumps(rec) + "\n```"}


class ApprovalVersions(unittest.TestCase):
    def test_current_record_accepts_phase(self):
        plan, overlay, anchor, prop, wl, rev = setup_case()
        ok, probs, acc = check_hashes.verify_approvals(plan, overlay, anchor, [record(plan, prop, wl, rev, ["P0"])],
                                                      prop, wl, rev, ["P0"], NOW, False)
        self.assertTrue(ok, probs)
        self.assertEqual(acc, ["P0"])

    def test_release_after_create_is_not_blocked_by_old_records(self):
        # P0 was approved and created at version N-1; release of P1 runs at version N.
        plan, overlay, anchor, prop, wl, rev = setup_case()
        old = record(plan, prop, wl, rev, ["P0"], version=plan["version"] - 1 if plan["version"] > 1 else 0,
                     rid="A-1", phash="0" * 64)
        if plan["version"] == 1:
            plan = copy.deepcopy(plan)
            plan["version"] = 2
            wl = dict(wl, plan_version=2)
            old = record(plan, prop, wl, rev, ["P0"], version=1, rid="A-1", phash="0" * 64)
        wl = render_proposal.write_list(plan, overlay, ["P1"])
        prop = render_proposal.proposal(plan, overlay, wl["phases"], wl)  # the release proposal at version N
        old = record(plan, prop, wl, rev, ["P0"], version=plan["version"] - 1, rid="A-1", phash="0" * 64)
        new = record(plan, prop, wl, rev, ["P1"], rid="A-2")
        info = []
        ok, probs, acc = check_hashes.verify_approvals(plan, overlay, anchor, [old, new], prop, wl, rev, ["P1"], NOW, False, info)
        self.assertTrue(ok, probs)
        self.assertEqual(acc, ["P1"])
        self.assertEqual(len(info), 1)
        self.assertIn("superseded", info[0])

    def test_stale_record_for_current_version_still_voids(self):
        plan, overlay, anchor, prop, wl, rev = setup_case()
        bad = record(plan, prop, wl, rev, ["P0"], phash="0" * 64)
        ok, probs, _ = check_hashes.verify_approvals(plan, overlay, anchor, [bad], prop, wl, rev, ["P0"], NOW, False)
        self.assertFalse(ok)
        self.assertTrue(any("plan_hash" in p for p in probs))

    def test_empty_phase_list_is_refused(self):
        plan, overlay, anchor, prop, wl, rev = setup_case()
        ok, probs, acc = check_hashes.verify_approvals(plan, overlay, anchor, [record(plan, prop, wl, rev, ["P0"])],
                                                      prop, wl, rev, [], NOW, False)
        self.assertFalse(ok)
        self.assertEqual(acc, [])


class ApprovalGates(unittest.TestCase):
    def test_every_all_phases_gate_needs_quorum(self):
        plan, overlay, anchor, prop, wl, rev = setup_case()
        overlay["approval_gates"].append({"id": "security", "applies_to": "all_phases",
                                          "approvers": [{"account_id": "acct-sec", "name": "Security Lead"}],
                                          "min_approvers": 1})
        anchor["gates"]["security"] = ["acct-sec"]
        one = [record(plan, prop, wl, rev, ["P0"])]
        ok, probs, _ = check_hashes.verify_approvals(plan, overlay, anchor, one, prop, wl, rev, ["P0"], NOW, False)
        self.assertFalse(ok)
        self.assertTrue(any("security" in p for p in probs), probs)
        both = one + [record(plan, prop, wl, rev, ["P0"], gate="security", who="acct-sec", rid="A-2")]
        ok, probs, acc = check_hashes.verify_approvals(plan, overlay, anchor, both, prop, wl, rev, ["P0"], NOW, False)
        self.assertTrue(ok, probs)
        self.assertEqual(acc, ["P0"])


class EmptyOffer(unittest.TestCase):
    def test_empty_offer_is_not_everything(self):
        plan, overlay, evidence = fresh("G1")
        self.assertEqual(validate_plan.check(plan, overlay, evidence, offered_arg=[]).offered, set())
        drafted = {p["id"] for p in plan["phases"] if p.get("state") != "outline"}
        self.assertEqual(validate_plan.check(plan, overlay, evidence, offered_arg=None).offered, drafted)


if __name__ == "__main__":
    unittest.main()
