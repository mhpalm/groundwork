#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Change requests: the front end to revise (planning model section 3).

Usage:
  change_request.py allocate LOG.json|- --plan-id ID --restatement TEXT --source runner|pasted
                    --origin ROLE --plan-version N --manifest-seq N [--derived-from EV1,EV2]
  change_request.py base LOG.json CR-n --plan-version N --manifest-seq N
  change_request.py assess BASE_PLAN.json NEW_PLAN.json LOG.json CR-n --cost drafted|outline|unknown
                    [--approved-unwritten P1,P2]
  change_request.py bind LOG.json CR-n --outcome declined --reason TEXT   (the entry a write list binds)
  change_request.py decide LOG.json CR-n --write-list VERIFIED_WRITE_LIST.json --proposal-hash HEX
                    [--restricted RESTRICTED.json]   (outcome and reason come from the bound entry)
  change_request.py basis RELEASED_PLAN.json CURRENT_PLAN.json --phase P
  change_request.py release-check CURRENT_PLAN.json --phase P --released P1=PLAN_AT_RELEASE.json ...

The log is change-requests-<n>.json in the plan store, outside plan_hash. Each
write is the latest file plus one entry, numbered under the lock, so two sets at
the same base never drop each other's entry. A CR id is allocated under the lock
by writing a pending entry. Cost is counted in one-day tasks; waits count 0 days.
"""

import argparse
import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_model  # noqa: E402
from gw_hash import basis_hash  # noqa: E402

OUTCOMES = ("added", "later", "own_epic", "declined")
# The four options an assessment always shows (3.3 step 6), with the approval each needs (3.4).
OPTIONS = [
    ("added", "Add to the current unreleased phase", "a revision: new plan version, full Gap review, phase records"),
    ("later", "Add a later phase (outline, needs a planning run)", "a new plan version with full Gap review, plan-level records"),
    ("own_epic", "Start its own epic", "a log entry here (plan-level records) and a separate new-project run; "
                                       "the new plan names this epic's key in a code span, with no link"),
    ("declined", "Decline", "a log entry only (plan-level records); no new plan version, so pending approvals stay valid"),
]
BRIEF_CHANGE_KEYS = ("outcome", "scope_in", "non_goals")
TASKS_PER_OUTLINE_PHASE = 5


def empty_log(plan_id):
    return {"schema_version": "1.0", "plan_id": plan_id, "n": 0, "entries": []}


def next_log(latest, entry):
    """The latest log file plus this set's own entry (replacing its pending entry, if any)."""
    log = copy.deepcopy(latest)
    log["entries"] = [e for e in log["entries"] if e["id"] != entry["id"]] + [entry]
    log["entries"].sort(key=lambda e: int(e["id"].split("-")[1]))
    log["n"] = latest["n"] + 1
    return log


def allocate(latest, restatement, source, origin_role_key, plan_version, manifest_seq, derived_from=()):
    """Allocate the next CR id as a pending entry. Call only while holding the epic lock."""
    if not restatement.strip():
        raise ValueError("a change request needs the runner-confirmed restatement")
    if source == "pasted" and not derived_from:
        raise ValueError("a restatement of pasted text names the evidence it came from (derived_from)")
    n = max([int(e["id"].split("-")[1]) for e in latest["entries"]] + [0]) + 1
    entry = {"id": f"CR-{n}", "restatement": restatement.strip(), "source": source, "derived_from": sorted(derived_from),
             "origin_role_key": origin_role_key, "outcome": "pending", "reason": None,
             "base": {"plan_version": plan_version, "manifest_seq": manifest_seq}, "decided_by": None}
    return next_log(latest, entry), entry


def entry_of(log, cr_id):
    e = next((e for e in log["entries"] if e["id"] == cr_id), None)
    if e is None:
        raise KeyError(f"no {cr_id} in the change-request log")
    return e


