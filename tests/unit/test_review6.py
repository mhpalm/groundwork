# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Sixth review: closes that landed before a crash, items a person finished after approval, link writes
that landed before a crash, blocked state cleared and set again, and schema-checked manifests."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
sys.path.insert(0, os.path.dirname(__file__))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import create_steps  # noqa: E402
import render_proposal  # noqa: E402
import retire  # noqa: E402
import revise_diff  # noqa: E402
from fake_tracker import FakeTracker, WriteFailed, latest_manifest, retire_items, run_close, run_create, run_retire  # noqa: E402
from test_review5 import tracker_report  # noqa: E402

PH = ["P0", "P1"]


def created():
    plan, ov, _e = fresh("G1")
    tr = FakeTracker()
    assert run_create(tr, plan, ov, PH)["ok"]
    return tr, plan, ov


def item(tr, tid):
    return next(i for i in tr.items.values() if i["key"].endswith(":" + tid))


def written(tr, plan, tid):
    return next(i for i in latest_manifest(tr, plan["id"])["items"] if i["key"].endswith(":" + tid))


def close_wl(keys):
    return {"plan_version": 1, "writes": [{"no": n, "kind": "close_item", "key": k, "reason": "not_planned"}
                                          for n, k in enumerate(keys, 1)]}


class CloseOutcomesAreRecorded(unittest.TestCase):
    """M1 and M2: the completion check can always finish."""

    def test_a_transition_that_landed_before_a_crash_is_recorded_on_resume(self):
        tr, plan, ov = created()
        k = item(tr, "P1-T05")["key"]
        run_close(tr, plan, ov, [{"key": k, "reason": "not_planned"}], crash_after="transition")
        self.assertEqual(written(tr, plan, "P1-T05")["close"]["state"], "intent")
        self.assertEqual(len(create_steps.unfinished(close_wl([k]), latest_manifest(tr, plan["id"]))), 1)
        before = copy.deepcopy(item(tr, "P1-T05"))
        r = run_close(tr, plan, ov, [{"key": k, "reason": "not_planned"}])
        self.assertTrue(r["ok"])
        self.assertFalse([s for s in r["steps"] if s["step"] in ("add_label", "transition")])  # nothing written again
        self.assertEqual(item(tr, "P1-T05"), before)
        self.assertEqual(written(tr, plan, "P1-T05")["close"], {"reason": "not_planned", "state": "closed"})
        self.assertEqual(create_steps.unfinished(close_wl([k]), latest_manifest(tr, plan["id"])), [])

    def test_an_item_a_person_finished_after_approval_is_recorded_as_finished(self):
        tr, plan, ov = created()
        k = item(tr, "P1-T05")["key"]
        tr.close(item(tr, "P1-T05")["tracker_id"], "Done")
        self.assertTrue(run_close(tr, plan, ov, [{"key": k, "reason": "not_planned"}])["ok"])
        self.assertEqual(written(tr, plan, "P1-T05")["close"]["state"], "finished")
        self.assertEqual(create_steps.unfinished(close_wl([k]), latest_manifest(tr, plan["id"])), [])
        self.assertNotIn("gw-closed:not_planned", item(tr, "P1-T05")["labels"])

    def test_a_retire_finishes_when_a_person_closed_an_item_after_approval(self):
        tr, plan, ov = created()
        approved = retire.plan_retire(retire_items(tr, plan, ov, "VOL-1"), {})
        victim = approved["closes"][0]["key"]
        tr.close(next(i for i in tr.items.values() if i["key"] == victim)["tracker_id"], "Done")
        self.assertTrue(run_retire(tr, plan, ov, approved, "a" * 64)["ok"])
        wl = retire.write_list(plan, ov, approved)
        self.assertEqual(create_steps.unfinished(wl, latest_manifest(tr, plan["id"])), [])
        w = next(i for i in latest_manifest(tr, plan["id"])["items"] if i["key"] == victim)
        self.assertEqual(w["close"]["state"], "finished")

    def test_a_retire_resumes_after_a_crash_between_transition_and_record(self):
        tr, plan, ov = created()
        approved = retire.plan_retire(retire_items(tr, plan, ov, "VOL-1"), {})
        keys = [c["key"] for c in approved["closes"]]
        run_retire(tr, plan, ov, approved, "a" * 64, crash_after="intent")
        run_close(tr, plan, ov, approved["closes"], crash_after="transition")
        self.assertTrue(run_retire(tr, plan, ov, approved, "a" * 64, resuming=(plan["version"], "a" * 64))["ok"])
        m = latest_manifest(tr, plan["id"])
        self.assertTrue(all(i["close"]["state"] == "closed" for i in m["items"] if i["key"] in keys))
        self.assertEqual(create_steps.unfinished(retire.write_list(plan, ov, approved), m), [])


