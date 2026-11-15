#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Mechanical decisions for create: lock winner, preflight actions, manifests.

The tracker skill does the reads and writes; this script decides what they
mean, so the decision is the same on every tracker and every surface.

Usage:
  create_steps.py lock LOCK_COMMENTS.json --run RUN_ID --account ACCOUNT --now TS
  create_steps.py preflight PLANNED.json FOUND.json MANIFEST.json --phases P1,P2 --write-list VERIFIED_WRITE_LIST.json
      [--relies-on DIFF_RELIES_ON.json]   (first preflight of a revise apply: stops if any item moved since the diff)
  create_steps.py manifest PREV_MANIFEST.json|- ITEMS.json --plan-id ID --run RUN_ID --seq N --now TS [--relies-on REFS.json]
                  [--status-file STATUS_FILE_ENTRY.json]
  create_steps.py status RAW.json MANIFEST.json|- --overlay OVERLAY.yaml
  create_steps.py close CLOSES.json MANIFEST.json|- FOUND.json
  create_steps.py scope COUNT --overlay OVERLAY.yaml [--limit N]
  create_steps.py recheck CONTEXT.json OPEN_ITEMS.json

LOCK_COMMENTS: [{ref, author_account_id, created_at, body}] where body holds
  a gw-lock line: "gw-lock claim|renew|release run=<id> account=<id> expires=<ts>".
PLANNED: [{key, phase, owned_hash, points, depends_on?: [keys], waits?: bool}]   (owned_hash from check_hashes.py owned)
FOUND:   [{key, tracker_id, owned_hash, under_epic, points, status, updated_at?}]   (find_by_key across the project, cross-checked by
         list_children; status from `status`)
RAW:     [{key, state: open|closed, category?: todo|in_progress, closed_as?: [tracker status, resolution or
         state_reason], labels: [..]}]   (what the tracker skill reads back; labels are untrusted)
CLOSES:  [{key, reason: not_planned|superseded|duplicate|completed}]
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gw_hash import item_hash  # noqa: E402

CLOSE_REASONS = ("not_planned", "superseded", "duplicate", "completed")
DEFAULT_CLOSE_PREFIX = "gw-closed:"
READ_SCOPE_MAX = 200

LOCK_LINE = re.compile(r"gw-lock (claim|renew|release) run=(\S+) account=(\S+)(?: expires=(\S+))?")
LOCK_MINUTES = 30
STATUSES = ("todo", "in_progress", "done", "closed_not_done")  # what create_steps.py status reports
RENEW_EVERY_WRITES = 10
BATCH = 10


def ts(s):
    return dt.datetime.strptime(s.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)