def base_problems(entry, plan_version, manifest_seq):
    """Proposal refuses if the plan version or the latest manifest moved since the assessment (3.3)."""
    b = entry["base"]
    probs = []
    if b["plan_version"] != plan_version:
        probs.append(f"the plan moved from version {b['plan_version']} to {plan_version} since {entry['id']} was assessed; assess again")
    if b["manifest_seq"] != manifest_seq:
        probs.append(f"the manifest moved from {b['manifest_seq']} to {manifest_seq} since {entry['id']} was assessed; assess again")
    return probs


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def similar_declined(log, restatement, threshold=0.5):
    """Declined requests whose restatement shares most of its words with this one, to show beside it."""
    mine = words(restatement)
    out = []
    for e in log["entries"]:
        if e["outcome"] != "declined":
            continue
        theirs = words(e["restatement"])
        if mine and theirs and len(mine & theirs) / len(mine | theirs) >= threshold:
            out.append({"id": e["id"], "restatement": e["restatement"], "reason": e["reason"], "decided_by": e["decided_by"]})
    return out


def _by_id(items):
    return {i["id"]: i for i in items}


def assess(base, new, log, cr_id, cost_kind, approved_unwritten=()):
    """Impact of a change request: fit, approach, traits, cost in one-day tasks, dependencies, options."""
    entry = entry_of(log, cr_id)
    model = gw_model.is_model_plan(base) and gw_model.is_model_plan(new)
    out = {"cr": cr_id, "restatement": entry["restatement"], "format": 2 if model else 1, "notes": []}

    # 1. Fit
    bt, nt = _by_id(base["tasks"]), _by_id(new["tasks"])
    added = sorted(set(nt) - set(bt))
    if model:
        bb, nb = gw_model.brief_by_key(base), gw_model.brief_by_key(new)
        changed = [k for k in BRIEF_CHANGE_KEYS if (bb.get(k) or {}).get("value") != (nb.get(k) or {}).get("value")
                   or (bb.get(k) or {}).get("value_rev") != (nb.get(k) or {}).get("value_rev")]
        fields = gw_model.brief_by_id(new)
        serves = sorted({fields[r]["key"] for t in added for r in nt[t].get("brief_refs", []) if r in fields})
        out["fit"] = {"changes_the_brief": changed, "serves": serves}
    else:
        out["fit"] = None
        out["notes"].append("format-1 plan: no brief, so the Fit step and the brief parts of the basis were skipped")

    # 2. Approach and basis
    if model:
        ba, na = base.get("approach", {}), new.get("approach", {})
        def diff_ids(kind):
            b, n = _by_id(ba.get(kind, [])), _by_id(na.get(kind, []))
            return sorted(k for k in set(b) | set(n) if b.get(k) != n.get(k))
        out["approach"] = {"decisions_changed": diff_ids("decisions"), "options_changed": diff_ids("options")}
    else:
        out["approach"] = None
    common = [p["id"] for p in new["phases"] if p["id"] in {q["id"] for q in base["phases"]}]
    out["basis_changed"] = sorted(p for p in common if basis_hash(base, p) != basis_hash(new, p))

    # 3. Traits
    bk = {(t["id"], t["version"]) for t in base.get("traits", [])}
    new_traits = [t for t in new.get("traits", []) if (t["id"], t["version"]) not in bk]
    out["traits_added"] = sorted(t["id"] for t in new_traits)
    for t in new_traits:
        if t.get("from_plan_version") != new["version"]:
            out["notes"].append(f"trait {t['id']} was added in this revision but from_plan_version is not {new['version']}")

    # 4. Cost in one-day tasks
    new_phases = [p for p in new["phases"] if p["id"] not in {q["id"] for q in base["phases"]}]
    waits = sorted({w["what"] for t in added for w in nt[t].get("waits_on", [])})
    blocking_q = sorted(q["id"] for q in new["open_questions"] if q["status"] == "open"
                        and q["id"] not in {x["id"] for x in base["open_questions"]})
    if cost_kind == "drafted":
        drafted = [t for t in added if next(p for p in new["phases"] if p["id"] == nt[t]["phase"])["state"] != "outline"]
        cost = {"kind": "drafted", "tasks": len(drafted), "task_ids": drafted}
        if new.get("review", {}).get("validator") is None:
            out["notes"].append("a drafted cost is exact only after Gap review of the draft; none is recorded")
    elif cost_kind == "outline":
        n = len([p for p in new_phases if p["state"] == "outline"]) or 1
        cost = {"kind": "outline", "phases": n, "tasks_about": n * TASKS_PER_OUTLINE_PHASE, "narrowed_by": blocking_q}
    elif cost_kind == "unknown":
        cost = {"kind": "unknown", "answer_first": blocking_q}
        if not blocking_q:
            out["notes"].append("an unknown cost names the open questions to answer first; none were added")
    else:
        raise ValueError("cost is drafted, outline or unknown")
    cost["waits"] = [{"what": w, "days": 0} for w in waits]
    out["cost"] = cost

    # 5. Dependencies: new edges, and existing tasks they touch
    edges, affected = [], set()
    for tid, t in sorted(nt.items()):
        before = {d["task"] for d in bt.get(tid, {}).get("depends_on", [])}
        for d in t["depends_on"]:
            if d["task"] not in before:
                edges.append({"task": tid, "depends_on": d["task"]})
                for x in (tid, d["task"]):
                    if x in bt:
                        affected.add(x)
    out["dependencies"] = {"new_edges": edges, "existing_tasks_affected": sorted(affected)}

    # 6. Options, always all four
    out["options"] = [{"outcome": k, "label": label, "approval": how} for k, label, how in OPTIONS]
    out["similar_declined"] = similar_declined({"entries": [e for e in log["entries"] if e["id"] != cr_id]},
                                               entry["restatement"])
    out["voids_pending"] = sorted(approved_unwritten)
    return out


