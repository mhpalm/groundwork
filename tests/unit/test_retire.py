# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Retire (planning model section 7): what closes, write order, the status file and the gate."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import create_steps  # noqa: E402
import retire  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, latest_status, retire_items, run_create, run_retire  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402

PH = ["P0", "P1"]
PH_HASH = "a" * 64
AT = "2026-11-15T13:00:00Z"


def created():
    plan, ov, _e = fresh("G1")
    tr = FakeTracker()
    assert run_create(tr, plan, ov, PH)["ok"]
    return tr, plan, ov


def item(tr, tid):
    return next(i for i in tr.items.values() if i["key"].endswith(":" + tid))


def approve(tr, plan, ov, choices=None):
    r = retire.plan_retire(retire_items(tr, plan, ov, "VOL-1"), choices or {})
    assert r["ok"], r
    return r


def retired():
    tr, plan, ov = created()
    r = run_retire(tr, plan, ov, approve(tr, plan, ov), {}, PH_HASH)
    assert r["ok"], r
    return tr, plan, ov


def gate(tr, plan, op, resuming=None):
    return retire.gate(op, plan, latest_manifest(tr, plan["id"]), latest_status(tr, plan["id"]),
                       tr.epic_state.get("VOL-1", "open"), resuming)


class WhatCloses(unittest.TestCase):
    def test_todo_closes_finished_stays_and_in_progress_needs_a_choice(self):
        items = [{"key": "a", "status": "todo"}, {"key": "b", "status": "done"},
                 {"key": "c", "status": "closed_not_done"}, {"key": "d", "status": "in_progress"}]
        r = retire.plan_retire(items, {})
        self.assertFalse(r["ok"])
        self.assertTrue(any(p.startswith("d is in progress") for p in r["problems"]))
        r = retire.plan_retire(items, {"d": {"leave": "developer"}})
        self.assertEqual(([c["key"] for c in r["closes"]], r["left_open"]), (["a"], [{"key": "d", "owner_role_key": "developer"}]))
        r = retire.plan_retire(items, {"d": "close"})
        self.assertEqual([c["key"] for c in r["closes"]], ["a", "d"])
        self.assertTrue(all(c["reason"] == "not_planned" for c in r["closes"]))

    def test_a_persons_child_is_named_and_never_closed(self):
        r = retire.plan_retire([{"key": "x", "status": "todo", "person_added": True}], {})
        self.assertEqual((r["closes"], r["person_added"]), ([], ["x"]))

    def test_a_leave_choice_without_an_owner_is_refused(self):
        r = retire.plan_retire([{"key": "d", "status": "in_progress"}], {"d": {"leave": ""}})
        self.assertFalse(r["ok"])


class WriteList(unittest.TestCase):
    def test_fixed_order_every_write_plan_scoped(self):
        tr, plan, ov = created()
        rp = approve(tr, plan, ov)
        wl = retire.write_list(plan, ov, rp, draft_label=True)
        kinds = [w["kind"] for w in wl["writes"]]
        self.assertEqual(kinds[:3], ["lock_claim", "remove_label", "manifest_put"])
        self.assertEqual(kinds[-6:], ["manifest_put", "status_put", "manifest_put", "snapshot_put", "close_epic", "lock_release"])
        closes = [w for w in wl["writes"] if w["kind"] == "close_item"]
        self.assertEqual(len(closes), len(rp["closes"]))
        for c in closes:  # each label goes on before its transition
            self.assertEqual(wl["writes"][c["no"] - 2]["kind"], "add_label")
        self.assertEqual(check_hashes.write_list_scope_problems(wl, "plan_level", []), [])
        bound = next(w for w in wl["writes"] if w["kind"] == "status_put")["status"]
        self.assertEqual(bound, {"schema_version": "1.0", "plan_id": plan["id"], "status": "retired"})
        self.assertNotIn(PH_HASH[:12], str(wl))  # never names its own proposal's hash
        self.assertEqual(retire.write_list(plan, ov, rp, pending_sets=["P2"])["voids_pending"], ["P2"])

    def test_status_record_is_valid_and_self_hashed(self):
        plan, _ov, _e = fresh("G1")
        st = retire.status_record(plan, 1, PH_HASH, AT)
        self.assertEqual(validate(st, load_schema("plan-status")), [])
        self.assertEqual(retire.rebuild_status(plan["id"], retire.status_intent(st)), st)
        bad = dict(retire.status_intent(st), at="2026-11-15T14:00:00Z")
        with self.assertRaises(ValueError):
            retire.rebuild_status(plan["id"], bad)


