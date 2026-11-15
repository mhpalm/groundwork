#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Every Groundwork hash and the checks built on them. The model never
computes a hash; it runs this script and reports what it prints.

Usage:
  check_hashes.py summary PLAN.json
  check_hashes.py view PLAN.json --evidence DIR [--rules RULES.json ...] --out BUNDLE.json
  check_hashes.py review REVIEW.json --bundle BUNDLE.json
  check_hashes.py view PLAN.json --plan-level --write-list WL.json --context CONTEXT.json [--assessment A.json] --out BUNDLE.json
  check_hashes.py approvals PLAN.json --overlay OVERLAY.yaml --anchor ANCHOR.json
                  --comments COMMENTS.json --proposal proposal.md --write-list WL.json
                  --review REVIEW.json --phases P0,P1 --now 2026-11-15T00:00:00Z
                  --latest-version N --manifests M_1.json ... M_n.json --status STATUS.json|- --epic open|closed
                  --evidence DIR [--rules RULES.json ...]
  check_hashes.py plan-level PLAN.json  (the same flags, without --phases, plus --context CONTEXT.json
                  [--assessment A.json]: the stored inputs the proposal is re-rendered from)
  check_hashes.py manifest-chain MANIFEST.json [MANIFEST.json ...] --plan-id ID   (any problem stops the run)
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
from gw_hash import (item_hash, phase_hashes, plan_bundle_kinds, plan_hash, plan_level_bundle, review_hash,  # noqa: E402
                     view_bundle, view_hash, write_list_hash)
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


PHASE_KINDS = ("initial", "release", "revision", "exception")
# Plan-level kinds: decline, own_epic and retire change no plan version; later stores a new
# version that adds only outline content and offers no phase (planning model 4.3).
PLAN_LEVEL_KINDS = ("decline", "own_epic", "retire", "later")


