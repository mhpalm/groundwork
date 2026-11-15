#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Revise mode diff: plan of record vs revised plan vs the tracker's current state.

Usage:
  revise_diff.py BASE_PLAN.json NEW_PLAN.json TRACKER.json --overlay OVERLAY.yaml

TRACKER.json is what read_epic returned, normalized by the tracker skill:
  [{key, tracker_id, owned_hash, status: todo|in_progress|done|closed_not_done, updated_at, points, drift?}]
  (owned_hash from check_hashes.py owned on each item's normalized fields; status and drift from
  create_steps.py status, so a gw-closed label only counts when the manifest recorded the close)

Prints {ok, added, changed, close, close_items, deps_changed, relinks, unblocks, phases_offered, drift, refused, relies_on}.
- drift: a person changed a plan-owned field. The tracker wins: the revised plan
  must carry exactly the tracker's text for that task (marked from_tracker), or the
  diff is refused.
- Done work is not edited: a changed or removed done or closed_not_done task is
  refused; add a follow-up task with a new id instead.
- A closed_not_done task never satisfies a dependency: a task that isn't finished
  and depends on one is refused until the dependency is re-pointed.
- A reopened item that Groundwork closed is drift.
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
from create_steps import blocked_state  # noqa: E402

OWNED = ("title", "role_key", "phase")
FINISHED = ("done", "closed_not_done")


def rendered_hash(plan, overlay, t):
    return owned_hash({"title": t["title"], "body_owned": task_body(plan, overlay, t), "role_key": t["role_key"],
                       "phase": t["phase"], "key": t["key"]})


def _by_id_changes(a, b):
    a, b = {x["id"]: x for x in a}, {x["id"]: x for x in b}
    return {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)),
            "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k])}


def model_changes(base, new):
    """The brief, options and decisions that changed (planning model 1.8). A format-1 side has none."""
    out = {}
    for name, get in (("brief", lambda p: p.get("brief")), ("options", lambda p: (p.get("approach") or {}).get("options")),
                      ("decisions", lambda p: (p.get("approach") or {}).get("decisions"))):
        a, b = get(base), get(new)
        if a is None and b is None:
            continue
        out[name] = _by_id_changes(a or [], b or [])
    return out


def required_closes(plan, manifest):
    """Every key of this plan the manifest records, that the plan no longer has, and whose close is not
    recorded as closed or finished. A plan version stored but never applied (or applied in part) is the
    base of the next one, so what it dropped is found here, never from the base plan (seventh review, M1)."""
    prefix = f"gw:{plan['id']}:"
    keys = {t["key"] for t in plan["tasks"]}
    out = []
    for w in (manifest or {}).get("items", []):
        c = w.get("close") or {}
        if w["key"].startswith(prefix) and w["key"] not in keys and c.get("state") not in ("closed", "finished", "missing"):
            out.append({"key": w["key"], "reason": c.get("reason", "not_planned")})
    return sorted(out, key=lambda c: c["key"])


def derived_writes(plan, manifest):
    """The relinks and unblocks the plan of record implies for every task the manifest records as written:
    links that no longer match its dependencies, and a blocked state Groundwork recorded as set on a task
    that no longer waits. Computed from the plan and the manifest alone, so the diff and the approvals
    rebuild derive the same writes (eighth review, M2)."""
    prefix = f"gw:{plan['id']}:"
    strip = lambda k: k[len(prefix):] if k.startswith(prefix) else k
    written = {w["key"]: w for w in (manifest or {}).get("items", [])}
    relinks, unblocks = [], []
    for t in sorted(plan["tasks"], key=lambda x: x["id"]):
        w = written.get(t["key"])
        if w is None:
            continue
        have = {lk["to_key"] for lk in w.get("links", []) if lk["type"] == "blocked_by"}
        want = {f"{prefix}{d['task']}" for d in t["depends_on"]}
        if have != want:
            relinks.append({"task": t["id"], "added": sorted(strip(k) for k in want - have),
                            "removed": sorted(strip(k) for k in have - want)})
        if not t.get("waits_on") and blocked_state(w) == "set":
            unblocks.append(t["id"])  # only what Groundwork recorded as set (seventh review, m1)
    return {"relinks": relinks, "unblocks": unblocks}


