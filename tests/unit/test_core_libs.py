# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import fresh  # noqa: E402
import gw_canon  # noqa: E402
import gw_hash  # noqa: E402
import gw_yaml  # noqa: E402


class Canonical(unittest.TestCase):
    def test_rfc8785_numbers(self):
        cases = {333333333.33333329: "333333333.3333333", 1e30: "1e+30", 4.5: "4.5", 2e-3: "0.002",
                 1e-27: "1e-27", -0.0: "0", 1e21: "1e+21", 1e20: "100000000000000000000", 5e-324: "5e-324"}
        for value, text in cases.items():
            self.assertEqual(gw_canon.canonicalize(value).decode(), text)

    def test_rfc8785_key_order_utf16(self):
        obj = {"\u20ac": "Euro", "\r": "CR", "\ufb33": "H", "1": "One", "\U0001f600": "e", "\u0080": "c", "\u00f6": "o"}
        self.assertEqual(gw_canon.canonicalize(obj).decode(),
                         '{"\\r":"CR","1":"One","\u0080":"c","\u00f6":"o","\u20ac":"Euro","\U0001f600":"e","\ufb33":"H"}')

    def test_rejects_unsafe(self):
        for bad in (float("nan"), 2 ** 60):
            with self.assertRaises(ValueError):
                gw_canon.canonicalize(bad)


class Yaml(unittest.TestCase):
    def test_round_trip(self):
        _p, overlay, _e = fresh("G1")
        self.assertEqual(gw_yaml.loads(gw_yaml.dumps(overlay)), overlay)

    def test_subset_errors(self):
        for bad in ("a: &x 1", "a:\n\tb: 1", "a: 1\na: 2", "a: [1, 2", "a: |\n  text"):
            with self.assertRaises(gw_yaml.YamlError):
                gw_yaml.loads(bad)

    def test_flow_and_comments(self):
        d = gw_yaml.loads("x: {a: 1, b: [p, 'q r']}  # note\ny:\n  - k: v\n    n: 2\n  - plain\n")
        self.assertEqual(d, {"x": {"a": 1, "b": ["p", "q r"]}, "y": [{"k": "v", "n": 2}, "plain"]})


class HashScope(unittest.TestCase):
    """phase_hash ignores state and bookkeeping, and changes with any task field."""

    def test_excluded_fields_leave_phase_hash_alone(self):
        plan, _o, _e = fresh("G1")
        before = gw_hash.phase_hashes(plan)
        p2 = copy.deepcopy(plan)
        p2["phases"][1]["state"] = "released"
        p2["status"] = "active"
        p2["version"] = 9
        p2["stamps"]["model"] = "other"
        p2["review"]["reviewer"] = None
        p2["history"].append({"version": 2, "at": "2026-11-15T00:00:00Z", "change": "x", "by": "y"})
        p2["coverage"][0]["inspected"].append("more")
        p2["approvals"].append("A-1")
        p2["epic"]["tracker_ref"] = "VOL-77"
        self.assertEqual(gw_hash.phase_hashes(p2), before)

    def test_every_task_field_changes_phase_hash(self):
        plan, _o, _e = fresh("G1")
        before = gw_hash.phase_hash(plan, "P1")
        task = next(t for t in plan["tasks"] if t["id"] == "P1-T02")
        for field in task:
            p2 = copy.deepcopy(plan)
            t2 = next(t for t in p2["tasks"] if t["id"] == "P1-T02")
            v = t2[field]
            if isinstance(v, bool):
                t2[field] = not v
            elif isinstance(v, (int, float)):
                t2[field] = v + 1
            elif isinstance(v, str):
                t2[field] = v + "x"
            elif isinstance(v, list):
                t2[field] = v + ["x"]
            elif isinstance(v, dict):
                t2[field] = dict(v, extra=1)
            else:
                t2[field] = "x"
            with self.subTest(field=field):
                self.assertNotEqual(gw_hash.phase_hash(p2, "P1"), before)

    def test_plan_hash_tracks_scope_and_questions(self):
        plan, _o, _e = fresh("G1")
        h = gw_hash.plan_hash(plan)
        p2 = copy.deepcopy(plan)
        p2["scope"]["out"].append("x")
        self.assertNotEqual(gw_hash.plan_hash(p2), h)

    def test_evidence_ids_are_stable(self):
        a = gw_hash.evidence_id("github", "gh", {"type": "file", "name": "r:x@main"})
        b = gw_hash.evidence_id("github", "gh", {"name": "r:x@main", "type": "file"})
        self.assertEqual(a, b)
        self.assertRegex(a, r"^ev-github-gh-[0-9a-f]{8}$")

    def test_reviewer_view_strips_drafting_reasoning(self):
        plan, _o, _e = fresh("G1")
        v = gw_hash.reviewer_view(plan)
        self.assertNotIn("history", v)
        self.assertTrue(all("origin" not in t for t in v["tasks"]))
        self.assertTrue(all(set(c) == {"id", "question", "answer"} for c in v["request"]["clarifications"]))