def _approval_set(plan, overlay, anchor, comments, proposal_text, wl, review, now, unverified_writer, info,
                  latest_stored_version, scope, plan_state=None):
    """The records of one approval set, after every per-record check. Returns (records, problems).

    The grouping filter runs first: a record counts toward this set only when its
    plan_id, plan_version and proposal_hash match. Every other record is reported
    in `info` (superseded, another proposal at this version, or unreadable) and is
    never a problem, so a malformed or edited record in another set cannot fail
    this one. A record in this set that fails any later check is a problem.
    """
    probs = []
    if overlay.get("provisional"):
        return [], ["a provisional overlay names no approvers; set up Groundwork for the tracker first (D-54)"]
    resuming_writes = False
    if plan_state is not None:
        # the retire gate (planning model 7): a retired plan, a retire in progress or a closed epic
        # refuses every set except the resume of the retire's own set
        import retire
        sf = (plan_state.get("manifest") or {}).get("status_file")
        own = (plan["version"], sha256_hex(proposal_text.encode("utf-8")))
        if scope == "plan_level" and sf:
            g = retire.gate("resume", plan, plan_state.get("manifest"), plan_state.get("status"), plan_state["epic"], own)
            # the retire's own set already started writing under a valid approval: its resume is not
            # held to the create window, or a crash could leave the plan stuck mid-retire for good
            resuming_writes = g["ok"] and g.get("resume_of_retire", False)
        else:
            g = retire.gate("create" if scope == "phases" else "retire", plan, plan_state.get("manifest"),
                            plan_state.get("status"), plan_state["epic"])
        if not g["ok"]:
            return [], g["problems"]
    if latest_stored_version is not None and latest_stored_version > plan["version"]:
        return [], [f"plan version {latest_stored_version} is stored, so every pending set at version {plan['version']} "
                    "is void; re-propose against the current version"]
    if anchor["overlay_id"] != overlay["id"] or anchor["version"] != overlay["version"] or anchor["hash"] != overlay.get("hash"):
        bound = plan.get("overlay", {})
        if resuming_writes and bound.get("id") == overlay["id"] and bound.get("hash") == overlay.get("hash"):
            # thirteenth review, M3: an admin published a new overlay while the retire was in progress. The
            # retire can't be drafted again, so its resume runs with the overlay the plan binds; approvers
            # are still checked against both that overlay's gates and the latest anchor's
            info.append("the overlay changed since this retire started; its resume runs with the overlay the plan binds (CR-12)")
        else:
            probs.append("the loaded overlay does not match the latest admin-anchored overlay record (CR-12)"
                         + ("; on a retire resume, load the overlay the plan binds, or have an admin anchor an overlay "
                            "that renders the same write list" if resuming_writes else ""))
    if anchor.get("author_account_id") not in {a["account_id"] for a in overlay["admins"]}:
        probs.append("the anchored overlay record was not authored by an overlay admin")
    schema = load_schema("approval")
    p_hash = plan_hash(plan)
    ph = phase_hashes(plan)
    prop_hash = sha256_hex(proposal_text.encode("utf-8"))
    wl_hash = write_list_hash(wl)
    r_hash = review_hash(review)
    gates = {g["id"]: g for g in overlay["approval_gates"]}
    window = overlay.get("create_window_days", 3)
    records = []
    # thirteenth review, M2: on the resume of a retire whose writes started, a record in this set that fails a
    # per-record check (edited, copied by another account, wrong scope) is not counted and is reported, never
    # a stop: no new set can be proposed, so a fresh record from an approver must be able to reach quorum
    bad = info if resuming_writes else probs
    rec_note = " (not counted; post a fresh record)" if resuming_writes else ""
    for c in comments:
        m = APPROVAL_BLOCK.search(c.get("body", ""))
        if not m:
            continue
        try:
            rec = json.loads(m.group(1))
        except ValueError:
            info.append(f"comment {c['ref']}: an approval block that is not valid JSON was ignored")
            continue
        if not isinstance(rec, dict) or rec.get("plan_id") != plan["id"]:
            continue
        if rec.get("plan_version") != plan["version"]:
            info.append(f"comment {c['ref']}: approval for plan version {rec.get('plan_version')} is superseded by version {plan['version']}")
            continue
        if rec.get("proposal_hash") != prop_hash:
            info.append(f"comment {c['ref']}: approval belongs to another proposal at version {plan['version']}")
            continue
        errs = validate(rec, schema)
        if errs:
            bad.append(f"comment {c['ref']}: {errs[0]}" + rec_note)
            continue
        if c["updated_at"] != c["created_at"]:
            bad.append(f"comment {c['ref']} was edited after it was posted; edited approvals are refused" + rec_note)
            continue
        if c["author_account_id"] != rec["approver"]["account_id"]:
            bad.append(f"comment {c['ref']} names approver {rec['approver']['account_id']} but was posted by {c['author_account_id']}" + rec_note)
            continue
        gate = gates.get(rec["gate"])
        anchored = set(anchor.get("gates", {}).get(rec["gate"], []))
        if not gate or c["author_account_id"] not in {a["account_id"] for a in gate["approvers"]} or c["author_account_id"] not in anchored:
            bad.append(f"comment {c['ref']}: {c['author_account_id']} is not an anchored approver on gate {rec['gate']}" + rec_note)
            continue
        rec_scope = rec.get("scope", "phases")
        if scope == "plan_level":
            if rec_scope != "plan_level" or rec["kind"] not in PLAN_LEVEL_KINDS or rec["phases"]:
                bad.append(f"comment {c['ref']}: a plan-level set takes only plan_level records with no phases "
                             f"(found {rec_scope}, {rec['kind']})" + rec_note)
                continue
        elif rec_scope != "phases" or rec["kind"] not in PHASE_KINDS:
            bad.append(f"comment {c['ref']}: a phase set takes only phase records (found {rec_scope}, {rec['kind']})" + rec_note)
            continue
        elif rec["kind"] != "exception" and sorted(rec["phases"]) != sorted(wl.get("phases", [])):
            # a record approves the whole offer; a smaller offer is a new proposal with its own write list
            bad.append(f"comment {c['ref']}: approves {', '.join(rec['phases']) or 'no phase'}, but the offer is "
                         f"{', '.join(wl.get('phases', []))}; a record approves the whole offer, so propose again to offer less" + rec_note)
            continue
        stale = []
        if rec["plan_hash"] != p_hash:
            stale.append("plan_hash")
        for pid in rec["phases"]:
            if rec["phase_hashes"].get(pid) != ph.get(pid):
                stale.append(f"phase_hashes.{pid}")
        if rec["write_list_hash"] != wl_hash:
            stale.append("write_list_hash")
        if rec["review_hash"] != r_hash:
            stale.append("review_hash")
        if rec["view_hash"] != review["view_hash"]:
            stale.append("view_hash")
        if stale:
            bad.append(f"comment {c['ref']}: does not match the current plan ({', '.join(stale)}); the approval is void" + rec_note)
            continue
        if unverified_writer and not rec["accept_unverified_writer"]:
            bad.append(f"comment {c['ref']}: the tracker skill is unverified on this surface and the record does not accept that" + rec_note)
            continue
        if (now - ts(c["created_at"])).days >= window and not resuming_writes:
            # an expired record is information, never a problem: fresh records for the same proposal
            # can still reach quorum, so a crashed create can be finished after the window
            info.append(f"comment {c['ref']}: older than create_window_days ({window}); not counted, post a fresh record")
            continue
        records.append((c, rec, gate))
    return records, probs


