# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Change requests (planning model section 3): log, ids, base, assessment, outcomes, basis after release."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import change_request as cr  # noqa: E402
import check_hashes  # noqa: E402
import render_proposal  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402


def g1():
    plan, ov, _e = fresh("G1")
    return plan, ov


def logged(plan, text="Also export the sign-up list as a spreadsheet for coordinators", source="runner", derived=()):
    log, entry = cr.allocate(cr.empty_log(plan["id"]), text, source, "business_user", plan["version"], 2, derived)
    return log, entry


def add_task(plan, tid="P1-T06", after="P1-T05", phase="P1", waits=()):
    new = copy.deepcopy(plan)
    new["version"] += 1
    t = copy.deepcopy(next(x for x in new["tasks"] if x["id"] == after))
    t.update(id=tid, key=f"gw:{plan['id']}:{tid}", order=max(x["order"] for x in new["tasks"]) + 1, phase=phase,
             depends_on=[{"task": after, "satisfied_by": "done"}], waits_on=list(waits))
    new["tasks"].append(t)
    next(p for p in new["phases"] if p["id"] == phase)["task_ids"].append(tid)
    return new


def to_format1(plan):
    p = copy.deepcopy(plan)
    p["stamps"]["plan_format"] = "1.0"
    for k in ("brief", "traits", "approach"):
        p.pop(k, None)
    return p


class Log(unittest.TestCase):
    def test_ids_are_sequential_pending_and_valid(self):
        plan, _ov = g1()
        log, e1 = logged(plan)
        log, e2 = cr.allocate(log, "Send a reminder email the day before each event", "runner", "comms", plan["version"], 2)
        self.assertEqual((e1["id"], e2["id"]), ("CR-1", "CR-2"))
        self.assertEqual({e["outcome"] for e in log["entries"]}, {"pending"})
        self.assertEqual(log["n"], 2)
        self.assertEqual(validate(log, load_schema("change-requests")), [])

    def test_restatement_and_pasted_provenance_are_required(self):
        plan, _ov = g1()
        with self.assertRaises(ValueError):
            logged(plan, text="  ")
        with self.assertRaises(ValueError):
            logged(plan, source="pasted")
        _log, e = logged(plan, source="pasted", derived=["ev-runner-0001"])
        self.assertEqual(e["derived_from"], ["ev-runner-0001"])

    def test_two_decisions_from_the_latest_file_keep_both(self):
        plan, _ov = g1()
        log, _ = logged(plan)
        log, _ = cr.allocate(log, "Show event capacity on the sign-up page", "runner", "business_user", plan["version"], 2)
        log, _ = cr.decide(log, "CR-1", "declined", "Outside the brief's scope", plan["version"], "a" * 64)
        log, _ = cr.decide(log, "CR-2", "added", "Fits the outcome", plan["version"] + 1, "b" * 64)
        self.assertEqual({e["id"]: e["outcome"] for e in log["entries"]}, {"CR-1": "declined", "CR-2": "added"})
        with self.assertRaises(ValueError):
            cr.decide(log, "CR-1", "added", "again", plan["version"], "c" * 64)

    def test_base_check_refuses_a_moved_plan_or_manifest(self):
        plan, _ov = g1()
        _log, e = logged(plan)
        self.assertEqual(cr.base_problems(e, plan["version"], 2), [])
        self.assertEqual(len(cr.base_problems(e, plan["version"] + 1, 3)), 2)

    def test_similar_declined_requests_are_shown(self):
        plan, _ov = g1()
        log, _ = logged(plan)
        log, _ = cr.decide(log, "CR-1", "declined", "Coordinators already get a CSV", plan["version"], "a" * 64)
        hits = cr.similar_declined(log, "Export the sign-up list as a spreadsheet for the coordinators")
        self.assertEqual([h["id"] for h in hits], ["CR-1"])
        self.assertEqual(cr.similar_declined(log, "Add a dark theme to the admin pages"), [])

    def test_log_is_scanned_for_secrets_and_restricted_values(self):
        plan, _ov = g1()
        log, _ = logged(plan, text="Email the list to jane@realcorp.co every night")
        self.assertTrue(cr.log_problems(log))
        log, _ = logged(plan, text="Use budget code 7781-ALPHA for the export")
        self.assertTrue(cr.log_problems(log, {"B-12": "7781-ALPHA"}))
        self.assertEqual(cr.log_problems(logged(plan)[0]), [])


