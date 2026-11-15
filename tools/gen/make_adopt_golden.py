# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Builds GA-adopt from G1 (run make_g1.py first): adopt by reference.

The plan refers to two legacy items and never writes to them. A manual task closes
`OLD-12` by hand (legacy_action close, its key only in code spans, with its own access
line), and P1-T02 waits for `OLD-15` to close, as an external_event wait that create
marks blocked through set_blocked.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "gen"))
sys.path.insert(0, os.path.join(ROOT, "..", "skills", "groundwork-core", "scripts"))
from make_goldens import BASE_ASSERT, derive_access, history, load_g1, rekey, rerun_evidence, set_overlay, step, task, task_by, write  # noqa: E402

READ_AT = "2026-11-14T09:00:00Z"
LEGACY = [
    {"key": "OLD-12", "status": "in_progress", "points": 3, "parent": "OLD-1", "updated_at": "2026-10-02T15:00:00Z", "read_at": READ_AT},
    {"key": "OLD-15", "status": "todo", "points": 1, "parent": "OLD-1", "updated_at": "2026-10-20T11:30:00Z", "read_at": READ_AT},
]


def main():
    plan, overlay, ev = load_g1()
    pid = "gw-01JCX7Q3RZ9V4N2T8K5M6P0T60"
    plan = rekey(plan, pid)
    E = rerun_evidence(ev, pid)
    plan["legacy_refs"] = LEGACY
    a1 = next(a for a in plan["access_list"] if a["id"] == "A1")
    n = len(plan["access_list"]) + 1
    plan["access_list"].append(dict(a1, id=f"A{n}", role_key="business_user",
                                    level="comment on and close issues in the old export project", needed_by=[]))
    task_by(plan, "P0-T01")["produces"].append({"type": "access_request", "name": f"A{n}"})
    order = max(t["order"] for t in plan["tasks"]) + 1
    t = task(pid, "P1-T06", order, "Close the old export ticket by hand", "comms", "business_user", 1,
             [("P1-T05", "done")],
             [step("Open `OLD-12` in the old export project and read its last comment."),
              step("Add a comment to `OLD-12` saying the new CSV export replaces it, and link this task in that comment."),
              step("Close `OLD-12` with the status your project uses for work that was replaced.")],
             "Close the old export ticket, which this plan replaces, without Groundwork writing to it.",
             ["`OLD-12` is closed with a comment that names this task."], ["`OLD-12` shows a closed status."],
             "`OLD-12` is closed.", ("comment_posted", "Comment on this task that `OLD-12` is closed"),
             access=[f"A{n}"])
    t["legacy_action"] = {"ref": "OLD-12", "action": "close"}
    plan["tasks"].append(t)
    next(p for p in plan["phases"] if p["id"] == "P1")["task_ids"].append("P1-T06")
    task_by(plan, "P1-T02")["waits_on"].append({
        "what": "`OLD-15` closed (any reason)", "kind": "external_event", "owner_role_key": "business_user",
        "condition": "`OLD-15` shows a closed status in the old export project", "legacy_ref": "OLD-15"})
    derive_access(plan)
    set_overlay(plan, overlay)
    history(plan, "drafted")
    a = dict(BASE_ASSERT, min_tasks=len(plan["tasks"]), max_tasks=len(plan["tasks"]))
    write("GA-adopt", "adopt by reference: legacy keys in code spans, a manual close and an external_event wait",
          plan["request"]["original_text"], overlay, E, plan, a)


if __name__ == "__main__":
    main()