def _same_review(a, b):
    return bool(a) and bool(b) and a.get("view_hash") == b.get("view_hash") and a.get("findings") == b.get("findings")


def rebuilt_write_list_problems(plan, overlay, wl, manifest=None):
    """A phase write list is rebuilt from the plan of record and the closes, edits and change-request
    entry it carries, and must come out identical: nothing else can be slipped into it. With the latest
    manifest, it must also close every written task the plan no longer has (seventh review, M1)."""
    import render_proposal
    if manifest is not None:
        from revise_diff import derived_writes, required_closes
        named = {w["key"] for w in wl.get("writes", []) if w.get("kind") == "close_item"}
        missing = [c["key"] for c in required_closes(plan, manifest) if c["key"] not in named]
        if missing:
            return ["the write list leaves open written tasks the plan of record no longer has: " + ", ".join(missing)
                    + "; diff against the latest manifest and render it again"]
        # the relinks and unblocks the manifest implies are required too, exactly (eighth review, M2)
        d = derived_writes(plan, manifest)
        offered = set(wl.get("phases", []))
        phase_of = {t["id"]: t["phase"] for t in plan["tasks"]}
        key = lambda tid: f"gw:{plan['id']}:{tid}"
        want = {("unlink_dependency", key(r["task"]), key(x)) for r in d["relinks"] for x in r["removed"]}
        want |= {("link_dependency", key(r["task"]), key(x)) for r in d["relinks"] for x in r["added"]
                 if phase_of[r["task"]] not in offered}
        want |= {("clear_blocked", key(t), None) for t in d["unblocks"]}
        got = {(w["kind"], w["key"], w.get("blocked_by")) for w in wl.get("writes", [])
               if w.get("scope") == "plan" and w.get("kind") in ("unlink_dependency", "link_dependency", "clear_blocked")}
        # a write the manifest already shows as landed is this set's own, on a resume (eleventh review, M3)
        import create_steps
        written = {w["key"]: w for w in manifest.get("items", [])}
        links = lambda k: {lk["to_key"] for lk in (written.get(k) or {}).get("links", []) if lk["type"] == "blocked_by"}
        landed = {g for g in got - want if (g[0] == "unlink_dependency" and g[2] not in links(g[1]))
                  or (g[0] == "link_dependency" and g[2] in links(g[1]))
                  or (g[0] == "clear_blocked" and create_steps.blocked_state(written.get(g[1])) == "cleared"
                      and (written[g[1]].get("blocked_changes") or [{}])[-1].get("plan_version") == plan["version"])}
        if not want <= got or got - want - landed:
            return ["the write list's relinks and unblocks are not the ones the latest manifest and the plan of record "
                    "imply (missing: " + ", ".join(sorted(f"{k} {i}" for k, i, _ in want - got)) + "; extra: "
                    + ", ".join(sorted(f"{k} {i}" for k, i, _ in got - want - landed)) + "); diff again and render it again"]
    task_of = {t["key"]: t["id"] for t in plan["tasks"]}
    closes = [{"key": w["key"], "reason": w["reason"]} for w in wl.get("writes", []) if w.get("kind") == "close_item"]
    edits = [task_of.get(w["key"], w["key"]) for w in wl.get("writes", []) if w.get("kind") == "update_item"]
    entries = [w["entry"] for w in wl.get("writes", []) if w.get("kind") == "cr_log_put"]
    rel = {}
    for w in wl.get("writes", []):
        if w.get("kind") == "unlink_dependency" or (w.get("kind") == "link_dependency" and w.get("scope") == "plan"):
            r = rel.setdefault(task_of.get(w["key"], w["key"]), {"added": [], "removed": []})
            # a removed dependency may be a task the plan dropped, so its id comes from its key
            prefix = f"gw:{plan['id']}:"
            dep = w["blocked_by"][len(prefix):] if w["blocked_by"].startswith(prefix) else w["blocked_by"]
            r["removed" if w["kind"] == "unlink_dependency" else "added"].append(dep)
    for tid, r in rel.items():  # a relink with only additions on an offered phase renders no write; keep it out
        r["task"] = tid
    unblocks = [task_of.get(w["key"], w["key"]) for w in wl.get("writes", []) if w.get("kind") == "clear_blocked"]
    try:
        again = render_proposal.write_list(plan, overlay, set(wl.get("phases", [])), closes or None,
                                           entries[0] if len(entries) == 1 else None, edits, list(rel.values()), unblocks)
    except (ValueError, KeyError) as e:
        return [f"the write list can't be rebuilt from the plan of record: {e}"]
    if len(entries) > 1 or hash_value(again) != hash_value(wl):
        return ["the write list is not the one Groundwork renders from the plan of record for these phases, closes, "
                "edits and change-request entry; render it again"]
    return []