def render(a):
    """The assessment section of a proposal. 'Changes the brief' comes first."""
    out = [f"## Change request {a['cr']}", ""]
    if a["fit"] and a["fit"]["changes_the_brief"]:
        out.append(f"**Changes the brief:** {', '.join(a['fit']['changes_the_brief'])}. Approvers are agreeing to a different "
                   "project, not only more work.")
        out.append("")
    out += [f"Request: {a['restatement']}", ""]
    if a["voids_pending"]:
        out.append(f"**Pending approvals become void:** {', '.join(a['voids_pending'])} were approved but not written, and a new "
                   "plan version voids those approvals.")
        out.append("")
    if a["fit"]:
        out.append("**Fit:** serves " + (", ".join(a["fit"]["serves"]) or "no brief field directly") + ".")
    if a["approach"]:
        ch = a["approach"]["decisions_changed"] + a["approach"]["options_changed"]
        out.append("**Approach:** " + (", ".join(ch) + " changed." if ch else "unchanged."))
    if a["basis_changed"]:
        out.append(f"**Basis changes for:** {', '.join(a['basis_changed'])}.")
    if a["traits_added"]:
        out.append(f"**Traits added:** {', '.join(a['traits_added'])}.")
    c = a["cost"]
    if c["kind"] == "drafted":
        out.append(f"**Cost:** {c['tasks']} one-day task{'s' if c['tasks'] != 1 else ''} ({', '.join(c['task_ids']) or 'none'}).")
    elif c["kind"] == "outline":
        out.append(f"**Cost:** about {c['phases']} phase{'s' if c['phases'] != 1 else ''} of about {TASKS_PER_OUTLINE_PHASE} "
                   f"one-day tasks (about {c['tasks_about']}), needs a planning run"
                   + (f"; narrowed by {', '.join(c['narrowed_by'])}" if c["narrowed_by"] else "") + ".")
    else:
        out.append("**Cost:** unknown until " + (", ".join(c["answer_first"]) or "the open questions") + " are answered.")
    if c["waits"]:
        out.append("**Waits (0 days each):** " + "; ".join(w["what"] for w in c["waits"]) + ".")
    d = a["dependencies"]
    if d["new_edges"]:
        out.append("**New dependencies:** " + "; ".join(f"{e['task']} after {e['depends_on']}" for e in d["new_edges"]) + ".")
    out.append("")
    out.append("**Options:**")
    out += [f"- {o['label']}: {o['approval']}." for o in a["options"]]
    if a["similar_declined"]:
        out.append("")
        out.append("**Similar requests declined before:**")
        out += [f"- {s['id']}: {s['restatement']} (declined: {s['reason']})" for s in a["similar_declined"]]
    for n in a["notes"]:
        out.append(f"\nNote: {n}.")
    out.append("")
    return "\n".join(out)


KIND_OUTCOME = {"revision": "added", "later": "later", "own_epic": "own_epic", "decline": "declined"}


