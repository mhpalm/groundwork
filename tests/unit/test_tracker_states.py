# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Blocked state, closes, closed_not_done and read_scope (planning model section 2, finding 8)."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import create_steps  # noqa: E402
import render_proposal  # noqa: E402
import revise_diff  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, run_close, run_create  # noqa: E402
from common import GOLDEN  # noqa: E402
import json  # noqa: E402


def fixture(golden, name):
    with open(os.path.join(GOLDEN, golden, "fixtures", name), encoding="utf-8") as f:
        return json.load(f)

PH = ["P0", "P1"]


def g1():
    plan, overlay, _e = fresh("G1")
    return plan, overlay


def by_task(tr, tid):
    return next(i for i in tr.items.values() if i["key"].endswith(":" + tid))


def status(tr, plan, ov, tid):
    item = by_task(tr, tid)
    m = latest_manifest(tr, plan["id"])
    w = next(i for i in m["items"] if i["key"] == item["key"])
    return create_steps.read_status(tr.raw(item["tracker_id"]), w, ov["skills"]["tracker"]["field_map"])


def created():
    plan, ov = g1()
    tr = FakeTracker()
    assert run_create(tr, plan, ov, PH)["ok"]
    return tr, plan, ov


class Blocked(unittest.TestCase):
    def test_every_waiting_task_is_blocked_once_at_create(self):
        tr, plan, _ov = created()
        waiting = {t["key"] for t in plan["tasks"] if t["phase"] in PH and t.get("waits_on")}
        self.assertTrue(waiting)
        self.assertEqual({i["key"] for i in tr.items.values() if i["blocked"]}, waiting)
        m = latest_manifest(tr, plan["id"])
        self.assertEqual({i["key"] for i in m["items"] if i.get("blocked_set")}, waiting)

    def test_a_cleared_block_is_never_reapplied(self):
        tr, plan, ov = created()
        item = by_task(tr, "P1-T02")
        tr.set_blocked(item["tracker_id"], on=False)  # the owner clears it by hand
        pf = run_create(tr, plan, ov, PH, run="run-2")
        self.assertTrue(pf["ok"])
        self.assertFalse(any(a["action"] == "set_blocked" for a in pf["actions"]))
        self.assertFalse(item["blocked"])

    def test_write_list_sets_blocked_for_each_wait(self):
        plan, ov = g1()
        wl = render_proposal.write_list(plan, ov, ["P1"])
        keys = [w["key"] for w in wl["writes"] if w["kind"] == "set_blocked"]
        self.assertEqual(keys, [t["key"] for t in sorted(plan["tasks"], key=lambda t: t["order"])
                                if t["phase"] == "P1" and t.get("waits_on")])
        self.assertTrue(all(w["field"] == "Flagged" for w in wl["writes"] if w["kind"] == "set_blocked"))