def open_blockers(review):
    return [f["id"] for f in review.get("findings", []) if f.get("severity") == "blocker" and f.get("resolution") != "fixed"]


def plan_level_basis(plan_state, wl):
    """The manifest a plan-level write list is rebuilt from: for a retire, the manifest before its status
    intent (retire_basis_of); for the others, the latest."""
    ps = plan_state or {}
    if wl.get("kind") == "retire" and "retire_basis" in ps:
        return ps["retire_basis"]
    return ps.get("manifest")


def rebuilt_plan_level_problems(plan, overlay, wl, context, manifest):
    """A plan-level write list must be the one Groundwork renders for this plan, kind and stored context
    (fourth review, M7): for a retire, the closes follow from the items the proposal showed and the
    runner's leave-open choices; for the others, from the change-request entry it binds."""
    import render_proposal
    import retire
    if wl.get("plan_id") != plan["id"] or wl.get("plan_version") != plan["version"]:
        return [f"the write list is for plan {wl.get('plan_id')} version {wl.get('plan_version')}, "
                f"not {plan['id']} version {plan['version']}"]
    kind = wl.get("kind")
    try:
        if kind == "retire":
            recorded = {w["key"] for w in (manifest or {}).get("items", [])}
            flagged = sorted(i["key"] for i in context["items"] if i.get("person_added") and i["key"] in recorded)
            if flagged:  # eighth review, M1: a key the manifest records is Groundwork's, never a person's
                return ["the stored proposal context names items the manifest records as added by a person: "
                        + ", ".join(flagged) + "; read again and propose again"]
            choices = {x["key"]: {"leave": x["owner_role_key"]} for x in wl.get("left_open", [])}
            for i in context["items"]:
                if i["status"] == "in_progress" and not i["person_added"]:
                    choices.setdefault(i["key"], "close")
            rp = retire.plan_retire(context["items"], choices, manifest)
            if not rp["ok"]:
                return [f"the retire can't be rebuilt from the stored context: {'; '.join(rp['problems'])}"]
            draft = any(w["kind"] == "remove_label" for w in wl.get("writes", []))
            again = retire.write_list(plan, overlay, rp, draft, wl.get("voids_pending", []))
        else:
            entries = [w["entry"] for w in wl.get("writes", []) if w.get("kind") == "cr_log_put"]
            if len(entries) > 1:
                return ["the write list binds more than one change-request entry"]
            again = render_proposal.plan_write_list(plan, overlay, kind, entries[0] if entries else None)
    except (ValueError, KeyError) as e:
        return [f"the write list can't be rebuilt from the plan of record and the stored context: {e}"]
    if hash_value(again) != hash_value(wl):
        return ["the write list is not the one Groundwork renders for this plan, kind and stored context; "
                "approvals bind only what Groundwork rendered"]
    return []


