# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Fourth review: the eight major findings, the minor ones fixed, and the guards no test covered."""
import copy
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
sys.path.insert(0, os.path.dirname(__file__))
from common import GOLDEN, fresh  # noqa: E402
import change_request as cr  # noqa: E402
import check_hashes  # noqa: E402
import create_steps  # noqa: E402
import render_proposal  # noqa: E402
import retire  # noqa: E402
import revise_diff  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, run_create  # noqa: E402
from test_approval_sets import (DECLINE_SUMMARY, NOW, PD, base, comment, decline_case, drev, dstored,  # noqa: E402
                                phase_case, phases_ok, plan_ok, record)

T0 = dt.datetime(2026, 11, 15, 10, 0, 0, tzinfo=dt.timezone.utc)
OVERLAY = os.path.join(GOLDEN, "G1", "overlay", "overlay.yaml")


def at(minutes):
    return T0 + dt.timedelta(minutes=minutes)


def lock_comment(ref, kind, run, account, minutes, poster=None):
    return {"ref": ref, "author_account_id": poster or account, "created_at": create_steps.fmt(at(minutes)),
            "body": create_steps.lock_line(kind, run, account, at(minutes))}


class Lock(unittest.TestCase):
    """M1, and the account checks on renew and release."""

    def test_a_late_renew_never_takes_the_lock_back(self):
        c = [lock_comment("c1", "claim", "run-a", "A", 0), lock_comment("c2", "claim", "run-b", "B", 31),
             lock_comment("c3", "renew", "run-a", "A", 32)]
        self.assertEqual(create_steps.lock_decision(c, "run-b", "B", at(33))["decision"], "held")
        self.assertEqual(create_steps.lock_decision(c, "run-a", "A", at(33))["decision"], "lost")

    def test_a_renew_while_live_extends_the_claim(self):
        c = [lock_comment("c1", "claim", "run-a", "A", 0), lock_comment("c2", "renew", "run-a", "A", 20),
             lock_comment("c3", "claim", "run-b", "B", 35)]
        self.assertEqual(create_steps.lock_decision(c, "run-a", "A", at(36))["decision"], "held")
        self.assertEqual(create_steps.lock_decision(c, "run-b", "B", at(36))["decision"], "lost")

    def test_a_fresh_claim_after_expiry_is_ordered_by_its_own_time(self):
        c = [lock_comment("c1", "claim", "run-a", "A", 0), lock_comment("c2", "claim", "run-b", "B", 31),
             lock_comment("c3", "claim", "run-a", "A", 32)]
        self.assertEqual(create_steps.lock_decision(c, "run-b", "B", at(33))["decision"], "held")
        self.assertEqual(create_steps.lock_decision(c, "run-a", "A", at(33))["decision"], "lost")

    def test_a_run_can_claim_again_after_its_own_claim_expired(self):
        c = [lock_comment("c1", "claim", "run-a", "A", 0), lock_comment("c2", "claim", "run-a", "A", 40)]
        self.assertEqual(create_steps.lock_decision(c, "run-a", "A", at(41))["decision"], "held")

    def test_only_the_claiming_account_can_renew_or_release(self):
        c = [lock_comment("c1", "claim", "run-a", "A", 0),
             lock_comment("c2", "release", "run-a", "B", 5),  # B names run-a but posts as itself
             lock_comment("c3", "claim", "run-b", "B", 6)]
        self.assertEqual(create_steps.lock_decision(c, "run-a", "A", at(7))["decision"], "held")
        c = [lock_comment("c1", "claim", "run-a", "A", 0), lock_comment("c2", "renew", "run-a", "B", 25),
             lock_comment("c3", "claim", "run-b", "B", 31)]
        self.assertEqual(create_steps.lock_decision(c, "run-b", "B", at(32))["decision"], "held")


