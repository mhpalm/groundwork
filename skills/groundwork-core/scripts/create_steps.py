#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Mechanical decisions for create: lock winner, preflight actions, manifests.

The tracker skill does the reads and writes; this script decides what they
mean, so the decision is the same on every tracker and every surface.

Usage:
  create_steps.py lock LOCK_COMMENTS.json --run RUN_ID --account ACCOUNT --now TS
  create_steps.py preflight PLANNED.json FOUND.json MANIFEST.json --phases P1,P2
  create_steps.py manifest PREV_MANIFEST.json|- ITEMS.json --plan-id ID --run RUN_ID --seq N --now TS [--relies-on REFS.json]

LOCK_COMMENTS: [{ref, author_account_id, created_at, body}] where body holds
  a gw-lock line: "gw-lock claim|renew|release run=<id> account=<id> expires=<ts>".
PLANNED: [{key, phase, owned_hash, points, depends_on?: [keys]}]   (owned_hash from check_hashes.py owned)
FOUND:   [{key, tracker_id, owned_hash, under_epic, points}]   (find_by_key across the project, cross-checked by list_children)
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gw_hash import item_hash  # noqa: E402

LOCK_LINE = re.compile(r"gw-lock (claim|renew|release) run=(\S+) account=(\S+)(?: expires=(\S+))?")
LOCK_MINUTES = 30
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
    A release ends that run's claim; a renew extends only the current holder.
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
            claims.setdefault(run, {"run": run, "account": account, "at": when, "expires": exp})
        elif kind == "renew" and run in claims and claims[run]["account"] == account:
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


def preflight(planned, found, manifest, phases):
    """Decide create | skip | adopt | link_parent | stop per planned item (spec section 8 table)."""
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
        gone = sorted(set(p.get("depends_on", [])) & deleted)
        if in_scope and gone:
            report("stop", f"depends on {', '.join(gone)}, which was written and then deleted by hand; "
                           "never recreated silently, so revise the plan first")
            continue
        if f is None and w is None:
            if in_scope:
                actions.append({"key": key, "action": "create"})
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
            report("stop", "a person changed a plan-owned field since it was written: drift")
            continue
        elif in_scope:
            actions.append({"key": key, "action": "skip", "tracker_id": f["tracker_id"]})
        if in_scope and not f.get("under_epic", True):
            actions.append({"key": key, "action": "link_parent", "tracker_id": f["tracker_id"], "why": "found outside the epic"})
        if f.get("points", 1) > 1 and w is not None and not w.get("split_comment"):
            # A comment, not a change: posted once, whatever phase is being written, and recorded in the manifest.
            # Points a person set are never changed.
            actions.append({"key": key, "action": "comment_split", "tracker_id": f["tracker_id"],
                            "why": f"a person set {f['points']} points; keep them and recommend a split"})
    return {"ok": not stops, "actions": actions, "stops": stops, "warnings": warnings}


def make_manifest(prev, items, plan_id, run, seq, now, relies_on):
    m = {"schema_version": "1.0", "plan_id": plan_id, "seq": seq, "prev_hash": prev["hash"] if prev else None,
         "written_at": fmt(now), "run_id": run, "relies_on": relies_on, "items": items}
    if prev and seq != prev["seq"] + 1:
        raise ValueError("manifest seq must be the previous seq + 1")
    if not prev and seq != 1:
        raise ValueError("the first manifest is seq 1")
    m["hash"] = item_hash(m)
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["lock", "preflight", "manifest"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--run")
    ap.add_argument("--account")
    ap.add_argument("--now")
    ap.add_argument("--phases")
    ap.add_argument("--plan-id")
    ap.add_argument("--seq", type=int)
    ap.add_argument("--relies-on")
    a = ap.parse_args(argv)
    J = lambda p: None if p == "-" else json.load(open(p, encoding="utf-8"))
    if a.cmd == "lock":
        out = lock_decision(J(a.files[0]), a.run, a.account, ts(a.now))
    elif a.cmd == "preflight":
        out = preflight(J(a.files[0]), J(a.files[1]), J(a.files[2]), [x.strip() for x in a.phases.split(",")])
    else:
        out = make_manifest(J(a.files[0]), J(a.files[1]), a.plan_id, a.run, a.seq, ts(a.now), J(a.relies_on) if a.relies_on else [])
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok", True) and out.get("decision") not in ("lost",) else 1


if __name__ == "__main__":
    sys.exit(main())