def verify_approvals(plan, overlay, anchor, comments, proposal_text, wl, review, phases, now, unverified_writer, info=None,
                     latest_stored_version=None, plan_state=None, view=None):
    """Return (ok, problems, accepted_phases) for a phase set (initial, release, revision).

    Only records for the plan's current version and this proposal count (the
    grouping filter, planning model 4.1). Older versions are superseded; a record
    for another proposal at this version (a decline beside a pending release) is
    information. Every all_phases gate must reach its own quorum for every phase.
    """
    info = info if info is not None else []
    if not phases:
        return False, ["no phases were named for create; name the approved phases to write"], []
    records, probs = _approval_set(plan, overlay, anchor, comments, proposal_text, wl, review, now, unverified_writer, info,
                                   latest_stored_version, "phases", plan_state)
    import render_proposal
    probs += rebuilt_write_list_problems(plan, overlay, wl, (plan_state or {}).get("manifest"))
    if review != (plan.get("review") or {}).get("reviewer") and not _same_review(review, (plan.get("review") or {}).get("reviewer")):
        probs.append("the review the approvals bind is not the review recorded in the plan of record")
    blockers = open_blockers(review)
    if blockers:
        probs.append(f"the review has open blocker findings ({', '.join(blockers)}); fix them and review again")
    if not overlay.get("provisional") and proposal_text != render_proposal.proposal(plan, overlay, wl.get("phases", []), wl):
        probs.append("the proposal does not re-render from the plan of record and the write list; approvals bind only "
                     "what Groundwork rendered")
    if view is not None and review["view_hash"] != view_hash(view_bundle(plan, view["evidence"], CHECKLIST_VERSION, view["rules"])):
        probs.append("the review was not made from this plan's reviewer view")
    gates = {g["id"]: g for g in overlay["approval_gates"]}
    accepted = set()
    phase_gates = [g for g in gates.values() if g["applies_to"] == "all_phases"]
    for pid in phases:
        short = []
        for gate in phase_gates:
            who = {c["author_account_id"] for c, rec, g in records if g["id"] == gate["id"] and pid in rec["phases"] and rec["kind"] != "exception"}
            if len(who) < gate.get("min_approvers", 1):
                short.append(gate["id"])
        if phase_gates and not short:
            accepted.add(pid)
        else:
            probs.append(f"phase {pid} has no valid approval quorum" + (f" on gate(s) {', '.join(short)}" if short else ""))
    needed_ex = {t["exception"]["id"] for t in plan["tasks"] if t["phase"] in phases and t["exception"]}
    ok_ex = set()
    for c, rec, gate in records:
        if gate["applies_to"] == "one_day_exceptions":
            ok_ex.update(rec["exceptions_accepted"])
        elif rec["exceptions_accepted"]:
            probs.append(f"comment {c['ref']}: a phase-release record cannot accept an exception; use the exception gate")
    for ex in sorted(needed_ex - ok_ex):
        probs.append(f"exception {ex} has not been accepted on the exception gate")
    probs += write_list_scope_problems(wl, "phases", phases)
    return (not probs), probs, sorted(accepted)