class LinkWritesReadTheTrackerFirst(unittest.TestCase):
    """m4: a link that landed before the session ended is recorded, never written twice."""

    def test_a_crash_after_link_writes_leaves_no_duplicate_links(self):
        plan, ov, _e = fresh("G1")
        for fail_at in range(2, 40):
            with self.subTest(fail_at=fail_at):
                tr = FakeTracker()
                tr.fail_at = fail_at
                try:
                    first = run_create(tr, plan, ov, PH)
                except WriteFailed:
                    first = {"ok": False}
                tr.fail_at = None
                if not first["ok"]:
                    self.assertTrue(run_create(tr, plan, ov, PH, run="run-2")["ok"])
                for i in tr.items.values():
                    self.assertEqual(len(i["links"]), len(set(i["links"])), i["key"])


class BlockedStateMovesWithThePlan(unittest.TestCase):
    """M4: a cleared block is recorded and checked, and a wait added back blocks the task again."""

    def setUp(self):
        self.tr, self.plan, self.ov = created()
        self.t = item(self.tr, "P1-T03")
        self.waits = copy.deepcopy(next(x for x in self.plan["tasks"] if x["id"] == "P1-T03")["waits_on"])
        self.assertTrue(self.waits and self.t["blocked"])

    def revise(self, base, waits):
        new = copy.deepcopy(base)
        new["version"] += 1
        next(x for x in new["tasks"] if x["id"] == "P1-T03")["waits_on"] = waits
        report, m = tracker_report(self.tr, base, self.ov)
        d = revise_diff.diff(base, new, report, self.ov, m)
        self.assertTrue(d["ok"], d)
        wl = render_proposal.write_list(new, self.ov, ["P1"], None, None, d["edits"], d["relinks"], d["unblocks"])
        self.assertEqual(check_hashes.rebuilt_write_list_problems(new, self.ov, wl), [])
        return new, d, wl

    def apply(self, plan, wl, run):
        ups = {w["key"]: w["owned_hash"] for w in wl["writes"] if w["kind"] == "update_item"}
        self.assertTrue(run_create(self.tr, plan, self.ov, ["P1"], run=run, updates=ups, write_list=wl)["ok"])

    def test_clear_then_block_again_is_recorded_each_time(self):
        v2, d, wl = self.revise(self.plan, [])
        self.assertEqual(d["unblocks"], ["P1-T03"])
        self.apply(v2, wl, "run-2")
        self.assertFalse(self.t["blocked"])
        self.assertEqual(create_steps.blocked_state(written(self.tr, v2, "P1-T03")), "cleared")
        self.assertEqual(create_steps.unfinished(wl, latest_manifest(self.tr, v2["id"])), [])
        v3, d, wl = self.revise(v2, self.waits)
        self.assertEqual(d["unblocks"], [])
        k = self.t["key"]
        self.assertIn(k, [w["key"] for w in wl["writes"] if w["kind"] == "set_blocked"])
        self.assertIn(k, [x["key"] for x in create_steps.unfinished(wl, latest_manifest(self.tr, v3["id"]))
                          if x["kind"] == "set_blocked"])
        self.apply(v3, wl, "run-3")
        self.assertTrue(self.t["blocked"])
        w = written(self.tr, v3, "P1-T03")
        self.assertEqual(w["blocked_changes"], [{"state": "cleared", "plan_version": 2}, {"state": "set", "plan_version": 3}])
        self.assertEqual(create_steps.unfinished(wl, latest_manifest(self.tr, v3["id"])), [])

    def test_a_skipped_clear_is_listed_as_unfinished(self):
        _v2, _d, wl = self.revise(self.plan, [])
        self.assertIn("clear_blocked", [x["kind"] for x in create_steps.unfinished(wl, latest_manifest(self.tr, self.plan["id"]))])

    def test_a_block_a_person_cleared_is_still_never_reapplied(self):
        self.tr.set_blocked(self.t["tracker_id"], False)
        self.assertTrue(run_create(self.tr, self.plan, self.ov, PH, run="run-2")["ok"])
        self.assertFalse(self.t["blocked"])

    def test_the_blocked_history_is_append_only(self):
        base = {"key": "k", "tracker_id": "T", "owned_hash": "a" * 64, "links": [], "not_ready": False, "blocked_set": True}
        c1 = create_steps.blocked_record(base, "cleared", 2)
        self.assertEqual(create_steps.blocked_record(c1, "cleared", 3), c1)
        s1 = create_steps.blocked_record(c1, "set", 3)
        self.assertIsNone(create_steps.blocked_changes_problems(c1, s1))
        for name, now in (("rewritten", dict(s1, blocked_changes=[{"state": "cleared", "plan_version": 1}])),
                          ("dropped", dict(base)),
                          ("not alternating", dict(base, blocked_changes=[{"state": "set", "plan_version": 2}])),
                          ("backwards", dict(base, blocked_changes=[{"state": "cleared", "plan_version": 3},
                                                                    {"state": "set", "plan_version": 3}])),
                          ("never applied", dict(base, blocked_set=False, blocked_changes=[{"state": "cleared", "plan_version": 2}]))):
            with self.subTest(name):
                self.assertIsNotNone(create_steps.blocked_changes_problems(s1 if name in ("rewritten", "dropped") else {}, now))
        self.assertEqual(create_steps.blocked_record({"key": "n", "blocked_set": False}, "set", 4)["blocked_set"], True)


