#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Revise mode diff: plan of record vs revised plan vs the tracker's current state.

Usage:
  revise_diff.py BASE_PLAN.json NEW_PLAN.json TRACKER.json --overlay OVERLAY.yaml

TRACKER.json is what read_epic returned, normalized by the tracker skill:
  [{key, tracker_id, owned_hash, status: todo|in_progress|done, updated_at, points}]
  (owned_hash from check_hashes.py owned on each item's normalized fields)

Prints {ok, added, changed, close, deps_changed, phases_offered, drift, refused, relies_on}.
- drift: a person changed a plan-owned field. The tracker wins: the revised plan
  must carry exactly the tracker's text for that task (marked from_tracker), or the
  diff is refused.
- Done work is not edited: a changed or removed done task is refused; add a
  follow-up task with a new id instead.
- Tasks are closed, never deleted.
- relies_on lists each touched item's updated_at; apply refuses if any changed.
Exit code 1 when anything is refused.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402
from check_hashes import owned_hash  # noqa: E402
from render_proposal import task_body  # noqa: E402

OWNED = ("title", "role_key", "phase")


def rendered_hash(plan, overlay, t):
    return owned_hash({"title": t["title"], "body_owned": task_body(plan, overlay, t), "role_key": t["role_key"],
                       "phase": t["phase"], "key": t["key"]})


def diff(base, new, tracker, overlay):
    out = {"added": [], "changed": [], "close": [], "deps_changed": [], "phases_offered": [], "drift": [],
           "refused": [], "relies_on": []}
    if new["id"] != base["id"]:
        out["refused"].append({"task": None, "why": "the revised plan has a different plan id; revise keeps the epic's plan id"})
        out["ok"] = False
        return out
    if new["version"] <= base["version"]:
        out["refused"].append({"task": None, "why": "the revised plan must take the next plan version"})
    bt = {t["id"]: t for t in base["tasks"]}
    nt = {t["id"]: t for t in new["tasks"]}
    tr = {i["key"]: i for i in tracker}
    touched = set()
    for tid, t in sorted(nt.items()):
        if tid not in bt:
            out["added"].append(tid)
            continue
        b = bt[tid]
        if t["key"] != b["key"]:
            out["refused"].append({"task": tid, "why": "a task's key never changes"})
            continue
        item = tr.get(b["key"])
        base_h, new_h = rendered_hash(base, overlay, b), rendered_hash(new, overlay, t)
        if item and item["owned_hash"] != base_h:
            out["drift"].append({"task": tid, "tracker_id": item["tracker_id"]})
            touched.add(b["key"])
            if new_h != item["owned_hash"]:
                out["refused"].append({"task": tid, "why": "a person changed this task in the tracker; the tracker wins, so the "
                                                           "revised plan must adopt that text (marked from_tracker) before other edits"})
            continue
        if new_h != base_h:
            if item and item.get("status") == "done":
                out["refused"].append({"task": tid, "why": "done work is not edited; add a follow-up task with a new id"})
                continue
            fields = [f for f in OWNED if t[f] != b[f]]
            if t["instructions"] != b["instructions"] or t["visible_result"] != b["visible_result"]:
                fields.append("body")
            out["changed"].append({"task": tid, "fields": fields or ["body"]})
            touched.add(b["key"])
        bd = {d["task"] for d in b["depends_on"]}
        nd = {d["task"] for d in t["depends_on"]}
        if bd != nd:
            if item and item.get("status") == "done":
                out["refused"].append({"task": tid, "why": "done work is not edited; its dependencies stay as they were"})
                continue
            out["deps_changed"].append({"task": tid, "added": sorted(nd - bd), "removed": sorted(bd - nd)})
            touched.add(b["key"])
    for tid, b in sorted(bt.items()):
        if tid in nt:
            continue
        item = tr.get(b["key"])
        if item and item.get("status") == "done":
            out["refused"].append({"task": tid, "why": "a done task cannot be removed from the plan"})
            continue
        out["close"].append(tid)
        touched.add(b["key"])
    for tid in out["added"]:
        if any(t["key"] == nt[tid]["key"] for t in base["tasks"]):
            out["refused"].append({"task": tid, "why": "a new task reuses a key from the plan of record; ids are append-only"})
    bp = {p["id"]: p for p in base["phases"]}
    for p in new["phases"]:
        if p["state"] != "outline" and bp.get(p["id"], {}).get("state", "outline") == "outline":
            out["phases_offered"].append(p["id"])
    for k in sorted(touched):
        if k in tr:
            out["relies_on"].append({"key": k, "tracker_id": tr[k]["tracker_id"], "updated_at": tr[k]["updated_at"]})
    out["ok"] = not out["refused"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("new")
    ap.add_argument("tracker")
    ap.add_argument("--overlay", required=True)
    a = ap.parse_args(argv)
    J = lambda p: json.load(open(p, encoding="utf-8"))
    out = diff(J(a.base), J(a.new), J(a.tracker), gw_yaml.load(a.overlay))
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
