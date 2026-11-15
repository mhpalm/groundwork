#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Render people-facing text from plan.json. Wording comes from the plan;
structure comes from here, so every run looks the same.

Usage:
  render_proposal.py proposal PLAN.json --overlay OVERLAY.yaml [--offer P0,P1] [--write-list WL.json] [--out proposal.md]
  render_proposal.py task PLAN.json --overlay OVERLAY.yaml --task P1-T02         (tracker item body)
  render_proposal.py epic PLAN.json --overlay OVERLAY.yaml                       (epic description)
  render_proposal.py write-list PLAN.json --overlay OVERLAY.yaml --offer P0,P1 [--out WL.json]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402
from gw_canon import canonicalize, sha256_hex, short  # noqa: E402
from gw_hash import phase_hashes, plan_hash, write_list_hash  # noqa: E402

OWNED_START = "<!-- groundwork:owned:start -->"
OWNED_END = "<!-- groundwork:owned:end -->"


PROVISIONAL_BANNER = ("> **Provisional: not connected to a tracker.** Planned with default settings and no inspected systems. "
                      "It cannot be approved or created until Groundwork is set up for your tracker and this plan is re-checked.")


def role_name(overlay, key):
    for r in overlay.get("roles", []):
        if r["key"] == key:
            return r["name"]
    return key


def stamps_footer(plan):
    s = plan["stamps"]
    skills = ", ".join(f"{x['name']}@{x['version']} ({x['verified']})" for x in s["skills"])
    ov = s["overlay"]
    return (f"---\nGroundwork {s['release']} · {s['core']} · contract {s['contract']} · plan format {s['plan_format']} · "
            f"validator {s['validator']} · {skills} · overlay {ov['id']} v{ov['version']} ({short(ov['hash'])}) · "
            f"surface {s['surface']} · model {s['model']} · plan {plan['id']} v{plan['version']} ({short(plan_hash(plan))})")


def task_body(plan, overlay, t):
    """The plan-owned part of a tracker item, between markers. Steps render as a checklist."""
    ins = t["instructions"]
    tasks = {x["id"]: x for x in plan["tasks"]}
    lines = [OWNED_START, f"**Purpose.** {ins['purpose']}", ""]
    lines.append(f"**Type:** {t['work_type'].capitalize()} · **Role:** {role_name(overlay, t['role_key'])} · **Estimate:** {t['estimate_hours']} h · **Points:** 1 · **Phase:** {t['phase']}")
    if t["depends_on"]:
        lines.append("**Depends on:** " + ", ".join(f"{d['task']} ({tasks[d['task']]['title'] if d['task'] in tasks else '?'}, when {d['satisfied_by']})" for d in t["depends_on"]))
    if t["waits_on"]:
        lines.append("**Waits on:** " + "; ".join(f"{w['what']} ({w['kind']}, {role_name(overlay, w['owner_role_key'])})" for w in t["waits_on"]))
    if t["access"]:
        lines.append("**Access needed:** " + ", ".join(t["access"]))
    if t.get("changes_existing"):
        ch = t["changes_existing"]
        names = {r["id"]: r["name"] for r in plan["request"]["starting_point"]["resources"]}
        lines.append("**Changes existing:** " + ", ".join(f"{r} ({names.get(r, '?')})" for r in ch["resources"])
                     + f". Why: {ch['why_needed']} Could break: {'; '.join(ch['could_break'])}. "
                     + f"Checked by: {', '.join(ch['regression_check'])}.")
    lines.append("")
    if ins["prerequisites"]:
        lines.append("**Prerequisites**")
        lines.extend(f"- {p}" for p in ins["prerequisites"])
        lines.append("")
    lines.append("**Steps**")
    for i, s in enumerate(ins["steps"], 1):
        mark = " (from the org's own files)" if s["from_evidence"] else ""
        lines.append(f"- [ ] {i}. {s['text']}{mark}")
    lines.append("")
    lines.append("**Acceptance criteria**")
    lines.extend(f"- {a}" for a in ins["acceptance_criteria"])
    lines.append("")
    lines.append("**How to verify**")
    lines.extend(f"- {v}" for v in ins["verify"])
    lines.append("")
    lines.append(f"**Done today:** {ins['done_today']}")
    lines.append(f"**Visible result:** {t['visible_result']['text']}")
    if t["exception"]:
        ex = t["exception"]
        lines.append("")
        lines.append(f"**One-day exception {ex['id']}:** {ex['reason']} ({ex['days']} days)")
        lines.extend(f"- Day {c['day']}: {c['visible_result']}" for c in ex["checkpoints"])
    lines.append(f"\n`{t['key']}`")
    lines.append(OWNED_END)
    return "\n".join(lines)


