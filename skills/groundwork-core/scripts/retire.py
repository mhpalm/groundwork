#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Retire a plan, and the gate every later operation passes (planning model section 7).

Usage:
  retire.py plan ITEMS.json CHOICES.json --plan-id ID --manifests M_1.json ... M_n.json
  retire.py write-list PLAN.json --overlay OVERLAY.yaml --plan-out RETIRE_PLAN.json [--draft-label]
            [--pending PHASE_ID ...]
  retire.py status PLAN.json --n N --proposal PROPOSAL.md --at TS   (at write time, under the lock; the
            verified proposal file, whose hash is computed here and never typed)
  retire.py rebuild PLAN_ID --manifests M_1.json ... M_n.json   (resume: the status file from the latest manifest's intent)
  retire.py recheck VERIFIED_WRITE_LIST.json ITEMS.json CONTEXT.json --plan-id ID --manifests M_1.json ...
            (at write time, before any write)
  retire.py gate OP --plan PLAN.json --manifests M_1.json ... --status STATUS.json|- --epic open|closed
            [--resuming PLAN_VERSION:PROPOSAL_HASH]

Retire writes no plan version. The status lives in status-<n>.json; the latest one
wins over plan.status. ITEMS: [{key, status, person_added, unrecorded}] from list_children
plus find_by_key for every plan key and every key a manifest records (status from create_steps.py
status). person_added: the key is neither one of the plan's task keys nor recorded in a manifest. unrecorded: a plan key no manifest records yet. CHOICES: {key: "close" | {leave:
owner_role_key}} for every in_progress plan-owned item.

Write order: lock claim, status intent manifest (the first write after the lock), draft
label removal, item closes (close procedure), status file, final manifest recording the
status file's hash, snapshot, epic close, lock release. Every later create, resume, freeze, release, revise, plan
phase and change request refuses a retired plan or a closed epic, except the resume
of the very set named in the status file's set_by.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402
from gw_hash import item_hash  # noqa: E402

OPS = ("retire", "create", "resume", "freeze", "release", "revise", "plan_phase", "change_request")


def plan_retire(items, choices, manifest=None):
    """What happens to each item: todo closes not_planned; in_progress follows the runner's choice;
    finished items are untouched; children a person added stay open and are named.

    manifest: the latest manifest (the CLI always passes it). A key it records is Groundwork's, even
    when the plan of record no longer has it, so it is closed like any other, never named as a person's
    (seventh review, M1); a recorded key the read didn't find is closed too, listed under missing, and the
    close procedure records it as missing once a project-wide find_by_key confirms it is gone."""
    closes, left, person, probs = [], [], [], []
    recorded = {w["key"]: w for w in (manifest or {}).get("items", [])}
    items = [dict(i, person_added=False) if i.get("person_added") and i["key"] in recorded else i for i in items]
    found = {i["key"] for i in items}
    missing = []
    for k, w in sorted(recorded.items()):
        if k not in found and (w.get("close") or {}).get("state") not in ("closed", "finished", "missing"):
            # a person deleted it: the close procedure records it as missing once a project-wide
            # find_by_key confirms it is gone (eighth review, M3)
            missing.append(k)
            closes.append({"key": k, "reason": (w.get("close") or {}).get("reason", "not_planned")})
    for it in sorted(items, key=lambda i: i["key"]):
        if it.get("person_added"):
            person.append(it["key"])
            continue
        if it.get("unrecorded"):
            probs.append(f"{it['key']} is plan-owned but no manifest records it (a create was cut short): "
                         "resume that create first, then retire")
            continue
        if it["status"] in ("done", "closed_not_done"):
            continue
        # a close the manifest already records keeps its reason, so the close procedure never stops on a
        # reason that differs from the recorded one after the status intent is written (tenth review, M1)
        reason = ((recorded.get(it["key"]) or {}).get("close") or {}).get("reason", "not_planned")
        if it["status"] == "todo":
            closes.append({"key": it["key"], "reason": reason})
            continue
        c = choices.get(it["key"])
        if c == "close":
            closes.append({"key": it["key"], "reason": reason})
        elif isinstance(c, dict) and c.get("leave"):
            left.append({"key": it["key"], "owner_role_key": c["leave"]})
        else:
            probs.append(f"{it['key']} is in progress: the runner chooses close, or leave open with a named owner role")
    seen = [{"key": i["key"], "status": i["status"], "person_added": bool(i.get("person_added"))}
            for i in sorted(items, key=lambda i: i["key"])]
    closes.sort(key=lambda c: c["key"])
    return {"ok": not probs, "closes": closes, "left_open": left, "person_added": person, "missing": missing,
            "problems": probs, "seen": seen}