def planned(key, phase="P1", deps=(), owned="a" * 64):
    return {"key": key, "phase": phase, "owned_hash": owned, "points": 1, "depends_on": list(deps), "waits": False}


def found(key, status="todo", owned="a" * 64, tid=None, under=True, points=1):
    return {"key": key, "tracker_id": tid or f"T-{key}", "owned_hash": owned, "under_epic": under, "points": points,
            "status": status}


class Preflight(unittest.TestCase):
    """M2, M3, M8, and the duplicate-key and parent-link rules."""

    def test_a_dependency_neither_written_nor_offered_stops(self):
        pf = create_steps.preflight([planned("b", deps=["a"]), planned("a", phase="P0")], [], None, ["P1"])
        self.assertFalse(pf["ok"])
        self.assertIn("neither written nor in this offer", pf["stops"][0]["why"])
        self.assertTrue(create_steps.preflight([planned("b", deps=["a"]), planned("a", phase="P0")], [], None, ["P0", "P1"])["ok"])

    def test_a_create_for_a_later_phase_alone_stops_end_to_end(self):
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()
        pf = run_create(tr, plan, ov, ["P1"])
        self.assertFalse(pf["ok"])
        self.assertEqual(tr.items, {})

    def test_a_found_item_without_status_stops(self):
        m = {"items": [{"key": "a", "tracker_id": "T-a", "owned_hash": "b" * 64, "links": [], "not_ready": False}]}
        f = found("a")
        del f["status"]
        pf = create_steps.preflight([planned("a")], [f], m, ["P1"], {"a": "a" * 64})
        self.assertFalse(pf["ok"])
        self.assertIn("no status", pf["stops"][0]["why"])

    def test_two_items_with_one_key_stop(self):
        pf = create_steps.preflight([planned("a")], [found("a", tid="T1"), found("a", tid="T2")], None, ["P1"])
        self.assertEqual(pf["stops"][0]["why"], "more than one item carries this key")

    def test_an_item_found_outside_the_epic_gets_its_parent_link(self):
        m = {"items": [{"key": "a", "tracker_id": "T-a", "owned_hash": "a" * 64, "links": [], "not_ready": False}]}
        pf = create_steps.preflight([planned("a")], [found("a", under=False)], m, ["P1"])
        self.assertIn("link_parent", [x["action"] for x in pf["actions"]])

    def test_the_cli_writes_only_the_verified_offer(self):
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)
        plan, ov, _e = fresh("G1")
        json.dump([planned("a", phase="P0"), planned("b", phase="P1")], open(P("planned.json"), "w"))
        json.dump([], open(P("found.json"), "w"))
        json.dump(render_proposal.write_list(plan, ov, ["P0"]), open(P("wl.json"), "w"))
        for phases, rc in (("P0,P1", 1), ("P1", 1), ("P0", 0)):
            with self.subTest(phases=phases), redirect_stdout(io.StringIO()):
                self.assertEqual(create_steps.main(["preflight", P("planned.json"), P("found.json"), "-", "--phases", phases,
                                                    "--write-list", P("wl.json")]), rc)


def mitem(key, tid, **extra):
    return dict({"key": key, "tracker_id": tid, "owned_hash": "a" * 64, "links": [], "not_ready": False}, **extra)


