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
        self.assertEqual(r["steps"], [])
        self.assertEqual([s["key"] for s in r["skipped"]], [self.key(plan, "P1-T05")])
        self.assertNotIn("gw-closed:not_planned", by_task(tr, "P1-T05")["labels"])

    def test_close_refuses_unknown_reasons_and_unwritten_items(self):
        tr, plan, _ov = created()
        m = latest_manifest(tr, plan["id"])
        found = [{"key": i["key"], "tracker_id": i["tracker_id"], "status": "todo"} for i in m["items"]]
        self.assertFalse(create_steps.close_steps([{"key": self.key(plan, "P1-T05"), "reason": "abandoned"}], m, found)["ok"])
        self.assertFalse(create_steps.close_steps([{"key": self.key(plan, "P2-T01"), "reason": "not_planned"}], m, found)["ok"])

    def test_write_list_close_sequence(self):
        plan, ov = g1()
        k = self.key(plan, "P1-T05")
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


if __name__ == "__main__":
    unittest.main()