def release_name(plan, phase):
    """The tracker release container for a phase (a Jira fix version, a GitHub milestone). Stable for the phase."""
    return f"{plan['epic']['title']} {phase['id']} {phase['name']}"[:255]


REVISE_CLOSE_REASONS = ("not_planned", "superseded", "duplicate")


def write_list(plan, overlay, offer, closes=None, cr_entry=None, edits=None, relinks=None, unblocks=None):
    """The numbered write list for the offered phases. Hashing it binds approval to exactly these writes.

    closes: [{key, reason}] for items to close (revise); rendered as the close procedure:
    a close-intent manifest first, then each item's gw-closed label and transition, then a manifest.
    cr_entry: {id, outcome, reason} for the change request this revision decides; create fills in
    decided_by from the verified proposal, so the write list never names its own proposal hash.
    edits: task ids whose plan-owned text changed (revise_diff `changed`); each gets an update_item
    write binding the new plan-owned hash, in its phase's scope, so its phase must be offered.
    relinks: [{task, added, removed}] for written tasks whose dependencies a revise re-pointed
    (revise_diff `relinks`): each removed dependency gets an unlink_dependency write and each added one
    a link_dependency write, plan-scoped, so a written task never stays blocked by work the plan dropped.
    unblocks: written task ids whose waits a revise removed; each gets a clear_blocked write.
    A wait added to a written task (or added back after a clear) changes its body, so its phase is in the
    offer and that phase's set_blocked write blocks it again; preflight sets it whenever the manifest's
    blocked state is not "set" (sixth review, M4).
    """
    if overlay.get("provisional"):
        raise ValueError("a provisional overlay has no tracker, so there is no write list (D-54)")
    # a revise closes only tasks the revised plan drops, never as completed: a completed close reads
    # back as done and would satisfy its dependents without the work (fourth review, M6)
    in_plan = {t["key"] for t in plan["tasks"]} | {f"gw:{plan['id']}:{t['id']}" for t in plan["tasks"]}
    for c in closes or []:
        if c["key"] in in_plan:
            raise ValueError(f"{c['key']} is still a task in the plan; a revise closes only tasks the plan drops")
        if not c["key"].startswith(f"gw:{plan['id']}:"):
            raise ValueError(f"{c['key']} is not one of this plan's keys")
        if c["reason"] not in REVISE_CLOSE_REASONS:
            raise ValueError(f"a revise closes as {', '.join(REVISE_CLOSE_REASONS)}, not {c['reason']}")
    tr = overlay["skills"]["tracker"]
    target = f"{tr['skill'].replace('groundwork-tracker-', '')}:{tr['instance']['id']}:{tr['instance']['project']}"
    edits = set(edits or ())
    tasks_by_id = {t["id"]: t for t in plan["tasks"]}
    for tid in sorted(edits):
        if tid not in tasks_by_id:
            raise ValueError(f"edit {tid} is not a task in this plan")
        if tasks_by_id[tid]["phase"] not in offer:
            raise ValueError(f"the edit to {tid} needs phase {tasks_by_id[tid]['phase']} in the offer")
    writes = [{"kind": "lock_claim", "on": "epic"}]
    if cr_entry is not None:
        # the decision is written first, so a crash later leaves it decided by this set (and the resume
        # finishes the work) rather than pending, where another set could decide it the other way
        writes.append({"kind": "cr_log_put", "entry": cr_entry, "note": "latest log file plus this entry; number allocated under the lock"})
    for phase in [p for p in sorted(plan["phases"], key=lambda p: p["order"]) if p["id"] in offer]:
        pid = phase["id"]
        first = len(writes)
        release = release_name(plan, phase)
        writes.append({"kind": "ensure_release", "phase": pid, "name": release,
                       "how": tr.get("field_map", {}).get("phase_release", "label")})
        tids = [t["id"] for t in sorted(plan["tasks"], key=lambda t: t["order"]) if t["phase"] == pid]
        for tid in tids:
            t = next(x for x in plan["tasks"] if x["id"] == tid)
            from check_hashes import owned_hash
            fields = {"title": t["title"], "body_owned": task_body(plan, overlay, t), "role_key": t["role_key"],
                      "phase": t["phase"], "key": t["key"]}
            # the create binds the exact text it writes, so preflight can refuse a PLANNED that differs (sixth review, M3)
            writes.append({"kind": "create_item", "key": f"gw:{plan['id']}:{tid}", "phase": pid, "not_ready": True,
                           "work_type": t["work_type"], "release": release, "owned_hash": owned_hash(fields)})
            if tid in edits:
                writes.append({"kind": "update_item", "key": t["key"], "phase": pid, "fields": "plan_owned",
                               "owned_hash": owned_hash(fields)})
        for tid in tids:
            t = next(x for x in plan["tasks"] if x["id"] == tid)
            writes.append({"kind": "link_parent", "key": t["key"], "to": plan["epic"]["key"],
                           "how": overlay["task_hierarchy"]["task_to_epic"]})
            for d in t["depends_on"]:
                writes.append({"kind": "link_dependency", "key": t["key"], "blocked_by": f"gw:{plan['id']}:{d['task']}"})
            if t.get("waits_on"):
                # Once, at create; the assignee or the wait's owner role clears it, and nothing reapplies it.
                writes.append({"kind": "set_blocked", "key": t["key"], "field": tr["field_map"]["blocked"],
                               "reason": "; ".join(w["what"] for w in t["waits_on"])})
        writes.append({"kind": "manifest_put", "phase": pid, "note": "after every batch of at most 10 writes"})
        for tid in tids:
            writes.append({"kind": "clear_not_ready", "key": f"gw:{plan['id']}:{tid}"})
        writes.append({"kind": "snapshot_put", "phase": pid})
        for w in writes[first:]:
            w["scope"] = f"phase:{pid}"
    for r in sorted(relinks or [], key=lambda r: r["task"]):
        t = tasks_by_id.get(r["task"])
        if t is None:
            raise ValueError(f"relink {r['task']} is not a task in this plan")
        now = {d["task"] for d in t["depends_on"]}
        if set(r["removed"]) & now or not set(r["added"]) <= now:
            raise ValueError(f"the relink of {r['task']} does not match its dependencies in the plan")
        for d in sorted(r["removed"]):
            writes.append({"kind": "unlink_dependency", "key": t["key"], "blocked_by": f"gw:{plan['id']}:{d}"})
        if t["phase"] not in offer:  # an offered phase links every dependency already
            for d in sorted(r["added"]):
                writes.append({"kind": "link_dependency", "key": t["key"], "blocked_by": f"gw:{plan['id']}:{d}"})
    for tid in sorted(unblocks or []):
        t = tasks_by_id.get(tid)
        if t is None or t.get("waits_on"):
            raise ValueError(f"{tid} still waits on something, so its blocked state stays")
        writes.append({"kind": "clear_blocked", "key": t["key"], "field": tr["field_map"]["blocked"]})
    if closes:
        prefix = tr["field_map"].get("close_label_prefix", "gw-closed:")
        writes.append({"kind": "manifest_put", "note": "close intent for " + ", ".join(c["key"] for c in closes)})
        for c in closes:
            writes.append({"kind": "add_label", "key": c["key"], "label": prefix + c["reason"]})
            writes.append({"kind": "close_item", "key": c["key"], "reason": c["reason"]})
        writes.append({"kind": "manifest_put", "note": "closes done"})
    if not any(p["state"] in ("writing", "released") for p in plan["phases"]):
        writes.append({"kind": "remove_label", "on": "epic", "label": overlay.get("labels", {}).get("draft", "gw-draft")})
    # preflight finds these at write time; the write list names the procedure so the approval covers it
    writes.append({"kind": "comment_split", "on": "written items whose points a person raised",
                   "note": "one comment recommending a split, never repeated (recorded as split_comment); points are never changed"})
    writes.append({"kind": "lock_release", "on": "epic"})
    for i, w in enumerate(writes, 1):
        w["no"] = i
        w["target"] = target
        w.setdefault("scope", "plan")
    return {"schema_version": "1.0", "plan_id": plan["id"], "plan_version": plan["version"], "phases": sorted(offer), "writes": writes}


