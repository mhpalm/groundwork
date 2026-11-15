# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Approval sets (planning model section 4): grouping, plan-level sets, scoped write lists, stored proposal inputs."""
import copy
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import create_steps  # noqa: E402
import validate_plan  # noqa: E402
import render_proposal  # noqa: E402
from gw_canon import sha256_hex  # noqa: E402
from gw_hash import phase_hashes, plan_hash, review_hash, write_list_hash  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402

NOW = dt.datetime(2026, 11, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
CREATED = "2026-11-15T10:00:00Z"
PD = "acct-program-director"


def base():
    plan, overlay, _e = fresh("G1")
    overlay = copy.deepcopy(overlay)
    overlay["hash"] = "f" * 64
    anchor = {"overlay_id": overlay["id"], "version": overlay["version"], "hash": overlay["hash"],
              "gates": {g["id"]: [a["account_id"] for a in g["approvers"]] for g in overlay["approval_gates"]},
              "author_account_id": PD}
    review = {"surface": "claude-code-cloud", "model": "test-model", "view_hash": "a" * 64, "independent": True,
              "mode": "subagent", "findings": [], "not_performed": []}
    plan["review"]["reviewer"] = dict(plan["review"]["reviewer"] or {}, **review)  # the review the plan records
    return plan, overlay, anchor, review


def comment(rec, who=PD, ref=None, created=CREATED, updated=None):
    return {"ref": ref or f"c-{rec.get('id', 'x')}", "author_account_id": who, "created_at": created,
            "updated_at": updated or created, "body": "Approved.\n```json\n" + json.dumps(rec) + "\n```"}


def record(plan, proposal, wl, review, phases, kind="initial", scope=None, gate="phase-release", who=PD, rid="A-1"):
    rec = {"schema_version": "1.0", "id": rid, "kind": kind, "plan_id": plan["id"], "plan_version": plan["version"],
           "plan_hash": plan_hash(plan), "plan_store_ref": "proposal-context-1.json", "phases": phases,
           "phase_hashes": {p: phase_hashes(plan)[p] for p in phases},
           "write_list_hash": write_list_hash(wl), "proposal_hash": sha256_hex(proposal.encode("utf-8")),
           "review_hash": review_hash(review), "view_hash": review["view_hash"], "accept_unverified_writer": False,
           "gate": gate, "approver": {"account_id": who, "name": "Program Director"},
           "minors_accepted": [], "exceptions_accepted": [], "artifact": None}
    if scope:
        rec["scope"] = scope
    return rec


def phase_case(plan, overlay, phases=("P1",)):
    wl = render_proposal.write_list(plan, overlay, list(phases))
    prop = render_proposal.proposal(plan, overlay, list(phases), wl)
    return wl, prop


def dassess(plan, wl):
    """The stored assessment of the change request a plan-level write list decides (None when it decides none)."""
    ids = [w["entry"]["id"] for w in wl["writes"] if w["kind"] == "cr_log_put"]
    if not ids:
        return None
    import change_request as cr
    log, _ = cr.allocate(cr.empty_log(plan["id"]), "Also export the sign-up list", "runner", "business_user",
                         plan["version"], 2)
    return dict(cr.assess(plan, plan, log, "CR-1", "unknown"), cr=ids[0])


def decline_case(plan, overlay, items=()):
    wl = render_proposal.plan_write_list(plan, overlay, "decline", cr_entry={"id": "CR-1", "outcome": "declined",
                                                                                "reason": "Outside the brief's scope"})
    ctx = render_proposal.proposal_context(plan, "decline", DECLINE_SUMMARY, items=items)
    return wl, ctx, render_proposal.plan_level_proposal(plan, overlay, wl, ctx, dassess(plan, wl))


def phases_ok(plan, overlay, anchor, comments, prop, wl, review, phases=("P1",), latest=None, info=None):
    return check_hashes.verify_approvals(plan, overlay, anchor, comments, prop, wl, review, list(phases), NOW, False,
                                         info, latest)


DECLINE_SUMMARY = "Decline CR-1: it is outside the brief's scope."


def dbundle(plan, wl, items=()):
    """The closes-and-decisions bundle a decline's review is made from."""
    ctx = render_proposal.proposal_context(plan, wl["kind"], DECLINE_SUMMARY, items=items)
    from gw_hash import plan_level_bundle
    return plan_level_bundle(plan, wl, ctx, check_hashes.CHECKLIST_VERSION, [], dassess(plan, wl))


def dstored(plan, wl, items=()):
    """What create reads from the plan store for a plan-level set."""
    return {"context": render_proposal.proposal_context(plan, wl["kind"], DECLINE_SUMMARY, items=items),
            "assessment": dassess(plan, wl), "rules": []}


def drev(plan, wl):
    from gw_hash import view_hash
    return {"view_hash": view_hash(dbundle(plan, wl)), "findings": []}


def plan_ok(plan, overlay, anchor, comments, prop, wl, review, latest=None, info=None, state=None):
    return check_hashes.verify_plan_level(plan, overlay, anchor, comments, prop, wl, review, NOW, False, info, latest,
                                          state, dstored(plan, wl))


class Grouping(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()
        self.wl, self.prop = phase_case(self.plan, self.ov)
        self.dwl, self.ctx, self.dprop = decline_case(self.plan, self.ov)
        self.phase_rec = comment(record(self.plan, self.prop, self.wl, self.rev, ["P1"]))
        self.decline_rec = comment(record(self.plan, self.dprop, self.dwl, drev(self.plan, self.dwl), [], kind="decline", scope="plan_level",
                                          rid="A-2"))

    def test_decline_and_pending_phase_set_at_one_version_both_pass(self):
        comments = [self.phase_rec, self.decline_rec]
        info = []
        ok, probs, acc = phases_ok(self.plan, self.ov, self.anchor, comments, self.prop, self.wl, self.rev, info=info)
        self.assertTrue(ok, probs)
        self.assertEqual(acc, ["P1"])
        self.assertTrue(any("another proposal" in i for i in info))
        ok, probs, kind = plan_ok(self.plan, self.ov, self.anchor, comments, self.dprop, self.dwl, drev(self.plan, self.dwl))
        self.assertTrue(ok, probs)
        self.assertEqual(kind, "decline")

    def test_malformed_record_in_another_set_does_not_fail_this_set(self):
        other = record(self.plan, "another proposal\n", self.wl, self.rev, ["P1"], rid="A-9")
        other["approver"] = "not an object"  # fails the schema, but belongs to another proposal
        edited = comment(record(self.plan, "yet another\n", self.wl, self.rev, ["P1"], rid="A-8"), updated="2026-11-15T11:00:00Z")
        junk = {"ref": "c-junk", "author_account_id": PD, "created_at": CREATED, "updated_at": CREATED,
                "body": "```json\n{not json\n```"}
        info = []
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, [self.phase_rec, comment(other), edited, junk],
                                 self.prop, self.wl, self.rev, info=info)
        self.assertTrue(ok, probs)
        self.assertEqual(len(info), 3)

    def test_malformed_record_in_this_set_is_a_problem(self):
        bad = record(self.plan, self.prop, self.wl, self.rev, ["P1"], rid="A-3")
        bad["approver"] = "not an object"
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, [self.phase_rec, comment(bad)], self.prop, self.wl, self.rev)
        self.assertFalse(ok)

    def test_stale_record_with_matching_proposal_still_voids(self):
        rec = record(self.plan, self.prop, self.wl, self.rev, ["P1"])
        rec["write_list_hash"] = "0" * 64
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, [comment(rec)], self.prop, self.wl, self.rev)
        self.assertFalse(ok)
        self.assertTrue(any("write_list_hash" in p for p in probs))

    def test_records_cannot_cross_scopes(self):
        cross = record(self.plan, self.dprop, self.dwl, drev(self.plan, self.dwl), [], kind="decline", rid="A-4")  # no plan_level scope
        ok, probs, _ = plan_ok(self.plan, self.ov, self.anchor, [comment(cross)], self.dprop, self.dwl, self.rev)
        self.assertFalse(ok)
        wrong = record(self.plan, self.prop, self.wl, self.rev, ["P1"], kind="retire", scope="plan_level", rid="A-5")
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, [comment(wrong)], self.prop, self.wl, self.rev)
        self.assertFalse(ok)