class Close(unittest.TestCase):
    def key(self, plan, tid):
        return f"gw:{plan['id']}:{tid}"

    def test_close_reads_back_as_closed_not_done(self):
        tr, plan, ov = created()
        r = run_close(tr, plan, ov, [{"key": self.key(plan, "P1-T05"), "reason": "not_planned"}])
        self.assertTrue(r["ok"], r)
        item = by_task(tr, "P1-T05")
        self.assertIn("gw-closed:not_planned", item["labels"])
        self.assertEqual(status(tr, plan, ov, "P1-T05")["status"], "closed_not_done")

    def test_intent_is_written_before_the_label(self):
        tr, plan, ov = created()
        r = run_close(tr, plan, ov, [{"key": self.key(plan, "P1-T05"), "reason": "superseded"}])
        kinds = [s["step"] for s in r["steps"]]
        self.assertEqual(kinds, ["manifest_intent", "add_label", "transition", "manifest_closed"])

    def test_open_item_with_label_is_close_pending_and_retried(self):
        tr, plan, ov = created()
        k = self.key(plan, "P1-T05")
        self.assertEqual(run_close(tr, plan, ov, [{"key": k, "reason": "not_planned"}], crash_after="label")["crashed"], "label")
        st = status(tr, plan, ov, "P1-T05")
        self.assertEqual((st["status"], st["close_pending"]), ("todo", True))
        r = run_close(tr, plan, ov, [{"key": k, "reason": "not_planned"}], run="run-c2")
        self.assertTrue(r["ok"], r)
        self.assertNotIn("manifest_intent", [s["step"] for s in r["steps"]])
        self.assertEqual(status(tr, plan, ov, "P1-T05")["status"], "closed_not_done")

    def test_crash_after_transition_still_reads_closed_not_done(self):
        tr, plan, ov = created()
        k = self.key(plan, "P1-T05")
        run_close(tr, plan, ov, [{"key": k, "reason": "not_planned"}], crash_after="transition")
        by_task(tr, "P1-T05")["closed_as"] = ["Done"]  # a workflow that forces a Done resolution
        self.assertEqual(status(tr, plan, ov, "P1-T05")["status"], "closed_not_done")

    def test_intent_alone_does_not_override_a_persons_done(self):
        tr, plan, ov = created()
        run_close(tr, plan, ov, [{"key": self.key(plan, "P1-T05"), "reason": "not_planned"}], crash_after="intent")
        st = status(tr, plan, ov, "P1-T05")
        self.assertTrue(st["close_pending"])
        tr.close(by_task(tr, "P1-T05")["tracker_id"], "Done")  # the work got done before the close resumed
        self.assertEqual(status(tr, plan, ov, "P1-T05")["status"], "done")

    def test_label_without_a_manifest_record_is_ignored(self):
        tr, plan, ov = created()
        fm = ov["skills"]["tracker"]["field_map"]
        item = by_task(tr, "P1-T04")
        tr.close(item["tracker_id"], "Won't Do")
        tr.add_label(item["tracker_id"], "gw-closed:completed")  # a person tries to turn not-done into done
        self.assertEqual(status(tr, plan, ov, "P1-T04")["status"], "closed_not_done")
        other = by_task(tr, "P1-T03")
        tr.close(other["tracker_id"], "Done")
        tr.add_label(other["tracker_id"], "gw-closed:not_planned")
        self.assertEqual(status(tr, plan, ov, "P1-T03")["status"], "done")
        self.assertEqual(create_steps.read_status(tr.raw(other["tracker_id"]), None, fm)["status"], "done")

    def test_reopen_of_a_groundwork_close_is_drift(self):
        tr, plan, ov = created()
        run_close(tr, plan, ov, [{"key": self.key(plan, "P1-T05"), "reason": "not_planned"}])
        tr.reopen(by_task(tr, "P1-T05")["tracker_id"])
        st = status(tr, plan, ov, "P1-T05")
        self.assertEqual(st["drift"], "reopened after Groundwork closed it")
        self.assertFalse(st["close_pending"])

    def test_github_duplicate_reads_as_closed_not_done(self):
        fm = {"statuses": {"done": ["completed"], "closed_not_done": ["not_planned", "duplicate"]}}
        raw = {"key": "k", "state": "closed", "closed_as": ["duplicate"], "labels": []}
        self.assertEqual(create_steps.read_status(raw, None, fm)["status"], "closed_not_done")
        raw["closed_as"] = ["completed"]
        self.assertEqual(create_steps.read_status(raw, None, fm)["status"], "done")

    def test_an_item_a_person_already_closed_is_skipped(self):
        tr, plan, ov = created()
        tr.close(by_task(tr, "P1-T05")["tracker_id"], "Done")
        r = run_close(tr, plan, ov, [{"key": self.key(plan, "P1-T05"), "reason": "not_planned"}])
        k = self.key(plan, "P1-T05")
        self.assertEqual(r["steps"], [{"step": "manifest_closed", "keys": [], "finished": [k],
                                       "records": [{"key": k, "close": {"reason": "not_planned", "state": "finished"}}]}])  # recorded, not relabelled
        self.assertEqual([s["key"] for s in r["skipped"]], [k])
        self.assertNotIn("gw-closed:not_planned", by_task(tr, "P1-T05")["labels"])
        w = next(i for i in latest_manifest(tr, plan["id"])["items"] if i["key"] == k)
        self.assertEqual(w["close"], {"reason": "not_planned", "state": "finished"})
        fm = ov["skills"]["tracker"]["field_map"]
        self.assertEqual(create_steps.read_status(tr.raw(by_task(tr, "P1-T05")["tracker_id"]), w, fm)["status"], "done")
        again = run_close(tr, plan, ov, [{"key": k, "reason": "not_planned"}])
        self.assertEqual(again["steps"], [])  # a second run changes nothing

    def test_close_refuses_unknown_reasons_and_unwritten_items(self):
        tr, plan, _ov = created()
        m = latest_manifest(tr, plan["id"])
        found = [{"key": i["key"], "tracker_id": i["tracker_id"], "status": "todo"} for i in m["items"]]
        self.assertFalse(create_steps.close_steps([{"key": self.key(plan, "P1-T05"), "reason": "abandoned"}], m, found)["ok"])
        self.assertFalse(create_steps.close_steps([{"key": self.key(plan, "P2-T01"), "reason": "not_planned"}], m, found)["ok"])

    def test_write_list_close_sequence(self):
        plan, ov = g1()
        k = f"gw:{plan['id']}:P1-T99"  # a task the revised plan dropped
        wl = render_proposal.write_list(plan, ov, ["P1"], closes=[{"key": k, "reason": "duplicate"}])
        kinds = [w["kind"] for w in wl["writes"]]
        i = kinds.index("add_label")
        self.assertEqual(kinds[i - 1:i + 3], ["manifest_put", "add_label", "close_item", "manifest_put"])
        self.assertEqual(wl["writes"][i]["label"], "gw-closed:duplicate")