PLAN_LEVEL_TITLES = {"decline": "Decline a change request", "own_epic": "Move a change request to its own epic",
                     "retire": "Retire this plan", "later": "Record later work as an outline phase"}


def plan_write_list(plan, overlay, kind, cr_entry=None):
    """The write list for a decline, own_epic or later set (planning model 4.3): only plan entries.

    cr_entry: the change-request log entry this set adds (the entry is bound, not the file
    number, which is allocated under the lock). Retire has its own fixed write order and
    uses `retire.py write-list`; no other kind closes items or writes a status file.
    """
    if kind == "retire":
        raise ValueError("a retire write list comes from retire.py write-list")
    if kind not in ("decline", "own_epic", "later"):
        raise ValueError("kind is decline, own_epic or later")
    if overlay.get("provisional"):
        raise ValueError("a provisional overlay has no tracker, so there is no write list (D-54)")
    want = {"decline": "declined", "own_epic": "own_epic", "later": "later"}[kind]
    if kind != "later" and cr_entry is None:
        raise ValueError(f"a {kind} write list binds the change-request entry it decides")
    if cr_entry is not None and cr_entry.get("outcome") != want:
        raise ValueError(f"a {kind} write list binds outcome {want}, not {cr_entry.get('outcome')}")
    tr = overlay["skills"]["tracker"]
    target = f"{tr['skill'].replace('groundwork-tracker-', '')}:{tr['instance']['id']}:{tr['instance']['project']}"
    writes = [{"kind": "lock_claim", "on": "epic"}]
    if cr_entry is not None:
        writes.append({"kind": "cr_log_put", "entry": cr_entry, "note": "latest log file plus this entry; number allocated under the lock"})
    writes.append({"kind": "snapshot_put"})
    writes.append({"kind": "lock_release", "on": "epic"})
    for i, w in enumerate(writes, 1):
        w.update(no=i, target=target, scope="plan")
    return {"schema_version": "1.0", "plan_id": plan["id"], "plan_version": plan["version"], "phases": [], "kind": kind,
            "writes": writes}