class Versions(unittest.TestCase):
    """Storing a new version voids every pending set at the older version (4.1a)."""

    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()

    def test_decline_then_revision_stored_voids_the_decline(self):
        dwl, _ctx, dprop = decline_case(self.plan, self.ov)
        rec = comment(record(self.plan, dprop, dwl, drev(self.plan, dwl), [], kind="decline", scope="plan_level"))
        ok, probs, _ = plan_ok(self.plan, self.ov, self.anchor, [rec], dprop, dwl, drev(self.plan, dwl), latest=self.plan["version"] + 1)
        self.assertFalse(ok)
        self.assertIn("is void", probs[0])

    def test_revision_stored_then_decline_coexist(self):
        v2 = copy.deepcopy(self.plan)
        v2["version"] += 1
        v2["epic"]["summary"] += " Revised."
        wl, prop = phase_case(v2, self.ov)
        dwl, _ctx, dprop = decline_case(v2, self.ov)
        recs = [comment(record(v2, prop, wl, self.rev, ["P1"])),
                comment(record(v2, dprop, dwl, drev(v2, dwl), [], kind="decline", scope="plan_level", rid="A-2"))]
        self.assertTrue(phases_ok(v2, self.ov, self.anchor, recs, prop, wl, self.rev, latest=v2["version"])[0])
        self.assertTrue(plan_ok(v2, self.ov, self.anchor, recs, dprop, dwl, drev(v2, dwl), latest=v2["version"])[0])