class Run(unittest.TestCase):
    def test_retire_closes_todo_records_status_and_closes_epic(self):
        tr, plan, ov = retired()
        self.assertEqual(tr.epic_state["VOL-1"], "closed")
        st = latest_status(tr, plan["id"])
        self.assertEqual((st["n"], st["set_by"]), (1, {"plan_version": plan["version"], "proposal_hash": PH_HASH}))
        m = latest_manifest(tr, plan["id"])
        self.assertEqual((m["status_file"]["state"], m["status_file"]["hash"]), ("recorded", st["hash"]))
        self.assertEqual(validate(m, load_schema("manifest")), [])
        self.assertTrue(all(i["state"] == "closed" for i in tr.items.values()))
        self.assertTrue(tr.comments[-1]["body"].startswith("gw-lock release"))

    def test_in_progress_left_open_and_done_untouched(self):
        tr, plan, ov = created()
        item(tr, "P1-T02")["category"] = "in_progress"
        tr.close(item(tr, "P1-T03")["tracker_id"], "completed")
        choices = {item(tr, "P1-T02")["key"]: {"leave": "developer"}}
        r = run_retire(tr, plan, ov, approve(tr, plan, ov, choices), choices, PH_HASH)
        self.assertTrue(r["ok"], r)
        self.assertEqual(item(tr, "P1-T02")["state"], "open")
        self.assertEqual(item(tr, "P1-T03")["closed_as"], ["completed"])
        self.assertNotIn("gw-closed:not_planned", item(tr, "P1-T03")["labels"])

    def test_draft_label_is_removed_first(self):
        tr, plan, ov = created()
        tr.epic_labels["VOL-1"] = {"gw-draft"}
        w0 = tr.writes
        run_retire(tr, plan, ov, approve(tr, plan, ov), {}, PH_HASH, draft_label="gw-draft", crash_after="closes")
        self.assertEqual(tr.epic_labels["VOL-1"], set())
        self.assertGreater(tr.writes, w0)

    def test_person_added_child_stays_open(self):
        tr, plan, ov = created()
        tid = tr.create_item("person:1", "A person's own task", "", "developer", "P1")
        tr.link_parent(tid, "VOL-1")
        rp = approve(tr, plan, ov)
        self.assertEqual(rp["person_added"], ["person:1"])
        self.assertTrue(run_retire(tr, plan, ov, rp, {}, PH_HASH)["ok"])
        self.assertEqual(tr.items[tid]["state"], "open")

    def test_a_plan_item_no_manifest_records_stops_until_create_resumes(self):
        plan, ov, _e = fresh("G1")
        tr = FakeTracker()
        tr.fail_at = 3  # the session dies after two creates, before any manifest
        self.assertTrue(run_create(tr, plan, ov, PH, hard_crash=True)["crashed"])
        items = retire_items(tr, plan, ov, "VOL-1")
        self.assertTrue(items and all(i["unrecorded"] and not i["person_added"] for i in items))
        r = retire.plan_retire(items, {})
        self.assertFalse(r["ok"])
        self.assertIn("resume that create first", r["problems"][0])
        self.assertTrue(run_create(tr, plan, ov, PH)["ok"])
        self.assertTrue(run_retire(tr, plan, ov, approve(tr, plan, ov), {}, PH_HASH)["ok"])

    def test_work_started_after_approval_stops_the_retire(self):
        tr, plan, ov = created()
        rp = approve(tr, plan, ov)
        item(tr, "P1-T04")["category"] = "in_progress"  # someone picked it up after the runner approved
        r = run_retire(tr, plan, ov, rp, {}, PH_HASH)
        self.assertFalse(r["ok"])
        self.assertTrue(any("in progress" in p for p in r["problems"]))
        self.assertEqual(item(tr, "P1-T04")["state"], "open")
        self.assertIsNone(latest_status(tr, plan["id"]))

    def test_a_close_the_approval_did_not_name_stops(self):
        tr, plan, ov = created()
        k = item(tr, "P1-T04")["key"]
        item(tr, "P1-T04")["category"] = "in_progress"
        rp = approve(tr, plan, ov, {k: {"leave": "developer"}})
        r = run_retire(tr, plan, ov, rp, {k: "close"}, PH_HASH)
        self.assertFalse(r["ok"])
        self.assertTrue(any("does not name it" in p for p in r["problems"]))