def proposal_context(plan, kind, summary, degraded=(), items=(), voided_sets=()):
    """proposal-context-<n>.json: every session- or tracker-dependent fact a proposal shows.

    Stored in the plan store at Proposal; create renders only from the plan of record,
    the write list and this file, never from session state or a fresh tracker read.
    items: [{key, status, person_added}] read from the tracker at Proposal (keys only;
    titles are untrusted and never rendered). voided_sets: pending sets this replaces.
    """
    return {"schema_version": "1.0", "plan_id": plan["id"], "plan_version": plan["version"], "kind": kind,
            "summary": summary, "degraded": sorted(degraded),
            "items": sorted(({"key": i["key"], "status": i["status"], "person_added": bool(i.get("person_added"))} for i in items),
                            key=lambda i: i["key"]),
            "voided_sets": sorted(voided_sets)}


def plan_level_proposal(plan, overlay, wl, context, assessment=None):
    """A plan-level proposal, rendered only from stored inputs."""
    if context["plan_id"] != plan["id"] or context["plan_version"] != plan["version"] or context["kind"] != wl.get("kind"):
        raise ValueError("the proposal context, plan and write list do not belong together")
    out = [f"# Proposal: {PLAN_LEVEL_TITLES[context['kind']]}", "",
           f"Plan {plan['id']} version {plan['version']}, plan hash {short(plan_hash(plan))}. "
           "This is a plan-level change: it offers no phase.", "", "## What and why", context["summary"], ""]
    if assessment is not None:
        # the stored assessment, so approvers outside the session see the fit, cost and options it showed
        import change_request
        out += change_request.render(assessment).rstrip("\n").split("\n") + [""]
    for w in wl["writes"]:
        if w["kind"] == "cr_log_put":
            e = w["entry"]
            out.append("## Change request decision")
            out.append(f"- `{e.get('id')}`: {str(e.get('outcome', e.get('decision', ''))).replace('_', ' ')}"
                       + (f". Reason: {e['reason']}" if e.get("reason") else ""))
            if e.get("restatement"):
                out.append(f"- The request, as the runner confirmed it: {e['restatement']}")
            out.append("")
        elif w["kind"] == "status_put":
            out.append("## Plan status")
            out.append(f"- The plan becomes {w['status']['status']}. The status file's number, set_by and time are "
                       "filled in at write time from the verified set.")
            out.append("")
    closes = [w for w in wl["writes"] if w["kind"] == "close_item"]
    out.append("## Items this closes")
    out += [f"- `{w['key']}`, as {w['reason'].replace('_', ' ')}" for w in closes] or ["None."]
    out.append("")
    if wl.get("kind") == "retire":
        out.append("## Items left open")
        out += [f"- `{x['key']}`, owned by {role_name(overlay, x['owner_role_key'])}" for x in wl.get("left_open", [])] or ["None."]
        out.append("")
        out.append("## Children a person added (left open)")
        out += [f"- `{k}`" for k in wl.get("person_added", [])] or ["None."]
        out.append("")
        out.append("## Pending phase approvals this retire voids")
        out += [f"- {p}" for p in wl.get("voids_pending", [])] or ["None."]
        out.append("")
    out.append("## Items on the epic when this was proposed")
    if context["items"]:
        for i in context["items"]:
            out.append(f"- `{i['key']}`: {i['status'].replace('_', ' ')}" + (", added by a person, not by Groundwork" if i["person_added"] else ""))
        out.append("")
        out.append("Create stops and asks for a new proposal if an open plan-owned item exists that is not in this list.")
    else:
        out.append("None.")
    out.append("")
    if context["voided_sets"]:
        out.append("## Pending approvals this replaces")
        out += [f"- {v}" for v in context["voided_sets"]]
        out.append("")
    if context["degraded"]:
        out.append("## Checks not fully run")
        out += [f"- {d}" for d in context["degraded"]]
        out.append("")
    out.append("## Write list")
    for w in wl["writes"]:
        detail = ", ".join(f"{k} {v}" if not isinstance(v, (dict, list)) else f"{k} `{canonicalize(v).decode()}`"
                           for k, v in w.items() if k not in ("no", "kind", "target", "scope", "note"))
        out.append(f"{w['no']}. {w['kind']}" + (f" ({detail})" if detail else ""))
    out.append("")
    out.append(f"Write list hash {short(write_list_hash(wl))}.")
    return "\n".join(out) + "\n"