class PlanLevel(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()
        self.dwl, self.ctx, self.dprop = decline_case(self.plan, self.ov)

    def test_zero_records_is_refused(self):
        ok, probs, _ = plan_ok(self.plan, self.ov, self.anchor, [], self.dprop, self.dwl, drev(self.plan, self.dwl))
        self.assertFalse(ok)
        self.assertTrue(any("zero records" in p for p in probs))

    def test_every_all_phases_gate_needs_quorum(self):
        ov = copy.deepcopy(self.ov)
        ov["approval_gates"].append({"id": "finance", "applies_to": "all_phases", "approvers": [{"account_id": "acct-fin", "name": "Finance"}],
                                     "min_approvers": 1})
        anchor = dict(self.anchor, gates=dict(self.anchor["gates"], finance=["acct-fin"]))
        one = comment(record(self.plan, self.dprop, self.dwl, drev(self.plan, self.dwl), [], kind="decline", scope="plan_level"))
        ok, probs, _ = plan_ok(self.plan, ov, anchor, [one], self.dprop, self.dwl, drev(self.plan, self.dwl))
        self.assertFalse(ok)
        self.assertTrue(any("finance" in p for p in probs))
        two = comment(record(self.plan, self.dprop, self.dwl, drev(self.plan, self.dwl), [], kind="decline", scope="plan_level", gate="finance",
                             who="acct-fin", rid="A-2"), who="acct-fin")
        self.assertTrue(plan_ok(self.plan, ov, anchor, [one, two], self.dprop, self.dwl, drev(self.plan, self.dwl))[0])

    def test_records_must_agree_on_kind_and_accept_no_exception(self):
        a = record(self.plan, self.dprop, self.dwl, drev(self.plan, self.dwl), [], kind="decline", scope="plan_level")
        a["exceptions_accepted"] = ["X-1"]
        ok, probs, _ = plan_ok(self.plan, self.ov, self.anchor, [comment(a)], self.dprop, self.dwl, self.rev)
        self.assertFalse(ok)

    def test_records_that_disagree_on_the_kind_are_refused(self):
        ov = copy.deepcopy(self.ov)
        ov["approval_gates"][0]["approvers"].append({"account_id": "acct-2", "name": "Second"})
        anchor = dict(self.anchor, gates={k: v + ["acct-2"] for k, v in self.anchor["gates"].items()})
        a = comment(record(self.plan, self.dprop, self.dwl, drev(self.plan, self.dwl), [], kind="decline", scope="plan_level"))
        b = comment(record(self.plan, self.dprop, self.dwl, drev(self.plan, self.dwl), [], kind="retire", scope="plan_level", who="acct-2",
                           rid="A-2"), who="acct-2")
        ok, probs, kind = plan_ok(self.plan, ov, anchor, [a, b], self.dprop, self.dwl, drev(self.plan, self.dwl))
        self.assertFalse(ok)
        self.assertIsNone(kind)
        self.assertTrue(any("disagree" in p for p in probs))

    def test_plan_level_write_list_holds_only_plan_entries(self):
        wl = copy.deepcopy(self.dwl)
        wl["writes"].insert(1, {"no": 99, "kind": "create_item", "key": "k", "scope": "plan"})
        self.assertTrue(check_hashes.write_list_scope_problems(wl, "plan_level", []))
        self.assertEqual(check_hashes.write_list_scope_problems(self.dwl, "plan_level", []), [])

    def test_phase_set_covers_only_its_phases(self):
        wl = render_proposal.write_list(self.plan, self.ov, ["P1", "P2"])
        self.assertTrue(check_hashes.write_list_scope_problems(wl, "phases", ["P1"]))
        self.assertEqual(check_hashes.write_list_scope_problems(wl, "phases", ["P1", "P2"]), [])
        unscoped = copy.deepcopy(wl)
        del unscoped["writes"][0]["scope"]
        self.assertTrue(check_hashes.write_list_scope_problems(unscoped, "phases", ["P1", "P2"]))

    def test_every_write_in_a_phase_list_is_scoped(self):
        wl = render_proposal.write_list(self.plan, self.ov, ["P1"], closes=[{"key": f"gw:{self.plan['id']}:P9-T01", "reason": "not_planned"}])
        scopes = {w["kind"]: w["scope"] for w in wl["writes"]}
        self.assertEqual(scopes["create_item"], "phase:P1")
        self.assertEqual(scopes["link_dependency"], "phase:P1")
        self.assertEqual(scopes["set_blocked"], "phase:P1")
        self.assertEqual(scopes["close_item"], "plan")
        self.assertEqual(scopes["lock_claim"], "plan")


class IntegrityProfile(unittest.TestCase):
    def test_reports_only_integrity_checks_and_offers_nothing(self):
        plan, ov, ev = fresh("G5")  # G5 has a blocking open question, which a decline does not care about
        full = validate_plan.check(plan, ov, ev)
        self.assertTrue(full.blocking())
        R = validate_plan.check(plan, ov, ev, profile="integrity")
        self.assertEqual(R.blocking(), [])
        plan["epic"]["summary"] += " Contact jane@realcorp.co."
        R = validate_plan.check(plan, ov, ev, profile="integrity")
        self.assertEqual([f["check"] for f in R.blocking()], ["GR-17"])


class StoredInputs(unittest.TestCase):
    def setUp(self):
        self.plan, self.ov, _a, _r = base()

    def test_context_is_valid_and_rerender_is_byte_identical(self):
        items = [{"key": "gw:x:P1-T01", "status": "todo"}, {"key": "gw:x:P9", "status": "in_progress", "person_added": True}]
        wl, ctx, text = decline_case(self.plan, self.ov, items)
        self.assertEqual(validate(ctx, load_schema("proposal-context")), [])
        stored = json.loads(json.dumps({"plan": self.plan, "wl": wl, "ctx": ctx}))  # what the plan store gives back
        again = render_proposal.plan_level_proposal(stored["plan"], self.ov, stored["wl"], stored["ctx"],
                                                    json.loads(json.dumps(dassess(self.plan, wl))))
        self.assertEqual(again.encode("utf-8"), text.encode("utf-8"))
        self.assertIn("added by a person", text)

    def test_decline_leaves_a_pending_release_proposal_unchanged(self):
        wl, before = phase_case(self.plan, self.ov, ["P2"])
        decline_case(self.plan, self.ov, [{"key": "k", "status": "todo"}])
        _wl, after = phase_case(self.plan, self.ov, ["P2"])
        self.assertEqual(before, after)

    def test_context_from_another_version_is_refused(self):
        wl, ctx, _t = decline_case(self.plan, self.ov)
        ctx = dict(ctx, plan_version=ctx["plan_version"] + 1)
        with self.assertRaises(ValueError):
            render_proposal.plan_level_proposal(self.plan, self.ov, wl, ctx)

    def test_items_created_after_the_proposal_force_a_new_proposal(self):
        _wl, ctx, _t = decline_case(self.plan, self.ov, [{"key": "a", "status": "todo"}])
        self.assertTrue(create_steps.plan_level_recheck(ctx, [{"key": "a"}])["ok"])
        r = create_steps.plan_level_recheck(ctx, [{"key": "a"}, {"key": "b"}])
        self.assertFalse(r["ok"])
        self.assertEqual(r["new_items"], ["b"])



class RetireGateInApprovals(unittest.TestCase):
    """Review finding 1: approvals themselves run the retire gate, so no set writes on a retired plan."""

    def setUp(self):
        import retire
        self.retire = retire
        self.plan, self.ov, self.anchor, self.rev = base()
        self.wl, self.prop = phase_case(self.plan, self.ov)
        self.recs = [comment(record(self.plan, self.prop, self.wl, self.rev, ["P1"]))]
        st = retire.status_record(self.plan, 1, "c" * 64, CREATED)
        self.retired = {"manifest": {"status_file": dict(retire.status_intent(st), state="recorded")}, "status": st,
                        "epic": "closed"}

    def run_phase(self, state):
        return check_hashes.verify_approvals(self.plan, self.ov, self.anchor, self.recs, self.prop, self.wl, self.rev,
                                             ["P1"], NOW, False, None, self.plan["version"], state)

    def test_a_pending_phase_set_is_refused_once_the_plan_is_retired(self):
        self.assertTrue(self.run_phase({"manifest": None, "status": None, "epic": "open"})[0])
        ok, probs, _ = self.run_phase(self.retired)
        self.assertFalse(ok)
        self.assertIn("retired plan", probs[0])

    def test_a_closed_epic_refuses_a_phase_set(self):
        ok, probs, _ = self.run_phase({"manifest": None, "status": None, "epic": "closed"})
        self.assertEqual((ok, probs[0]), (False, "the epic is closed; start a new plan"))

    def test_only_the_retire_set_itself_passes_a_retired_plan(self):
        wl, ctx, prop = decline_case(self.plan, self.ov)
        recs = [comment(record(self.plan, prop, wl, drev(self.plan, wl), [], kind="decline", scope="plan_level"))]
        ok, probs, _ = check_hashes.verify_plan_level(self.plan, self.ov, self.anchor, recs, prop, wl, drev(self.plan, wl), NOW,
                                                      False, None, self.plan["version"], self.retired, dstored(self.plan, wl))
        self.assertFalse(ok)
        own = sha256_hex(prop.encode("utf-8"))
        st = self.retire.status_record(self.plan, 1, own, CREATED)
        mine = {"manifest": {"status_file": dict(self.retire.status_intent(st), state="recorded")}, "status": st,
                "epic": "closed"}
        ok, probs, _ = check_hashes.verify_plan_level(self.plan, self.ov, self.anchor, recs, prop, wl, drev(self.plan, wl), NOW,
                                                      False, None, self.plan["version"], mine, dstored(self.plan, wl))
        self.assertTrue(ok, probs)

    def test_cli_refuses_without_latest_version_and_retire_gate_inputs(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check_hashes.main(["approvals", "plan.json", "--phases", "P1"])
        self.assertEqual(rc, 1)
        self.assertIn("--latest-version, --manifests, --status, --epic, --rules, --evidence required", buf.getvalue())


class KindBinding(unittest.TestCase):
    """Review finding 9: the record's kind must be the write list's kind, and each kind allows only its writes."""

    def test_decline_records_cannot_approve_a_retire_write_list(self):
        plan, ov, anchor, rev = base()
        wl, ctx, prop = decline_case(plan, ov)
        wl = dict(wl, kind="retire")
        recs = [comment(record(plan, prop, wl, drev(plan, wl), [], kind="decline", scope="plan_level"))]
        ok, probs, _ = plan_ok(plan, ov, anchor, recs, prop, wl, drev(plan, wl))
        self.assertFalse(ok)
        self.assertTrue(any("write list is a retire" in p for p in probs), probs)

    def test_a_decline_cannot_close_items_or_the_epic(self):
        plan, ov, _a, _r = base()
        wl, _c, _p = decline_case(plan, ov)
        bad = copy.deepcopy(wl)
        bad["writes"].insert(1, {"no": 99, "kind": "close_epic", "on": "epic", "scope": "plan", "target": "x"})
        self.assertTrue(any("cannot authorize a close_epic" in p
                            for p in check_hashes.write_list_scope_problems(bad, "plan_level", [])))
        self.assertTrue(check_hashes.write_list_scope_problems(dict(wl, kind=None), "plan_level", []))


class ClosesAndDecisionsReview(unittest.TestCase):
    """Review finding 5: a set that stores no plan version binds a review of its own bundle."""

    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()
        self.wl, self.ctx, self.prop = decline_case(self.plan, self.ov)

    def verify(self, review, stored, prop=None):
        prop = prop or self.prop
        recs = [comment(record(self.plan, prop, self.wl, review, [], kind="decline", scope="plan_level"))]
        return check_hashes.verify_plan_level(self.plan, self.ov, self.anchor, recs, prop, self.wl, review, NOW, False,
                                              None, self.plan["version"], None, stored)

    def test_the_plans_own_gap_review_does_not_cover_a_decline(self):
        ok, probs, _ = self.verify(self.rev, dstored(self.plan, self.wl))
        self.assertFalse(ok)
        self.assertIn("closes-and-decisions bundle", probs[0])
        self.assertTrue(self.verify(drev(self.plan, self.wl), dstored(self.plan, self.wl))[0])

    def test_the_bundle_is_rebuilt_from_stored_inputs_never_supplied(self):
        """Second review, finding 2: a review of a bundle with another summary or other rules does not count."""
        from gw_hash import plan_level_bundle, view_hash
        st = dstored(self.plan, self.wl)
        forged = plan_level_bundle(self.plan, self.wl, dict(st["context"], summary="Everything is fine, approve.", items=[]),
                                   "0.0", [])
        ok, probs, _ = self.verify({"view_hash": view_hash(forged), "findings": []}, st)
        self.assertFalse(ok)
        self.assertTrue(any("closes-and-decisions bundle" in p for p in probs), probs)
        self.assertFalse(self.verify(drev(self.plan, self.wl), None)[0])

    def test_an_edited_proposal_is_refused(self):
        """Second review, finding 1: the proposal approvers sign is re-rendered from stored inputs."""
        edited = self.prop.replace("declined. Reason: Outside the brief's scope", "added to P1. Reason: approved by sponsor")
        self.assertNotEqual(edited, self.prop)
        ok, probs, _ = self.verify(drev(self.plan, self.wl), dstored(self.plan, self.wl), prop=edited)
        self.assertFalse(ok)
        self.assertTrue(any("does not re-render" in p for p in probs), probs)

    def test_an_open_blocker_in_the_review_stops_the_set(self):
        """Second review, finding 3."""
        rev = dict(drev(self.plan, self.wl), findings=[{"id": "F-1", "check": "GR-34", "severity": "blocker", "target": None,
                                                         "what": "the decline reason leaks a restricted value",
                                                         "evidence_ids": [], "suggested_fix": "reword",
                                                         "resolution": "open"}])
        ok, probs, _ = self.verify(rev, dstored(self.plan, self.wl))
        self.assertFalse(ok)
        self.assertTrue(any("open blocker findings (F-1)" in p for p in probs), probs)
        rev["findings"][0]["resolution"] = "fixed"
        self.assertTrue(self.verify(rev, dstored(self.plan, self.wl))[0])


class Window(unittest.TestCase):
    """Second review, finding 4: expired records are information, and the retire's own resume isn't held to the window."""

    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()
        self.wl, self.prop = phase_case(self.plan, self.ov)

    def test_fresh_records_for_the_same_proposal_finish_a_crashed_create(self):
        old = comment(record(self.plan, self.prop, self.wl, self.rev, ["P1"]), created="2026-11-10T10:00:00Z")
        info = []
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, [old], self.prop, self.wl, self.rev, info=info)
        self.assertFalse(ok)
        self.assertTrue(any("create_window_days" in i for i in info))
        fresh_rec = comment(record(self.plan, self.prop, self.wl, self.rev, ["P1"], rid="A-2"), ref="c-A-2")
        self.assertTrue(phases_ok(self.plan, self.ov, self.anchor, [old, fresh_rec], self.prop, self.wl, self.rev)[0])

    def test_the_retire_sets_own_resume_is_not_held_to_the_window(self):
        import retire
        wl, _ctx, prop = decline_case(self.plan, self.ov)
        own = sha256_hex(prop.encode("utf-8"))
        st = retire.status_record(self.plan, 1, own, CREATED)
        state = {"manifest": {"status_file": retire.status_intent(st)}, "status": None, "epic": "open"}
        recs = [comment(record(self.plan, prop, wl, drev(self.plan, wl), [], kind="decline", scope="plan_level"),
                        created="2026-11-01T10:00:00Z")]
        self.assertTrue(plan_ok(self.plan, self.ov, self.anchor, recs, prop, wl, drev(self.plan, wl), state=state)[0])
        self.assertFalse(plan_ok(self.plan, self.ov, self.anchor, recs, prop, wl, drev(self.plan, wl))[0])


class PhaseReviewView(unittest.TestCase):
    """Second review, finding 3: a phase set's review must be of this plan's reviewer view."""

    def test_an_edited_phase_proposal_is_refused(self):
        plan, ov, anchor, rev = base()
        wl, prop = phase_case(plan, ov)
        edited = prop + "\nAlso approved: delete the old export.\n"
        recs = [comment(record(plan, edited, wl, rev, ["P1"]))]
        ok, probs, _ = phases_ok(plan, ov, anchor, recs, edited, wl, rev)
        self.assertFalse(ok)
        self.assertTrue(any("does not re-render" in p for p in probs), probs)

    def test_review_of_another_view_is_refused(self):
        from gw_hash import view_bundle, view_hash
        plan, ov, anchor, _rev = base()
        wl, prop = phase_case(plan, ov)
        view = {"evidence": [], "rules": []}
        good = {"view_hash": view_hash(view_bundle(plan, [], check_hashes.CHECKLIST_VERSION, [])), "findings": []}
        plan["review"]["reviewer"].update(good)
        wl, prop = phase_case(plan, ov)  # the proposal shows the recorded review, so render it after
        for rev, want in ((good, True), ({"view_hash": "a" * 64, "findings": []}, False)):
            recs = [comment(record(plan, prop, wl, rev, ["P1"]))]
            ok, probs, _ = check_hashes.verify_approvals(plan, ov, anchor, recs, prop, wl, rev, ["P1"], NOW, False, None,
                                                         plan["version"], None, view)
            self.assertEqual(ok, want, probs)

class ReviewThreeBindings(unittest.TestCase):
    """Third review, findings 1 to 5: approvals bind only what Groundwork renders and reviews."""

    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()

    def test_an_injected_epic_close_in_a_phase_write_list_is_refused(self):
        wl, _ = phase_case(self.plan, self.ov)
        wl = copy.deepcopy(wl)
        wl["writes"].insert(-1, {"n": 0, "kind": "close_epic", "phase": "P1"})
        for i, w in enumerate(wl["writes"], 1):
            w["n"] = i
        prop = render_proposal.proposal(self.plan, self.ov, ["P1"], wl)
        recs = [comment(record(self.plan, prop, wl, self.rev, ["P1"]))]
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, recs, prop, wl, self.rev)
        self.assertFalse(ok)
        self.assertTrue(any("not the one Groundwork renders" in p for p in probs), probs)

    def test_an_open_blocker_in_the_review_is_refused(self):
        bad = dict(self.rev, findings=[{"id": "F-1", "check": "GR-04", "severity": "blocker", "target": "P1-T01",
                                        "what": "Who decides is unclear.", "evidence_ids": [], "suggested_fix": "Ask.",
                                        "resolution": "open"}])
        self.plan["review"]["reviewer"] = bad
        wl, prop = phase_case(self.plan, self.ov)
        recs = [comment(record(self.plan, prop, wl, bad, ["P1"]))]
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, recs, prop, wl, bad)
        self.assertFalse(ok)
        self.assertTrue(any("F-1" in p for p in probs), probs)
        bad["findings"][0]["resolution"] = "fixed"
        wl, prop = phase_case(self.plan, self.ov)
        recs = [comment(record(self.plan, prop, wl, bad, ["P1"]))]
        self.assertTrue(phases_ok(self.plan, self.ov, self.anchor, recs, prop, wl, bad)[0])

    def test_a_review_other_than_the_recorded_one_is_refused(self):
        wl, prop = phase_case(self.plan, self.ov)
        other = dict(self.rev, view_hash="b" * 64)
        recs = [comment(record(self.plan, prop, wl, other, ["P1"]))]
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, recs, prop, wl, other)
        self.assertFalse(ok)
        self.assertTrue(any("not the review recorded" in p for p in probs), probs)

    def test_the_epic_key_set_after_review_leaves_the_view_unchanged(self):
        from gw_hash import view_bundle, view_hash
        before = view_hash(view_bundle(self.plan, [], check_hashes.CHECKLIST_VERSION, []))
        p = copy.deepcopy(self.plan)
        p.setdefault("epic", {})["tracker_ref"] = "VOL-1"
        self.assertEqual(view_hash(view_bundle(p, [], check_hashes.CHECKLIST_VERSION, [])), before)
        p["title"] = p["title"] + " (edited)"
        self.assertNotEqual(view_hash(view_bundle(p, [], check_hashes.CHECKLIST_VERSION, [])), before)

    def test_an_evidence_reread_with_the_same_facts_leaves_the_view_unchanged(self):
        from gw_hash import view_bundle, view_hash
        _p, _o, ev = fresh("G1")
        before = view_hash(view_bundle(self.plan, ev, check_hashes.CHECKLIST_VERSION, []))
        again = copy.deepcopy(ev)
        for e in again:
            e["collected_at"] = "2026-11-15T09:00:00Z"
            if "hash" in e:
                e["hash"] = "c" * 64
        self.assertEqual(view_hash(view_bundle(self.plan, again, check_hashes.CHECKLIST_VERSION, [])), before)
        again[0]["facts"] = dict(again[0].get("facts") or {}, changed=True)
        self.assertNotEqual(view_hash(view_bundle(self.plan, again, check_hashes.CHECKLIST_VERSION, [])), before)

    def test_the_proposal_names_updates_closes_and_the_decision(self):
        t = next(t for t in self.plan["tasks"] if t["phase"] == "P1")
        other = {"key": f"gw:{self.plan['id']}:P0-T99"}  # a task the revised plan dropped
        entry = {"id": "CR-3", "outcome": "added", "reason": "Fits the brief.", "restatement": "Add a export."}
        wl = render_proposal.write_list(self.plan, self.ov, ["P1"], [{"key": other["key"], "reason": "not_planned"}],
                                        entry, [t["id"]])
        prop = render_proposal.proposal(self.plan, self.ov, ["P1"], wl)
        self.assertIn(f"{t['id']} (`", prop)
        self.assertIn(f"`{other['key']}` as not planned", prop)
        self.assertIn("`CR-3`, added", prop)

    def test_the_write_list_clis_print_their_hash(self):
        import io
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        d = tempfile.mkdtemp()
        pp, op = os.path.join(d, "plan.json"), os.path.join(d, "overlay.json")
        json.dump(self.plan, open(pp, "w"))
        json.dump(self.ov, open(op, "w"))
        for argv in (["write-list", pp, "--overlay", op, "--offer", "P1"],
                     ["plan-write-list", pp, "--overlay", op, "--kind", "later"]):
            with self.subTest(argv=argv[0]):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = render_proposal.main(argv)
                self.assertEqual(rc, 0)
                self.assertIn(f"write_list_hash {write_list_hash(json.loads(out.getvalue()))}", err.getvalue())


