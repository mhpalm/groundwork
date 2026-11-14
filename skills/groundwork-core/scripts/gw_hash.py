# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""The normative hashed subsets (see reference/hashing.md).

phase_hash  the phase's id, name, goal, order, depends_on and task_ids, plus
            every field of each of its tasks. Never phase state, plan status,
            version, stamps, review, history, coverage, epic.tracker_ref or
            approvals, so moving a phase through its states never changes it.
plan_hash   every phase_hash, plus scope, epic.title, epic.summary,
            open_questions and access_list.
"""

import copy

from gw_canon import hash_value

PHASE_FIELDS = ("id", "name", "goal", "order", "depends_on", "task_ids")


def phase_subset(plan, phase_id):
    phase = next((p for p in plan["phases"] if p["id"] == phase_id), None)
    if phase is None:
        raise KeyError(f"no phase {phase_id}")
    tasks = sorted((t for t in plan["tasks"] if t["phase"] == phase_id), key=lambda t: t["id"])
    return {"phase": {k: phase.get(k) for k in PHASE_FIELDS}, "tasks": tasks}


def phase_hash(plan, phase_id):
    return hash_value(phase_subset(plan, phase_id))


def phase_hashes(plan):
    return {p["id"]: phase_hash(plan, p["id"]) for p in plan["phases"]}


def plan_subset(plan):
    return {
        "phase_hashes": phase_hashes(plan),
        "scope": plan["scope"],
        "epic": {"title": plan["epic"]["title"], "summary": plan["epic"]["summary"]},
        "open_questions": plan["open_questions"],
        "access_list": plan["access_list"],
    }


def plan_hash(plan):
    return hash_value(plan_subset(plan))


def item_hash(item, field="hash"):
    """Hash of a persisted record without its own hash field."""
    body = {k: v for k, v in item.items() if k != field}
    return hash_value(body)


def write_list_hash(write_list):
    return hash_value(write_list)


def reviewer_view(plan):
    """The plan the reviewer sees: no history, no origin, clarifications as Q and A only."""
    v = copy.deepcopy(plan)
    v.pop("history", None)
    v.pop("review", None)
    v.pop("approvals", None)
    for t in v.get("tasks", []):
        t.pop("origin", None)
    req = v.get("request", {})
    req["clarifications"] = [{"id": c["id"], "question": c["question"], "answer": c["answer"]}
                             for c in req.get("clarifications", [])]
    return v


def view_bundle(plan, evidence, checklist_version, rules):
    return {
        "schema_version": "1.0",
        "plan": reviewer_view(plan),
        "evidence": sorted(evidence, key=lambda e: e["id"]),
        "checklist_version": checklist_version,
        "rules": sorted(rules, key=lambda r: r["id"]),
    }


def view_hash(bundle):
    return hash_value(bundle)


def review_hash(review):
    return hash_value({"findings": review["findings"], "view_hash": review["view_hash"]})


def evidence_id(platform, instance, subject):
    """ev-<platform>-<instance>-<8 hex of the subject>, stable across re-reads."""
    sub = {"type": subject["type"], "name": subject["name"]}
    return f"ev-{platform}-{instance}-{hash_value(sub)[:8]}"
