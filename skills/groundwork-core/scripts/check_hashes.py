#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Every Groundwork hash and the checks built on them. The model never
computes a hash; it runs this script and reports what it prints.

Usage:
  check_hashes.py summary PLAN.json
  check_hashes.py view PLAN.json --evidence DIR [--rules RULES.json ...] --out BUNDLE.json
  check_hashes.py review REVIEW.json --bundle BUNDLE.json
  check_hashes.py approvals PLAN.json --overlay OVERLAY.yaml --anchor ANCHOR.json
                  --comments COMMENTS.json --proposal proposal.md --write-list WL.json
                  --review REVIEW.json --phases P0,P1 --now 2026-11-15T00:00:00Z
  check_hashes.py manifest-chain MANIFEST.json [MANIFEST.json ...]
  check_hashes.py owned FIELDS.json            plan-owned hash of normalized item fields

COMMENTS.json is what the tracker skill's read procedure returns for epic
comments: [{ref, author_account_id, created_at, updated_at, body}].
ANCHOR.json is the latest admin-authored overlay record read from the anchor
issue: {overlay_id, version, hash, gates: {gate_id: [account ids]}, author_account_id}.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402
from gw_canon import hash_value, sha256_hex  # noqa: E402
from gw_hash import item_hash, phase_hashes, plan_hash, review_hash, view_bundle, view_hash, write_list_hash  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402

CHECKLIST_VERSION = "1.0"
APPROVAL_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def ts(s):
    return dt.datetime.strptime(s.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)


def load_evidence(path):
    out = []
    for root, _d, files in os.walk(path):
        for n in sorted(files):
            if n.endswith(".json") and n != "manifest.json":
                d = json.load(open(os.path.join(root, n), encoding="utf-8"))
                out.extend(d if isinstance(d, list) else [d])
    return out


def owned_hash(fields):
    """fields = {title, body_owned, role_key, phase, key} as read back by the tracker skill's normalize."""
    want = ("title", "body_owned", "role_key", "phase", "key")
    missing = [k for k in want if k not in fields]
    if missing:
        raise ValueError(f"normalized fields missing {missing}")
    norm = {k: fields[k] for k in want}
    lines = [line.rstrip() for line in norm["body_owned"].replace("\r\n", "\n").strip().split("\n")]
    # A person ticking a checklist step is progress, not drift.
    lines = [re.sub(r"^- \[[xX]\] ", "- [ ] ", line) for line in lines]
    norm["body_owned"] = "\n".join(lines)
    norm["title"] = " ".join(norm["title"].split())
    return hash_value(norm)


def verify_approvals(plan, overlay, anchor, comments, proposal_text, wl, review, phases, now, unverified_writer):
    """Return (ok, problems, accepted_phases). Implements section 8 of the spec."""
    probs = []
    schema = load_schema("approval")
    if anchor["overlay_id"] != overlay["id"] or anchor["version"] != overlay["version"] or anchor["hash"] != overlay.get("hash"):
        probs.append("the loaded overlay does not match the latest admin-anchored overlay record (CR-12)")
    if anchor.get("author_account_id") not in {a["account_id"] for a in overlay["admins"]}:
        probs.append("the anchored overlay record was not authored by an overlay admin")
    p_hash = plan_hash(plan)
    ph = phase_hashes(plan)
    prop_hash = sha256_hex(proposal_text.encode("utf-8"))
    wl_hash = write_list_hash(wl)
    r_hash = review_hash(review)
    gates = {g["id"]: g for g in overlay["approval_gates"]}
    window = overlay.get("create_window_days", 3)
    records = []
    for c in comments:
        m = APPROVAL_BLOCK.search(c.get("body", ""))
        if not m:
            continue
        try:
            rec = json.loads(m.group(1))
        except ValueError:
            probs.append(f"comment {c['ref']}: approval block is not valid JSON")
            continue
        if rec.get("plan_id") != plan["id"]:
            continue
        errs = validate(rec, schema)
        if errs:
            probs.append(f"comment {c['ref']}: {errs[0]}")
            continue
        if c["updated_at"] != c["created_at"]:
            probs.append(f"comment {c['ref']} was edited after it was posted; edited approvals are refused")
            continue
        if c["author_account_id"] != rec["approver"]["account_id"]:
            probs.append(f"comment {c['ref']} names approver {rec['approver']['account_id']} but was posted by {c['author_account_id']}")
            continue
        gate = gates.get(rec["gate"])
        anchored = set(anchor.get("gates", {}).get(rec["gate"], []))
        if not gate or c["author_account_id"] not in {a["account_id"] for a in gate["approvers"]} or c["author_account_id"] not in anchored:
            probs.append(f"comment {c['ref']}: {c['author_account_id']} is not an anchored approver on gate {rec['gate']}")
            continue
        stale = []
        if rec["plan_hash"] != p_hash:
            stale.append("plan_hash")
        for pid in rec["phases"]:
            if rec["phase_hashes"].get(pid) != ph.get(pid):
                stale.append(f"phase_hashes.{pid}")
        if rec["proposal_hash"] != prop_hash:
            stale.append("proposal_hash")
        if rec["write_list_hash"] != wl_hash:
            stale.append("write_list_hash")
        if rec["review_hash"] != r_hash:
            stale.append("review_hash")
        if rec["view_hash"] != review["view_hash"]:
            stale.append("view_hash")
        if stale:
            probs.append(f"comment {c['ref']}: does not match the current plan ({', '.join(stale)}); the approval is void")
            continue
        if unverified_writer and not rec["accept_unverified_writer"]:
            probs.append(f"comment {c['ref']}: the tracker skill is unverified on this surface and the record does not accept that")
            continue
        if (now - ts(c["created_at"])).days >= window:
            probs.append(f"comment {c['ref']}: older than create_window_days ({window}); approvers must post fresh records")
            continue
        records.append((c, rec, gate))
    accepted = set()
    for pid in phases:
        for gid, gate in gates.items():
            if gate["applies_to"] != "all_phases":
                continue
            who = {c["author_account_id"] for c, rec, g in records if g["id"] == gid and pid in rec["phases"] and rec["kind"] != "exception"}
            if len(who) >= gate.get("min_approvers", 1):
                accepted.add(pid)
        if pid not in accepted:
            probs.append(f"phase {pid} has no valid approval quorum")
    needed_ex = {t["exception"]["id"] for t in plan["tasks"] if t["phase"] in phases and t["exception"]}
    ok_ex = set()
    for c, rec, gate in records:
        if gate["applies_to"] == "one_day_exceptions":
            ok_ex.update(rec["exceptions_accepted"])
        elif rec["exceptions_accepted"]:
            probs.append(f"comment {c['ref']}: a phase-release record cannot accept an exception; use the exception gate")
    for ex in sorted(needed_ex - ok_ex):
        probs.append(f"exception {ex} has not been accepted on the exception gate")
    return (not probs), probs, sorted(accepted)


