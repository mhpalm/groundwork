# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Planning model helpers (plan format 2): the brief, traits and approach.

Format-1 plans have no brief, traits or approach. Every function here treats a
format-1 plan as "not applicable" so older plans keep validating unchanged.
"""

import os

import gw_yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TRAITS_FILE = os.path.join(HERE, "..", "reference", "traits.yaml")

# Always asked in Clarify (plan format 2).
CORE_KEYS = ["outcome", "success_measure", "scope_in", "non_goals", "starting_point", "consumers", "constraints", "risks",
             "deliverable_signoffs", "run_owner_after_handoff", "external_dependencies", "budget", "legal_duties",
             "nonfunctional", "comms_audiences"]
# Approvers must always see these, so they can never be restricted (a sensitive source is paraphrased instead).
UNRESTRICTABLE = ("outcome", "success_measure", "scope_in", "non_goals")
# A task's brief_refs must reach one of these, directly or through a decision (necessity is judged against the brief).
TRACE_KEYS = ("outcome", "scope_in")


def plan_format(plan):
    try:
        return int(str(plan.get("stamps", {}).get("plan_format", "1.0")).split(".")[0])
    except ValueError:
        return 1


def plan_format_minor(plan):
    """(major, minor) of stamps.plan_format; (1, 0) when it is missing or malformed."""
    try:
        a, b = str(plan.get("stamps", {}).get("plan_format", "1.0")).split(".")
        return int(a), int(b)
    except ValueError:
        return 1, 0


def body_layout(plan):
    """Task body layout: 2 for plan format 2.1 and later, 1 before (kept byte for byte so stored hashes match)."""
    return 2 if plan_format_minor(plan) >= (2, 1) else 1


def is_model_plan(plan):
    return plan_format(plan) >= 2


def load_traits(overlay=None):
    """{(id, version): trait} for core traits plus the overlay's x- traits."""
    data = gw_yaml.load(TRAITS_FILE)
    out = {(t["id"], t["version"]): t for t in data["traits"]}
    for t in (overlay or {}).get("traits", []) or []:
        out[(t["id"], t["version"])] = t
    return out


def pinned_traits(plan, overlay=None):
    """(traits found, ids or versions not found)."""
    known = load_traits(overlay)
    found, missing = [], []
    for p in plan.get("traits", []):
        t = known.get((p["id"], p["version"]))
        (found.append((p, t)) if t else missing.append(f"{p['id']}@{p['version']}"))
    return found, missing


def required_keys(plan, overlay=None):
    keys = list(CORE_KEYS)
    for _p, t in pinned_traits(plan, overlay)[0]:
        for q in t.get("questions", []):
            if q["key"] not in keys:
                keys.append(q["key"])
    return keys


def trait_kinds(plan, overlay=None):
    kinds = []
    for _p, t in pinned_traits(plan, overlay)[0]:
        for k in t.get("standard_work", []):
            if k not in kinds:
                kinds.append(k)
    return kinds


def brief_by_id(plan):
    return {f["id"]: f for f in plan.get("brief", [])}


def brief_by_key(plan):
    return {f["key"]: f for f in plan.get("brief", [])}


def traces_to_brief(plan, task):
    """True when the task's brief_refs, or the brief_refs of a decision it cites, reach outcome or scope_in."""
    fields = brief_by_id(plan)
    ads = {d["id"]: d for d in plan.get("approach", {}).get("decisions", [])}
    refs = list(task.get("brief_refs", []))
    for a in task.get("approach_refs", []):
        refs += ads.get(a, {}).get("brief_refs", [])
    return any(fields.get(r, {}).get("key") in TRACE_KEYS for r in refs)


def basis_subset(plan, phase_id):
    """What phase P relies on, without P's own tasks (informational only; never an approval binding).

    The brief fields its tasks cite, the decisions they cite with each decision's
    chosen and rejected options in full, the brief fields those options'
    rejections cite, the open questions that block P or one of P's tasks, and
    P's access lines.
    """
    tasks = [t for t in plan.get("tasks", []) if t["phase"] == phase_id]
    tids = {t["id"] for t in tasks}
    fields = brief_by_id(plan)
    approach = plan.get("approach", {"options": [], "decisions": []})
    ads = {d["id"]: d for d in approach.get("decisions", [])}
    opts = {o["id"]: o for o in approach.get("options", [])}
    ad_ids = sorted({a for t in tasks for a in t.get("approach_refs", [])})
    b_ids = {b for t in tasks for b in t.get("brief_refs", [])}
    for a in ad_ids:
        b_ids |= set(ads.get(a, {}).get("brief_refs", []))
    options = sorted(opts.values(), key=lambda o: o["id"]) if ad_ids else []
    for o in options:
        if o.get("rejected_because"):
            b_ids.add(o["rejected_because"]["brief_ref"])
    access = sorted({a for t in tasks for a in t.get("access", [])})
    return {
        "brief": [fields[b] for b in sorted(b_ids) if b in fields],
        "decisions": [ads[a] for a in ad_ids if a in ads],
        "options": options,
        "open_questions": [q for q in plan.get("open_questions", []) if set(q["blocks"]) & (tids | {phase_id})],
        "access": [x for x in plan.get("access_list", []) if x["id"] in access],
    }