def recheck(wl, items, seen, manifest=None):
    """At write time, check the items as they are now against the verified retire write list.

    wl: the verified write list (its close_item writes and left_open); seen: the statuses the
    proposal showed ({key: status}, from the stored proposal context). Nothing at write time can
    add a close or change a choice: an item finished since is skipped by the close procedure, and
    anything else the approved set didn't name stops with "propose again"."""
    if wl.get("kind") != "retire":
        return ["recheck takes the verified retire write list"]
    closes = {w["key"] for w in wl["writes"] if w["kind"] == "close_item"}
    left = {x["key"] for x in wl.get("left_open", [])}
    person = set(wl.get("person_added", []))
    recorded = {w["key"] for w in (manifest or {}).get("items", [])}
    # a key the manifest records is Groundwork's, whatever the runner's read flagged (eighth review, M1)
    items = [dict(i, person_added=False) if i.get("person_added") and i["key"] in recorded else i for i in items]
    probs = []
    for it in sorted(items, key=lambda i: i["key"]):
        k, st = it["key"], it["status"]
        if it.get("person_added"):
            if k not in person and st not in ("done", "closed_not_done"):
                probs.append(f"{k} was added by a person after the proposal and is not named in it: propose again")
            continue
        if it.get("unrecorded"):
            probs.append(f"{k} is plan-owned but no manifest records it: resume that create first, then propose again")
            continue
        if st in ("done", "closed_not_done"):
            continue
        if k in left:
            continue
        if k not in closes:
            probs.append(f"{k} is open but the approved retire neither closes it nor leaves it open: propose again")
        elif st == "in_progress" and seen.get(k) != "in_progress":
            probs.append(f"{k} was started after the retire was approved; closing it needs a new choice: propose again")
    return probs


def status_record(plan, n, proposal_hash, at):
    rec = {"schema_version": "1.0", "plan_id": plan["id"], "n": n, "status": "retired",
           "set_by": {"plan_version": plan["version"], "proposal_hash": proposal_hash}, "at": at}
    rec["hash"] = item_hash(rec)
    return rec


def status_intent(status):
    """The manifest's status_file entry before status-<n>.json is written. It carries everything the
    record is built from, so a resume rebuilds the identical file (same hash) after a crash."""
    return {"state": "intent", "n": status["n"], "hash": status["hash"], "at": status["at"],
            "set_by": dict(status["set_by"])}


def rebuild_status(plan_id, sf):
    rec = {"schema_version": "1.0", "plan_id": plan_id, "n": sf["n"], "status": "retired",
           "set_by": dict(sf["set_by"]), "at": sf["at"]}
    rec["hash"] = item_hash(rec)
    if rec["hash"] != sf["hash"]:
        raise ValueError("the status intent does not rebuild to its recorded hash: stop")
    return rec


def status_template(plan):
    """What the write list binds for the status file. The number is allocated at write time under the
    lock, set_by comes from the verified set (a write list never names its own proposal's hash) and
    at is the write time; the status intent records all three before the file is written."""
    return {"schema_version": "1.0", "plan_id": plan["id"], "status": "retired"}


