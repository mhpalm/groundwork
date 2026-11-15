# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Builds the trait goldens from G1 (run make_g1.py first).

  GT-<trait>     G1 with one trait pinned: its brief questions answered, its
                 standard work planned in a phase P4, and its roles mapped.
  GT-combined    three traits at once, including the declared conflict between
                 moves_data and removes_something, settled by a decision.

Traits are pinned in the fixtures, so golden runs do not vary on trait choice.
"""
import copy
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "gen"))
sys.path.insert(0, os.path.join(ROOT, "..", "skills", "groundwork-core", "scripts"))
import gw_model  # noqa: E402
from make_goldens import BASE_ASSERT, bf, derive_access, history, load_g1, rekey, rerun_evidence, set_overlay, step, task, write  # noqa: E402

TASK_KIND = {"reconciliation": "reconciliation", "spike": "spike", "decision_record": "design", "training": "training",
             "support_handoff": "handoff", "procurement": "setup", "signoff_prep": "signoff_prep", "load_test": "test",
             "compat_test": "test", "consumer_comms": "comms", "decommission_decision": "design", "archive": "data",
             "dry_run": "test", "event_runbook": "docs", "evidence_collection": "docs", "definition_signoff": "signoff_prep"}
ROLE_NAMES = {"comms": "Comms Lead", "trainer": "Coordinator Trainer", "procurement": "Purchasing Officer",
              "facilitator": "Event Facilitator", "legal": "Legal Counsel", "analyst": "Data Analyst"}
ALL = {t["id"]: t for t in gw_model.load_traits().values()}


def trait_task(pid, tid, order, kind, role, after, trait):
    words = kind.replace("_", " ")
    t = task(pid, tid, order, f"Complete the {words} work", TASK_KIND[kind], role, 3, [(after, "done")],
             [step(f"Open this project's brief and read the {trait['id'].replace('_', ' ')} answers in the epic description."),
              step(f"Do the {words} work the brief describes and record the result in a comment on this task."),
              step("Mention the role-holder named in the epic for anything you could not finish.")],
             f"Carry out the {words} standard work that the {trait['id'].replace('_', ' ')} trait requires.",
             [f"The {words} result is recorded on this task."], ["The comment on this task shows the result."],
             "The result comment is posted.", ("comment_posted", f"Comment with the {words} result"))
    t["brief_refs"] = ["B-3"]
    return t


def build(name, trait_ids, conflict=None):
    plan, overlay, ev = load_g1()
    n = 30 + sorted(ALL).index(trait_ids[0]) if len(trait_ids) == 1 else 49
    pid = f"gw-01JCX7Q3RZ9V4N2T8K5M6P0T{n:02d}"
    plan = rekey(plan, pid)
    E = rerun_evidence(ev, pid)
    plan["traits"] = list(plan["traits"])
    next_b = len(plan["brief"]) + 1
    roles_used = set(BASE_ASSERT["roles_used_subset_of"])
    tasks, order = [], len(plan["tasks"]) + 1
    kinds_done = {s["kind"] for s in plan["standard_work"]}
    after = "P3-T05"
    for tid_ in trait_ids:
        tr = ALL[tid_]
        plan["traits"].append({"id": tr["id"], "version": tr["version"], "from_plan_version": 1})
        have = {f["key"] for f in plan["brief"]}
        for q in tr["questions"]:
            if q["key"] not in have:
                plan["brief"].append(bf(next_b, q["key"], f"Answered for this fixture: {q['text'].rstrip('?')}."))
                next_b += 1
        for role in tr["roles"]:
            if role not in {r["key"] for r in overlay["roles"]}:
                overlay["roles"].append({"key": role, "name": ROLE_NAMES[role]})
            roles_used.add(role)
        for kind in tr["standard_work"]:
            if kind in kinds_done:
                continue
            tid = f"P4-T{len(tasks) + 1:02d}"
            role = tr["roles"][0] if tr["roles"] else "developer"
            t = trait_task(pid, tid, order, kind, role, after, tr)
            if kind == "reconciliation":
                t["waits_on"] = [{"what": "Two weeks of side-by-side running with matching counts", "kind": "elapsed",
                                  "owner_role_key": "developer",
                                  "condition": "Daily counts match between the old and new copies for 14 days in a row",
                                  "legacy_ref": None}]
            tasks.append(t)
            plan["standard_work"].append({"kind": kind, "tasks": [tid], "not_applicable_reason": None})
            kinds_done.add(kind)
            order += 1
    plan["tasks"] += tasks
    plan["phases"].append({"id": "P4", "order": 4, "name": "Trait work", "goal": "The standard work the pinned traits add is done.",
                           "state": "drafted", "depends_on": ["P3"], "task_ids": [t["id"] for t in tasks]})
    if conflict:
        plan["approach"]["decisions"].append({
            "id": "AD-2", "decision": conflict, "chosen_option": "O-1", "deferred_to_task": None,
            "brief_refs": ["B-3"], "evidence": [], "trait_conflict": ["moves_data", "removes_something"]})
    derive_access(plan)
    set_overlay(plan, overlay)
    history(plan, "drafted")
    a = dict(BASE_ASSERT, min_tasks=len(plan["tasks"]), max_tasks=len(plan["tasks"]),
             standard_work=sorted(BASE_ASSERT["standard_work"] + [k for k in gw_model.trait_kinds(plan, overlay) if k != "compat_test"]),
             roles_used_subset_of=sorted(roles_used), traits_pinned=sorted(t["id"] for t in plan["traits"]))
    write(name, f"trait golden: {', '.join(trait_ids)}", plan["request"]["original_text"], overlay, E, plan, a)


def main():
    for tid in sorted(ALL):
        if tid == "has_consumers":
            continue  # G1 itself pins has_consumers
        build(f"GT-{tid}", [tid])
    build("GT-combined", ["moves_data", "removes_something", "outcome_unknown"],
          "Run the old and new copies side by side for two weeks with daily reconciliation, then switch the old one off.")


if __name__ == "__main__":
    main()