if __name__ == "__main__":
    unittest.main()


class PlanWithoutConnection(unittest.TestCase):
    """D-54: a run can plan through Proposal with no tracker connection."""

    def setUp(self):
        import gw_yaml
        root = os.path.join(os.path.dirname(__file__), "..", "..", "skills", "groundwork-core")
        self.prov = gw_yaml.load(os.path.join(root, "templates", "provisional-overlay.yaml"))
        self.g1 = gw_yaml.load(os.path.join(os.path.dirname(__file__), "..", "golden", "G1", "overlay", "overlay.yaml"))

    def test_provisional_overlay_is_valid_and_plan_only(self):
        import check_identity
        import validate_overlay
        self.assertEqual([p for p in validate_overlay.problems(self.prov) if not p.startswith("note")], [])
        self.assertEqual(check_identity.check(self.prov, [])["run"], "plan_only")

    def test_provisional_overlay_cannot_hold_approvers_or_instances(self):
        import copy
        import validate_overlay
        bad = copy.deepcopy(self.prov)
        bad["approval_gates"] = copy.deepcopy(self.g1["approval_gates"])
        bad["skills"]["tracker"]["instance"] = copy.deepcopy(self.g1["skills"]["tracker"]["instance"])
        probs = validate_overlay.problems(bad)
        self.assertTrue(any("no tracker instance" in p for p in probs))
        self.assertTrue(any("can never approve" in p for p in probs))
        real = copy.deepcopy(self.g1)
        real["id"] = "provisional"
        real["hash"] = None
        self.assertTrue(any("reserved" in p for p in validate_overlay.problems(real)))

    def test_unconnected_tracker_defers_but_wrong_project_stops(self):
        import check_identity
        gh = {"skill": "groundwork-system-github", "instance": "gh", "url": "https://github.com/example-org",
              "account": "dev", "identity": {"org": "example-org"}}
        out = check_identity.check(self.g1, [gh, {"skill": "groundwork-tracker-jira", "instance": "main", "status": "not_connected"}])
        self.assertEqual(out["run"], "plan_only")
        wrong = {"skill": "groundwork-tracker-jira", "instance": "main", "url": "https://example-org.atlassian.net",
                 "account": "dev", "identity": {"project": "OTHER"}}
        self.assertEqual(check_identity.check(self.g1, [gh, wrong])["run"], "stop")
        self.assertEqual(check_identity.check(self.g1, [gh])["run"], "stop")

    def test_provisional_has_no_write_list_or_approvals(self):
        import check_hashes
        import render_proposal
        with self.assertRaises(ValueError):
            render_proposal.write_list({}, self.prov, [])
        ok, probs, _ = check_hashes.verify_approvals({}, self.prov, {}, [], "", {}, {}, [], None, False)
        self.assertFalse(ok)

    def test_provisional_run_promotes_without_evidence_only(self):
        import json
        import shutil
        import tempfile
        import run_bundle
        src = tempfile.mkdtemp()
        plan = json.load(open(os.path.join(os.path.dirname(__file__), "..", "golden", "G1", "expected", "plan.json"), encoding="utf-8"))
        plan["overlay"] = {"id": "provisional", "version": 1, "hash": None}
        with open(os.path.join(src, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(plan, f)
        runs = tempfile.mkdtemp()
        out = run_bundle.do_import(run_bundle.export(src), self.g1, runs)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["rerun_from"], "discover")
        os.makedirs(os.path.join(src, "evidence"))
        with open(os.path.join(src, "evidence", "x.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "x"}, f)
        out = run_bundle.do_import(run_bundle.export(src), self.g1, tempfile.mkdtemp())
        self.assertFalse(out["ok"])
        shutil.rmtree(src)
        shutil.rmtree(runs)