def decide(latest, cr_id, outcome, reason, plan_version, proposal_hash):
    """The log entry create writes once the proposal is verified; decided_by names the proposal.
    Deciding again with the same outcome, reason and decided_by is the resume of that same set:
    it returns the log unchanged with already=True. Any other second decision is refused."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome is one of {', '.join(OUTCOMES)}")
    e = copy.deepcopy(entry_of(latest, cr_id))
    by = {"plan_version": plan_version, "proposal_hash": proposal_hash}
    if e["outcome"] != "pending":
        if (e["outcome"], e["reason"], e["decided_by"]) == (outcome, reason, by):
            return latest, dict(e, already=True)
        raise ValueError(f"{cr_id} was already decided ({e['outcome']})")
    e.update(outcome=outcome, reason=reason, decided_by=by)
    return next_log(latest, e), e


def bound_entry(wl):
    """The change-request entry a verified write list binds. Create decides from this, never from
    values typed at create time, so the log says exactly what the approvers approved."""
    puts = [w for w in wl.get("writes", []) if w["kind"] == "cr_log_put"]
    if len(puts) != 1:
        raise ValueError("the write list binds no change-request entry" if not puts else "the write list binds more than one entry")
    e = puts[0]["entry"]
    missing = [k for k in ("id", "outcome", "reason") if not e.get(k)]
    if missing:
        raise ValueError(f"the bound entry lacks {', '.join(missing)}")
    kind = wl.get("kind") or ("revision" if wl.get("phases") else None)
    if KIND_OUTCOME.get(kind) != e["outcome"]:
        raise ValueError(f"a {kind} write list cannot bind outcome {e['outcome']}")
    return e


DECIDED_FIELDS = ("outcome", "reason", "decided_by")


def to_bind(latest, cr_id, outcome, reason):
    """The entry a write list binds: the logged pending entry as allocated, with the outcome and reason
    the proposal decides, and no decided_by (create fills that in from the verified proposal)."""
    e = copy.deepcopy(entry_of(latest, cr_id))
    if e["outcome"] != "pending":
        raise ValueError(f"{cr_id} was already decided ({e['outcome']})")
    e.pop("decided_by", None)
    e.update(outcome=outcome, reason=reason)
    return e


def bound_matches_log(latest, bound):
    """Third review, finding 6: the approvers approved the restatement, source, origin and base the
    write list shows. Create refuses unless the logged entry is that same request."""
    logged = entry_of(latest, bound["id"])
    keep = lambda e: {k: v for k, v in e.items() if k not in DECIDED_FIELDS}
    if keep(logged) != keep(bound):
        diff = sorted(k for k in set(keep(logged)) | set(keep(bound)) if logged.get(k) != bound.get(k))
        raise ValueError(f"the write list's {bound['id']} is not the logged request ({', '.join(diff)} differ); propose again")


def decide_bound(latest, wl, proposal_hash, cr_id=None):
    if not re.fullmatch(r"[0-9a-f]{64}", proposal_hash or ""):
        raise ValueError("decided_by names the verified proposal's full sha256 (64 hex characters)")
    e = bound_entry(wl)
    if cr_id is not None and cr_id != e["id"]:
        raise ValueError(f"the write list decides {e['id']}, not {cr_id}")
    if "decided_by" in e:
        raise ValueError("the bound entry carries decided_by; the write list never names its own proposal")
    bound_matches_log(latest, e)
    return decide(latest, e["id"], e["outcome"], e["reason"], wl["plan_version"], proposal_hash)


def log_problems(log, restricted=None):
    """GR-17 and GR-34 over the log: it is shown to everyone who can see the epic."""
    from validate_plan import gr17_scan
    probs = [w for w, _fix in gr17_scan("change-request log", log)]
    for fid, v in (restricted or {}).items():
        v = (v or "").strip()
        if len(v) >= 3 and v.lower() in json.dumps(log, ensure_ascii=False).lower():
            probs.append(f"the change-request log contains the restricted value of {fid}")
    ids = [e["id"] for e in log["entries"]]
    if len(ids) != len(set(ids)):
        probs.append("the change-request log has duplicate ids")
    return probs


def basis_changes(released, current, phase_id):
    """What changed in P's basis since release (informational; revise lists it, nothing is generated)."""
    a, b = gw_model.basis_subset(released, phase_id), gw_model.basis_subset(current, phase_id)
    return sorted(k for k in a if a[k] != b[k])