class PlanLevelAssessment(unittest.TestCase):
    """Third review, finding 11: create re-renders a plan-level proposal with its stored assessment."""

    def test_a_proposal_that_leaves_out_the_stored_assessment_is_refused(self):
        import change_request as cr
        from gw_hash import plan_level_bundle, view_hash
        plan, ov, anchor, _r = base()
        log, _ = cr.allocate(cr.empty_log(plan["id"]), "Also export a spreadsheet", "runner", "business_user",
                             plan["version"], 2)
        a = cr.assess(plan, plan, log, "CR-1", "unknown")
        wl = render_proposal.plan_write_list(plan, ov, "decline", cr_entry=cr.to_bind(log, "CR-1", "declined", "Too costly"))
        ctx = render_proposal.proposal_context(plan, "decline", DECLINE_SUMMARY)
        stored = {"context": ctx, "assessment": a, "rules": []}
        rev = {"view_hash": view_hash(plan_level_bundle(plan, wl, ctx, check_hashes.CHECKLIST_VERSION, [], a)), "findings": []}
        for prop, want in ((render_proposal.plan_level_proposal(plan, ov, wl, ctx, a), True),
                           (render_proposal.plan_level_proposal(plan, ov, wl, ctx), False)):
            recs = [comment(record(plan, prop, wl, rev, [], kind="decline", scope="plan_level", rid="A-2"))]
            ok, probs, _ = check_hashes.verify_plan_level(plan, ov, anchor, recs, prop, wl, rev, NOW, False, None, None,
                                                          None, stored)
            self.assertEqual(ok, want, probs)


class WholeOffer(unittest.TestCase):
    """Third review, finding 8: a record approves the whole offer."""

    def test_a_record_for_part_of_the_offer_is_refused(self):
        plan, ov, anchor, rev = base()
        wl, prop = phase_case(plan, ov, ("P0", "P1"))
        part = [comment(record(plan, prop, wl, rev, ["P1"]))]
        ok, probs, acc = phases_ok(plan, ov, anchor, part, prop, wl, rev, phases=("P0", "P1"))
        self.assertFalse(ok)
        self.assertTrue(any("whole offer" in p for p in probs), probs)
        ok, probs, acc = phases_ok(plan, ov, anchor, part, prop, wl, rev, phases=("P1",))
        self.assertFalse(ok)
        whole = [comment(record(plan, prop, wl, rev, ["P0", "P1"]))]
        ok, probs, acc = phases_ok(plan, ov, anchor, whole, prop, wl, rev, phases=("P0", "P1"))
        self.assertTrue(ok, probs)
        self.assertEqual(acc, ["P0", "P1"])


if __name__ == "__main__":
    unittest.main()