class ClosedNotDone(unittest.TestCase):
    def test_never_satisfies_depends_on_at_create(self):
        plan, ov = g1()
        tr = FakeTracker()
        self.assertTrue(run_create(tr, plan, ov, ["P0", "P1"])["ok"])
        tr.close(by_task(tr, "P1-T05")["tracker_id"], "Won't Do")
        pf = run_create(tr, plan, ov, ["P2"], run="run-2")
        self.assertFalse(pf["ok"])
        self.assertIn(f"gw:{plan['id']}:P2-T01", [s["key"] for s in pf["stops"]])
        self.assertIn("closed without being done", pf["stops"][0]["why"])

    def revise(self):
        new, ov, _ev = fresh("G6")
        base = fixture("G6", "base-plan.json")
        tracker = copy.deepcopy(fixture("G6", "tracker.json"))
        return base, new, tracker, ov

    def test_revise_refuses_edits_removal_and_dependencies(self):
        base, new, tracker, ov = self.revise()
        item = next(i for i in tracker if i["key"].endswith(":P1-T02"))
        item["status"] = "closed_not_done"
        d = revise_diff.diff(base, new, tracker, ov)
        refused = {r["task"] for r in d["refused"]}
        self.assertIn("P1-T03", refused)  # P1-T03 depends on P1-T02 and isn't finished
        n2 = copy.deepcopy(new)
        n2["tasks"] = [t for t in n2["tasks"] if t["id"] != "P1-T02"]
        for t in n2["tasks"]:
            t["depends_on"] = [x for x in t["depends_on"] if x["task"] != "P1-T02"]
        d2 = revise_diff.diff(base, n2, tracker, ov)
        self.assertTrue(any(r["task"] == "P1-T02" and "cannot be removed" in r["why"] for r in d2["refused"]))

    def test_revise_reports_reopen_as_drift_and_gives_close_reasons(self):
        base, new, tracker, ov = self.revise()
        tracker[3]["drift"] = "reopened after Groundwork closed it"
        d = revise_diff.diff(base, new, tracker, ov)
        self.assertIn("reopened after Groundwork closed it", [x.get("why") for x in d["drift"]])
        self.assertEqual(len(d["close_items"]), len(d["close"]))
        self.assertTrue(all(c["reason"] == "not_planned" for c in d["close_items"]))

    def test_removing_an_unwritten_task_drops_it_and_closes_nothing(self):
        """Review finding 2: a close entry for an item that was never written would stop create halfway."""
        base, new, tracker, ov = self.revise()
        written = {i["key"] for i in tracker}
        unwritten = next(t for t in base["tasks"] if t["key"] not in written)
        n2 = copy.deepcopy(new)
        n2["tasks"] = [t for t in n2["tasks"] if t["id"] != unwritten["id"]]
        for t in n2["tasks"]:
            t["depends_on"] = [x for x in t["depends_on"] if x["task"] != unwritten["id"]]
        for ph in n2["phases"]:
            ph["task_ids"] = [x for x in ph["task_ids"] if x != unwritten["id"]]
        d = revise_diff.diff(base, n2, tracker, ov, {"items": [{"key": i["key"]} for i in tracker]})
        self.assertIn(unwritten["id"], d["dropped"])
        self.assertNotIn(unwritten["key"], [c["key"] for c in d["close_items"]])
        self.assertTrue(all(c["key"] in written for c in d["close_items"]))
        # second review, finding 11: a task the manifest records but the epic read doesn't show is never dropped
        missing = next(i for i in tracker if i["status"] != "done")
        mt = next(t for t in base["tasks"] if t["key"] == missing["key"])
        n3 = copy.deepcopy(n2)
        n3["tasks"] = [t for t in n3["tasks"] if t["id"] != mt["id"]]
        for t in n3["tasks"]:
            t["depends_on"] = [x for x in t["depends_on"] if x["task"] != mt["id"]]
        for ph in n3["phases"]:
            ph["task_ids"] = [x for x in ph["task_ids"] if x != mt["id"]]
        d3 = revise_diff.diff(base, n3, [i for i in tracker if i is not missing], ov, {"items": [{"key": i["key"]} for i in tracker]})
        self.assertNotIn(mt["id"], d3["dropped"])
        # ninth review, M1: it is closed, and listed missing for a project-wide find_by_key to confirm
        self.assertIn(mt["key"], d3["missing"])
        self.assertIn(mt["key"], [c["key"] for c in d3["close_items"]])
        self.assertFalse(revise_diff.diff(base, n2, tracker, ov)["ok"])  # no manifest: nothing is dropped