def release_basis_problems(current, released, phase_id):
    """Release stops when an earlier released phase's basis changed since its release (planning model 1.8).
    released: {phase_id: the plan of record that phase was released at}."""
    order = {p["id"]: p["order"] for p in current["phases"]}
    if phase_id not in order:
        raise KeyError(f"no phase {phase_id}")
    probs = []
    for pid, plan_then in sorted(released.items()):
        if order.get(pid, 0) >= order[phase_id]:
            continue
        changed = basis_changes(plan_then, current, pid)
        if changed:
            probs.append(f"the basis of released phase {pid} changed since its release ({', '.join(changed)}); "
                         "release stops: run a revise first")
    missing = [p["id"] for p in current["phases"] if p["state"] == "released" and p["order"] < order[phase_id]
               and p["id"] not in released]
    probs += [f"no plan of record given for released phase {pid}; the basis check can't run" for pid in missing]
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["allocate", "base", "assess", "bind", "decide", "basis", "release-check"])
    ap.add_argument("--released", nargs="*", default=[], help="release-check: PHASE=PLAN_AT_RELEASE.json for each released phase")
    ap.add_argument("files", nargs="*")
    for a in ("--plan-id", "--restatement", "--source", "--origin", "--derived-from", "--cost", "--approved-unwritten",
              "--proposal-hash", "--phase", "--write-list", "--restricted", "--outcome", "--reason"):
        ap.add_argument(a)
    ap.add_argument("--plan-version", type=int)
    ap.add_argument("--manifest-seq", type=int)
    a = ap.parse_args(argv)
    J = lambda p: json.load(open(p, encoding="utf-8"))
    restricted = lambda a: J(a.restricted) if a.restricted else None
    split = lambda s: [x.strip() for x in (s or "").split(",") if x.strip()]
    if a.cmd == "allocate":
        latest = J(a.files[0]) if a.files[0] != "-" else empty_log(a.plan_id)
        log, entry = allocate(latest, a.restatement, a.source, a.origin, a.plan_version, a.manifest_seq, split(a.derived_from))
        out = {"log": log, "entry": entry, "similar_declined": similar_declined(latest, entry["restatement"]),
               "problems": log_problems(log, restricted(a))}
    elif a.cmd == "base":
        probs = base_problems(entry_of(J(a.files[0]), a.files[1]), a.plan_version, a.manifest_seq)
        out = {"ok": not probs, "problems": probs}
    elif a.cmd == "assess":
        res = assess(J(a.files[0]), J(a.files[1]), J(a.files[2]), a.files[3], a.cost, split(a.approved_unwritten))
        out = {"assessment": res, "markdown": render(res)}
    elif a.cmd == "bind":
        try:
            out = {"entry": to_bind(J(a.files[0]), a.files[1], a.outcome, a.reason)}
        except (ValueError, KeyError) as e:
            print(json.dumps({"ok": False, "problems": [str(e)]}, indent=2))
            return 1
    elif a.cmd == "decide":
        if not a.write_list:
            print(json.dumps({"ok": False, "problems": ["--write-list required: the outcome comes from the verified write list"]}))
            return 1
        try:
            log, entry = decide_bound(J(a.files[0]), J(a.write_list), a.proposal_hash, a.files[1])
        except (ValueError, KeyError) as e:
            print(json.dumps({"ok": False, "problems": [str(e)]}, indent=2))
            return 1
        out = {"log": log, "entry": entry, "problems": log_problems(log, restricted(a))}
    elif a.cmd == "release-check":
        rel = {x.split("=", 1)[0]: J(x.split("=", 1)[1]) for x in a.released}
        probs = release_basis_problems(J(a.files[0]), rel, a.phase)
        out = {"ok": not probs, "problems": probs}
    else:
        out = {"phase": a.phase, "changed": basis_changes(J(a.files[0]), J(a.files[1]), a.phase)}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok", True) and not out.get("problems") else 1


if __name__ == "__main__":
    sys.exit(main())