class Crash(unittest.TestCase):
    def crash_then_resume(self, where):
        tr, plan, ov = created()
        rp = approve(tr, plan, ov)
        self.assertEqual(run_retire(tr, plan, ov, rp, {}, PH_HASH, crash_after=where)["crashed"], where)
        return tr, plan, ov, rp

    def test_resume_of_the_retire_set_completes_after_every_crash_point(self):
        for where in ("closes", "intent", "status", "recorded", "snapshot", "epic"):
            with self.subTest(where=where):
                tr, plan, ov, rp = self.crash_then_resume(where)
                own = (plan["version"], PH_HASH)
                if where != "closes":
                    self.assertFalse(gate(tr, plan, "create")["ok"])
                    self.assertFalse(gate(tr, plan, "resume", (plan["version"], "b" * 64))["ok"])
                r = run_retire(tr, plan, ov, rp, {}, PH_HASH, resuming=own if where != "closes" else None)
                self.assertTrue(r["ok"], (where, r))
                self.assertEqual(tr.epic_state["VOL-1"], "closed")
                self.assertEqual(latest_manifest(tr, plan["id"])["status_file"]["state"], "recorded")
                self.assertEqual(len([k for k in tr.store if "-status-" in k]), 1)

    def test_crash_between_status_file_and_epic_close_is_retired_not_reopenable(self):
        tr, plan, ov, _rp = self.crash_then_resume("status")
        self.assertEqual(tr.epic_state.get("VOL-1", "open"), "open")
        for op in ("create", "freeze", "release", "revise", "plan_phase", "change_request", "retire"):
            self.assertFalse(gate(tr, plan, op)["ok"], op)
        self.assertTrue(gate(tr, plan, "resume", (plan["version"], PH_HASH))["ok"])

    def test_a_status_file_without_a_recorded_intent_stops(self):
        tr, plan, ov = created()
        tr.put(f"{plan['id']}-status-1", retire.status_record(plan, 1, PH_HASH, AT))
        g = gate(tr, plan, "resume", (plan["version"], PH_HASH))
        self.assertFalse(g["ok"])
        self.assertIn("neither records nor intends", g["problems"][0])

    def test_recorded_but_missing_status_file_stops(self):
        tr, plan, ov = retired()
        del tr.store[f"{plan['id']}-status-1"]
        self.assertIn("missing", gate(tr, plan, "resume", (plan["version"], PH_HASH))["problems"][0])

    def test_tampered_or_swapped_status_file_stops(self):
        tr, plan, ov = retired()
        st = tr.store[f"{plan['id']}-status-1"]
        st["at"] = "2026-11-16T00:00:00Z"
        self.assertIn("its own hash", gate(tr, plan, "resume", (plan["version"], PH_HASH))["problems"][0])
        other = retire.status_record(plan, 1, "c" * 64, AT)  # self-consistent, but not the set the manifest names
        tr.store[f"{plan['id']}-status-1"] = other
        self.assertIn("does not match", gate(tr, plan, "resume", (plan["version"], PH_HASH))["problems"][0])

    def test_status_file_from_another_plan_stops(self):
        tr, plan, ov = retired()
        other = copy.deepcopy(plan)
        other["id"] = "gw-01OTHERPLANAAAAAAAAAAAAAA"
        self.assertFalse(retire.gate("resume", other, latest_manifest(tr, plan["id"]),
                                     latest_status(tr, plan["id"]), "closed", (plan["version"], PH_HASH))["ok"])

    def test_later_manifests_keep_the_status_file(self):
        tr, plan, ov = retired()
        m = latest_manifest(tr, plan["id"])
        nxt = create_steps.make_manifest(m, m["items"], plan["id"], "run-x", m["seq"] + 1, tr.clock, [])
        self.assertEqual(nxt["status_file"], m["status_file"])