class ManifestChainOnRead(unittest.TestCase):
    """M4: every rule make_manifest writes by is checked again when the chain is read."""

    PID = "gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC"

    def chain(self, second_items, sf2=create_steps._KEEP, sf1=None, pid2=None):
        m1 = create_steps.make_manifest(None, [mitem("k1", "T1", close={"reason": "not_planned", "state": "closed"},
                                                     blocked_set=True)], self.PID, "r", 1, T0, [])
        if sf1:
            m1 = dict(m1, status_file=sf1)
            m1["hash"] = create_steps.item_hash(m1)
        m2 = {"schema_version": "1.0", "plan_id": pid2 or self.PID, "seq": 2, "prev_hash": m1["hash"],
              "written_at": create_steps.fmt(T0), "run_id": "r", "relies_on": [], "items": second_items}
        sf = m1.get("status_file") if sf2 is create_steps._KEEP else sf2
        if sf is not None:
            m2["status_file"] = sf
        m2["hash"] = create_steps.item_hash(m2)  # a hand edit with its hash recomputed
        return check_hashes.verify_chain([m1, m2], self.PID)

    def test_a_faithful_successor_is_the_latest(self):
        latest, probs = self.chain([mitem("k1", "T1", close={"reason": "not_planned", "state": "closed"}, blocked_set=True),
                                    mitem("k2", "T2")])
        self.assertEqual((latest["seq"], probs), (2, []))

    def test_hand_edited_successors_are_refused(self):
        for name, items in (("drops k1", []),
                            ("moves k1", [mitem("k1", "T9", close={"reason": "not_planned", "state": "closed"}, blocked_set=True)]),
                            ("clears the close", [mitem("k1", "T1", blocked_set=True)]),
                            ("clears blocked_set", [mitem("k1", "T1", close={"reason": "not_planned", "state": "closed"})])):
            with self.subTest(name):
                latest, probs = self.chain(items)
                self.assertTrue(probs)
                self.assertEqual(latest["seq"], 1)

    def test_a_dropped_status_file_and_a_foreign_plan_are_refused(self):
        keep = [mitem("k1", "T1", close={"reason": "not_planned", "state": "closed"}, blocked_set=True)]
        sf = {"state": "intent", "n": 1, "hash": "c" * 64, "at": "2026-11-15T10:00:00Z",
              "set_by": {"plan_version": 1, "proposal_hash": "d" * 64}}
        _l, probs = self.chain(keep, sf2=None, sf1=sf)
        self.assertTrue(any("status_file" in p for p in probs), probs)
        _l, probs = self.chain(keep, pid2="gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ")
        self.assertTrue(any("names plan" in p for p in probs), probs)
        m1 = create_steps.make_manifest(None, [], "gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ", "r", 1, T0, [])
        self.assertTrue(check_hashes.verify_chain([m1], self.PID)[1])

    def test_the_cli_needs_the_plan_id(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "m1.json")
        json.dump(create_steps.make_manifest(None, [], self.PID, "r", 1, T0, []), open(p, "w"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(check_hashes.main(["manifest-chain", p]), 1)
            self.assertEqual(check_hashes.main(["manifest-chain", p, "--plan-id", self.PID]), 0)


class ChangeRequestLogChain(unittest.TestCase):
    """M5: the change-request log is chained, append-only and bound to its plan."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")
        self.pid = self.plan["id"]
        self.l1, _ = cr.allocate(cr.empty_log(self.pid), "Export the list", "runner", "business_user", 1, 2)
        wl = render_proposal.plan_write_list(self.plan, self.ov, "decline", cr.to_bind(self.l1, "CR-1", "declined", "No"))
        self.l2, _ = cr.decide_bound(self.l1, wl, "d" * 64)
        self.l3, _ = cr.allocate(self.l2, "Add a report", "runner", "business_user", 1, 2)

    def test_the_chain_gives_the_latest(self):
        latest, probs = cr.verify_log_chain([self.l3, self.l1, self.l2], self.pid)
        self.assertEqual((latest["n"], probs), (3, []))
        self.assertEqual(cr.verify_log_chain([], self.pid), (cr.empty_log(self.pid), []))

    def forge(self, log, change):
        bad = copy.deepcopy(log)
        change(bad)
        bad.pop("hash")
        bad["hash"] = cr.item_hash(bad)
        return bad

    def test_dropping_or_reopening_a_decision_is_refused(self):
        for name, change in (("drops CR-1", lambda l: l.update(entries=[e for e in l["entries"] if e["id"] != "CR-1"])),
                             ("reopens CR-1", lambda l: l["entries"][0].update(outcome="pending", reason=None, decided_by=None)),
                             ("rewrites CR-1", lambda l: l["entries"][0].update(restatement="Something else"))):
            with self.subTest(name):
                latest, probs = cr.verify_log_chain([self.l1, self.l2, self.forge(self.l3, change)], self.pid)
                self.assertTrue(probs)
                self.assertEqual(latest["n"], 2)

    def test_an_edit_without_a_new_hash_a_break_or_a_foreign_log_is_refused(self):
        edited = copy.deepcopy(self.l3)
        edited["entries"][0]["reason"] = "Yes"
        self.assertTrue(cr.verify_log_chain([self.l1, self.l2, edited], self.pid)[1])
        edited = copy.deepcopy(self.l3)
        edited["entries"][1]["restatement"] = "Add a different report"  # the newest entry: only its hash shows it
        self.assertTrue(any("hash does not match" in p for p in cr.verify_log_chain([self.l1, self.l2, edited], self.pid)[1]))
        self.assertTrue(cr.verify_log_chain([self.l1, self.l3], self.pid)[1])  # log 2 is missing
        self.assertTrue(cr.verify_log_chain([self.l1, self.l2, self.l3], "gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ")[1])

    def test_next_log_refuses_to_rewrite_a_request(self):
        with self.assertRaises(ValueError):
            cr.next_log(self.l2, dict(cr.entry_of(self.l2, "CR-1"), outcome="added"))

    def test_decide_refuses_a_write_list_for_another_plan(self):
        wl = render_proposal.plan_write_list(self.plan, self.ov, "decline", cr.to_bind(self.l3, "CR-2", "declined", "No"))
        wl["plan_id"] = "gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ"
        with self.assertRaises(ValueError):
            cr.decide_bound(self.l3, wl, "d" * 64)

    def test_duplicate_ids_are_reported(self):
        log = copy.deepcopy(self.l3)
        log["entries"].append(copy.deepcopy(log["entries"][0]))
        self.assertTrue(any("duplicate" in p for p in cr.log_problems(log)))

    def test_the_cli_reads_the_chain_and_hashes_the_proposal_file(self):
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)
        for i, log in enumerate((self.l1, self.l2, self.l3), 1):
            json.dump(log, open(P(f"l{i}.json"), "w"))
        wl = render_proposal.plan_write_list(self.plan, self.ov, "decline", cr.to_bind(self.l3, "CR-2", "declined", "No"))
        json.dump(wl, open(P("wl.json"), "w"))
        open(P("proposal.md"), "w").write("# Proposal\n")
        base_args = ["--plan-id", self.pid, "--logs", P("l1.json"), P("l2.json"), P("l3.json")]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cr.main(["decide", "CR-2", "--write-list", P("wl.json")] + base_args), 1)  # no --proposal
            self.assertEqual(cr.main(["decide", "CR-2", "--write-list", P("wl.json"), "--proposal", P("proposal.md"),
                                      "--plan-id", self.pid, "--logs", P("l1.json"), P("l3.json")]), 1)  # gap in chain
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cr.main(["decide", "CR-2", "--write-list", P("wl.json"), "--proposal", P("proposal.md")] + base_args)
        self.assertEqual(rc, 0, buf.getvalue())
        from gw_canon import sha256_hex
        out = json.loads(buf.getvalue())
        self.assertEqual(out["entry"]["decided_by"]["proposal_hash"], sha256_hex(b"# Proposal\n"))
        self.assertEqual(out["log"]["prev_hash"], self.l3["hash"])


class RevisesCloseOnlyDroppedTasks(unittest.TestCase):
    """M6."""

    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()

    def test_the_write_list_refuses_closing_a_planned_or_foreign_task_or_as_completed(self):
        pid = self.plan["id"]
        for key, reason in ((f"gw:{pid}:P0-T01", "not_planned"), ("gw:gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ:P0-T01", "not_planned"),
                            (f"gw:{pid}:P0-T99", "completed")):
            with self.subTest(key=key, reason=reason), self.assertRaises(ValueError):
                render_proposal.write_list(self.plan, self.ov, ["P1"], [{"key": key, "reason": reason}])

    def test_a_set_whose_write_list_closes_a_planned_task_is_refused(self):
        wl, _ = phase_case(self.plan, self.ov)
        wl = copy.deepcopy(wl)
        key = f"gw:{self.plan['id']}:P0-T01"
        at_ = next(i for i, w in enumerate(wl["writes"]) if w["kind"] == "lock_release")
        wl["writes"][at_:at_] = [{"kind": "add_label", "key": key, "label": "gw-closed:completed"},
                                 {"kind": "close_item", "key": key, "reason": "completed"}]
        for i, w in enumerate(wl["writes"], 1):
            w.update(no=i, scope=w.get("scope", "plan"), target=wl["writes"][0]["target"])
        prop = render_proposal.proposal(self.plan, self.ov, ["P1"], wl)
        recs = [comment(record(self.plan, prop, wl, self.rev, ["P1"]))]
        ok, probs, _ = phases_ok(self.plan, self.ov, self.anchor, recs, prop, wl, self.rev)
        self.assertFalse(ok)
        self.assertTrue(any("still a task in the plan" in p for p in probs), probs)


class PlanLevelWriteListsAreRebuilt(unittest.TestCase):
    """M7, plus no manifest in decline-like sets and the plan-level 'no phases' rule."""

    def setUp(self):
        self.plan, self.ov, self.anchor, _r = base()

    def check(self, wl, items=()):
        prop = render_proposal.plan_level_proposal(self.plan, self.ov, wl, render_proposal.proposal_context(
            self.plan, wl["kind"], DECLINE_SUMMARY, items=items))
        rev = drev(self.plan, wl) if not items else {"view_hash": check_hashes.view_hash(
            __import__("gw_hash").plan_level_bundle(self.plan, wl, dstored(self.plan, wl, items)["context"],
                                                     check_hashes.CHECKLIST_VERSION, [])), "findings": []}
        recs = [comment(record(self.plan, prop, wl, rev, [], kind=wl["kind"], scope="plan_level", rid="A-2"))]
        return check_hashes.verify_plan_level(self.plan, self.ov, self.anchor, recs, prop, wl, rev, NOW, False, None, None,
                                              None, dstored(self.plan, wl, items))

    def test_a_faithful_decline_passes(self):
        wl, _c, _p = decline_case(self.plan, self.ov)
        self.assertTrue(self.check(wl)[0])

    def test_a_decline_for_another_version_or_plan_is_refused(self):
        for k, v in (("plan_version", 8), ("plan_id", "gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ")):
            with self.subTest(field=k):
                wl, _c, _p = decline_case(self.plan, self.ov)
                wl[k] = v
                ok, probs, _ = self.check(wl)
                self.assertFalse(ok)
                self.assertTrue(any("the write list is for plan" in p for p in probs), probs)

    def test_a_decline_with_a_manifest_or_phases_is_refused(self):
        wl, _c, _p = decline_case(self.plan, self.ov)
        wl["writes"].insert(1, dict(wl["writes"][1], kind="manifest_put", note="x"))
        for i, w in enumerate(wl["writes"], 1):
            w["no"] = i
        self.assertTrue(any("manifest_put" in p for p in check_hashes.write_list_scope_problems(wl, "plan_level", [])))
        wl, _c, _p = decline_case(self.plan, self.ov)
        wl["phases"] = ["P1"]
        self.assertIn("a plan-level write list offers no phases", check_hashes.write_list_scope_problems(wl, "plan_level", []))

    def test_a_decline_binding_two_entries_is_refused(self):
        wl, _c, _p = decline_case(self.plan, self.ov)
        put = next(w for w in wl["writes"] if w["kind"] == "cr_log_put")
        wl["writes"].insert(put["no"], dict(copy.deepcopy(put), entry=dict(put["entry"], id="CR-2")))
        for i, w in enumerate(wl["writes"], 1):
            w["no"] = i
        ok, probs, _ = self.check(wl)
        self.assertFalse(ok)
        self.assertTrue(any("more than one" in p for p in probs), probs)

    def test_a_retire_write_list_edited_by_hand_is_refused(self):
        items = [{"key": f"gw:{self.plan['id']}:P0-T01", "status": "todo", "person_added": False},
                 {"key": f"gw:{self.plan['id']}:P0-T02", "status": "in_progress", "person_added": False}]
        rp = retire.plan_retire(items, {items[1]["key"]: {"leave": "developer"}})
        good = retire.write_list(self.plan, self.ov, rp)
        self.assertEqual(check_hashes.rebuilt_plan_level_problems(self.plan, self.ov, good,
                                                                  {"items": items}), [])
        for name, change in (("closes as completed", lambda wl: [w.update(reason="completed") for w in wl["writes"]
                                                                  if w["kind"] == "close_item"]),
                             ("drops the status file", lambda wl: wl.update(writes=[w for w in wl["writes"]
                                                                                     if w["kind"] != "status_put"])),
                             ("leaves a todo item open", lambda wl: wl["left_open"].append(
                                 {"key": items[0]["key"], "owner_role_key": "developer"}))):
            with self.subTest(name):
                bad = copy.deepcopy(good)
                change(bad)
                self.assertTrue(check_hashes.rebuilt_plan_level_problems(self.plan, self.ov, bad, {"items": items}))


class RecordChecks(unittest.TestCase):
    """Guards no test covered: the anchor's author, anchored gate membership, the unverified writer,
    exceptions on the wrong gate."""

    def setUp(self):
        self.plan, self.ov, self.anchor, self.rev = base()
        self.wl, self.prop = phase_case(self.plan, self.ov)

    def ok(self, recs, anchor=None, unverified=False, wl=None):
        return check_hashes.verify_approvals(self.plan, self.ov, anchor or self.anchor, recs, self.prop, wl or self.wl,
                                             self.rev, ["P1"], NOW, unverified)

    def test_the_anchor_must_be_authored_by_an_admin(self):
        recs = [comment(record(self.plan, self.prop, self.wl, self.rev, ["P1"]))]
        self.assertTrue(self.ok(recs)[0])
        ok, probs, _ = self.ok(recs, dict(self.anchor, author_account_id="acct-dev"))
        self.assertFalse(ok)
        self.assertTrue(any("not authored by an overlay admin" in p for p in probs))

    def test_an_approver_missing_from_the_anchored_gate_is_refused(self):
        recs = [comment(record(self.plan, self.prop, self.wl, self.rev, ["P1"]))]
        anchor = copy.deepcopy(self.anchor)
        anchor["gates"]["phase-release"] = []
        ok, probs, _ = self.ok(recs, anchor)
        self.assertFalse(ok)
        self.assertTrue(any("not an anchored approver" in p for p in probs))

    def test_an_unverified_writer_needs_each_record_to_accept_it(self):
        rec = record(self.plan, self.prop, self.wl, self.rev, ["P1"])
        self.assertFalse(self.ok([comment(rec)], unverified=True)[0])
        rec["accept_unverified_writer"] = True
        self.assertTrue(self.ok([comment(rec)], unverified=True)[0])

    def test_a_phase_release_record_cannot_accept_an_exception(self):
        rec = record(self.plan, self.prop, self.wl, self.rev, ["P1"])
        rec["exceptions_accepted"] = ["EX-1"]
        ok, probs, _ = self.ok([comment(rec)])
        self.assertFalse(ok)
        self.assertTrue(any("use the exception gate" in p for p in probs))

    def test_a_plan_level_record_cannot_accept_an_exception(self):
        wl, _c, prop = decline_case(self.plan, self.ov)
        rev = drev(self.plan, wl)
        rec = record(self.plan, prop, wl, rev, [], kind="decline", scope="plan_level", rid="A-2")
        rec["exceptions_accepted"] = ["EX-1"]
        ok, probs, _ = plan_ok(self.plan, self.ov, self.anchor, [comment(rec)], prop, wl, rev)
        self.assertFalse(ok)
        self.assertTrue(any("cannot accept an exception" in p for p in probs))

    def test_the_phase_write_list_names_split_comments(self):
        self.assertIn("comment_split", [w["kind"] for w in self.wl["writes"]])


class CloseSteps(unittest.TestCase):
    def test_a_second_close_reason_stops(self):
        m = {"items": [mitem("k", "T1", close={"reason": "not_planned", "state": "intent"})]}
        out = create_steps.close_steps([{"key": "k", "reason": "duplicate"}], m,
                                       [{"key": "k", "tracker_id": "T1", "status": "todo"}])
        self.assertTrue(out["stops"])
        self.assertIn("already recorded", out["stops"][0]["why"])


class ReviseDiffRefusals(unittest.TestCase):
    """Guards no test covered: plan id, version, key changes and key reuse."""

    def setUp(self):
        here = os.path.join(GOLDEN, "G6", "fixtures")
        self.base = json.load(open(os.path.join(here, "base-plan.json"), encoding="utf-8"))
        self.tracker = json.load(open(os.path.join(here, "tracker.json"), encoding="utf-8"))
        from common import fresh as f
        self.new, self.ov, _e = f("G6")
        self.manifest = {"items": [{"key": i["key"]} for i in self.tracker]}

    def diff(self, new):
        return revise_diff.diff(self.base, new, self.tracker, self.ov, self.manifest)

    def test_each_refusal(self):
        self.assertTrue(self.diff(self.new)["ok"])
        added = next(t["id"] for t in self.new["tasks"] if t["id"] not in {b["id"] for b in self.base["tasks"]})
        kept = next(t["id"] for t in self.new["tasks"] if t["id"] in {b["id"] for b in self.base["tasks"]})
        cases = (("plan id", lambda n: n.update(id="gw-01JCX7Q3RZ9V4N2T8K5M6P0XYZ"), "different plan id"),
                 ("version", lambda n: n.update(version=self.base["version"]), "next plan version"),
                 ("key change", lambda n: next(t for t in n["tasks"] if t["id"] == kept).update(key=f"gw:{n['id']}:P9-T09"),
                  "key never changes"),
                 ("key reuse", lambda n: next(t for t in n["tasks"] if t["id"] == added).update(
                     key=next(b["key"] for b in self.base["tasks"])), "reuses a key"))
        for name, change, why in cases:
            with self.subTest(name):
                new = copy.deepcopy(self.new)
                change(new)
                d = self.diff(new)
                self.assertFalse(d["ok"])
                self.assertTrue(any(why in r["why"] for r in d["refused"]), d["refused"])


class PhaseWriteListBindsOneEntry(unittest.TestCase):
    def test_a_phase_write_list_binding_two_entries_is_refused(self):
        plan, ov, _a, _r = base()
        wl = render_proposal.write_list(plan, ov, ["P1"], cr_entry={"id": "CR-1", "outcome": "added", "reason": "Fits"})
        put = next(w for w in wl["writes"] if w["kind"] == "cr_log_put")
        wl["writes"].insert(put["no"], dict(copy.deepcopy(put), entry=dict(put["entry"], id="CR-2")))
        for i, w in enumerate(wl["writes"], 1):
            w["no"] = i
        self.assertTrue(check_hashes.rebuilt_write_list_problems(plan, ov, wl))


if __name__ == "__main__":
    unittest.main()
