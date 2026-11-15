# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""A blocker the confirm review still finds goes to a person (needs_person), who decides it on the approval
record itself. Create must be able to pass once every approver has decided it, and only then."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
sys.path.insert(0, os.path.dirname(__file__))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import render_proposal  # noqa: E402
import validate_plan  # noqa: E402
from test_approvals import NOW, setup_case, record  # noqa: E402

BLOCKER = {"id": "R-1", "check": "GR-33", "severity": "blocker", "target": None, "what": "A trait is not pinned.",
           "evidence_ids": [], "suggested_fix": "Pin it.", "resolution": "needs_person"}


def case(resolution="needs_person"):
    plan, overlay, anchor, _prop, wl, rev = setup_case()
    rev["findings"] = [dict(BLOCKER, resolution=resolution)]
    plan["review"]["reviewer"] = dict(plan["review"]["reviewer"], findings=rev["findings"])
    prop = render_proposal.proposal(plan, overlay, wl["phases"], wl)
    return plan, overlay, anchor, prop, wl, rev


def with_decisions(comment, decisions):
    head, js, tail = comment["body"].split("```")
    rec = json.loads(js[len("json\n"):])
    rec["decisions"] = decisions
    return dict(comment, body=head + "```json\n" + json.dumps(rec) + "\n```" + tail)


class PersonDecisions(unittest.TestCase):
    def verify(self, comments, plan, overlay, anchor, prop, wl, rev):
        return check_hashes.verify_approvals(plan, overlay, anchor, comments, prop, wl, rev, ["P0"], NOW, False)

    def test_undecided_blocker_stops_create(self):
        plan, overlay, anchor, prop, wl, rev = case()
        ok, probs, _ = self.verify([record(plan, prop, wl, rev, ["P0"])], plan, overlay, anchor, prop, wl, rev)
        self.assertFalse(ok)
        self.assertTrue(any("does not decide" in p and "R-1" in p for p in probs), probs)

    def test_decided_blocker_passes(self):
        plan, overlay, anchor, prop, wl, rev = case()
        c = with_decisions(record(plan, prop, wl, rev, ["P0"]), [{"finding": "R-1", "decision": "Pin it when P2 is planned."}])
        ok, probs, acc = self.verify([c], plan, overlay, anchor, prop, wl, rev)
        self.assertTrue(ok, probs)
        self.assertEqual(acc, ["P0"])

    def test_blank_decision_does_not_count(self):
        plan, overlay, anchor, prop, wl, rev = case()
        c = with_decisions(record(plan, prop, wl, rev, ["P0"]), [{"finding": "R-1", "decision": "   "}])
        ok, probs, _ = self.verify([c], plan, overlay, anchor, prop, wl, rev)
        self.assertFalse(ok)

    def test_decision_cannot_wave_off_an_open_blocker(self):
        plan, overlay, anchor, prop, wl, rev = case(resolution="open")
        c = with_decisions(record(plan, prop, wl, rev, ["P0"]), [{"finding": "R-1", "decision": "Ignore it."}])
        ok, probs, _ = self.verify([c], plan, overlay, anchor, prop, wl, rev)
        self.assertFalse(ok)
        self.assertTrue(any("open blocker findings (R-1)" in p for p in probs), probs)
        self.assertTrue(any("not blockers handed to a person" in p for p in probs), probs)

    def test_every_approver_decides(self):
        plan, overlay, anchor, prop, wl, rev = case()
        overlay["approval_gates"].append({"id": "security", "applies_to": "all_phases",
                                          "approvers": [{"account_id": "acct-sec", "name": "Security Lead"}],
                                          "min_approvers": 1})
        anchor["gates"]["security"] = ["acct-sec"]
        a = with_decisions(record(plan, prop, wl, rev, ["P0"]), [{"finding": "R-1", "decision": "Defer."}])
        b = record(plan, prop, wl, rev, ["P0"], gate="security", who="acct-sec", rid="A-2")
        ok, probs, _ = self.verify([a, b], plan, overlay, anchor, prop, wl, rev)
        self.assertFalse(ok)
        self.assertTrue(any("c-A-2" in p for p in probs), probs)

    def test_proposal_shows_the_blocker_to_decide(self):
        _plan, _o, _a, prop, _wl, _rev = case()
        self.assertIn("Blockers for the approver to decide", prop)
        self.assertIn("R-1 (GR-33, plan)", prop)

    def test_proposal_without_such_blockers_is_unchanged(self):
        plan, overlay, _a, prop, wl, _rev = setup_case()
        self.assertNotIn("Blockers for the approver to decide", prop)

    def test_validator_leaves_it_to_the_approval_check(self):
        plan, overlay, _a, _p, _wl, _rev = case()
        _x, _y, evidence = fresh("G1")
        res = validate_plan.check(plan, overlay, evidence, offered_arg=["P0"], stage="create")
        self.assertFalse([r for r in res.items if r["check"] == "REVIEW"], res.items)
        plan, overlay, _a, _p, _wl, _rev = case(resolution="open")
        res = validate_plan.check(plan, overlay, evidence, offered_arg=["P0"], stage="create")
        self.assertTrue([r for r in res.items if r["check"] == "REVIEW"])


if __name__ == "__main__":
    unittest.main()