class Gate(unittest.TestCase):
    def test_never_retired_plan_without_status_file_is_fine(self):
        tr, plan, ov = created()
        for op in retire.OPS:
            self.assertTrue(gate(tr, plan, op)["ok"], op)

    def test_every_operation_refuses_a_retired_plan(self):
        tr, plan, ov = retired()
        for op in retire.OPS:
            g = gate(tr, plan, op)
            self.assertFalse(g["ok"], op)
        self.assertIn("retired plan", gate(tr, plan, "create")["problems"][0])

    def test_only_the_own_set_resumes_and_a_resume_of_a_finished_retire_writes_nothing(self):
        tr, plan, ov = retired()
        self.assertFalse(gate(tr, plan, "resume", (plan["version"] + 1, PH_HASH))["ok"])
        self.assertTrue(gate(tr, plan, "resume", (plan["version"], PH_HASH))["resume_of_retire"])
        before = copy.deepcopy(tr.store)
        r = run_retire(tr, plan, ov, approve(tr, plan, ov), {}, PH_HASH, run="run-r3", resuming=(plan["version"], PH_HASH))
        self.assertTrue(r["ok"], r)
        self.assertEqual(tr.store, before)

    def test_a_second_retire_is_refused(self):
        tr, plan, ov = retired()
        r = run_retire(tr, plan, ov, approve(tr, plan, ov), {}, "d" * 64, run="run-r4")
        self.assertFalse(r["ok"])

    def test_a_closed_epic_refuses_create_even_without_a_status_file(self):
        tr, plan, ov = created()
        tr.close_epic("VOL-1")
        g = gate(tr, plan, "create")
        self.assertEqual((g["ok"], g["problems"]), (False, ["the epic is closed; start a new plan"]))
        self.assertFalse(gate(tr, plan, "resume", (plan["version"], PH_HASH))["ok"])

    def test_unknown_op_or_epic_state_raises(self):
        tr, plan, ov = created()
        with self.assertRaises(ValueError):
            gate(tr, plan, "delete")
        with self.assertRaises(ValueError):
            retire.gate("create", plan, None, None, "archived")



class Bundle(unittest.TestCase):

    def test_the_review_bundle_carries_the_closes_and_left_open_items(self):
        import gw_hash
        tr, plan, ov = created()
        rp = approve(tr, plan, ov)
        wl = retire.write_list(plan, ov, rp)
        ctx = {"items": [], "summary": "Retire."}
        b = gw_hash.plan_level_bundle(plan, wl, ctx, "1.0", [])
        self.assertEqual(b["closes"], rp["closes"])
        self.assertEqual(b["status"]["status"], "retired")
        fewer = copy.deepcopy(wl)
        fewer["writes"] = [w for w in fewer["writes"] if w["kind"] != "close_item" or w["key"] != rp["closes"][0]["key"]]
        self.assertNotEqual(gw_hash.view_hash(gw_hash.plan_level_bundle(plan, fewer, ctx, "1.0", [])), gw_hash.view_hash(b))


