# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist
"""Golden projects G2 to G9: each expected plan passes its assertions, and the
behaviour each project exists for is checked against the core's scripts."""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import GOLDEN, NOW, fresh  # noqa: E402
import check_identity  # noqa: E402
import gw_yaml  # noqa: E402
import revise_diff  # noqa: E402
import run_bundle  # noqa: E402
import validate_plan  # noqa: E402
from assert_golden import assert_plan  # noqa: E402
from fake_tracker import FakeTracker, run_create  # noqa: E402


def fixture(project, name):
    with open(os.path.join(GOLDEN, project, "fixtures", name), encoding="utf-8") as f:
        return json.load(f)


def blockers(plan, overlay, evidence, offered=None):
    return validate_plan.check(plan, overlay, evidence, offered_arg=offered, now=NOW).blocking()


class AllGoldens(unittest.TestCase):
    def test_expected_plans_pass_their_assertions(self):
        for g in sorted(os.listdir(GOLDEN)):
            with self.subTest(golden=g):
                plan, _o, _e = fresh(g)
                self.assertEqual(assert_plan(g, plan), [])


class G2TooBig(unittest.TestCase):
    def test_outline_phase_cannot_be_offered(self):
        plan, ov, ev = fresh("G2")
        self.assertTrue(any(f["check"] == "OFFER" for f in blockers(plan, ov, ev, ["P4"])))

    def test_outline_phase_with_tasks_is_refused(self):
        plan, ov, ev = fresh("G2")
        p4 = next(p for p in plan["phases"] if p["id"] == "P4")
        p4["task_ids"] = ["P3-T05"]
        self.assertTrue(any(f["check"] == "PHASE" for f in validate_plan.check(plan, ov, ev, now=NOW).items))


class G3NonDev(unittest.TestCase):
    def test_production_change_breaks_the_non_dev_assertion(self):
        plan, _o, _e = fresh("G3")
        plan["tasks"][3]["production_change"] = True
        self.assertTrue(assert_plan("G3", plan))


class G4ReducedCoverage(unittest.TestCase):
    def test_task_on_uninspected_system_must_wait_on_a_question(self):
        plan, ov, ev = fresh("G4")
        plan["open_questions"] = []
        hits = [f for f in blockers(plan, ov, ev) if f["check"] == "GR-18"]
        self.assertEqual([f["target"] for f in hits], ["P3-T04"])

    def test_missing_coverage_row_is_a_blocker(self):
        plan, ov, ev = fresh("G4")
        plan["coverage"] = [c for c in plan["coverage"] if c["system"] != "mailing-list"]
        self.assertTrue(any(f["check"] == "GR-18" and f["target"] is None for f in blockers(plan, ov, ev, ["P0"])))


class G5Ambiguity(unittest.TestCase):
    def test_answering_the_question_frees_the_tasks(self):
        plan, ov, ev = fresh("G5")
        q = plan["open_questions"][0]
        q.update(status="answered", answer="The coordinator lead.", answered_by="acct-program-director", at="2026-11-14T20:00:00Z")
        self.assertFalse([f for f in blockers(plan, ov, ev) if f["check"] == "GR-04"])


class G6Revise(unittest.TestCase):
    def setUp(self):
        self.new, self.ov, self.ev = fresh("G6")
        self.base = fixture("G6", "base-plan.json")
        self.tracker = fixture("G6", "tracker.json")
        self.want = fixture("G6", "expected-diff.json")

    def diff(self, new=None, tracker=None):
        return revise_diff.diff(self.base, new or self.new, tracker or self.tracker, self.ov)

    def test_diff_shape(self):
        d = self.diff()
        self.assertTrue(d["ok"], d["refused"])
        self.assertEqual(d["added"], self.want["added"])
        self.assertEqual(d["close"], self.want["close"])
        self.assertEqual([x["task"] for x in d["drift"]], self.want["drift"])
        self.assertEqual({x["task"]: {"added": x["added"], "removed": x["removed"]} for x in d["deps_changed"]},
                         self.want["deps_changed"])
        changed = {x["task"] for x in d["changed"]}
        self.assertTrue(set(self.want["changed_include"]) <= changed)
        self.assertFalse(set(self.want["changed_exclude"]) & changed)
        self.assertIn("P1-T04", {r["key"].split(":")[-1] for r in d["relies_on"]})

    def test_editing_done_work_is_refused(self):
        new = copy.deepcopy(self.new)
        next(t for t in new["tasks"] if t["id"] == "P1-T01")["title"] = "Add the sign-ups CSV serializer with empty events"
        self.assertFalse(self.diff(new)["ok"])

    def test_ignoring_a_tracker_edit_is_refused(self):
        new = copy.deepcopy(self.new)
        base_title = next(t for t in self.base["tasks"] if t["id"] == "P1-T04")["title"]
        next(t for t in new["tasks"] if t["id"] == "P1-T04")["title"] = base_title
        d = self.diff(new)
        self.assertFalse(d["ok"])
        self.assertEqual([r["task"] for r in d["refused"]], ["P1-T04"])

    def test_removing_done_work_is_refused(self):
        new = copy.deepcopy(self.new)
        new["tasks"] = [t for t in new["tasks"] if t["id"] != "P0-T02"]
        self.assertFalse(self.diff(new)["ok"])

    def test_revised_plan_still_validates(self):
        self.assertEqual(blockers(self.new, self.ov, self.ev), [])