class ReadScope(unittest.TestCase):
    def test_limit_is_200_and_can_only_be_lowered(self):
        _p, ov = g1()
        self.assertTrue(create_steps.scope_decision(200, ov)["ok"])
        self.assertFalse(create_steps.scope_decision(201, ov)["ok"])
        self.assertEqual(create_steps.scope_decision(10, ov, requested=500)["limit"], 200)
        ov = copy.deepcopy(ov)
        ov["skills"]["tracker"]["read_scope_limit"] = 50
        self.assertFalse(create_steps.scope_decision(51, ov)["ok"])
        self.assertEqual(create_steps.scope_decision(5, ov, requested=20)["limit"], 20)



class ApprovedEdits(unittest.TestCase):
    """Review finding 3: an approved edit to a written task is written; an unapproved difference stops."""

    def edited(self):
        tr, plan, ov = created()
        new = copy.deepcopy(plan)
        new["version"] += 1
        t = next(x for x in new["tasks"] if x["id"] == "P1-T02")
        t["title"] = t["title"] + " (with an empty-file check)"
        return tr, new, ov, t

    def changed_keys(self, tr, new, ov):
        """Every key whose rendered text moved (a dependent's body names its dependency's title)."""
        m = {i["key"]: i["owned_hash"] for i in latest_manifest(tr, new["id"])["items"]}
        return {p["key"]: p["owned_hash"] for p in fake_planned(new, ov) if p["key"] in m and m[p["key"]] != p["owned_hash"]}

    def test_write_list_binds_the_update_in_its_phase(self):
        _tr, new, ov, t = self.edited()
        wl = render_proposal.write_list(new, ov, ["P1"], edits=["P1-T02"])
        ups = [w for w in wl["writes"] if w["kind"] == "update_item"]
        self.assertEqual([(w["key"], w["scope"]) for w in ups], [(t["key"], "phase:P1")])
        self.assertEqual(len(ups[0]["owned_hash"]), 64)
        with self.assertRaises(ValueError):
            render_proposal.write_list(new, ov, ["P0"], edits=["P1-T02"])

    def test_approved_edit_reaches_the_tracker_and_the_manifest(self):
        tr, new, ov, t = self.edited()
        ups = self.changed_keys(tr, new, ov)
        self.assertGreater(len(ups), 1)  # the edit moved a dependent's body too
        pf = run_create(tr, new, ov, PH, run="run-2", updates=ups)
        self.assertTrue(pf["ok"], pf)
        self.assertIn("update", [a["action"] for a in pf["actions"] if a["key"] == t["key"]])
        self.assertEqual(by_task(tr, "P1-T02")["title"], t["title"])
        planned = next(p for p in fake_planned(new, ov) if p["key"] == t["key"])
        w = next(i for i in latest_manifest(tr, new["id"])["items"] if i["key"] == t["key"])
        self.assertEqual(w["owned_hash"], planned["owned_hash"])
        again = run_create(tr, new, ov, PH, run="run-3", updates=ups)
        self.assertEqual([a["action"] for a in again["actions"] if a["key"] == t["key"]], ["skip"])

    def test_a_difference_the_write_list_does_not_name_stops(self):
        tr, new, ov, t = self.edited()
        before = by_task(tr, "P1-T02")["title"]
        pf = run_create(tr, new, ov, PH, run="run-2")
        self.assertFalse(pf["ok"])
        self.assertIn("no update for it", pf["stops"][0]["why"])
        self.assertEqual(by_task(tr, "P1-T02")["title"], before)

    def test_crash_between_update_and_manifest_is_adopted_on_resume(self):
        tr, new, ov, t = self.edited()
        ups = self.changed_keys(tr, new, ov)
        self.assertEqual(run_create(tr, new, ov, PH, run="run-2", updates=ups, crash_after_update=True)["crashed"],
                         "update")
        pf = run_create(tr, new, ov, PH, run="run-2", updates=ups)
        self.assertTrue(pf["ok"], pf)
        self.assertIn("adopt_update", [a["action"] for a in pf["actions"] if a["key"] == t["key"]])
        # without the approval, the same tracker text is drift
        pf2 = run_create(tr, new, ov, PH, run="run-4")
        self.assertTrue(pf2["ok"], pf2)  # the manifest now records the new text, so nothing differs

    def test_an_approved_update_never_overwrites_a_persons_edit(self):
        tr, new, ov, t = self.edited()
        ups = self.changed_keys(tr, new, ov)
        by_task(tr, "P1-T02")["title"] = "A person's own wording"
        pf = run_create(tr, new, ov, PH, run="run-2", updates=ups)
        self.assertFalse(pf["ok"])
        self.assertTrue(any(s["key"] == t["key"] and "drift" in s["why"] for s in pf["stops"]), pf["stops"])
        self.assertEqual(by_task(tr, "P1-T02")["title"], "A person's own wording")

    def test_an_update_writes_only_the_text_the_write_list_binds(self):
        """Second review, finding 6."""
        tr, new, ov, t = self.edited()
        ups = dict(self.changed_keys(tr, new, ov), **{t["key"]: "9" * 64})
        pf = run_create(tr, new, ov, PH, run="run-2", updates=ups)
        self.assertFalse(pf["ok"])
        self.assertTrue(any(s["key"] == t["key"] and "differs from the text the approved update binds" in s["why"]
                            for s in pf["stops"]), pf["stops"])
        self.assertNotEqual(by_task(tr, "P1-T02")["title"], t["title"])
        self.assertFalse(run_create(tr, new, ov, PH, run="run-3", updates=list(self.changed_keys(tr, new, ov)))["ok"])

    def test_finished_work_is_never_updated(self):
        """Second review, finding 5: the task was done between approval and create."""
        tr, new, ov, t = self.edited()
        ups = self.changed_keys(tr, new, ov)
        tr.close(by_task(tr, "P1-T02")["tracker_id"], "Done")
        before = by_task(tr, "P1-T02")["title"]
        pf = run_create(tr, new, ov, PH, run="run-2", updates=ups)
        self.assertFalse(pf["ok"])
        self.assertTrue(any(s["key"] == t["key"] and "finished work is not edited" in s["why"] for s in pf["stops"]),
                        pf["stops"])
        self.assertEqual(by_task(tr, "P1-T02")["title"], before)

    def test_adopted_tracker_text_is_recorded_not_stopped(self):
        """Second review, finding 8: a person's edit the plan adopts is recorded through adopt_update."""
        tr, plan, ov = created()
        by_task(tr, "P1-T02")["title"] = "Add the CSV export endpoint, as the team renamed it"
        new = copy.deepcopy(plan)
        new["version"] += 1
        next(x for x in new["tasks"] if x["id"] == "P1-T02")["title"] = "Add the CSV export endpoint, as the team renamed it"
        ups = self.changed_keys(tr, new, ov)
        self.assertFalse(run_create(tr, new, ov, PH, run="run-2")["ok"])  # without the bound update it is drift
        pf = run_create(tr, new, ov, PH, run="run-3", updates=ups)
        self.assertTrue(pf["ok"], pf)
        key = by_task(tr, "P1-T02")["key"]
        self.assertEqual([a["action"] for a in pf["actions"] if a["key"] == key], ["adopt_update"])