class Scripts(unittest.TestCase):
    """Review findings 4 and 6: every retire step has a script, and the proposal shows what approvers bind."""

    def test_manifest_moves_intent_to_recorded_and_refuses_any_other_change(self):
        tr, plan, ov = created()
        m = latest_manifest(tr, plan["id"])
        intent = retire.status_intent(retire.status_record(plan, 1, PH_HASH, AT))
        m2 = create_steps.make_manifest(m, m["items"], plan["id"], "run-r", m["seq"] + 1, tr.clock, [], status_file=intent)
        m3 = create_steps.make_manifest(m2, m["items"], plan["id"], "run-r", m2["seq"] + 1, tr.clock, [],
                                        status_file=dict(intent, state="recorded"))
        self.assertEqual(m3["status_file"]["state"], "recorded")
        for bad in (None, dict(intent, n=2), dict(intent, hash="0" * 64), dict(intent, state="intent")):
            with self.assertRaises(ValueError, msg=bad):
                create_steps.make_manifest(m3, m["items"], plan["id"], "run-r", m3["seq"] + 1, tr.clock, [], status_file=bad)

    def test_cli_status_manifest_rebuild_and_recheck(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        tr, plan, ov = created()
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)

        def run(mod, argv):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mod.main(argv)
            return rc, json.loads(buf.getvalue())

        json.dump(plan, open(P("plan.json"), "w"))
        rc, st = run(retire, ["status", P("plan.json"), "--n", "1", "--proposal-hash", PH_HASH, "--at", AT])
        self.assertEqual(rc, 0)
        json.dump(st["intent"], open(P("sf.json"), "w"))
        m = latest_manifest(tr, plan["id"])
        json.dump(m, open(P("m.json"), "w"))
        json.dump(m["items"], open(P("items.json"), "w"))
        rc, m2 = run(create_steps, ["manifest", P("m.json"), P("items.json"), "--plan-id", plan["id"], "--run", "run-r",
                                    "--seq", str(m["seq"] + 1), "--now", AT, "--status-file", P("sf.json")])
        self.assertEqual((rc, m2["status_file"]), (0, st["intent"]))
        json.dump(m2, open(P("m2.json"), "w"))
        rc, rb = run(retire, ["rebuild", plan["id"], P("m2.json")])
        self.assertEqual((rc, rb["status_record"]), (0, st["status_record"]))
        rp = approve(tr, plan, ov)
        json.dump(rp, open(P("rp.json"), "w"))
        json.dump(retire_items(tr, plan, ov, "VOL-1"), open(P("now.json"), "w"))
        json.dump({}, open(P("ch.json"), "w"))
        self.assertEqual(run(retire, ["recheck", P("rp.json"), P("now.json"), P("ch.json")])[0], 0)

    def test_retire_proposal_lists_left_open_person_added_and_voided_sets(self):
        import render_proposal
        tr, plan, ov = created()
        k = item(tr, "P1-T02")["key"]
        item(tr, "P1-T02")["category"] = "in_progress"
        tid = tr.create_item("person:1", "A person's own task", "", "developer", "P1")
        tr.link_parent(tid, "VOL-1")
        rp = approve(tr, plan, ov, {k: {"leave": "developer"}})
        wl = retire.write_list(plan, ov, rp, pending_sets=["P2"])
        ctx = render_proposal.proposal_context(plan, "retire", "Retire the plan: the event series was cancelled.",
                                               items=retire_items(tr, plan, ov, "VOL-1"))
        md = render_proposal.plan_level_proposal(plan, ov, wl, ctx)
        self.assertIn(f"`{k}`, owned by", md)
        self.assertIn("- `person:1`", md.split("## Children a person added")[1])
        self.assertIn("- P2", md.split("## Pending phase approvals this retire voids")[1])
        self.assertIn("## Plan status", md)
        self.assertIn('status `{"plan_id"', md)  # dict-valued writes are rendered, never dropped


if __name__ == "__main__":
    unittest.main()