def verify_plan_level(plan, overlay, anchor, comments, proposal_text, wl, review, now, unverified_writer, info=None,
                      latest_stored_version=None, plan_state=None, stored=None, view=None):
    """Return (ok, problems, kind) for a plan-level set (decline, own_epic, retire, later).

    The same grouping filter and per-record checks as a phase set. Every all_phases
    gate must reach min_approvers on plan-level records, zero records never pass,
    all records agree on the kind, no record accepts an exception, and the write
    list holds only plan entries.
    """
    info = info if info is not None else []
    records, probs = _approval_set(plan, overlay, anchor, comments, proposal_text, wl, review, now, unverified_writer, info,
                                   latest_stored_version, "plan_level", plan_state)
    if not records:
        probs.append("no valid plan-level approval records for this proposal; zero records is never a pass")
    kinds = sorted({rec["kind"] for _c, rec, _g in records})
    if len(kinds) > 1:
        probs.append(f"the records disagree on the kind of plan-level change ({', '.join(kinds)})")
    if kinds and kinds != [wl.get("kind")]:
        probs.append(f"the records approve a {', '.join(kinds)} but the write list is a {wl.get('kind')}")
    for c, rec, _g in records:
        if rec["exceptions_accepted"]:
            probs.append(f"comment {c['ref']}: a plan-level record cannot accept an exception")
    for gate in [g for g in overlay["approval_gates"] if g["applies_to"] == "all_phases"]:
        who = {c["author_account_id"] for c, rec, g in records if g["id"] == gate["id"]}
        if len(who) < gate.get("min_approvers", 1):
            probs.append(f"gate {gate['id']} has no plan-level quorum ({len(who)} of {gate.get('min_approvers', 1)})")
    # stored: {context, assessment, rules} as stored at Proposal. The proposal and the review bundle are
    # rebuilt from them here, never taken from a file the session supplies.
    if stored is None:
        probs.append("a plan-level set is verified only against its stored proposal context")
    else:
        probs += rebuilt_plan_level_problems(plan, overlay, wl, stored["context"], plan_level_basis(plan_state, wl))
        # a set that decides a change request shows that request's assessment (fit, cost, options):
        # approvers never decide one without it (fifth review, finding 8)
        decided = [w["entry"]["id"] for w in wl.get("writes", []) if w.get("kind") == "cr_log_put"]
        a = stored.get("assessment")
        if decided and (a is None or a.get("cr") != decided[0]):
            probs.append(f"a set that decides {decided[0]} is verified only with that request's stored assessment "
                         "(--assessment), which its proposal shows")
        import render_proposal
        try:
            again = render_proposal.plan_level_proposal(plan, overlay, wl, stored["context"], stored.get("assessment"))
        except (ValueError, KeyError) as e:
            again = None
            probs.append(f"the stored proposal context does not fit this set: {e}")
        if again is not None and proposal_text != again:
            probs.append("the proposal does not re-render from the plan of record, the write list and the stored "
                         "context; approvals bind only what Groundwork rendered")
        if wl.get("kind") in plan_bundle_kinds():
            # the set stores no plan version, so the review it binds must be of its own closes-and-decisions
            # bundle, never the plan's ordinary Gap review (planning model 4.3)
            want = plan_level_bundle(plan, wl, stored["context"], CHECKLIST_VERSION, stored["rules"], stored.get("assessment"))
            if review["view_hash"] != view_hash(want):
                probs.append("the review was not made from this set's closes-and-decisions bundle")
        elif view is not None and review["view_hash"] != view_hash(view_bundle(plan, view["evidence"], CHECKLIST_VERSION,
                                                                               view["rules"])):
            probs.append("the review was not made from this plan's reviewer view")
    blockers = open_blockers(review)
    if blockers:
        probs.append(f"the review has open blocker findings ({', '.join(blockers)}); fix them and review again")
    probs += write_list_scope_problems(wl, "plan_level", [])
    return (not probs), probs, (kinds[0] if len(kinds) == 1 else None)


# Writes a plan-level set may authorize (planning model 4.3), by kind. Bookkeeping (lock, manifest,
# snapshot) goes with every kind; only retire closes items, writes the status file or touches the epic.
_PLAN_BOOKKEEPING = ("lock_claim", "lock_release", "manifest_put", "snapshot_put")
PLAN_LEVEL_WRITES_BY_KIND = {
    # decline, own epic and later write nothing to the tracker, so they write no manifest
    "decline": ("lock_claim", "lock_release", "snapshot_put", "cr_log_put"),
    "own_epic": ("lock_claim", "lock_release", "snapshot_put", "cr_log_put"),
    "later": ("lock_claim", "lock_release", "snapshot_put", "cr_log_put"),
    "retire": _PLAN_BOOKKEEPING + ("add_label", "close_item", "status_put", "remove_label", "close_epic"),
}
PLAN_LEVEL_WRITES = tuple(sorted({k for v in PLAN_LEVEL_WRITES_BY_KIND.values() for k in v}))


def write_list_scope_problems(wl, scope, phases):
    """Every write carries scope phase:<id> or plan; a set authorizes only its own scopes, and a
    plan-level write list only the writes its kind allows."""
    probs = []
    allowed = {f"phase:{p}" for p in phases} | {"plan"}
    kind_writes = PLAN_LEVEL_WRITES_BY_KIND.get(wl.get("kind"))
    if scope == "plan_level" and kind_writes is None:
        probs.append(f"a plan-level write list needs a kind, one of {', '.join(PLAN_LEVEL_WRITES_BY_KIND)}")
        kind_writes = ()
    for w in wl.get("writes", []):
        sc = w.get("scope")
        if sc is None:
            probs.append(f"write {w.get('no')}: has no scope")
        elif sc not in allowed:
            probs.append(f"write {w.get('no')}: scope {sc} is not covered by this set")
        elif scope == "plan_level" and w["kind"] not in kind_writes:
            probs.append(f"write {w.get('no')}: a plan-level {wl.get('kind')} set cannot authorize a {w['kind']} write")
    if scope == "plan_level" and wl.get("phases"):
        probs.append("a plan-level write list offers no phases")
    return probs


