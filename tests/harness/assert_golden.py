#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Check a plan produced by a golden run against the project's assertions.yaml.

Usage: assert_golden.py PROJECT PLAN.json     (PROJECT is a folder under tests/golden)
Used by the release-tag golden runs: run the pipeline headlessly on the
project's request with its fixture evidence, then call this on the result.
A release passes only if each project passes in 3 of 3 runs.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import GOLDEN, NOW, gw_yaml  # noqa: E402
import validate_plan  # noqa: E402

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")


def assert_plan(project, plan):
    d = os.path.join(GOLDEN, project)
    a = gw_yaml.load(os.path.join(d, "assertions.yaml"))
    overlay = gw_yaml.load(os.path.join(d, "overlay", "overlay.yaml"))
    evidence = validate_plan.load_evidence(os.path.join(d, "evidence"))
    fails = []
    R = validate_plan.check(plan, overlay, evidence, now=NOW)
    if len(R.blocking()) > a.get("validator_blockers", 0):
        fails += [f"validator: {f['check']} {f['target']}: {f['what']}" for f in R.blocking()]
    for f in R.items:
        if f["severity"] == "minor" and f["check"] not in a.get("allowed_minors", []):
            fails.append(f"unexpected minor {f['check']} on {f['target']}")
    n = len(plan["tasks"])
    if not a.get("min_tasks", 0) <= n <= a.get("max_tasks", 999):
        fails.append(f"{n} tasks, expected {a.get('min_tasks')} to {a.get('max_tasks')}")
    ids = {p["id"] for p in plan["phases"]}
    fails += [f"missing phase {p}" for p in a.get("phases_required", []) if p not in ids]
    kinds = {s["kind"] for s in plan["standard_work"] if s["tasks"]}
    fails += [f"no {k} tasks" for k in a.get("standard_work", []) if k not in kinds]
    if sum(t["production_change"] for t in plan["tasks"]) < a.get("production_change_tasks_min", 0):
        fails.append("no task is marked as a production change")
    roles = set(a.get("roles_used_subset_of", []))
    for t in plan["tasks"]:
        if roles and t["role_key"] not in roles:
            fails.append(f"{t['id']} uses unexpected role {t['role_key']}")
    waits = {w["kind"] for t in plan["tasks"] for w in t["waits_on"]}
    fails += [f"no wait of kind {k}" for k in a.get("must_wait_on_kinds", []) if k not in waits]
    if a.get("no_external_recipients"):
        for t in plan["tasks"]:
            for m in EMAIL.finditer(json.dumps(t)):
                if not m.group(0).endswith(("example.com", "example.org")):
                    fails.append(f"{t['id']} sends to an external address")
    for forbidden in a.get("forbidden_task_text", []):
        for t in plan["tasks"]:
            if forbidden.lower() in json.dumps(t["instructions"]).lower():
                fails.append(f"{t['id']} contains planted directive text '{forbidden}'")
    return fails


def main(argv):
    fails = assert_plan(argv[0], json.load(open(argv[1], encoding="utf-8")))
    for f in fails:
        print(f)
    print(f"{argv[0]}: {'pass' if not fails else f'{len(fails)} failure(s)'}", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
