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
    offered = a.get("proposable_phases")
    R = validate_plan.check(plan, overlay, evidence, offered_arg=offered, now=NOW)
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
        for where in ("brief", "approach"):
            if where in plan and forbidden.lower() in json.dumps(plan[where]).lower():
                fails.append(f"the {where} contains planted directive text '{forbidden}'")
    phases = {p["id"]: p for p in plan["phases"]}
    for pid in a.get("outline_phases", []):
        p = phases.get(pid)
        if not p or p["state"] != "outline" or p["task_ids"]:
            fails.append(f"{pid} should be an outline phase with no tasks")
    for pid in a.get("unproposable_phases", []):
        if not validate_plan.check(plan, overlay, evidence, offered_arg=[pid], now=NOW).blocking():
            fails.append(f"offering {pid} should be blocked")
    if "blocked_tasks" in a:
        got = sorted({f["target"] for f in R.items if f["check"] == "GR-04"})
        if got != sorted(a["blocked_tasks"]):
            fails.append(f"open questions block {got}, expected {sorted(a['blocked_tasks'])}")
    if "production_change_tasks_max" in a and sum(t["production_change"] for t in plan["tasks"]) > a["production_change_tasks_max"]:
        fails.append("too many production-change tasks")
    sw = {s["kind"]: s for s in plan["standard_work"]}
    for k in a.get("standard_work_not_applicable", []):
        if k not in sw or sw[k]["tasks"] or not (sw[k]["not_applicable_reason"] or "").strip():
            fails.append(f"standard work {k} should be marked not applicable with a reason")
    if "non_dev_share_min" in a:
        share = sum(t["kind"] not in ("build", "config", "data") for t in plan["tasks"]) / max(1, len(plan["tasks"]))
        if share < a["non_dev_share_min"]:
            fails.append(f"only {share:.0%} of tasks are non-development work")
    for sysname in a.get("coverage_not_inspected", []):
        if not any(c["system"] == sysname and c["status"] == "not_inspected" and c["reason"].strip() for c in plan["coverage"]):
            fails.append(f"coverage should show {sysname} as not inspected, with a reason")
    sp = plan["request"]["starting_point"]
    if "starting_point" in a and sp["kind"] != a["starting_point"]:
        fails.append(f"starting point is {sp['kind']}, expected {a['starting_point']}")
    changed = [t for t in plan["tasks"] if t.get("changes_existing")]
    if len(changed) < a.get("changes_existing_tasks_min", 0):
        fails.append(f"{len(changed)} tasks declare changes to existing resources, expected at least {a['changes_existing_tasks_min']}")
    if a.get("changes_justified"):
        for t in changed:
            ch = t["changes_existing"]
            if not ch["why_needed"].strip() or not ch["could_break"] or not ch["regression_check"]:
                fails.append(f"{t['id']} changes an existing resource without a reason, a risk or a regression check")
    if "traits_pinned" in a:
        got = sorted(t["id"] for t in plan.get("traits", []))
        if got != sorted(a["traits_pinned"]):
            fails.append(f"pinned traits are {got}, expected {sorted(a['traits_pinned'])}")
    return fails


def main(argv):
    fails = assert_plan(argv[0], json.load(open(argv[1], encoding="utf-8")))
    for f in fails:
        print(f)
    print(f"{argv[0]}: {'pass' if not fails else f'{len(fails)} failure(s)'}", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