def verify_chain(manifests, plan_id=None):
    """Latest manifest = highest seq whose prev_hash chain back to seq 1 is intact, where every link also
    keeps the append-only rules make_manifest writes by (no item dropped or moved, nothing done once
    forgotten, the status file carried forward) and every manifest names the same plan."""
    import create_steps
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
        if m["prev_hash"] != (prev or {}).get("hash"):
            probs.append(f"manifest seq {seq}: prev_hash does not match seq {seq - 1}; chain broken")
            break
        bad = ([f"names plan {m['plan_id']}, not {plan_id}"] if plan_id and m["plan_id"] != plan_id else []) + \
            (create_steps.successor_problems(prev, m) if prev else [])
        if bad:
            probs.append(f"manifest seq {seq}: {bad[0]}; refused as edited by hand; stop and resolve before any write")
            break
        latest = m
        prev = m
        seq += 1
    return latest, probs


def latest_manifest_of(paths, plan_id):
    """The latest manifest, derived from every manifest file in the plan store, never taken from one
    file the runner names (fifth review, finding 5). None when none is written yet. Any problem in the
    chain raises, because no write may run on a broken or hand-edited chain."""
    if paths is None:
        raise ValueError("--manifests required: every manifest file in the plan store (none: --manifests with no files)")
    ms = [json.load(open(p, encoding="utf-8")) for p in paths]
    latest, probs = verify_chain(ms, plan_id)
    if probs:
        raise ValueError("; ".join(probs))
    if ms and latest is None:
        raise ValueError("manifest files were given but none starts the chain at seq 1")
    if latest is not None and max(m["seq"] for m in ms) != latest["seq"]:
        raise ValueError(f"a manifest after seq {latest['seq']} does not chain to it; stop")
    return latest


def retire_basis_of(paths, plan_id):
    """The manifest a retire's write list is rebuilt from: the latest one, or, once a retire's status intent
    is recorded, the last manifest before that intent. The retire's own closes are recorded after the
    intent, so on a resume the latest manifest would show them as Groundwork's earlier closes (a person's
    reopen) and the rebuild would differ from the approved set (eleventh review, M1 and m2). The chain is
    verified by latest_manifest_of first."""
    latest = latest_manifest_of(paths, plan_id)
    if latest is None or latest.get("status_file") is None:
        return latest
    ms = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            ms.append(json.load(f))
    ms.sort(key=lambda m: m["seq"])
    before = [m for m in ms if m["seq"] <= latest["seq"] and m.get("status_file") is None]
    return before[-1] if before else None


def add_manifests_arg(ap):
    ap.add_argument("--manifests", nargs="*", default=None,
                    help="every <plan.id>-manifest-<seq> file in the plan store (with no files when none is written yet); "
                         "the latest is derived by verifying the chain")


def cli_rules(a):
    return [r for p in a.rules for r in json.load(open(p, encoding="utf-8")).get("rules", [])]