class Assessment(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov = g1()
        self.log, self.entry = logged(self.plan)

    def test_drafted_add_counts_one_day_tasks_and_dependencies(self):
        new = add_task(self.plan, waits=[{"what": "Coordinators confirm the column order", "kind": "external",
                                          "owner_role_key": "business_user", "condition": None, "legacy_ref": None}])
        a = cr.assess(self.plan, new, self.log, "CR-1", "drafted")
        self.assertEqual((a["cost"]["kind"], a["cost"]["tasks"], a["cost"]["task_ids"]), ("drafted", 1, ["P1-T06"]))
        self.assertEqual(a["cost"]["waits"], [{"what": "Coordinators confirm the column order", "days": 0}])
        self.assertEqual(a["dependencies"]["new_edges"], [{"task": "P1-T06", "depends_on": "P1-T05"}])
        self.assertEqual(a["dependencies"]["existing_tasks_affected"], ["P1-T05"])
        self.assertEqual(a["fit"]["changes_the_brief"], [])
        self.assertIn("scope_in", a["fit"]["serves"])
        self.assertEqual([o["outcome"] for o in a["options"]], ["added", "later", "own_epic", "declined"])

    def test_changing_the_brief_is_flagged_first(self):
        new = add_task(self.plan)
        f = next(x for x in new["brief"] if x["key"] == "scope_in")
        f["value"] += " Also a coordinator spreadsheet."
        a = cr.assess(self.plan, new, self.log, "CR-1", "drafted")
        self.assertEqual(a["fit"]["changes_the_brief"], ["scope_in"])
        md = cr.render(a)
        self.assertLess(md.index("Changes the brief"), md.index("Request:"))

    def test_outline_cost_is_about_five_tasks_a_phase(self):
        new = copy.deepcopy(self.plan)
        new["version"] += 1
        new["phases"].append({"id": "P4", "order": 4, "name": "Spreadsheet export", "goal": "Coordinators get a spreadsheet.",
                              "state": "outline", "depends_on": ["P3"], "task_ids": []})
        new["open_questions"].append({"id": "Q-9", "text": "Which spreadsheet format do coordinators use?", "blocks": ["P4"],
                                      "status": "open", "answer": None, "answered_by": None, "at": None})
        a = cr.assess(self.plan, new, self.log, "CR-1", "outline")
        self.assertEqual((a["cost"]["phases"], a["cost"]["tasks_about"], a["cost"]["narrowed_by"]), (1, 5, ["Q-9"]))
        self.assertIn("needs a planning run", cr.render(a))
        u = cr.assess(self.plan, new, self.log, "CR-1", "unknown")
        self.assertEqual(u["cost"]["answer_first"], ["Q-9"])

    def test_pending_approvals_that_become_void_are_named(self):
        a = cr.assess(self.plan, add_task(self.plan), self.log, "CR-1", "drafted", approved_unwritten=["P2"])
        self.assertIn("Pending approvals become void", cr.render(a))
        quiet = cr.assess(self.plan, add_task(self.plan), self.log, "CR-1", "drafted")
        self.assertNotIn("Pending approvals", cr.render(quiet))

    def test_format1_plan_skips_fit_and_says_so(self):
        base, new = to_format1(self.plan), to_format1(add_task(self.plan))
        a = cr.assess(base, new, self.log, "CR-1", "drafted")
        self.assertIsNone(a["fit"])
        self.assertTrue(any("format-1" in n for n in a["notes"]))
        self.assertEqual(a["cost"]["tasks"], 1)

    def test_added_trait_must_carry_its_plan_version(self):
        new = add_task(self.plan)
        new["traits"].append({"id": "moves_data", "version": "1.0.0", "from_plan_version": 1})
        a = cr.assess(self.plan, new, self.log, "CR-1", "drafted")
        self.assertEqual(a["traits_added"], ["moves_data"])
        self.assertTrue(any("from_plan_version" in n for n in a["notes"]))


class Outcomes(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov = g1()
        self.log, _ = logged(self.plan)

    def test_revision_write_list_binds_the_entry_without_its_own_proposal_hash(self):
        new = add_task(self.plan)
        entry = {"id": "CR-1", "outcome": "added", "reason": "Fits the outcome"}
        wl = render_proposal.write_list(new, self.ov, ["P1"], cr_entry=entry)
        w = next(x for x in wl["writes"] if x["kind"] == "cr_log_put")
        self.assertEqual((w["scope"], w["entry"]), ("plan", entry))
        self.assertEqual(check_hashes.write_list_scope_problems(wl, "phases", ["P1"]), [])

    def test_decline_is_plan_level_and_writes_no_plan_version(self):
        entry = {"id": "CR-1", "outcome": "declined", "reason": "Outside the brief's scope"}
        wl = render_proposal.plan_write_list(self.plan, self.ov, "decline", cr_entry=entry)
        self.assertEqual(wl["plan_version"], self.plan["version"])
        self.assertEqual(check_hashes.write_list_scope_problems(wl, "plan_level", []), [])
        log, e = cr.decide(self.log, "CR-1", "declined", entry["reason"], self.plan["version"], "d" * 64)
        self.assertEqual(e["decided_by"], {"plan_version": self.plan["version"], "proposal_hash": "d" * 64})
        self.assertEqual(validate(log, load_schema("change-requests")), [])

    def test_unknown_outcome_is_refused(self):
        with self.assertRaises(ValueError):
            cr.decide(self.log, "CR-1", "maybe", "x", 1, "e" * 64)


class BoundDecision(unittest.TestCase):
    """Review findings 4 and 10: create decides from the bound entry, the proposal shows it, a resume is a no-op."""

    def setUp(self):
        self.plan, self.ov = g1()
        self.log, _ = logged(self.plan)
        self.entry = {"id": "CR-1", "outcome": "declined", "reason": "Outside the brief's scope"}
        self.wl = render_proposal.plan_write_list(self.plan, self.ov, "decline", cr_entry=self.entry)

    def test_decide_takes_outcome_and_reason_from_the_write_list(self):
        log, e = cr.decide_bound(self.log, self.wl, "d" * 64)
        self.assertEqual((e["outcome"], e["reason"]), ("declined", "Outside the brief's scope"))
        self.assertEqual(e["decided_by"], {"plan_version": self.plan["version"], "proposal_hash": "d" * 64})

    def test_a_write_list_cannot_bind_an_outcome_its_kind_does_not_allow(self):
        with self.assertRaises(ValueError):
            render_proposal.plan_write_list(self.plan, self.ov, "decline", cr_entry=dict(self.entry, outcome="added"))
        forged = copy.deepcopy(self.wl)
        next(w for w in forged["writes"] if w["kind"] == "cr_log_put")["entry"]["outcome"] = "added"
        with self.assertRaises(ValueError):
            cr.decide_bound(self.log, forged, "d" * 64)
        with self.assertRaises(ValueError):
            render_proposal.plan_write_list(self.plan, self.ov, "retire")

    def test_the_proposal_shows_the_bound_outcome_and_reason(self):
        ctx = render_proposal.proposal_context(self.plan, "decline", "Decline CR-1.")
        md = render_proposal.plan_level_proposal(self.plan, self.ov, self.wl, ctx)
        self.assertIn("## Change request decision", md)
        self.assertIn("`CR-1`: declined. Reason: Outside the brief's scope", md)
        other = render_proposal.plan_write_list(self.plan, self.ov, "decline", cr_entry=dict(self.entry, reason="Too costly"))
        self.assertNotEqual(render_proposal.plan_level_proposal(self.plan, self.ov, other, ctx), md)

    def test_resuming_the_same_decision_changes_nothing(self):
        log, _ = cr.decide_bound(self.log, self.wl, "d" * 64)
        again, e = cr.decide_bound(log, self.wl, "d" * 64)
        self.assertIs(again, log)
        self.assertTrue(e["already"])
        with self.assertRaises(ValueError):
            cr.decide_bound(log, self.wl, "e" * 64)  # another set cannot re-decide it

    def test_cli_decide_needs_the_write_list_and_checks_restricted_values(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        d = tempfile.mkdtemp()
        lp, wp, rp = (os.path.join(d, n) for n in ("log.json", "wl.json", "r.json"))
        json.dump(self.log, open(lp, "w"))
        json.dump(self.wl, open(wp, "w"))
        json.dump({"B-12": "sign-up list"}, open(rp, "w"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cr.main(["decide", lp, "CR-1", "--proposal-hash", "d" * 64]), 1)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cr.main(["decide", lp, "CR-1", "--write-list", wp, "--proposal-hash", "d" * 64, "--restricted", rp])
        self.assertEqual(rc, 1)
        self.assertIn("restricted value of B-12", buf.getvalue())


class BasisAfterRelease(unittest.TestCase):
    def test_a_changed_cited_brief_field_is_listed(self):
        released, _ov = g1()
        current = copy.deepcopy(released)
        current["version"] += 1
        self.assertEqual(cr.basis_changes(released, current, "P1"), [])
        next(f for f in current["brief"] if f["id"] == "B-3")["value"] += " Plus a spreadsheet."
        self.assertEqual(cr.basis_changes(released, current, "P1"), ["brief"])

    def test_an_uncited_field_does_not_flag_the_phase(self):
        released, _ov = g1()
        current = copy.deepcopy(released)
        import gw_model
        cited = {f["id"] for f in gw_model.basis_subset(current, "P1")["brief"]}  # tasks, decisions and option rejections
        f = next(f for f in current["brief"] if f["id"] not in cited and f["status"] == "answered"
                 and f["sensitivity"] != "restricted")
        f["value"] += " Changed."
        self.assertEqual(cr.basis_changes(released, current, "P1"), [])


class ReleaseStopsOnBasisChange(unittest.TestCase):
    """Review finding 14: release stops when an earlier released phase's basis changed (design 1.8)."""

    def test_release_of_a_later_phase_stops_until_revise(self):
        released, _ov = g1()
        current = copy.deepcopy(released)
        current["version"] += 1
        for p in current["phases"]:
            if p["id"] in ("P0", "P1"):
                p["state"] = "released"
        self.assertEqual(cr.release_basis_problems(current, {"P0": released, "P1": released}, "P2"), [])
        next(f for f in current["brief"] if f["id"] == "B-3")["value"] += " Plus a spreadsheet."
        probs = cr.release_basis_problems(current, {"P0": released, "P1": released}, "P2")
        self.assertTrue(any("released phase P1 changed" in p for p in probs), probs)
        self.assertTrue(any("no plan of record given for released phase P1" in p
                            for p in cr.release_basis_problems(current, {"P0": released}, "P2")))

    def test_revise_diff_lists_brief_and_approach_changes(self):
        import revise_diff
        base, _ov = g1()
        new = copy.deepcopy(base)
        next(f for f in new["brief"] if f["id"] == "B-3")["value"] += " Plus a spreadsheet."
        new["approach"]["decisions"][0]["decision"] += " Revised."
        m = revise_diff.model_changes(base, new)
        self.assertEqual(m["brief"]["changed"], ["B-3"])
        self.assertEqual(m["decisions"]["changed"], [new["approach"]["decisions"][0]["id"]])
        self.assertEqual(revise_diff.model_changes(to_format1(base), to_format1(new)), {})



class RevisionDecides(unittest.TestCase):
    """Second review, finding 9: an add decided by a revision binds its entry through write-list --entry."""

    def test_write_list_cli_binds_an_added_entry_and_decide_reads_it(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        plan, ov = g1()
        log, _ = logged(plan)
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)
        json.dump(plan, open(P("plan.json"), "w"))
        json.dump({"id": "CR-1", "outcome": "added", "reason": "Fits the outcome"}, open(P("e.json"), "w"))
        ovp = os.path.join(os.path.dirname(__file__), "..", "golden", "G1", "overlay", "overlay.yaml")
        with redirect_stdout(io.StringIO()):
            render_proposal.main(["write-list", P("plan.json"), "--overlay", ovp, "--offer", "P1", "--entry", P("e.json"),
                                  "--out", P("wl.json")])
        wl = json.load(open(P("wl.json")))
        json.dump({"id": "CR-1", "outcome": "declined", "reason": "x"}, open(P("bad.json"), "w"))
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            render_proposal.main(["write-list", P("plan.json"), "--overlay", ovp, "--offer", "P1", "--entry", P("bad.json")])
        log2, e = cr.decide_bound(log, wl, "d" * 64, "CR-1")
        self.assertEqual(e["outcome"], "added")
        with self.assertRaises(ValueError):
            cr.decide_bound(log, wl, "a76e")
        with self.assertRaises(ValueError):
            cr.decide_bound(log, wl, "d" * 64, "CR-2")

if __name__ == "__main__":
    unittest.main()
