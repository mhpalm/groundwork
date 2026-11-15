# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Sandbox run 2 findings: the review an approval binds, the freeze's epic text, the snapshot,
and the approach basis wording."""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import check_hashes  # noqa: E402
import create_steps  # noqa: E402
import gw_hash  # noqa: E402
import render_proposal  # noqa: E402
from fake_tracker import FakeTracker, latest_manifest, run_create  # noqa: E402

PH = ["P0", "P1"]
T = create_steps.ts("2026-11-15T10:00:00Z")


def raw_review(plan):
    """The reviewer's own file for the plan's recorded review: the same findings, every one still open."""
    rec = plan["review"]["reviewer"]
    return {"schema_version": "1.0", "view_hash": rec["view_hash"], "surface": rec["surface"], "model": rec["model"],
            "mode": rec["mode"], "findings": [dict(f, resolution="open") for f in rec["findings"]],
            "not_performed": rec["not_performed"]}


def with_minor(plan):
    p = copy.deepcopy(plan)
    p["review"] = dict(p.get("review") or {})
    p["review"]["reviewer"] = {"surface": "claude-code-cloud", "model": "m", "view_hash": "1" * 64, "independent": True,
                               "mode": "subagent", "not_performed": [],
                               "findings": [{"id": "R-1", "check": "GR-06", "severity": "minor", "target": "P1-T01",
                                             "what": "wording", "evidence_ids": [], "suggested_fix": "reword",
                                             "resolution": "accepted_minor"}]}
    return p


class RecordedReview(unittest.TestCase):
    """Finding 23: approvals bind the review as the plan records it, resolutions included."""

    def setUp(self):
        self.plan = with_minor(fresh("G1")[0])
        self.raw = raw_review(self.plan)

    def test_resolutions_come_from_the_plan(self):
        out = check_hashes.recorded_review(self.plan, self.raw)
        self.assertEqual([f["resolution"] for f in out["findings"]], ["accepted_minor"])
        self.assertTrue(check_hashes._same_review(out, self.plan["review"]["reviewer"]))
        self.assertNotEqual(gw_hash.review_hash(out), gw_hash.review_hash(self.raw))

    def test_another_view_is_refused(self):
        self.raw["view_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            check_hashes.recorded_review(self.plan, self.raw)

    def test_a_changed_finding_is_refused(self):
        self.raw["findings"][0]["what"] = "something else"
        with self.assertRaises(ValueError):
            check_hashes.recorded_review(self.plan, self.raw)

    def test_cli_prints_the_hash_and_writes_the_file(self):
        d = tempfile.mkdtemp()
        P = lambda n: os.path.join(d, n)
        for n, v in (("plan.json", self.plan), ("raw.json", self.raw)):
            with open(P(n), "w") as f:
                json.dump(v, f)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check_hashes.main(["recorded-review", P("plan.json"), "--review", P("raw.json"), "--out", P("rec.json")])
        self.assertEqual(rc, 0)
        with open(P("rec.json")) as f:
            self.assertEqual(buf.getvalue().strip(), gw_hash.review_hash(json.load(f)))


class FreezeUpdatesTheEpic(unittest.TestCase):
    """Finding 27: the epic stops saying "planned, not released" once its phases are released."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")
        self.wl = render_proposal.write_list(self.plan, self.ov, PH)

    def test_the_write_list_binds_the_released_text(self):
        ws = [w for w in self.wl["writes"] if w["kind"] == "update_epic"]
        self.assertEqual(len(ws), 1)
        text = render_proposal.epic_description(self.plan, self.ov, released=PH)
        table = text.split("**Access list**")[0]
        self.assertIn("| P0 | Setup | released |", table)
        self.assertIn("| P2 | UAT and release prep | planned, not released |", table)  # not offered
        fields = {"title": self.plan["epic"]["title"], "body_owned": text, "role_key": None, "phase": None,
                  "key": self.plan["epic"]["key"]}
        self.assertEqual(ws[0]["owned_hash"], check_hashes.owned_hash(fields))
        self.assertEqual(ws[0]["scope"], "plan")

    def test_a_partial_offer_keeps_the_rest_unreleased(self):
        wl = render_proposal.write_list(self.plan, self.ov, ["P0"])
        w = next(w for w in wl["writes"] if w["kind"] == "update_epic")
        self.assertEqual(w["released"], ["P0"])

    def test_done_waits_for_it_and_the_record_is_kept(self):
        wl = {"plan_version": 1, "writes": [{"no": 1, "kind": "update_epic", "owned_hash": "a" * 64}]}
        pid = self.plan["id"]
        m1 = create_steps.make_manifest(None, [], pid, "r", 1, T, [])
        self.assertEqual(len(create_steps.unfinished(wl, m1)), 1)
        m2 = create_steps.make_manifest(m1, [], pid, "r", 2, T, [], epic_owned_hash="a" * 64)
        self.assertEqual(create_steps.unfinished(wl, m2), [])
        m3 = create_steps.make_manifest(m2, [], pid, "r", 3, T, [])
        self.assertEqual(m3["epic_owned_hash"], "a" * 64)  # carried forward
        bad = dict(m3)
        bad.pop("epic_owned_hash")
        self.assertTrue(create_steps.successor_problems(m2, bad))

    def test_a_create_writes_and_records_it(self):
        tr = FakeTracker()
        self.assertTrue(run_create(tr, self.plan, self.ov, PH, write_list=self.wl)["ok"])
        want = next(w for w in self.wl["writes"] if w["kind"] == "update_epic")["owned_hash"]
        self.assertEqual(tr.epic_owned["VOL-1"], want)
        self.assertEqual(create_steps.unfinished(self.wl, latest_manifest(tr, self.plan["id"])), [])