def cli_plan_state(a, plan_id, plan=None):
    load = lambda p: None if p == "-" else json.load(open(p, encoding="utf-8"))
    m = latest_manifest_of(a.manifests, plan_id)
    if m is None and plan is not None and any(p["state"] in ("writing", "released") for p in plan.get("phases", [])):
        # eighth review, m4: a written plan with no manifest would skip every manifest-derived check
        raise ValueError("the plan has written phases but no manifest was given: pass every manifest file")
    return {"manifest": m, "retire_basis": retire_basis_of(a.manifests, plan_id), "status": load(a.status), "epic": a.epic}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["summary", "view", "review", "approvals", "plan-level", "manifest-chain", "owned"])
    ap.add_argument("--plan-id", help="manifest-chain: the plan every manifest must name")
    ap.add_argument("--latest-version", type=int, help="the latest plan-of-record version in the plan store")
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
    ap.add_argument("--plan-level", action="store_true", help="view: the closes-and-decisions bundle of a plan-level set")
    ap.add_argument("--context", help="view --plan-level: the stored proposal context")
    ap.add_argument("--assessment", help="view --plan-level: the change request's stored assessment, if any")
    add_manifests_arg(ap)
    ap.add_argument("--status", help="the latest status file (JSON), or - when the plan store has none")
    ap.add_argument("--epic", choices=["open", "closed"], help="the epic's tracker state")
    a = ap.parse_args(argv)
    J = lambda p: json.load(open(p, encoding="utf-8"))
    if a.cmd == "summary":
        plan = J(a.files[0])
        print(json.dumps({"plan_id": plan["id"], "version": plan["version"], "plan_hash": plan_hash(plan), "phase_hashes": phase_hashes(plan)}, indent=2))
        return 0
    if a.cmd == "view":
        plan = J(a.files[0])
        rules = [r for p in a.rules for r in J(p).get("rules", [])]
        if a.plan_level:
            bundle = plan_level_bundle(plan, J(a.write_list), J(a.context), CHECKLIST_VERSION, rules,
                                       J(a.assessment) if a.assessment else None)
        else:
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
    if a.cmd in ("approvals", "plan-level"):
        need = [("--latest-version", a.latest_version), ("--manifests", a.manifests), ("--status", a.status),
                ("--epic", a.epic), ("--rules", a.rules or None), ("--evidence", a.evidence)]
        if a.cmd == "plan-level":
            need.append(("--context", a.context))
        missing = [f for f, v in need if v is None]
        if missing:
            print(json.dumps({"ok": False, "problems": [f"{', '.join(missing)} required: approvals are never verified "
                                                         "without the latest stored version, the retire gate and the "
                                                         "stored inputs the proposal and review are rebuilt from"]}, indent=2))
            return 1
    try:
        return _run(a, J)
    except ValueError as e:  # a broken or hand-edited manifest chain stops the check
        print(json.dumps({"ok": False, "problems": [str(e)]}, indent=2))
        return 1


def _run(a, J):
    if a.cmd == "approvals":
        plan = J(a.files[0])
        overlay = gw_yaml.load(a.overlay)
        proposal_text = open(a.proposal, encoding="utf-8", newline="").read()
        unverified = any(s["verified"] != "verified" and s["name"] == overlay["skills"]["tracker"]["skill"] for s in plan["stamps"]["skills"])
        info = []
        phases = [x.strip() for x in (a.phases or "").split(",") if x.strip()]
        ok, probs, accepted = verify_approvals(plan, overlay, J(a.anchor), J(a.comments), proposal_text, J(a.write_list), J(a.review),
                                               phases, ts(a.now), unverified, info, a.latest_version, cli_plan_state(a, plan["id"], plan),
                                               {"evidence": load_evidence(a.evidence), "rules": cli_rules(a)})
        print(json.dumps({"ok": ok, "accepted_phases": accepted, "problems": probs, "superseded": info}, indent=2))
        return 0 if ok else 1
    if a.cmd == "plan-level":
        plan = J(a.files[0])
        overlay = gw_yaml.load(a.overlay)
        proposal_text = open(a.proposal, encoding="utf-8", newline="").read()
        unverified = any(s["verified"] != "verified" and s["name"] == overlay["skills"]["tracker"]["skill"] for s in plan["stamps"]["skills"])
        info = []
        ok, probs, kind = verify_plan_level(plan, overlay, J(a.anchor), J(a.comments), proposal_text, J(a.write_list), J(a.review),
                                            ts(a.now), unverified, info, a.latest_version, cli_plan_state(a, plan["id"], plan),
                                            {"context": J(a.context), "assessment": J(a.assessment) if a.assessment else None,
                                             "rules": cli_rules(a)},
                                            {"evidence": load_evidence(a.evidence), "rules": cli_rules(a)})
        print(json.dumps({"ok": ok, "kind": kind, "problems": probs, "other_sets": info}, indent=2))
        return 0 if ok else 1
    if a.cmd == "manifest-chain":
        if not a.plan_id:
            print(json.dumps({"ok": False, "problems": ["--plan-id required: every manifest in the chain must name this plan"]}))
            return 1
        latest, probs = verify_chain([J(p) for p in a.files], a.plan_id)
        print(json.dumps({"ok": not probs, "latest_seq": latest["seq"] if latest else None, "problems": probs}, indent=2))
        return 0 if not probs else 1
    if a.cmd == "owned":
        print(owned_hash(J(a.files[0])))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