def brief_value(f):
    if f["status"] == "not_applicable":
        return f"not applicable: {f['na_reason']}"
    if f["status"] == "open":
        return f"open, see {f['open_question']}"
    if f["sensitivity"] == "restricted":
        return "restricted, answered"
    return f["value"]


def model_sections(plan, overlay):
    """Brief, traits and approach (plan format 2). Restricted values render only as 'restricted, answered'."""
    out = ["## Brief", "| Id | Field | Answer | Source |", "| --- | --- | --- | --- |"]
    for f in plan["brief"]:
        src = f["source"] + (f", confirmed by {role_name(overlay, f['basis_role_key'])}" if f["basis_role_key"] else "")
        parked = f" (parked on {f['phase']})" if f["phase"] else ""
        out.append(f"| {f['id']} | {f['key']} | {brief_value(f)}{parked} | {src} |")
    out.append("")
    out.append("**Traits:** " + (", ".join(f"{t['id']} {t['version']}" for t in plan["traits"]) or "none of the listed traits apply"))
    out.append("")
    ap = plan["approach"]
    out.append("## Approach")
    out.append("**Options considered**")
    for o in ap["options"]:
        basis = f"{len(o['evidence'])} evidence item{'s' if len(o['evidence']) != 1 else ''}" if o["evidence"] else f"not inspected: {o['not_inspected_reason']}"
        verdict = f" Rejected because of {o['rejected_because']['brief_ref']}: {o['rejected_because']['why']}" if o["rejected_because"] else " Chosen."
        out.append(f"- **{o['id']}** ({o['kind'].replace('_', ' ')}) {o['summary']} Basis: {basis}.{verdict}")
    out.append("")
    out.append("**Decisions**")
    for d in ap["decisions"]:
        if d["chosen_option"] == "deferred":
            out.append(f"- **{d['id']}** {d['decision']} Deferred: settled by {d['deferred_to_task']}; tasks that rely on it wait until then.")
        else:
            out.append(f"- **{d['id']}** {d['decision']} Chose {d['chosen_option']}. Serves {', '.join(d['brief_refs']) or 'nothing listed'}.")
    if ap["unchanged"]:
        out.append("")
        out.append("**Stays unchanged:** " + ", ".join(ap["unchanged"]))
    out.append("")
    return out


def other_writes(plan, wl):
    """What a phase write list does besides creating its phases: updates, closes, a change-request
    decision. Approvers outside the session see only the proposal, so each is named here."""
    by_key = {t["key"]: t["id"] for t in plan["tasks"]}
    ups = [w for w in wl["writes"] if w["kind"] == "update_item"]
    closes = [w for w in wl["writes"] if w["kind"] == "close_item"]
    crs = [w for w in wl["writes"] if w["kind"] == "cr_log_put"]
    out = []
    if ups:
        out.append("**Tasks whose plan-owned text is updated:** "
                   + ", ".join(f"{by_key.get(w['key'], w['key'])} (`{w['owned_hash'][:12]}`)" for w in ups) + ".")
    rel = [w for w in wl["writes"] if w["kind"] in ("unlink_dependency", "link_dependency") and w.get("scope") == "plan"]
    if rel:
        out.append("**Dependencies re-pointed on written tasks:** " + ", ".join(
            f"{by_key.get(w['key'], w['key'])} {'no longer' if w['kind'] == 'unlink_dependency' else 'now'} waits on "
            f"{by_key.get(w['blocked_by'], w['blocked_by'])}" for w in rel) + ".")
    unb = [w for w in wl["writes"] if w["kind"] == "clear_blocked"]
    if unb:
        out.append("**Blocked state cleared (the wait was removed):** " + ", ".join(by_key.get(w["key"], w["key"]) for w in unb) + ".")
    if closes:
        out.append("**Tasks closed:** " + ", ".join(f"`{w['key']}` as {w['reason'].replace('_', ' ')}" for w in closes) + ".")
    for w in crs:
        e = w["entry"]
        out.append(f"**Change request decided:** `{e.get('id')}`, {e.get('outcome')}. Reason: {e.get('reason')}"
                   + (f" The request, as the runner confirmed it: {e['restatement']}" if e.get("restatement") else ""))
    return out + ([""] if out else [])