def fmt(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_line(kind, run, account, now):
    exp = "" if kind == "release" else f" expires={fmt(now + dt.timedelta(minutes=LOCK_MINUTES))}"
    return f"gw-lock {kind} run={run} account={account}{exp}"


def lock_state(comments, now):
    """Return the holder {run, account, expires} or None. Earliest unexpired claim wins.

    Comments are ordered by created_at, then by tracker ref, so two runners that read
    the same list reach the same answer even when their claims land in the same second.
    A release ends that run's claim. A renew extends a claim only while it is live; a claim posted
    after the run's earlier claim expired starts again at its own time.
    """
    events = []
    for c in comments:
        m = LOCK_LINE.search(c.get("body", ""))
        if m:
            kind, run, account, exp = m.groups()
            if account != c["author_account_id"]:
                continue  # a lock line must be posted by the account it names
            events.append((ts(c["created_at"]), str(c["ref"]), kind, run, account, ts(exp) if exp else None))
    events.sort()
    claims = {}
    for when, _ref, kind, run, account, exp in events:
        if kind == "claim":
            # a claim posted after this run's earlier claim expired is a fresh claim, ordered by its own time
            if run not in claims or claims[run]["expires"] <= when:
                claims[run] = {"run": run, "account": account, "at": when, "expires": exp}
        elif kind == "renew" and run in claims and claims[run]["account"] == account:
            # a renew extends only a claim still live when it is posted; a late renew never revives one,
            # so a run that stalled past expiry can't take the lock back from the run that claimed after it
            if when < claims[run]["expires"]:
                claims[run]["expires"] = max(claims[run]["expires"], exp)
        elif kind == "release" and run in claims and claims[run]["account"] == account:
            claims.pop(run)
    live = sorted((c for c in claims.values() if c["expires"] > now), key=lambda c: c["at"])
    return live[0] if live else None


def lock_decision(comments, run, account, now):
    holder = lock_state(comments, now)
    if holder is None:
        return {"decision": "claim", "post": lock_line("claim", run, account, now),
                "then": "re-read lock comments and call lock again; proceed only if you hold it"}
    if holder["run"] == run:
        return {"decision": "held", "expires": fmt(holder["expires"])}
    if holder["account"] == account and holder["run"] != run:
        return {"decision": "held_by_your_other_run", "holder_run": holder["run"],
                "then": "resume that run, or post a release for it before starting this one"}
    return {"decision": "lost", "holder_account": holder["account"], "expires": fmt(holder["expires"]),
            "post": lock_line("release", run, account, now), "then": "post the release if you posted a claim, then stop"}


def preflight(planned, found, manifest, phases, approved_updates=(), relies_on=None):
    """Decide create | skip | adopt | update | adopt_update | link_parent | stop per planned item (spec section 8 table).

    approved_updates: {key: owned_hash} from the verified write list's update_item writes. A written
    item whose planned text differs from what the manifest recorded is updated only when the write
    list names it with exactly the planned hash, and only while the item is not finished; otherwise
    create stops, so an approved edit is never skipped silently and nothing else is ever written."""
    approved_updates = dict(approved_updates) if isinstance(approved_updates, dict) else {k: None for k in approved_updates}
    # relies_on (revise apply): each item the diff read, with its updated_at then. The first preflight of a
    # revise apply passes it, and any change since the diff stops create: diff again. A resume of that
    # same apply leaves it out, because its own writes moved updated_at; the drift rules below still hold.
    moved = []
    by_key_now = {f["key"]: f for f in found}
    for r in relies_on or []:
        now = by_key_now.get(r["key"])
        if now is None or now.get("tracker_id") != r["tracker_id"] or now.get("updated_at") != r["updated_at"]:
            moved.append({"key": r["key"], "why": "changed in the tracker since the revise diff read it "
                          f"(updated {r['updated_at']}, now {(now or {}).get('updated_at', 'missing')}); diff again"})

    def update_problem(p, f):
        bound = approved_updates.get(p["key"])
        if p["key"] not in approved_updates:
            return ("the plan's text for this task differs from what was written, and the approved write "
                    "list has no update for it; revise and approve the change")
        if bound != p["owned_hash"]:
            return "the rendered text differs from the text the approved update binds; render again from the plan of record"
        if f.get("status") in ("done", "closed_not_done"):
            return f"the task is {f['status'].replace('_', ' ')} now, and finished work is not edited; revise with a follow-up task"
        return None
    written = {i["key"]: i for i in (manifest or {}).get("items", [])}
    found_by_key = {}
    dupes = set()
    for f in found:
        if f["key"] in found_by_key:
            dupes.add(f["key"])
        found_by_key[f["key"]] = f
    actions, stops, warnings = [], [], []
    deleted = {p["key"] for p in planned if p["key"] not in found_by_key and p["key"] in written}
    for p in planned:
        key = p["key"]
        in_scope = p["phase"] in phases
        f = found_by_key.get(key)
        w = written.get(key)

        def report(kind, why):
            (stops if in_scope else warnings).append({"key": key, "why": why})
            if in_scope:
                actions.append({"key": key, "action": "stop", "why": why})

        if key in dupes:
            report("stop", "more than one item carries this key")
            continue
        if f is not None and f.get("status") not in STATUSES:
            # the finished-work and closed_not_done rules read status; without it they would pass silently
            report("stop", "the found item has no status from create_steps.py status; read it before preflight")
            continue
        gone = sorted(set(p.get("depends_on", [])) & deleted)
        if in_scope and gone:
            report("stop", f"depends on {', '.join(gone)}, which was written and then deleted by hand; "
                           "never recreated silently, so revise the plan first")
            continue
        creating = {q["key"] for q in planned if q["phase"] in phases}
        unwritten = sorted(d for d in p.get("depends_on", []) if d not in found_by_key and d not in written and d not in creating)
        if in_scope and unwritten:
            report("stop", f"depends on {', '.join(unwritten)}, which is neither written nor in this offer, so its "
                           "dependency link can't be made; write that phase first or offer it with this one")
            continue
        dead = sorted(d for d in p.get("depends_on", []) if found_by_key.get(d, {}).get("status") == "closed_not_done")
        if in_scope and dead:
            report("stop", f"depends on {', '.join(dead)}, which was closed without being done; "
                           "a closed_not_done task never satisfies a dependency, so revise to re-point it")
            continue
        if f is None and w is None:
            if in_scope:
                actions.append({"key": key, "action": "create"})
                if p.get("waits"):
                    actions.append({"key": key, "action": "set_blocked", "tracker_id": None, "why": "after create"})
            continue
        if f is None and w is not None:
            report("stop", "manifest says written but no item has this key: deleted or moved; never recreated silently")
            continue
        if w is None:
            if f["owned_hash"] == p["owned_hash"]:
                if in_scope:
                    actions.append({"key": key, "action": "adopt", "tracker_id": f["tracker_id"],
                                    "why": "written before the last manifest (crash between write and manifest)"})
            else:
                report("stop", "an item with this key exists that Groundwork never recorded and it differs from the plan: drift")
                continue
        elif f["owned_hash"] != w["owned_hash"]:
            if in_scope and f["owned_hash"] == p["owned_hash"] and update_problem(p, f) is None:
                # the approved update reached the tracker, but the session ended before the manifest
                actions.append({"key": key, "action": "adopt_update", "tracker_id": f["tracker_id"]})
            else:
                report("stop", "a person changed a plan-owned field since it was written: drift")
                continue
        elif in_scope and p["owned_hash"] != w["owned_hash"]:
            why = update_problem(p, f)
            if why:
                report("stop", why)
                continue
            actions.append({"key": key, "action": "update", "tracker_id": f["tracker_id"]})
        elif in_scope:
            actions.append({"key": key, "action": "skip", "tracker_id": f["tracker_id"]})
        if in_scope and p.get("waits") and not (w or {}).get("blocked_set"):
            # Applied once, keyed (key + "blocked"); never reapplied after a person cleared it.
            actions.append({"key": key, "action": "set_blocked", "tracker_id": f["tracker_id"]})
        if in_scope and not f.get("under_epic", True):
            actions.append({"key": key, "action": "link_parent", "tracker_id": f["tracker_id"], "why": "found outside the epic"})
        if f.get("points", 1) > 1 and w is not None and not w.get("split_comment"):
            # A comment, not a change: posted once, whatever phase is being written, and recorded in the manifest.
            # Points a person set are never changed.
            actions.append({"key": key, "action": "comment_split", "tracker_id": f["tracker_id"],
                            "why": f"a person set {f['points']} points; keep them and recommend a split"})
    stops = moved + stops
    if moved:
        actions = [{"key": m["key"], "action": "stop", "why": m["why"]} for m in moved] + actions
    return {"ok": not stops, "actions": actions, "stops": stops, "warnings": warnings}


def read_status(raw, written, field_map):
    """What a tracker item's state means (section 2 of the planning model).

    A Groundwork close counts only when the manifest records it (an intent or a
    finished close) and either the gw-closed label for that reason is on the item
    or the manifest says the transition happened. A gw-closed label with no
    manifest record is ignored, so a person can't turn a not-planned close into
    done, or done into not-planned, by adding a label. Any other close reads by
    the tracker's own status, resolution or close reason against
    field_map.statuses.closed_not_done.
    """
    prefix = field_map.get("close_label_prefix", DEFAULT_CLOSE_PREFIX)
    labels = {lab[len(prefix):] for lab in raw.get("labels", []) if lab.startswith(prefix)}
    close = (written or {}).get("close")
    ours = close["reason"] if close and (close["reason"] in labels or close["state"] == "closed") else None
    if raw["state"] == "closed":
        if ours:
            status = "done" if ours == "completed" else "closed_not_done"
        else:
            names = set(raw.get("closed_as", []))
            status = "closed_not_done" if names & set(field_map["statuses"]["closed_not_done"]) else "done"
        return {"key": raw["key"], "status": status, "close_pending": False, "drift": None}
    category = raw.get("category", "todo")
    if close and close["state"] == "closed":
        return {"key": raw["key"], "status": category, "close_pending": False,
                "drift": "reopened after Groundwork closed it"}
    return {"key": raw["key"], "status": category, "close_pending": bool(close), "drift": None}


def close_steps(closes, manifest, found):
    """Ordered steps to close items: intent in the manifest first, as a batch of its own,
    then for each item the gw-closed label and the transition, then the manifest again.

    found: [{key, tracker_id, status, close_pending?}] from status. An item already
    closed is skipped (a person's close is never relabelled). Close never deletes.
    """
    written = {i["key"]: i for i in (manifest or {}).get("items", [])}
    by_key = {f["key"]: f for f in found}
    intents, per_item, skipped, stops = [], [], [], []
    for c in closes:
        key, reason = c["key"], c["reason"]
        if reason not in CLOSE_REASONS:
            stops.append({"key": key, "why": f"unknown close reason '{reason}'"})
            continue
        f = by_key.get(key)
        if f is None or key not in written:
            stops.append({"key": key, "why": "no written item with this key; only items Groundwork wrote are closed"})
            continue
        if f["status"] in ("done", "closed_not_done") and not f.get("close_pending"):
            skipped.append({"key": key, "why": f"already {f['status']}"})
            continue
        prior = written[key].get("close")
        if prior and prior["reason"] != reason:
            stops.append({"key": key, "why": f"a close as {prior['reason']} is already recorded; finish or revise it first"})
            continue
        if not prior:
            intents.append({"key": key, "reason": reason})
        per_item.append({"key": key, "tracker_id": f["tracker_id"], "reason": reason})
    steps = []
    if intents:
        steps.append({"step": "manifest_intent", "items": intents})
    for it in per_item:
        steps.append({"step": "add_label", **it})
        steps.append({"step": "transition", **it,
                      "then": "if the tracker needs a person (no direct transition, a screen field, more than one hop), "
                              "stop and name the item; it stays close pending"})
    if per_item:
        steps.append({"step": "manifest_closed", "keys": [it["key"] for it in per_item]})
    return {"ok": not stops, "steps": steps, "skipped": skipped, "stops": stops}


def plan_level_recheck(context, open_items):
    """Plan-level create re-reads list_children and find_by_key and stops if an open
    plan-owned item exists that the stored proposal context did not list (for example
    one another set created after this proposal). open_items: [{key}] open now."""
    known = {i["key"] for i in context["items"]}
    new = sorted(i["key"] for i in open_items if i["key"] not in known)
    if new:
        return {"ok": False, "new_items": new, "then": "re-propose: the epic changed after this proposal was made"}
    return {"ok": True, "new_items": []}


def scope_limit(overlay, requested=None):
    """read_scope's limit: at most 200, lowered by the overlay or the runner, never raised."""
    limit = min(READ_SCOPE_MAX, overlay.get("skills", {}).get("tracker", {}).get("read_scope_limit", READ_SCOPE_MAX))
    if requested is not None:
        limit = min(limit, requested)
    return limit


def scope_decision(count, overlay, requested=None):
    limit = scope_limit(overlay, requested)
    if count > limit:
        return {"ok": False, "count": count, "limit": limit,
                "then": "the scope is too large; ask the runner to narrow it (one epic, or a tighter filter) and read again"}
    return {"ok": True, "count": count, "limit": limit}


_KEEP = object()


CLOSE_ORDER = {"intent": 0, "closed": 1}


def status_file_problems(prior, sf):
    """Once a manifest names a retire status file, every later one carries it; only its state may
    move, from intent to recorded."""
    if prior is None:
        return
    same = lambda x: {k: v for k, v in (x or {}).items() if k != "state"}
    if sf is None or same(prior) != same(sf):
        raise ValueError("the status_file differs from the one the previous manifest names; "
                         "only its state may move from intent to recorded")
    if prior["state"] == "recorded" and sf["state"] != "recorded":
        raise ValueError("a recorded status file never goes back to intent")


def successor_problems(prev, m):
    """Every rule make_manifest enforces when writing, checked again when reading the chain, so a
    manifest edited by hand (with its self-hash recomputed) is refused at every read."""
    try:
        if m["plan_id"] != prev["plan_id"]:
            raise ValueError(f"names plan {m['plan_id']}, not {prev['plan_id']}")
        status_file_problems(prev.get("status_file"), m.get("status_file"))
        item_history_problems(prev["items"], m["items"])
    except ValueError as e:
        return [str(e)]
    return []


def item_history_problems(prev_items, items):
    """Third review, finding 7: a manifest is the record of what Groundwork wrote and did once. A later
    manifest keeps every item the previous one records, under the same tracker id, and never forgets a
    close, a blocked flag applied or a split comment posted (each would be redone or lost on resume)."""
    now = {i["key"]: i for i in items}
    for p in prev_items:
        n = now.get(p["key"])
        if n is None:
            raise ValueError(f"the manifest drops {p['key']}, which the previous manifest records")
        if n["tracker_id"] != p["tracker_id"]:
            raise ValueError(f"{p['key']} moved from tracker item {p['tracker_id']} to {n['tracker_id']}")
        for flag in ("blocked_set", "split_comment"):
            if p.get(flag) and not n.get(flag):
                raise ValueError(f"the manifest clears {flag} on {p['key']}; it records something already done once")
        pc, nc = p.get("close"), n.get("close")
        if pc and (not nc or nc["reason"] != pc["reason"] or CLOSE_ORDER[nc["state"]] < CLOSE_ORDER[pc["state"]]):
            raise ValueError(f"the manifest changes or clears the recorded close of {p['key']}")


def make_manifest(prev, items, plan_id, run, seq, now, relies_on, status_file=_KEEP):
    """status_file: the retire record to set; by default it is carried forward from prev, so a later
    manifest can never drop a recorded or intended status file."""
    m = {"schema_version": "1.0", "plan_id": plan_id, "seq": seq, "prev_hash": prev["hash"] if prev else None,
         "written_at": fmt(now), "run_id": run, "relies_on": relies_on, "items": items}
    prior = (prev or {}).get("status_file")
    sf = prior if status_file is _KEEP else status_file
    status_file_problems(prior, sf)
    if sf is not None:
        m["status_file"] = sf
    if prev:
        item_history_problems(prev["items"], items)
    if prev and seq != prev["seq"] + 1:
        raise ValueError("manifest seq must be the previous seq + 1")
    if not prev and seq != 1:
        raise ValueError("the first manifest is seq 1")
    m["hash"] = item_hash(m)
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["lock", "preflight", "manifest", "status", "close", "scope", "recheck"])
    ap.add_argument("--overlay")
    ap.add_argument("--limit", type=int)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--run")
    ap.add_argument("--account")
    ap.add_argument("--now")
    ap.add_argument("--phases")
    ap.add_argument("--plan-id")
    ap.add_argument("--seq", type=int)
    ap.add_argument("--relies-on")
    ap.add_argument("--write-list", help="preflight: the verified write list (its update_item writes)")
    ap.add_argument("--status-file", help="manifest: the retire status_file entry to set (JSON, from retire.py status "
                                         "or with state recorded); omitted, it is carried forward from the previous manifest")
    a = ap.parse_args(argv)
    J = lambda p: None if p == "-" else json.load(open(p, encoding="utf-8"))
    if a.cmd == "lock":
        out = lock_decision(J(a.files[0]), a.run, a.account, ts(a.now))
    elif a.cmd == "preflight":
        if not a.write_list:
            print(json.dumps({"ok": False, "problems": ["--write-list required: preflight updates only what it approves"]}))
            return 1
        wl = J(a.write_list)
        phases = [x.strip() for x in (a.phases or "").split(",") if x.strip()]
        if sorted(phases) != sorted(wl.get("phases", [])):
            # the phases written are exactly the phases the verified write list offers (fourth review, M8)
            print(json.dumps({"ok": False, "problems": [f"--phases {','.join(phases) or '(none)'} is not the verified write "
                                                        f"list's offer ({','.join(wl.get('phases', [])) or 'none'})"]}))
            return 1
        ups = {w["key"]: w["owned_hash"] for w in wl["writes"] if w["kind"] == "update_item"}
        out = preflight(J(a.files[0]), J(a.files[1]), J(a.files[2]), phases, ups,
                        J(a.relies_on) if a.relies_on else None)
    elif a.cmd == "status":
        import gw_yaml
        fm = gw_yaml.load(a.overlay)["skills"]["tracker"]["field_map"]
        written = {i["key"]: i for i in (J(a.files[1]) or {}).get("items", [])}
        out = {"items": [read_status(r, written.get(r["key"]), fm) for r in J(a.files[0])]}
    elif a.cmd == "close":
        out = close_steps(J(a.files[0]), J(a.files[1]), J(a.files[2]))
    elif a.cmd == "recheck":
        out = plan_level_recheck(J(a.files[0]), J(a.files[1]))
    elif a.cmd == "scope":
        import gw_yaml
        out = scope_decision(int(a.files[0]), gw_yaml.load(a.overlay), a.limit)
    else:
        try:
            out = make_manifest(J(a.files[0]), J(a.files[1]), a.plan_id, a.run, a.seq, ts(a.now),
                                J(a.relies_on) if a.relies_on else [],
                                status_file=J(a.status_file) if a.status_file else _KEEP)
        except ValueError as e:
            print(json.dumps({"ok": False, "problems": [str(e)]}, indent=2))
            return 1
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok", True) and out.get("decision") not in ("lost",) else 1


if __name__ == "__main__":
    sys.exit(main())