def catch_up(out, new, tr, manifest, touched, finished):
    """The tracker changes the plan of record implies, from what the manifest records Groundwork did:
    closes of written tasks the plan dropped, and the derived relinks and unblocks. Earlier versions that
    were stored but never applied can't lose them, because none of this comes from the base plan. A dropped
    task the tracker read doesn't show is still closed: the close procedure records it as missing once a
    project-wide find_by_key confirms it is gone (eighth review, M3)."""
    prefix = f"gw:{new['id']}:"
    have = {c["key"] for c in out["close_items"]}
    found_again = [{"key": w["key"], "reason": w["close"]["reason"]} for w in manifest.get("items", [])
                   if (w.get("close") or {}).get("state") == "missing" and w["key"] in tr]
    for c in required_closes(new, manifest) + found_again:
        if c["key"] in have:
            continue
        tid = c["key"][len(prefix):]
        if c["key"] not in tr:
            out["missing"].append(c["key"])
        out["close"].append(tid)
        out["close_items"].append(c)
        touched.add(c["key"])
    d = derived_writes(new, manifest)
    for r in d["relinks"] + [{"task": x} for x in d["unblocks"]]:
        key = f"{prefix}{r['task']}"
        if key not in tr:
            out["refused"].append({"task": r["task"], "why": "the manifest records this task as written but the tracker "
                                   "read doesn't show it: find it by key before revising"})
        touched.add(key)
    out["relinks"], out["unblocks"] = d["relinks"], d["unblocks"]