def verify_chain(manifests):
    """Latest manifest = highest seq whose prev_hash chain back to seq 1 is intact."""
    schema = load_schema("manifest")
    by_seq = {}
    probs = []
    for m in manifests:
        errs = validate(m, schema)
        if errs:
            probs.append(f"manifest seq {m.get('seq')}: {errs[0]}")
            continue
        if item_hash(m) != m["hash"]:
            probs.append(f"manifest seq {m['seq']}: hash does not match contents (edited after writing)")
            continue
        by_seq[m["seq"]] = m
    latest = None
    seq = 1
    prev = None
    while seq in by_seq:
        m = by_seq[seq]
        if m["prev_hash"] != prev:
            probs.append(f"manifest seq {seq}: prev_hash does not match seq {seq - 1}; chain broken")
            break
        latest = m
        prev = m["hash"]
        seq += 1
    return latest, probs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["summary", "view", "review", "approvals", "manifest-chain", "owned"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--evidence")
    ap.add_argument("--rules", action="append", default=[])
    ap.add_argument("--bundle")
    ap.add_argument("--overlay")
    ap.add_argument("--anchor")
    ap.add_argument("--comments")
    ap.add_argument("--proposal")
    ap.add_argument("--write-list")
    ap.add_argument("--review")
    ap.add_argument("--phases")
    ap.add_argument("--now")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    J = lambda p: json.load(open(p, encoding="utf-8"))
    if a.cmd == "summary":
        plan = J(a.files[0])
        print(json.dumps({"plan_id": plan["id"], "version": plan["version"], "plan_hash": plan_hash(plan), "phase_hashes": phase_hashes(plan)}, indent=2))
        return 0
    if a.cmd == "view":
        plan = J(a.files[0])
        rules = [r for p in a.rules for r in J(p).get("rules", [])]
        bundle = view_bundle(plan, load_evidence(a.evidence), CHECKLIST_VERSION, rules)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
        print(view_hash(bundle))
        return 0
    if a.cmd == "review":
        rev = J(a.files[0])
        errs = validate(rev, load_schema("review"))
        bh = view_hash(J(a.bundle))
        if errs:
            print("\n".join(errs))
            return 1
        if rev["view_hash"] != bh:
            print(f"review was made from a different reviewer view ({rev['view_hash'][:12]} vs {bh[:12]}); it does not count")
            return 1
        print(review_hash(rev))
        return 0
    if a.cmd == "approvals":
        plan = J(a.files[0])
        overlay = gw_yaml.load(a.overlay)
        proposal_text = open(a.proposal, encoding="utf-8").read()
        unverified = any(s["verified"] != "verified" and s["name"] == overlay["skills"]["tracker"]["skill"] for s in plan["stamps"]["skills"])
        ok, probs, accepted = verify_approvals(plan, overlay, J(a.anchor), J(a.comments), proposal_text, J(a.write_list), J(a.review),
                                               [x.strip() for x in a.phases.split(",")], ts(a.now), unverified)
        print(json.dumps({"ok": ok, "accepted_phases": accepted, "problems": probs}, indent=2))
        return 0 if ok else 1
    if a.cmd == "manifest-chain":
        latest, probs = verify_chain([J(p) for p in a.files])
        print(json.dumps({"latest_seq": latest["seq"] if latest else None, "problems": probs}, indent=2))
        return 0 if not probs else 1
    if a.cmd == "owned":
        print(owned_hash(J(a.files[0])))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
