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
from gw_canon import sha256_hex, short  # noqa: E402
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


def write_list(plan, overlay, offer, closes=None):
    """The numbered write list for the offered phases. Hashing it binds approval to exactly these writes.

    closes: [{key, reason}] for items to close (revise); rendered as the close procedure:
    a close-intent manifest first, then each item's gw-closed label and transition, then a manifest.
    """
    if overlay.get("provisional"):
        raise ValueError("a provisional overlay has no tracker, so there is no write list (D-54)")
    tr = overlay["skills"]["tracker"]
    target = f"{tr['skill'].replace('groundwork-tracker-', '')}:{tr['instance']['id']}:{tr['instance']['project']}"
    writes = [{"kind": "lock_claim", "on": "epic"}]
    for phase in [p for p in sorted(plan["phases"], key=lambda p: p["order"]) if p["id"] in offer]:
        pid = phase["id"]
        release = release_name(plan, phase)
        writes.append({"kind": "ensure_release", "phase": pid, "name": release,
                       "how": tr.get("field_map", {}).get("phase_release", "label")})
        tids = [t["id"] for t in sorted(plan["tasks"], key=lambda t: t["order"]) if t["phase"] == pid]
        for tid in tids:
            t = next(x for x in plan["tasks"] if x["id"] == tid)
            writes.append({"kind": "create_item", "key": f"gw:{plan['id']}:{tid}", "phase": pid, "not_ready": True,
                           "work_type": t["work_type"], "release": release})
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
    if closes:
        prefix = tr["field_map"].get("close_label_prefix", "gw-closed:")
        writes.append({"kind": "manifest_put", "note": "close intent for " + ", ".join(c["key"] for c in closes)})
        for c in closes:
            writes.append({"kind": "add_label", "key": c["key"], "label": prefix + c["reason"]})
            writes.append({"kind": "close_item", "key": c["key"], "reason": c["reason"]})
        writes.append({"kind": "manifest_put", "note": "closes done"})
    if not any(p["state"] in ("writing", "released") for p in plan["phases"]):
        writes.append({"kind": "remove_label", "on": "epic", "label": overlay.get("labels", {}).get("draft", "gw-draft")})
    writes.append({"kind": "lock_release", "on": "epic"})
    for i, w in enumerate(writes, 1):
        w["no"] = i
        w["target"] = target
    return {"schema_version": "1.0", "plan_id": plan["id"], "plan_version": plan["version"], "phases": sorted(offer), "writes": writes}


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
    ap.add_argument("what", choices=["proposal", "task", "epic", "write-list"])
    ap.add_argument("plan")
    ap.add_argument("--overlay", required=True)
    ap.add_argument("--offer")
    ap.add_argument("--task")
    ap.add_argument("--write-list")
    ap.add_argument("--closes", help="JSON file of [{key, reason}] to close (revise)")
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
    elif a.what == "epic":
        text = epic_description(plan, overlay)
    else:
        closes = json.load(open(a.closes, encoding="utf-8")) if a.closes else None
        text = json.dumps(write_list(plan, overlay, offer, closes), indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    if a.what == "proposal":
        print(f"proposal_hash {proposal_hash(text)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