def proposal(plan, overlay, offer, wl=None):
    tasks = {t["id"]: t for t in plan["tasks"]}
    phases = sorted(plan["phases"], key=lambda p: p["order"])
    ph = phase_hashes(plan)
    out = [f"# Proposal: {plan['title']}", ""]
    if overlay.get("provisional"):
        out += [PROVISIONAL_BANNER, ""]
    out.append(f"Plan {plan['id']} version {plan['version']}, overlay {plan['overlay']['id']} v{plan['overlay']['version']}.")
    out.append("")
    open_q = [q for q in plan["open_questions"] if q["status"] == "open"]
    out.append("## Open questions")
    if open_q:
        for q in open_q:
            out.append(f"- **{q['id']}** {q['text']} Blocks: {', '.join(q['blocks'])}.")
    else:
        out.append("None.")
    out.append("")
    out.append("## Request")
    out.append(plan["request"]["restatement"])
    out.append("")
    out.append("**In scope:** " + "; ".join(plan["scope"]["in"]))
    out.append("")
    out.append("**Out of scope:** " + ("; ".join(plan["scope"]["out"]) or "nothing listed"))
    out.append("")
    sp = plan["request"]["starting_point"]
    out.append("## What already exists")
    if sp["kind"] == "from_scratch":
        out.append("Nothing; this project starts from scratch.")
    for r in sp["resources"]:
        how = f"inspected ({len(r['inspected'])} evidence item{'s' if len(r['inspected']) != 1 else ''})" if r["inspected"] else f"not inspected: {r['not_inspected_reason']}"
        changed = [t["id"] for t in plan["tasks"] if t.get("changes_existing") and r["id"] in t["changes_existing"]["resources"]]
        out.append(f"- **{r['id']} {r['name']}** ({r['kind']}, {r['location']}): {how}. "
                   + (f"Changed by {', '.join(changed)}." if changed else "Not changed."))
    out.append("")
    if "brief" in plan:
        out += model_sections(plan, overlay)
    legacy_waits = [(t, w) for t in sorted(plan["tasks"], key=lambda t: t["order"]) if t["phase"] in offer
                    for w in t["waits_on"] if w.get("legacy_ref")]
    if legacy_waits:
        out.append("## Waits on legacy items")
        out.append("These items are outside this plan and are never written to. Before approving, confirm each wait is still pending.")
        for t, w in legacy_waits:
            out.append(f"- {t['id']} waits for `{w['legacy_ref']}`: {w['what']} (owner: {role_name(overlay, w['owner_role_key'])})")
        out.append("")
    if overlay.get("org_process"):
        out.append("## Org processes that apply")
        out += [f"- **{x['name']}** {x['note']}" for x in overlay["org_process"]]
        out.append("")
    out.append("## What was and wasn't inspected")
    out.append("| System | Instance | Status | Read-only | Inspected | Not inspected |")
    out.append("| --- | --- | --- | --- | --- | --- |")
    for c in plan["coverage"]:
        reason = f" ({c['reason']})" if c["reason"] else ""
        out.append(f"| {c['system']} | {c['instance']} | {c['status']}{reason} | {c['read_only']} | {', '.join(c['inspected']) or 'nothing'} | {', '.join(c['not_inspected']) or 'nothing'} |")
    out.append("")
    rev = plan["review"].get("reviewer")
    out.append("## Review")
    val = plan["review"].get("validator")
    if val:
        out.append(f"Validator {val['version']}: {'passed' if val['passed'] else 'blockers remain'}.")
    if rev:
        how = "a subagent" if rev["mode"] == "subagent" else "a fresh conversation the runner started"
        out.append(f"Independent review by {how} on {rev['surface']} ({rev['model']}), reviewer view {short(rev['view_hash'])}.")
        if rev["not_performed"]:
            out.append("Checks the reviewer could not perform: " + "; ".join(rev["not_performed"]) + ".")
    else:
        out.append("No independent review is recorded. This plan cannot be approved until one is.")
    if val and val.get("not_run"):
        out.append("Checks not run in the session that made this proposal: " + "; ".join(val["not_run"]) + ".")
    minors = [f for f in (val["results"] if val else []) + (rev["findings"] if rev else []) if f["severity"] == "minor"]
    if minors:
        out.append("")
        out.append("**Minor findings, for acceptance by id:**")
        for f in minors:
            out.append(f"- {f['id']} ({f['check']}, {f['target'] or 'plan'}): {f['what']}")
    out.append("")
    out.append("## Phases")
    out.append("| Phase | Name | Goal | State | Tasks | Offered now | Phase hash |")
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for p in phases:
        state = "outline, needs a planning run" if p["state"] == "outline" else p["state"]
        out.append(f"| {p['id']} | {p['name']} | {p['goal']} | {state} | {len(p['task_ids'])} | {'yes' if p['id'] in offer else 'no'} | {short(ph[p['id']])} |")
    out.append("")
    out.append("## Tasks")
    out.append("| Task | Title | Role | Hours | Depends on | Visible result |")
    out.append("| --- | --- | --- | --- | --- | --- |")
    for t in sorted(plan["tasks"], key=lambda t: t["order"]):
        deps = ", ".join(f"{d['task']} {d['satisfied_by']}" for d in t["depends_on"]) or "none"
        if t["waits_on"]:
            deps += "; waits on " + ", ".join(w["what"] for w in t["waits_on"])
        out.append(f"| {t['id']} | {t['title']} | {role_name(overlay, t['role_key'])} | {t['estimate_hours']} | {deps} | {t['visible_result']['text']} |")
    out.append("")
    out.append("## Access list")
    out.append("| Id | Role | System | Access | Needed by |")
    out.append("| --- | --- | --- | --- | --- |")
    for a in plan["access_list"]:
        out.append(f"| {a['id']} | {role_name(overlay, a['role_key'])} | {a['system']} {a['instance']} | {a['level']} | {', '.join(a['needed_by'])} |")
    out.append("")
    copied = [(t["id"], i, s) for t in sorted(plan["tasks"], key=lambda t: t["order"]) for i, s in enumerate(t["instructions"]["steps"], 1) if s["from_evidence"]]
    out.append("## Commands taken from the org's own files")
    if copied:
        out.extend(f"- {tid} step {i}: {s['text']} (from {s['from_evidence']})" for tid, i, s in copied)
    else:
        out.append("None.")
    out.append("")
    out.append("## Task instructions")
    for t in sorted(plan["tasks"], key=lambda t: t["order"]):
        if t["phase"] not in offer:
            continue
        out.append(f"### {t['id']} {t['title']}")
        body = task_body(plan, overlay, t)
        out.append(body.replace(OWNED_START + "\n", "").replace("\n" + OWNED_END, ""))
        out.append("")
    out.append("## Approval")
    if overlay.get("provisional"):
        out.append("None yet. This plan was drafted without a tracker connection, so nothing can be approved or written. "
                   "Set up Groundwork for your tracker, then resume: the plan is re-checked against the real tracker and reviewed again.")
        out.append("")
        out.append(stamps_footer(plan))
        return "\n".join(out) + "\n"
    out.append(f"Phases offered: {', '.join(sorted(offer))}. plan_hash {short(plan_hash(plan))}.")
    if wl:
        out += other_writes(plan, wl)
        out.append(f"Write list: {len(wl['writes'])} numbered writes, write_list_hash {short(write_list_hash(wl))}.")
    out.append("Each approver posts their own approval record as a comment on the epic, from their own tracker account.")
    out.append("")
    out.append(stamps_footer(plan))
    return "\n".join(out) + "\n"