def diff(base, new, tracker, overlay, manifest=None):
    """manifest: the latest manifest. A task is "never written" only when neither the tracker read
    nor the manifest knows its key; without the manifest, nothing is dropped."""
    out = {"added": [], "changed": [], "close": [], "close_items": [], "dropped": [], "adopted": [], "changed_unwritten": [], "deps_changed": [], "relinks": [], "unblocks": [], "phases_offered": [],
           "drift": [], "refused": [], "relies_on": [], "missing": []}
    if new["id"] != base["id"]:
        out["refused"].append({"task": None, "why": "the revised plan has a different plan id; revise keeps the epic's plan id"})
        out["ok"] = False
        return out
    if new["version"] <= base["version"]:
        out["refused"].append({"task": None, "why": "the revised plan must take the next plan version"})
    bt = {t["id"]: t for t in base["tasks"]}
    nt = {t["id"]: t for t in new["tasks"]}
    tr = {i["key"]: i for i in tracker}
    recorded_items = {w["key"]: w for w in (manifest or {}).get("items", [])}
    touched = set()

    def finished(item):
        return bool(item) and item.get("status") in FINISHED

    for k, item in sorted(tr.items()):
        if item.get("drift"):
            task = next((x["id"] for x in base["tasks"] if x["key"] == k), None)
            out["drift"].append({"task": task, "tracker_id": item["tracker_id"], "why": item["drift"]})
    dead = {x["id"] for x in base["tasks"] if tr.get(x["key"], {}).get("status") == "closed_not_done"}
    for tid, t in sorted(nt.items()):
        if finished(tr.get(t["key"])):
            continue
        bad = sorted({d["task"] for d in t["depends_on"]} & dead)
        if bad:
            out["refused"].append({"task": tid, "why": f"depends on {', '.join(bad)}, which was closed without being done; "
                                                       "re-point the dependency or drop it"})
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
        # drift is measured against the text Groundwork recorded writing, not the base plan's text: a base
        # version stored but never applied isn't on the tracker, and that is not a person's edit (seventh review)
        rec = recorded_items.get(b["key"])
        written_h = (rec or {}).get("owned_hash") or base_h
        if item and item["owned_hash"] != written_h and item["owned_hash"] == base_h:
            # the plan of record's own approved update reached the tracker, but the session ended before the
            # manifest recorded it: not a person's edit (eighth review, m2). Record it first; edit it after.
            touched.add(b["key"])
            if new_h == base_h:
                out["adopted"].append(tid)
            else:
                out["refused"].append({"task": tid, "why": "the plan of record's update to this task landed but was never "
                                                           "recorded; revise once without changing it, so the update is "
                                                           "recorded, then edit it"})
            continue
        if item and item["owned_hash"] != written_h:
            out["drift"].append({"task": tid, "tracker_id": item["tracker_id"]})
            touched.add(b["key"])
            if new_h != item["owned_hash"]:
                out["refused"].append({"task": tid, "why": "a person changed this task in the tracker; the tracker wins, so the "
                                                           "revised plan must adopt that text (marked from_tracker) before other edits"})
            else:
                # adopted: the manifest still records the old text, so the write list binds an update to the
                # adopted text, and create records it (adopt_update) without writing over the person's edit
                out["adopted"].append(tid)
            continue
        if new_h != base_h and item is None:
            out["changed_unwritten"].append(tid)  # never written: the new text is simply created later
        elif item is not None and new_h != written_h:
            if finished(item):
                out["refused"].append({"task": tid, "why": f"{item['status'].replace('_', ' ')} work is not edited; "
                                                           "add a follow-up task with a new id"})
                continue
            fields = [f for f in OWNED if t[f] != b[f]]
            if t["instructions"] != b["instructions"] or t["visible_result"] != b["visible_result"]:
                fields.append("body")
            out["changed"].append({"task": tid, "fields": fields or ["body"]})
            touched.add(b["key"])
        bd = {d["task"] for d in b["depends_on"]}
        nd = {d["task"] for d in t["depends_on"]}
        if bd != nd:
            if finished(item):
                out["refused"].append({"task": tid, "why": "finished work is not edited; its dependencies stay as they were"})
                continue
            out["deps_changed"].append({"task": tid, "added": sorted(nd - bd), "removed": sorted(bd - nd)})
            touched.add(b["key"])
            if item is not None:  # written: its tracker links move with the plan
                out["relinks"].append({"task": tid, "added": sorted(nd - bd), "removed": sorted(bd - nd)})
        if item is not None and b.get("waits_on") and not t.get("waits_on") and not finished(item):
            out["unblocks"].append(tid)
            touched.add(b["key"])
    for tid, b in sorted(bt.items()):
        if tid in nt:
            continue
        item = tr.get(b["key"])
        if finished(item):
            out["refused"].append({"task": tid, "why": f"a {item['status'].replace('_', ' ')} task cannot be removed from the plan"})
            continue
        if item is None:
            recorded = b["key"] in {i["key"] for i in (manifest or {}).get("items", [])}
            if manifest is None:
                out["refused"].append({"task": tid, "why": "the tracker read doesn't show this task but no manifest was "
                                       "given, so it can't be told apart from a written task: pass the latest manifest"})
                continue
            if recorded:
                # written, and the read doesn't show it: closed as missing once a project-wide find_by_key
                # confirms it is gone (ninth review, M1); catch_up adds the close
                continue
            out["dropped"].append(tid)  # never written: removing it from the plan is enough, there is nothing to close
            continue
        out["close"].append(tid)
        out["close_items"].append({"key": b["key"], "reason": "not_planned"})
        touched.add(b["key"])
    if manifest is not None:
        catch_up(out, new, tr, manifest, touched, finished)
    for tid in out["added"]:
        if any(t["key"] == nt[tid]["key"] for t in base["tasks"]):
            out["refused"].append({"task": tid, "why": "a new task reuses a key from the plan of record; ids are append-only"})
        elif nt[tid]["key"] in recorded_items:  # eighth review, m1: a dropped, written key is never reused
            out["refused"].append({"task": tid, "why": "a new task reuses the key of a written task an earlier version "
                                                       "dropped; ids are append-only, so take a new id"})
    bp = {p["id"]: p for p in base["phases"]}
    for p in new["phases"]:
        if p["state"] != "outline" and bp.get(p["id"], {}).get("state", "outline") == "outline":
            out["phases_offered"].append(p["id"])
    for k in sorted(touched):
        if k in tr:
            out["relies_on"].append({"key": k, "tracker_id": tr[k]["tracker_id"], "updated_at": tr[k]["updated_at"]})
    out["model"] = model_changes(base, new)
    # what render_proposal.py write-list --edits takes: every written task whose text moves, adopted text included
    out["edits"] = sorted(set(x["task"] for x in out["changed"]) | set(out["adopted"]))
    out["ok"] = not out["refused"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("new")
    ap.add_argument("tracker")
    ap.add_argument("--overlay", required=True)
    import check_hashes
    check_hashes.add_manifests_arg(ap)
    a = ap.parse_args(argv)
    J = lambda p: None if p == "-" else json.load(open(p, encoding="utf-8"))
    base = J(a.base)
    try:
        manifest = check_hashes.latest_manifest_of(a.manifests, base["id"])
        if manifest is None and any(i["key"].startswith(f"gw:{base['id']}:") for i in J(a.tracker)):
            # eighth review, m4: an empty manifest set while the tracker holds this plan's items would turn
            # off every manifest-derived close, relink and unblock
            raise ValueError("the tracker holds items of this plan but no manifest was given: pass every manifest file")
        manifest = manifest or {"items": []}
    except ValueError as e:
        print(json.dumps({"ok": False, "problems": [str(e)]}, indent=2))
        return 1
    out = diff(base, J(a.new), J(a.tracker), gw_yaml.load(a.overlay), manifest)
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