class G8CrossOrg(unittest.TestCase):
    def setUp(self):
        self.ov = gw_yaml.load(os.path.join(GOLDEN, "G8", "overlay", "overlay.yaml"))
        self.want = fixture("G8", "expected.json")

    def test_identity_checks(self):
        for name in ("connect-ok.json", "connect-wrong-org.json", "connect-wrong-tracker.json"):
            with self.subTest(fixture=name):
                out = check_identity.check(self.ov, fixture("G8", name))
                stopped = [f"{r['skill']}/{r['instance']}" for r in out["results"] if r["decision"] == "stop"]
                self.assertEqual(out["run"], self.want[name]["run"])
                self.assertEqual(stopped, self.want[name]["stopped"])

    def test_missing_report_stops_that_system(self):
        out = check_identity.check(self.ov, fixture("G8", "connect-ok.json")[1:])
        self.assertEqual([r["decision"] for r in out["results"]], ["stop", "proceed"])

    def test_foreign_bundle_is_refused(self):
        out = run_bundle.do_import(fixture("G8", "foreign-bundle.json"), self.ov, tempfile.mkdtemp())
        self.assertFalse(out["ok"])
        self.assertTrue(any("CR-12" in p for p in out["problems"]))

    def test_own_bundle_round_trips_and_tampering_is_refused(self):
        src, dst = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            shutil.copy(os.path.join(GOLDEN, "G8", "expected", "plan.json"), os.path.join(src, "plan.json"))
            shutil.copytree(os.path.join(GOLDEN, "G8", "evidence"), os.path.join(src, "evidence"))
            b = run_bundle.export(src)
            bad = copy.deepcopy(b)
            bad["files"][0]["content"] += " "
            self.assertFalse(run_bundle.do_import(bad, self.ov, dst)["ok"])
            evil = copy.deepcopy(b)
            evil["files"][0]["path"] = "../outside.json"
            self.assertFalse(run_bundle.do_import(evil, self.ov, dst)["ok"])
            out = run_bundle.do_import(b, self.ov, dst)
            self.assertTrue(out["ok"], out)
            self.assertFalse(run_bundle.do_import(b, self.ov, dst)["ok"])  # never imports over an existing run
        finally:
            shutil.rmtree(src)
            shutil.rmtree(dst)

    def test_foreign_evidence_is_flagged(self):
        plan, ov, ev = fresh("G8")
        ev.append(fixture("G8", "foreign-evidence.json"))
        self.assertTrue(any(f["check"] == "CR-12" for f in blockers(plan, ov, ev)))


class G9LiveBaseline(unittest.TestCase):
    def test_release_on_a_worked_baseline(self):
        plan, ov, _e = fresh("G9")
        sc = fixture("G9", "scenario.json")
        key = lambda tid: f"gw:{plan['id']}:{tid}"
        tr = FakeTracker()
        self.assertTrue(run_create(tr, plan, ov, sc["written_phases"])["ok"])
        by_key = {i["key"]: i for i in tr.items.values()}
        h = sc["human_changes"]
        for tid, status in h["status"].items():
            by_key[key(tid)]["status"] = status
        for tid, nums in h["ticked_steps"].items():
            for n in nums:
                by_key[key(tid)]["body"] = by_key[key(tid)]["body"].replace(f"- [ ] {n}. ", f"- [x] {n}. ", 1)
        for tid, note in h["notes_outside_markers"].items():
            by_key[key(tid)]["body"] += f"\n\n{note}\n"
        for tid, pts in h["points"].items():
            by_key[key(tid)]["points"] = pts
        for tid in h["deleted"]:
            del tr.items[by_key[key(tid)]["tracker_id"]]

        exp = sc["expected_first_release"]
        pf = run_create(tr, plan, ov, [sc["release_phase"]], run="run-2")
        self.assertEqual(pf["ok"], exp["ok"])
        self.assertEqual([s["key"] for s in pf["stops"]], [key(t) for t in exp["stops"]])
        self.assertTrue({key(t) for t in exp["warnings_include"]} <= {w["key"] for w in pf["warnings"]})
        self.assertFalse([x for x in pf["stops"] + pf["warnings"] if "drift" in x["why"]])
        self.assertEqual([a["key"] for a in pf["actions"] if a["action"] == "comment_split"], [key(t) for t in exp["comment_split"]])

        rp = sc["revise_then_release"]
        for tid, change in rp["repoint"].items():
            t = next(t for t in plan["tasks"] if t["id"] == tid)
            for d in t["depends_on"]:
                if d["task"] == change["from"]:
                    d["task"] = change["to"]
        want = rp["expected"]
        for attempt in range(2):  # the second run must not repeat the split comment
            pf = run_create(tr, plan, ov, [sc["release_phase"]], run=f"run-{3 + attempt}")
            self.assertEqual(pf["ok"], want["ok"], pf)
            by_key = {i["key"]: i for i in tr.items.values()}
            for tid, pts in want["points_kept"].items():
                self.assertEqual(by_key[key(tid)]["points"], pts)
            for tid, n in want["split_comments"].items():
                self.assertEqual(len(by_key[key(tid)].get("comments", [])), n)
            self.assertNotIn(key("P1-T05"), by_key)
            p2 = [t["id"] for t in plan["tasks"] if t["phase"] == want["created_phase"]]
            self.assertTrue(all(key(t) in by_key and not by_key[key(t)]["not_ready"] for t in p2))


if __name__ == "__main__":
    unittest.main()