def epic_description(plan, overlay):
    out = [OWNED_START, plan["epic"]["summary"], "", "| Phase | Name | State |", "| --- | --- | --- |"]
    for p in sorted(plan["phases"], key=lambda p: p["order"]):
        state = {"outline": "outline, needs a planning run", "released": "released"}.get(p["state"], "planned, not released")
        out.append(f"| {p['id']} | {p['name']} | {state} |")
    out.append("")
    out.append("**Access list**")
    out.extend(f"- {a['id']}: {role_name(overlay, a['role_key'])}, {a['level']}" for a in plan["access_list"])
    out.append("")
    out.append("**Role holders**")
    out.extend(f"- {role_name(overlay, r['role_key'])}: {r['display']}" + (f" ({r['handle']})" if r.get("handle") else "") for r in overlay.get("role_holders", []))
    req = overlay.get("access_requests")
    if req:
        out.append("")
        out.append(f"**Access requests:** {req['how']}" + (f" {req['link']}" if req.get("link") else ""))
    ch = overlay.get("channels") or {}
    if ch:
        out.append(f"**Channels:** release {ch.get('release') or 'none'}, announcements {ch.get('announcements') or 'none'}")
    out.append("")
    out.append(f"`{plan['epic']['key']}` · overlay `{plan['overlay']['id']}` v{plan['overlay']['version']} {short(plan['overlay']['hash'])}")
    out.append(stamps_footer(plan))
    out.append(OWNED_END)
    return "\n".join(out)