def fake_planned(plan, ov):
    from fake_tracker import planned_items
    return planned_items(plan, ov, PH)


class ManifestKeepsHistory(unittest.TestCase):
    """Third review, finding 7: a later manifest never forgets an item or something done once."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")
        self.tr = FakeTracker()
        self.assertTrue(run_create(self.tr, self.plan, self.ov, PH)["ok"])
        self.m = latest_manifest(self.tr, self.plan["id"])

    def next(self, items):
        return create_steps.make_manifest(self.m, items, self.plan["id"], "run-x", self.m["seq"] + 1, self.tr.clock, [])

    def test_carrying_items_forward_is_allowed(self):
        items = copy.deepcopy(self.m["items"])
        items[0]["close"] = {"reason": "not_planned", "state": "intent"}
        m2 = self.next(items)
        items = copy.deepcopy(m2["items"])
        items[0]["close"]["state"] = "closed"
        create_steps.make_manifest(m2, items, self.plan["id"], "run-x", m2["seq"] + 1, self.tr.clock, [])

    def test_dropping_or_moving_an_item_is_refused(self):
        with self.assertRaises(ValueError):
            self.next(self.m["items"][1:])
        items = copy.deepcopy(self.m["items"])
        items[0]["tracker_id"] = "999"
        with self.assertRaises(ValueError):
            self.next(items)

    def test_clearing_something_done_once_is_refused(self):
        base = copy.deepcopy(self.m["items"])
        base[0].update(blocked_set=True, split_comment=True, close={"reason": "not_planned", "state": "closed"})
        m2 = self.next(base)
        for change in (lambda i: i.pop("blocked_set"), lambda i: i.update(split_comment=False), lambda i: i.pop("close"),
                       lambda i: i.update(close={"reason": "not_planned", "state": "intent"}),
                       lambda i: i.update(close={"reason": "duplicate", "state": "closed"})):
            items = copy.deepcopy(m2["items"])
            change(items[0])
            with self.assertRaises(ValueError):
                create_steps.make_manifest(m2, items, self.plan["id"], "run-x", m2["seq"] + 1, self.tr.clock, [])


class ReliesOnRecheck(unittest.TestCase):
    """Third review, finding 9: a revise apply stops if any item the diff read moved since."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")
        self.tr = FakeTracker()
        self.assertTrue(run_create(self.tr, self.plan, self.ov, ["P0"])["ok"])
        self.refs = [{"key": i["key"], "tracker_id": i["tracker_id"], "updated_at": self.tr.updated_at(i["tracker_id"])}
                     for i in self.tr.items.values()]

    def test_nothing_moved_goes_ahead(self):
        self.assertTrue(run_create(self.tr, self.plan, self.ov, ["P1"], run="run-2", relies_on=self.refs)["ok"])

    def test_a_status_change_since_the_diff_stops(self):
        item = next(iter(self.tr.items.values()))
        item["category"] = "in_progress"
        pf = run_create(self.tr, self.plan, self.ov, ["P1"], run="run-2", relies_on=self.refs)
        self.assertFalse(pf["ok"])
        self.assertEqual([s["key"] for s in pf["stops"]], [item["key"]])
        self.assertIn("diff again", pf["stops"][0]["why"])
        self.assertFalse([a for a in pf["actions"] if a["action"] == "create"] and pf["ok"])

    def test_a_deleted_item_stops(self):
        tid = next(iter(self.tr.items))
        key = self.tr.items[tid]["key"]
        del self.tr.items[tid]
        pf = run_create(self.tr, self.plan, self.ov, ["P1"], run="run-2", relies_on=self.refs)
        self.assertFalse(pf["ok"])
        self.assertIn(key, [s["key"] for s in pf["stops"]])


if __name__ == "__main__":
    unittest.main()
