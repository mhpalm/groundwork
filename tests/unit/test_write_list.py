# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Write list: each offered phase gets its release container before its items (D-53)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from common import GOLDEN, gw_yaml  # noqa: E402
import render_proposal  # noqa: E402


class WriteList(unittest.TestCase):
    def setUp(self):
        self.plan = json.load(open(os.path.join(GOLDEN, "G1", "expected", "plan.json"), encoding="utf-8"))
        self.overlay = gw_yaml.load(os.path.join(GOLDEN, "G1", "overlay", "overlay.yaml"))

    def test_release_precedes_items_and_items_carry_type(self):
        wl = render_proposal.write_list(self.plan, self.overlay, ["P0", "P1"])
        kinds = [w["kind"] for w in wl["writes"]]
        for pid in ("P0", "P1"):
            rel = next(i for i, w in enumerate(wl["writes"]) if w["kind"] == "ensure_release" and w["phase"] == pid)
            first = next(i for i, w in enumerate(wl["writes"]) if w["kind"] == "create_item" and w["phase"] == pid)
            self.assertLess(rel, first)
            self.assertEqual(wl["writes"][rel]["how"], "version")
        self.assertEqual(kinds.count("ensure_release"), 2)
        types = {t["key"]: t["work_type"] for t in self.plan["tasks"]}
        for w in wl["writes"]:
            if w["kind"] == "create_item":
                self.assertEqual(w["work_type"], types[w["key"]])
                self.assertTrue(w["release"].startswith(self.plan["epic"]["title"]))

    def test_release_name_is_stable_across_state_changes(self):
        p = self.plan["phases"][0]
        before = render_proposal.release_name(self.plan, p)
        p["state"] = "released"
        self.assertEqual(render_proposal.release_name(self.plan, p), before)


if __name__ == "__main__":
    unittest.main()
