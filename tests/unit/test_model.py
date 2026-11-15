# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Planning model (plan format 2): brief, traits, approach, hashing (GR-29 to GR-34)."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import NOW, fresh  # noqa: E402
import gw_hash  # noqa: E402
import render_proposal  # noqa: E402
import validate_overlay  # noqa: E402
import validate_plan  # noqa: E402


def run(plan, overlay, evidence, **kw):
    return validate_plan.check(plan, overlay, evidence, now=NOW, **kw)


def checks(R, check=None):
    return [(f["check"], f["target"]) for f in R.blocking() if check is None or f["check"] == check]


def field(plan, key):
    return next(f for f in plan["brief"] if f["key"] == key)


def to_format1(plan):
    p = copy.deepcopy(plan)
    for k in ("brief", "traits", "approach"):
        p.pop(k)
    for t in p["tasks"]:
        for k in ("brief_refs", "approach_refs", "derived_from_rec"):
            t.pop(k)
    p["standard_work"] = [s for s in p["standard_work"] if s["kind"] in validate_plan.STANDARD_KINDS]
    p["stamps"]["plan_format"] = "1.0"
    return p


class Compatibility(unittest.TestCase):
    def test_golden_passes(self):
        plan, ov, ev = fresh("G1")
        self.assertEqual(checks(run(plan, ov, ev)), [])

    def test_format1_plan_still_validates_without_model_checks(self):
        plan, ov, ev = fresh("G1")
        p1 = to_format1(plan)
        self.assertEqual(checks(run(p1, ov, ev)), [])

    def test_format1_plan_hash_has_no_model_keys(self):
        plan, _ov, _ev = fresh("G1")
        p1 = to_format1(plan)
        self.assertNotIn("brief", gw_hash.plan_subset(p1))
        self.assertIn("brief", gw_hash.plan_subset(plan))

    def test_format2_without_brief_is_refused(self):
        plan, ov, ev = fresh("G1")
        plan.pop("brief")
        self.assertIn(("GR-29", None), checks(run(plan, ov, ev)))