def write_list(plan, overlay, retire_plan, draft_label=False, pending_sets=()):
    """One plan-level write list, every entry scope plan, in the fixed retire order."""
    tr = overlay["skills"]["tracker"]
    target = f"{tr['skill'].replace('groundwork-tracker-', '')}:{tr['instance']['id']}:{tr['instance']['project']}"
    prefix = tr["field_map"].get("close_label_prefix", "gw-closed:")
    writes = [{"kind": "lock_claim", "on": "epic"},
              # the status intent comes first, so from the retire's first write every other operation,
              # including the creates of the pending sets it voids, is refused (fifth review, finding 2)
              {"kind": "manifest_put", "note": "status intent: the status file's number, set_by, at and hash"}]
    if draft_label:
        writes.append({"kind": "remove_label", "on": "epic", "label": overlay.get("labels", {}).get("draft", "gw-draft")})
    closes = retire_plan["closes"]
    if closes:
        writes.append({"kind": "manifest_put", "note": "close intent for " + ", ".join(c["key"] for c in closes)})
        for c in closes:
            writes.append({"kind": "add_label", "key": c["key"], "label": prefix + c["reason"]})
            writes.append({"kind": "close_item", "key": c["key"], "reason": c["reason"]})
        writes.append({"kind": "manifest_put", "note": "closes done"})
    writes.append({"kind": "status_put", "status": status_template(plan)})
    writes.append({"kind": "manifest_put", "note": "records the status file's hash"})
    writes.append({"kind": "snapshot_put"})
    writes.append({"kind": "close_epic", "on": "epic"})
    writes.append({"kind": "lock_release", "on": "epic"})
    for i, w in enumerate(writes, 1):
        w.update(no=i, target=target, scope="plan")
    return {"schema_version": "1.0", "plan_id": plan["id"], "plan_version": plan["version"], "phases": [], "kind": "retire",
            "writes": writes, "left_open": retire_plan["left_open"], "person_added": retire_plan["person_added"],
            "missing": retire_plan.get("missing", []), "voids_pending": sorted(pending_sets)}


def status_state(manifest, status):
    """(state, problems). state: None (never retired), 'intended' (intent recorded, file not yet
    written) or 'retired' (the file is written and matches what the manifest intends or records)."""
    sf = (manifest or {}).get("status_file")
    probs = []
    if status is not None and item_hash(status) != status.get("hash"):
        probs.append("the status file does not match its own hash: stop")
    if sf is None:
        if status is not None:
            probs.append("a status file exists that the latest manifest neither records nor intends: stop")
        return None, probs
    if status is None:
        if sf["state"] == "recorded":
            probs.append(f"the manifest records status-{sf['n']} but it is missing: stop")
        return "intended", probs
    if status["n"] != sf["n"] or status["hash"] != sf["hash"] or status["set_by"] != sf["set_by"]:
        verb = "records" if sf["state"] == "recorded" else "intends"
        probs.append(f"status-{status['n']} does not match the status file the manifest {verb}: stop")
    return "retired", probs