def proposal_hash(text):
    return sha256_hex(text.encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["proposal", "task", "epic", "write-list", "plan-level", "plan-write-list", "context"])
    ap.add_argument("--kind", help="plan-write-list and context: decline, own_epic, later (context also retire)")
    ap.add_argument("--entry", help="write-list (outcome added) and plan-write-list: the change-request log entry JSON this set binds")
    ap.add_argument("--summary", help="context: the proposal's what-and-why, in Groundwork's words")
    ap.add_argument("--items", help="context: JSON [{key, status, person_added}] read from the tracker at Proposal")
    ap.add_argument("--voided", nargs="*", default=[], help="context: pending sets this replaces")
    ap.add_argument("--degraded", nargs="*", default=[], help="context: checks not fully run")
    ap.add_argument("--context", help="proposal-context JSON (plan-level proposals)")
    ap.add_argument("--assessment", help="plan-level: the change request's stored assessment (change_request.py assess), if any")
    ap.add_argument("plan")
    ap.add_argument("--overlay", required=True)
    ap.add_argument("--offer")
    ap.add_argument("--task")
    ap.add_argument("--write-list")
    ap.add_argument("--closes", help="JSON file of [{key, reason}] to close (revise)")
    ap.add_argument("--relinks", help="JSON file of revise_diff relinks [{task, added, removed}] (revise)")
    ap.add_argument("--unblocks", help="comma-separated written task ids whose waits a revise removed (revise_diff unblocks)")
    ap.add_argument("--edits", help="comma-separated task ids whose plan-owned text changed (revise_diff changed)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan, encoding="utf-8"))
    overlay = gw_yaml.load(a.overlay)
    offer = set(x.strip() for x in a.offer.split(",") if x.strip()) if a.offer is not None else {p["id"] for p in plan["phases"] if p["state"] != "outline"}
    if a.what == "proposal":
        if overlay.get("provisional"):
            wl = None
        else:
            wl = json.load(open(a.write_list, encoding="utf-8")) if a.write_list else write_list(plan, overlay, offer)
        text = proposal(plan, overlay, offer, wl)
    elif a.what == "task":
        text = task_body(plan, overlay, next(t for t in plan["tasks"] if t["id"] == a.task))
    elif a.what == "plan-level":
        text = plan_level_proposal(plan, overlay, json.load(open(a.write_list, encoding="utf-8")),
                                   json.load(open(a.context, encoding="utf-8")),
                                   json.load(open(a.assessment, encoding="utf-8")) if a.assessment else None)
    elif a.what == "plan-write-list":
        entry = json.load(open(a.entry, encoding="utf-8")) if a.entry else None
        text = json.dumps(plan_write_list(plan, overlay, a.kind, entry), indent=2)
    elif a.what == "context":
        items = json.load(open(a.items, encoding="utf-8")) if a.items else []
        text = json.dumps(proposal_context(plan, a.kind, a.summary, a.degraded, items, a.voided), indent=2)
    elif a.what == "epic":
        text = epic_description(plan, overlay)
    else:
        closes = json.load(open(a.closes, encoding="utf-8")) if a.closes else None
        edits = [x.strip() for x in (a.edits or "").split(",") if x.strip()]
        entry = json.load(open(a.entry, encoding="utf-8")) if a.entry else None
        if entry is not None and entry.get("outcome") != "added":
            raise SystemExit("a revision write list binds a change request only with outcome added")
        relinks = json.load(open(a.relinks, encoding="utf-8")) if a.relinks else None
        unblocks = [x.strip() for x in (a.unblocks or "").split(",") if x.strip()]
        text = json.dumps(write_list(plan, overlay, offer, closes, cr_entry=entry, edits=edits, relinks=relinks,
                                     unblocks=unblocks), indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    if a.what in ("proposal", "plan-level"):
        print(f"proposal_hash {proposal_hash(text)}", file=sys.stderr)
    if a.what in ("write-list", "plan-write-list"):
        print(f"write_list_hash {write_list_hash(json.loads(text))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