class Brief(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov, self.ev = fresh("G1")

    def test_missing_core_key(self):
        self.plan["brief"] = [f for f in self.plan["brief"] if f["key"] != "budget"]
        self.assertTrue(any(c == "GR-29" for c, _ in checks(run(self.plan, self.ov, self.ev))))

    def test_missing_trait_key(self):
        self.plan["brief"] = [f for f in self.plan["brief"] if f["key"] != "consumer_notice"]
        self.assertTrue(checks(run(self.plan, self.ov, self.ev), "GR-29"))

    def test_core_keys_cannot_be_restricted(self):
        f = field(self.plan, "outcome")
        f.update(sensitivity="restricted", value=None, value_rev=1)
        self.assertIn(("GR-29", f["id"]), checks(run(self.plan, self.ov, self.ev)))

    def test_restricted_field_stores_no_value(self):
        f = field(self.plan, "risks")
        f.update(sensitivity="restricted", value_rev=1)
        self.assertIn(("GR-29", f["id"]), checks(run(self.plan, self.ov, self.ev)))
        f["value"] = None
        self.assertEqual(checks(run(self.plan, self.ov, self.ev)), [])

    def test_open_field_must_block_something(self):
        f = field(self.plan, "risks")
        self.plan["open_questions"].append({"id": "Q-1", "text": "What are the risks?", "blocks": [], "status": "open",
                                            "answer": None, "answered_by": None, "at": None})
        f.update(status="open", value=None, open_question="Q-1")
        self.assertIn(("GR-29", f["id"]), checks(run(self.plan, self.ov, self.ev)))
        # In the assess profile there are no phases, so a question may block nothing.
        self.assertNotIn(("GR-29", f["id"]), checks(run(self.plan, self.ov, self.ev, profile="assess")))

    def test_parked_field_must_match_its_question(self):
        f = field(self.plan, "risks")
        self.plan["open_questions"].append({"id": "Q-1", "text": "What are the risks?", "blocks": ["P2"], "status": "open",
                                            "answer": None, "answered_by": None, "at": None})
        f.update(status="open", value=None, open_question="Q-1", phase="P3")
        self.assertIn(("GR-29", f["id"]), checks(run(self.plan, self.ov, self.ev)))

    def test_confirmed_source_needs_a_role(self):
        f = field(self.plan, "consumers")
        f["source"] = "from_tracker"
        self.assertIn(("GR-29", f["id"]), checks(run(self.plan, self.ov, self.ev)))

    def test_exactly_one_measurement_task(self):
        t = next(t for t in self.plan["tasks"] if t["id"] == "P3-T05")
        t["visible_result"]["type"] = "measurement"
        self.assertIn(("GR-29", field(self.plan, "success_measure")["id"]), checks(run(self.plan, self.ov, self.ev)))

    def test_signoffs_need_a_signoff_prep_task(self):
        f = field(self.plan, "deliverable_signoffs")
        f.update(status="answered", value="The Program Director signs off the guide.", na_reason=None)
        self.assertIn(("GR-29", f["id"]), checks(run(self.plan, self.ov, self.ev)))


class Approach(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov, self.ev = fresh("G1")
        self.ap = self.plan["approach"]

    def test_reuse_option_required(self):
        self.ap["options"][0]["kind"] = "new"
        self.assertIn(("GR-31", None), checks(run(self.plan, self.ov, self.ev)))

    def test_smaller_or_do_nothing_required(self):
        self.ap["options"][1]["kind"] = "other"
        self.assertIn(("GR-31", None), checks(run(self.plan, self.ov, self.ev)))

    def test_rejected_option_needs_a_brief_reason(self):
        self.ap["options"][2]["rejected_because"] = None
        self.assertIn(("GR-31", "O-3"), checks(run(self.plan, self.ov, self.ev)))
        self.ap["options"][2]["rejected_because"] = {"brief_ref": "B-99", "why": "x"}
        self.assertIn(("GR-31", "O-3"), checks(run(self.plan, self.ov, self.ev)))

    def test_every_task_traces_to_the_brief(self):
        t = self.plan["tasks"][3]
        t["brief_refs"], t["approach_refs"] = ["B-8"], []
        self.assertIn(("GR-31", t["id"]), checks(run(self.plan, self.ov, self.ev)))
        self.assertNotIn(("GR-31", t["id"]), checks(run(self.plan, self.ov, self.ev, done_tasks={t["id"]})))

    def test_trace_through_a_decision(self):
        t = next(t for t in self.plan["tasks"] if t["approach_refs"])
        t["brief_refs"] = []
        self.assertNotIn(("GR-31", t["id"]), checks(run(self.plan, self.ov, self.ev)))

    def test_existing_resource_must_be_changed_or_unchanged(self):
        self.plan["request"]["starting_point"]["resources"].append(
            {"id": "R3", "name": "Help page", "kind": "doc", "location": "docs", "inspected": [], "not_inspected_reason": "Not needed"})
        self.assertIn(("GR-31", "R3"), checks(run(self.plan, self.ov, self.ev)))
        self.ap["unchanged"].append("R3")
        self.assertNotIn(("GR-31", "R3"), checks(run(self.plan, self.ov, self.ev)))

    def test_deferred_decision_blocks_the_tasks_that_cite_it(self):
        design = "P1-T01"
        self.ap["decisions"].append({"id": "AD-2", "decision": "Choose the CSV library.", "chosen_option": "deferred",
                                     "deferred_to_task": design, "brief_refs": ["B-3"], "evidence": []})
        for tid in (design, "P1-T02"):
            next(t for t in self.plan["tasks"] if t["id"] == tid)["approach_refs"].append("AD-2")
        got = checks(run(self.plan, self.ov, self.ev), "GR-04")
        self.assertIn(("GR-04", "P1-T02"), got)
        self.assertNotIn(("GR-04", design), got)


class Traits(unittest.TestCase):
    def test_trait_standard_work_required(self):
        plan, ov, ev = fresh("G1")
        plan["standard_work"] = [s for s in plan["standard_work"] if s["kind"] != "consumer_comms"]
        self.assertTrue(checks(run(plan, ov, ev), "GR-33"))

    def test_unknown_trait(self):
        plan, ov, ev = fresh("G1")
        plan["traits"].append({"id": "made_up", "version": "1.0.0", "from_plan_version": 1})
        self.assertTrue(checks(run(plan, ov, ev), "GR-29"))

    def test_trait_role_must_be_mapped(self):
        plan, ov, ev = fresh("GT-vendor_or_spend")
        ov["roles"] = [r for r in ov["roles"] if r["key"] != "procurement"]
        self.assertTrue(checks(run(plan, ov, ev), "GR-14"))

    def test_conflicting_traits_need_a_decision(self):
        plan, ov, ev = fresh("GT-combined")
        self.assertEqual(checks(run(plan, ov, ev)), [])
        plan["approach"]["decisions"] = [d for d in plan["approach"]["decisions"] if not d.get("trait_conflict")]
        self.assertTrue(checks(run(plan, ov, ev), "GR-33"))


class Restricted(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov, self.ev = fresh("G1")
        self.f = field(self.plan, "risks")
        self.f.update(sensitivity="restricted", value=None, value_rev=1)

    def test_not_run_without_values(self):
        R = run(self.plan, self.ov, self.ev)
        self.assertTrue(any("GR-34" in n for n in R.not_run))

    def test_value_leak_found_with_values(self):
        secret = "team blue may be cut"
        self.assertEqual(checks(run(self.plan, self.ov, self.ev, restricted={self.f["id"]: secret}), "GR-34"), [])
        self.plan["tasks"][0]["instructions"]["purpose"] += f" Note: {secret}."
        self.assertTrue(checks(run(self.plan, self.ov, self.ev, restricted={self.f["id"]: secret}), "GR-34"))

    def test_proposal_never_shows_restricted_values(self):
        text = render_proposal.proposal(self.plan, self.ov, {"P0"})
        self.assertIn("restricted, answered", text)

    def test_reanswer_changes_plan_hash(self):
        h1 = gw_hash.plan_hash(self.plan)
        self.f["value_rev"] = 2
        self.assertNotEqual(h1, gw_hash.plan_hash(self.plan))


class Hashing(unittest.TestCase):
    def test_brief_and_approach_are_in_plan_hash(self):
        plan, _ov, _ev = fresh("G1")
        h = gw_hash.plan_hash(plan)
        field(plan, "risks")["value"] += " More."
        self.assertNotEqual(h, gw_hash.plan_hash(plan))
        plan2, _o, _e = fresh("G1")
        plan2["approach"]["options"][2]["summary"] += " Changed."
        self.assertNotEqual(h, gw_hash.plan_hash(plan2))

    def test_basis_hash_excludes_own_tasks(self):
        plan, _ov, _ev = fresh("G1")
        b = gw_hash.basis_hash(plan, "P1")
        plan["tasks"][2]["instructions"]["purpose"] += " Edited."
        self.assertEqual(b, gw_hash.basis_hash(plan, "P1"))
        plan["approach"]["options"][1]["summary"] += " Edited."
        self.assertNotEqual(b, gw_hash.basis_hash(plan, "P1"))

    def test_basis_hash_follows_cited_brief_fields(self):
        plan, _ov, _ev = fresh("G1")
        b = gw_hash.basis_hash(plan, "P2")
        field(plan, "risks")["value"] += " Uncited."
        self.assertEqual(b, gw_hash.basis_hash(plan, "P2"))
        field(plan, "scope_in")["value"] += " Cited."
        self.assertNotEqual(b, gw_hash.basis_hash(plan, "P2"))


class OverlayModel(unittest.TestCase):
    def overlay(self):
        _p, ov, _e = fresh("G1")
        ov["hash"] = None
        return ov

    def test_executor_profile_needs_a_mapped_role(self):
        ov = self.overlay()
        ov["executor_profiles"] = {"legal": "junior_no_context"}
        self.assertTrue(any("executor_profiles" in p for p in validate_overlay.problems(ov)))
        ov["executor_profiles"] = {"developer": "junior_with_context"}
        self.assertEqual(validate_overlay.problems(ov), [])

    def test_executor_profile_cannot_describe_an_expert(self):
        ov = self.overlay()
        ov["executor_profiles"] = {"developer": "a senior engineer who knows the codebase"}
        self.assertTrue(validate_overlay.problems(ov))

    def test_reviewed_proposal_does_not_claim_a_missing_review(self):
        plan, ov, _e = fresh("G1")
        plan["review"]["reviewer"] = {"mode": "subagent", "surface": "claude-code-local", "model": "reviewer-model",
                                      "view_hash": "a" * 64, "not_performed": [], "findings": []}
        text = render_proposal.proposal(plan, ov, [])
        self.assertNotIn("No independent review is recorded", text)
        plan["review"]["validator"] = {"version": "1.0.0", "passed": True, "results": [],
                                       "not_run": ["GR-34 value search: not run"]}
        text = render_proposal.proposal(plan, ov, [])
        self.assertNotIn("No independent review is recorded", text)
        self.assertIn("Checks not run in the session", text)
        plan["review"]["reviewer"] = None
        self.assertIn("No independent review is recorded", render_proposal.proposal(plan, ov, []))

    def test_org_process_is_shown_in_the_proposal(self):
        plan, ov, _e = fresh("G1")
        ov["org_process"] = [{"name": "Change freeze", "note": "No production changes in exam weeks."}]
        text = render_proposal.proposal(plan, ov, [])
        self.assertIn("## Org processes that apply", text)
        self.assertIn("Change freeze", text)

    def test_overlay_traits_are_x_prefixed_and_need_mapped_roles(self):
        ov = self.overlay()
        trait = {"id": "x-board_review", "version": "1.0.0", "summary": "Goes to the board.",
                 "questions": [{"key": "board_date_condition", "text": "When does the board meet?"}],
                 "standard_work": ["board_paper"], "roles": ["approver"], "conflicts": []}
        ov["traits"] = [trait]
        self.assertEqual(validate_overlay.problems(ov), [])
        ov["traits"] = [dict(trait, id="moves_data")]
        self.assertTrue(validate_overlay.problems(ov))
        ov["traits"] = [dict(trait, roles=["legal"])]
        self.assertTrue(any("not mapped" in p for p in validate_overlay.problems(ov)))



class ElapsedWait(unittest.TestCase):
    """Review finding 13: an elapsed wait states its condition (design 1.4)."""

    def test_elapsed_wait_without_condition_is_a_blocker(self):
        plan, ov, ev = fresh("G1")
        t = next(x for x in plan["tasks"] if x["phase"] == "P1" and not x["waits_on"])
        wait = {"what": "Two weeks of sign-ups accumulate", "kind": "elapsed", "owner_role_key": t["role_key"],
                "condition": "  ", "legacy_ref": None}
        t["waits_on"] = [wait]
        self.assertIn(("GR-16", t["id"]), checks(run(plan, ov, ev), "GR-16"))
        wait["condition"] = "At least 50 sign-ups exist across two events"
        self.assertNotIn(("GR-16", t["id"]), checks(run(plan, ov, ev), "GR-16"))


if __name__ == "__main__":
    unittest.main()