def gate(op, plan, manifest, status, epic_state, resuming=None):
    """May this operation run? resuming: (plan_version, proposal_hash) of the set being resumed.
    The only operation a retired, retiring or closed-epic plan allows is the resume of the very
    set the manifest's status_file names."""
    if op not in OPS:
        raise ValueError(f"op is one of {', '.join(OPS)}")
    if epic_state not in ("open", "closed"):
        raise ValueError("epic_state is open or closed")
    state, probs = status_state(manifest, status)
    if status is not None and status.get("plan_id") != plan["id"]:
        probs.append(f"the status file belongs to plan {status.get('plan_id')}, not {plan['id']}: stop")
    if probs:
        return {"ok": False, "problems": probs}
    sf = (manifest or {}).get("status_file")
    own = (sf["set_by"]["plan_version"], sf["set_by"]["proposal_hash"]) if sf else None
    is_own_resume = op == "resume" and own is not None and resuming is not None and tuple(resuming) == own
    if state is not None and not is_own_resume:
        return {"ok": False, "problems": ["retired plan, start a new plan" if state == "retired"
                                          else "a retire is in progress; only the resume of its own set may run"]}
    if epic_state == "closed" and not is_own_resume:
        return {"ok": False, "problems": ["the epic is closed; start a new plan"]}
    return {"ok": True, "problems": [], "resume_of_retire": is_own_resume}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "write-list", "status", "rebuild", "recheck", "gate"])
    ap.add_argument("files", nargs="*")
    for x in ("--plan-id", "--overlay", "--plan-out", "--proposal", "--at", "--plan", "--status", "--epic", "--resuming"):
        ap.add_argument(x)
    import check_hashes
    check_hashes.add_manifests_arg(ap)
    ap.add_argument("--draft-label", action="store_true")
    ap.add_argument("--pending", nargs="*", default=[])
    ap.add_argument("--n", type=int, help="status: the latest status file's number plus one (1 when there is none)")
    a = ap.parse_args(argv)
    J = lambda p: None if p in (None, "-") else json.load(open(p, encoding="utf-8"))
    if a.cmd == "plan":
        if not a.plan_id or a.manifests is None:
            out = {"ok": False, "problems": ["--plan-id and --manifests required: a key the manifest records is never a person's"]}
        else:
            try:
                out = plan_retire(J(a.files[0]), J(a.files[1]), check_hashes.latest_manifest_of(a.manifests, a.plan_id))
            except ValueError as e:
                out = {"ok": False, "problems": [str(e)]}
    elif a.cmd == "write-list":
        out = write_list(J(a.files[0]), gw_yaml.load(a.overlay), J(a.plan_out), a.draft_label, a.pending)
    elif a.cmd == "rebuild":
        try:
            import check_hashes
            m = check_hashes.latest_manifest_of(a.manifests, a.files[0])
            out = {"ok": True, "status_record": rebuild_status(a.files[0], (m or {}).get("status_file"))}
        except (ValueError, KeyError, TypeError) as e:
            out = {"ok": False, "problems": [f"cannot rebuild the status file: {e}"]}
    elif a.cmd == "recheck":
        seen = {i["key"]: i["status"] for i in J(a.files[2])["items"]}
        if not a.plan_id or a.manifests is None:
            out = {"ok": False, "problems": ["--plan-id and --manifests required: a key the manifest records is never a person's"]}
        else:
            try:
                probs = recheck(J(a.files[0]), J(a.files[1]), seen, check_hashes.latest_manifest_of(a.manifests, a.plan_id))
                out = {"ok": not probs, "problems": probs}
            except ValueError as e:
                out = {"ok": False, "problems": [str(e)]}
    elif a.cmd == "status" and a.n is None:
        out = {"ok": False, "problems": ["--n required: the number is allocated under the lock at write time"]}
    elif a.cmd == "status" and not (a.proposal and a.at):
        out = {"ok": False, "problems": ["--proposal and --at required: the verified proposal file and the write time"]}
    elif a.cmd == "status":
        # sixth review, M5: the hash comes from the verified proposal file, so a typo or a null can't bind
        # the status intent to a set nobody approved (which no resume could then match)
        from gw_canon import sha256_hex
        st = status_record(J(a.files[0]), a.n, sha256_hex(open(a.proposal, "rb").read()), a.at)
        out = {"status_record": st, "intent": status_intent(st)}
    else:
        res = None
        if a.resuming:
            v, h = a.resuming.split(":", 1)
            res = (int(v), h)
        import check_hashes
        plan = J(a.plan)
        try:
            manifest = check_hashes.latest_manifest_of(a.manifests, plan["id"])
        except ValueError as e:
            out = {"ok": False, "problems": [str(e)]}
        else:
            out = gate(a.files[0], plan, manifest, J(a.status), a.epic, res)
    print(json.dumps(out, indent=2))
    if a.cmd == "write-list":
        from gw_hash import write_list_hash
        print(f"write_list_hash {write_list_hash(out)}", file=sys.stderr)
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