class PlannedIsBoundToTheWriteList(unittest.TestCase):
    """M3: preflight refuses a PLANNED the approved write list doesn't create, with exactly its text."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")
        self.wl = render_proposal.write_list(self.plan, self.ov, ["P0"])
        self.creates = {w["key"]: w["owned_hash"] for w in self.wl["writes"] if w["kind"] == "create_item"}
        self.planned = [{"key": k, "phase": "P0", "owned_hash": h, "points": 1, "depends_on": [], "waits": False}
                        for k, h in self.creates.items()]

    def run_pf(self, planned):
        return create_steps.preflight(planned, [], None, ["P0"], {}, None, self.creates)

    def test_the_planned_items_of_the_write_list_pass(self):
        self.assertTrue(self.run_pf(self.planned)["ok"])

    def test_an_extra_a_changed_or_a_missing_item_stops(self):
        extra = self.planned + [dict(self.planned[0], key=f"gw:{self.plan['id']}:P0-T99")]
        changed = [dict(self.planned[0], owned_hash="1" * 64)] + self.planned[1:]
        for name, pl in (("extra", extra), ("changed", changed), ("missing", self.planned[1:])):
            with self.subTest(name):
                out = self.run_pf(pl)
                self.assertFalse(out["ok"])
                self.assertEqual(len(out["stops"]), 1)

    def test_every_create_binds_the_rendered_text(self):
        for w in self.wl["writes"]:
            if w["kind"] == "create_item":
                t = next(x for x in self.plan["tasks"] if x["key"] == w["key"])
                fields = {"title": t["title"], "body_owned": render_proposal.task_body(self.plan, self.ov, t),
                          "role_key": t["role_key"], "phase": t["phase"], "key": t["key"]}
                self.assertEqual(w["owned_hash"], check_hashes.owned_hash(fields))


class GuardsNoTestCovered(unittest.TestCase):
    """m3: guards the sixth review found untested."""

    def test_done_lists_not_ready_parent_and_status_file_writes(self):
        m = {"items": [{"key": "k", "tracker_id": "T", "owned_hash": "a" * 64, "links": [], "not_ready": True}]}
        wl = {"plan_version": 1, "writes": [{"no": 1, "kind": "clear_not_ready", "key": "k"},
                                            {"no": 2, "kind": "link_parent", "key": "k", "to": "E"},
                                            {"no": 3, "kind": "status_put"}]}
        self.assertEqual([x["no"] for x in create_steps.unfinished(wl, m)], [1, 2, 3])
        m["items"][0].update(not_ready=False, links=[{"type": "parent", "to_key": "E"}])
        m["status_file"] = {"state": "recorded"}
        self.assertEqual(create_steps.unfinished(wl, m), [])

    def test_a_relink_must_match_the_plan(self):
        plan, ov, _e = fresh("G1")
        t = next(x for x in plan["tasks"] if x["depends_on"])
        dep = t["depends_on"][0]["task"]
        for bad in ({"task": t["id"], "added": ["P9-T99"], "removed": []},
                    {"task": t["id"], "added": [], "removed": [dep]},
                    {"task": "P9-T99", "added": [], "removed": []}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                render_proposal.write_list(plan, ov, [], relinks=[bad])

    def test_relies_on_stops_when_the_item_moved_to_another_tracker_id(self):
        f = [{"key": "k", "tracker_id": "T2", "owned_hash": "a" * 64, "updated_at": "2026-11-15T10:00:00Z", "status": "todo"}]
        out = create_steps.preflight([], f, None, [], {}, [{"key": "k", "tracker_id": "T1", "updated_at": "2026-11-15T10:00:00Z"}])
        self.assertFalse(out["ok"])
        out = create_steps.preflight([], f, None, [], {}, [{"key": "k", "tracker_id": "T2", "updated_at": "2026-11-15T10:00:00Z"}])
        self.assertTrue(out["ok"])

    def test_make_manifest_refuses_a_rewritten_blocked_history(self):
        pid = fresh("G1")[0]["id"]
        it = {"key": "k", "tracker_id": "T", "owned_hash": "a" * 64, "links": [], "not_ready": False, "blocked_set": True,
              "blocked_changes": [{"state": "cleared", "plan_version": 2}]}
        m1 = create_steps.make_manifest(None, [it], pid, "r", 1, create_steps.ts("2026-11-15T10:00:00Z"), [])
        with self.assertRaises(ValueError):
            create_steps.make_manifest(m1, [dict(it, blocked_changes=[])], pid, "r", 2, create_steps.ts("2026-11-15T10:01:00Z"), [])

    def test_the_preflight_cli_binds_the_write_list_creates(self):
        import io, json, tempfile
        from contextlib import redirect_stdout
        plan, ov, _e = fresh("G1")
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)
        wl = render_proposal.write_list(plan, ov, ["P0"])
        pl = [{"key": w["key"], "phase": "P0", "owned_hash": w["owned_hash"], "points": 1, "depends_on": [], "waits": False}
              for w in wl["writes"] if w["kind"] == "create_item"]
        json.dump(wl, open(P("wl.json"), "w"))
        json.dump([], open(P("found.json"), "w"))
        for name, planned, rc in (("faithful", pl, 0), ("changed", [dict(pl[0], owned_hash="1" * 64)] + pl[1:], 1)):
            json.dump(planned, open(P("planned.json"), "w"))
            with self.subTest(name), redirect_stdout(io.StringIO()):
                self.assertEqual(create_steps.main(["preflight", P("planned.json"), P("found.json"), "--phases", "P0",
                                                    "--plan-id", plan["id"], "--manifests", "--write-list", P("wl.json")]), rc)


class ManifestsAreSchemaChecked(unittest.TestCase):
    """M5: make_manifest refuses a manifest its schema refuses."""

    def test_a_malformed_item_is_refused(self):
        pid = fresh("G1")[0]["id"]
        now = create_steps.ts("2026-11-15T10:00:00Z")
        for bad in ({"key": "k", "tracker_id": "T", "links": [], "not_ready": True},
                    {"key": "k", "tracker_id": "T", "owned_hash": "a" * 64, "links": [], "not_ready": True,
                     "close": {"reason": "not_planned", "state": "gone"}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                create_steps.make_manifest(None, [bad], pid, "r", 1, now, [])


if __name__ == "__main__":
    unittest.main()