class Snapshot(unittest.TestCase):
    """Finding 26: the snapshot is rebuilt from the plan of record and the manifest it follows."""

    def setUp(self):
        self.plan, self.ov, _e = fresh("G1")
        self.tr = FakeTracker()
        self.assertTrue(run_create(self.tr, self.plan, self.ov, PH)["ok"])
        self.m = latest_manifest(self.tr, self.plan["id"])

    def test_it_lists_the_phase_items(self):
        s = create_steps.snapshot(self.plan, self.m, "P1", T)
        keys = sorted(t["key"] for t in self.plan["tasks"] if t["phase"] == "P1")
        self.assertEqual([i["key"] for i in s["items"]], keys)
        self.assertEqual(s["manifest"], {"seq": self.m["seq"], "hash": self.m["hash"]})
        self.assertEqual(s["phase_hash"], gw_hash.phase_hash(self.plan, "P1"))
        self.assertEqual(s["name"], f"{self.plan['id']}-snapshot-{self.m['seq']}-2026-11-15")

    def test_it_refuses_a_phase_not_yet_ready(self):
        m = copy.deepcopy(self.m)
        m["items"][0]["not_ready"] = True
        ph = next(t["phase"] for t in self.plan["tasks"] if t["key"] == m["items"][0]["key"])
        with self.assertRaises(ValueError):
            create_steps.snapshot(self.plan, m, ph, T)

    def test_it_refuses_a_missing_item(self):
        m = copy.deepcopy(self.m)
        m["items"] = [i for i in m["items"] if not i["key"].endswith("P1-T01")]
        with self.assertRaises(ValueError):
            create_steps.snapshot(self.plan, m, "P1", T)


class BasisWording(unittest.TestCase):
    """Finding 19: a reason that ends with a period is not given a second one."""

    def test_no_double_period(self):
        plan, ov, _e = fresh("G1")
        if not plan.get("approach"):
            self.skipTest("G1 has no approach")
        p = copy.deepcopy(plan)
        o = p["approach"]["options"][0]
        o["evidence"], o["not_inspected_reason"] = [], "Nothing to inspect."
        text = render_proposal.proposal(p, ov, PH, render_proposal.write_list(p, ov, PH))
        self.assertIn("not inspected: Nothing to inspect.", text)
        self.assertNotIn("inspect..", text)


if __name__ == "__main__":
    unittest.main()
