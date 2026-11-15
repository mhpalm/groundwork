#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Groundwork plan validator: the mechanical (V) gap-review checks.

Usage:
  validate_plan.py PLAN.json --overlay OVERLAY.yaml --evidence DIR
                   [--offer P0,P1] [--now 2026-11-14T00:00:00Z]
                   [--stage draft|proposal|create] [--proposal proposal.md]
                   [--out results.json]

Exit code 0 when no blocker is found in the phases being offered, 1 when
there are blockers, 2 when the inputs cannot be read. The results file is
the `review.validator` block of the plan.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_model  # noqa: E402
import gw_yaml  # noqa: E402
from gw_hash import item_hash  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402

VERSION = "1.0.0"
STANDARD_KINDS = ["test", "uat", "cutover", "rollback", "docs", "handoff"]
INSTRUCTION_PARTS = ["purpose", "prerequisites", "steps", "acceptance_criteria", "verify", "done_today"]

SECRET_PATTERNS = [
    ("github token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("stripe key", re.compile(r"\b(sk|rk)_(live|test)_[A-Za-z0-9]{10,}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("password", re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*\S{4,}")),
    ("us ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
RESERVED_DOMAINS = ("example.com", "example.org", "example.net", "example.edu")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def luhn(digits):
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


class Results:
    def __init__(self, offered):
        self.items = []
        self.offered = offered
        self.not_run = []  # checks that could not run in this session, shown in the proposal

    def add(self, check, severity, target, what, fix="", evidence_ids=None, phase=None):
        self.items.append({
            "id": f"V-{len(self.items) + 1}", "check": check, "severity": severity,
            "target": target, "what": what, "evidence_ids": evidence_ids or [],
            "suggested_fix": fix, "resolution": "open", "_phase": phase,
        })

    def blocking(self):
        out = []
        for f in self.items:
            if f["severity"] != "blocker":
                continue
            if f["_phase"] is None or f["_phase"] in self.offered:
                out.append(f)
        return out

    def export(self):
        return [{k: v for k, v in f.items() if not k.startswith("_")} for f in self.items]


def strings(obj, path="$"):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from strings(v, f"{path}[{i}]")


def gr17_scan(src, blob):
    """GR-17 over any JSON value: [(what, fix)] for secrets, personal email addresses and card numbers."""
    out = []
    for path, s in strings(blob):
        for label, pat in SECRET_PATTERNS:
            if pat.search(s):
                out.append((f"{src} {path} looks like it contains a {label}", "Remove it; record structure only"))
        for m in EMAIL.finditer(s):
            dom = m.group(0).split("@", 1)[1].lower()
            if not dom.endswith(RESERVED_DOMAINS):
                out.append((f"{src} {path} contains an email address", "Name the role, not the person's address"))
        for m in CARD.finditer(s):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and luhn(digits):
                out.append((f"{src} {path} contains what looks like a card number", "Remove it"))
    return out


def parse_ts(s):
    return dt.datetime.strptime(s.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)


def load_evidence(path):
    items = []
    if not path:
        return items
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            if name.endswith(".json") and name != "manifest.json":
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    data = json.load(f)
                items.extend(data if isinstance(data, list) else [data])
    return items


def ancestors(task_id, deps):
    seen, stack = set(), list(deps.get(task_id, []))
    while stack:
        t = stack.pop()
        if t in seen:
            continue
        seen.add(t)
        stack.extend(deps.get(t, []))
    return seen


def find_cycle(deps):
    WHITE, GREY, BLACK = 0, 1, 2
    color = {t: WHITE for t in deps}

    def visit(t, path):
        color[t] = GREY
        for d in deps.get(t, []):
            if d not in color:
                continue
            if color[d] == GREY:
                return path + [t, d]
            if color[d] == WHITE:
                c = visit(d, path + [t])
                if c:
                    return c
        color[t] = BLACK
        return None

    for t in deps:
        if color[t] == WHITE:
            c = visit(t, [])
            if c:
                return c
    return None


# A plan-level set that changes no version (decline, own epic, retire) is checked with these only
# (planning model 4.3): the shape, the evidence's integrity, the org boundary, secrets and restricted values.
INTEGRITY_CHECKS = ("SCHEMA", "EVIDENCE-HASH", "EVIDENCE-ID", "CR-12", "GR-17", "GR-25", "GR-34")


def check(plan, overlay, evidence, offered_arg=None, now=None, stage="draft", proposal_text=None,
          restricted=None, done_tasks=None, profile="plan"):
    """restricted: {brief id: plaintext} from the run folder's restricted.json, when this session has it.
    done_tasks: task ids the tracker reports done or closed_not_done (revise), exempt from GR-31's trace rule.
    profile: "plan"; "assess" for a reconstruction with no phases (open questions may block nothing); or
    "integrity" for a plan-level set with no version change, which offers no phase and reports only
    INTEGRITY_CHECKS."""
    if profile == "integrity":
        R = _check(plan, overlay, evidence, [], now, stage, proposal_text, restricted, done_tasks, "plan")
        R.items = [f for f in R.items if f["check"] in INTEGRITY_CHECKS]
        R.offered = set()
        for f in R.items:
            f["_phase"] = None  # nothing is offered, so every integrity finding counts
        return R
    return _check(plan, overlay, evidence, offered_arg, now, stage, proposal_text, restricted, done_tasks, profile)


def _check(plan, overlay, evidence, offered_arg=None, now=None, stage="draft", proposal_text=None,
           restricted=None, done_tasks=None, profile="plan"):
    phases = {p["id"]: p for p in plan.get("phases", [])}
    drafted = [p["id"] for p in plan.get("phases", []) if p.get("state") != "outline"]
    # None means "not given": offer every drafted phase. An empty list means no phases.
    offered = set(offered_arg) if offered_arg is not None else set(drafted)
    R = Results(offered)

    # Schema first: if the shape is wrong, later checks can't be trusted.
    errs = validate(plan, load_schema("plan"))
    for e in errs[:50]:
        cid = "SCHEMA"
        for frag, gr in ((".points", "GR-15"), (".visible_result", "GR-03"), (".waits_on", "GR-16"),
                         (".satisfied_by", "GR-23"), (".estimate_hours", "GR-01"), (".instructions", "GR-05")):
            if frag in e.split(":")[0]:
                cid = gr
        R.add(cid, "blocker", None, f"plan.json: {e}", "Fix the field so it matches plan.schema.json")
    if errs:
        return R
    oerrs = validate(overlay, load_schema("overlay"))
    for e in oerrs[:20]:
        R.add("SCHEMA", "blocker", None, f"overlay: {e}", "Run validate_overlay.py and fix the overlay")
    ev_by_id = {}
    ev_schema = load_schema("evidence")
    for item in evidence:
        for e in validate(item, ev_schema)[:5]:
            R.add("SCHEMA", "blocker", item.get("id"), f"evidence: {e}", "Re-run discovery for this item")
        if "hash" in item and item_hash(item) != item["hash"]:
            R.add("EVIDENCE-HASH", "blocker", item.get("id"), "evidence item hash does not match its contents",
                  "The item was edited after discovery; re-discover it")
        if item.get("id") in ev_by_id:
            R.add("EVIDENCE-ID", "blocker", item.get("id"), "duplicate evidence id", "Ids are derived from the subject; merge the duplicates")
        ev_by_id[item.get("id")] = item
        if item.get("run_id") != plan["id"] and stage != "draft":
            pass  # imported bundles keep their own run id; overlay match below is what matters
        if item.get("overlay_id") != overlay.get("id"):
            R.add("CR-12", "blocker", item.get("id"), "evidence was collected under a different overlay",
                  "Discard it and discover again under this org's overlay")

    tasks = {t["id"]: t for t in plan["tasks"]}
    # GR-27 (D-55): what already exists is recorded, and each existing resource was inspected or says why not.
    sp = plan["request"]["starting_point"]
    res_ids = {r["id"] for r in sp["resources"]}
    if sp["kind"] == "extends_existing" and not sp["resources"]:
        R.add("GR-27", "blocker", None, "plan extends existing work but lists no existing resource",
              "List each existing resource the runner named")
    if sp["kind"] == "from_scratch" and sp["resources"]:
        R.add("GR-27", "blocker", None, "plan starts from scratch but lists existing resources", "Set kind to extends_existing")
    for r in sp["resources"]:
        if not r["inspected"] and not (r["not_inspected_reason"] or "").strip():
            R.add("GR-27", "blocker", r["id"], "existing resource was neither inspected nor marked not inspected with a reason",
                  "Inspect it read-only, or record why it could not be")
        for e in r["inspected"]:
            if e not in ev_by_id:
                R.add("GR-27", "blocker", r["id"], f"says it was inspected by {e}, which discovery did not find",
                      "Discover it or remove the reference")
    whd = plan["executor"]["working_day_hours"]
    if overlay.get("working_day_hours") not in (None, whd):
        R.add("EXECUTOR", "blocker", None, "executor.working_day_hours differs from the overlay",
              "Copy working_day_hours from the overlay")
    if overlay.get("assumed_executor") not in (None, plan["executor"]["profile"]):
        R.add("EXECUTOR", "blocker", None, "executor.profile differs from the overlay", "Copy assumed_executor from the overlay")
    if plan["overlay"]["id"] != overlay.get("id"):
        R.add("CR-12", "blocker", None, "plan is bound to a different overlay id", "Use the overlay this plan was made with")
    if overlay.get("hash") and plan["overlay"]["hash"] != overlay["hash"]:
        R.add("CR-12", "blocker", None, "plan's overlay hash differs from the loaded overlay",
              "The overlay changed since drafting; re-run Draft against the current overlay")

    # Identity and structure
    if plan["epic"]["key"] != f"gw:{plan['id']}:epic":
        R.add("KEY", "blocker", None, "epic key does not match the plan id", f"Set epic.key to gw:{plan['id']}:epic")
    if len(tasks) != len(plan["tasks"]):
        R.add("ID", "blocker", None, "duplicate task ids", "Task ids are append-only and unique")
    if "P0" not in phases:
        R.add("GR-13", "blocker", None, "plan has no P0 setup phase", "Add P0 with the access and environment requests")
    listed = {}
    for p in plan["phases"]:
        for tid in p["task_ids"]:
            listed.setdefault(tid, []).append(p["id"])
            if tid not in tasks:
                R.add("ID", "blocker", tid, f"phase {p['id']} lists unknown task {tid}", "Remove it or add the task", phase=p["id"])
            elif tasks[tid]["phase"] != p["id"]:
                R.add("ID", "blocker", tid, f"task says phase {tasks[tid]['phase']} but is listed under {p['id']}", "Make them agree", phase=p["id"])
        if p["state"] == "outline" and p["task_ids"]:
            R.add("PHASE", "blocker", p["id"], "an outline phase has tasks", "Mark it drafted or move the tasks", phase=p["id"])
        if p["state"] != "outline" and not p["task_ids"]:
            R.add("PHASE", "blocker", p["id"], "a drafted phase has no tasks", "Add its tasks or mark it outline", phase=p["id"])
        for d in p["depends_on"]:
            if d not in phases:
                R.add("GR-08", "blocker", p["id"], f"phase depends on unknown phase {d}", "Fix the phase dependency", phase=p["id"])
            elif phases[d]["order"] >= p["order"]:
                R.add("GR-08", "blocker", p["id"], f"phase depends on {d}, which is not earlier", "Phases depend only on earlier phases", phase=p["id"])
    for tid, t in tasks.items():
        if tid not in listed:
            R.add("ID", "blocker", tid, "task is not listed in any phase", "Add it to its phase's task_ids", phase=t["phase"])
        if t["phase"] not in phases:
            R.add("ID", "blocker", tid, f"task's phase {t['phase']} does not exist", "Fix the phase", phase=t["phase"])
        if not tid.startswith(t["phase"] + "-"):
            R.add("ID", "blocker", tid, "task id prefix does not match its phase", "Ids are P<n>-T<nn> of their phase", phase=t["phase"])
        if t["key"] != f"gw:{plan['id']}:{tid}":
            R.add("KEY", "blocker", tid, "task key does not match plan id and task id", f"Set key to gw:{plan['id']}:{tid}", phase=t["phase"])

    deps = {tid: [d["task"] for d in t["depends_on"]] for tid, t in tasks.items()}
    porder = {pid: p["order"] for pid, p in phases.items()}

    # GR-08
    for tid, t in tasks.items():
        for d in t["depends_on"]:
            if d["task"] not in tasks:
                R.add("GR-08", "blocker", tid, f"depends on unknown task {d['task']}", "Point at a real task", phase=t["phase"])
            elif porder.get(tasks[d["task"]]["phase"], 0) > porder.get(t["phase"], 0):
                R.add("GR-08", "blocker", tid, f"depends on {d['task']} in a later phase", "Move one of them", phase=t["phase"])
    cyc = find_cycle(deps)
    if cyc:
        R.add("GR-08", "blocker", cyc[0], "dependency cycle: " + " -> ".join(cyc), "Break the cycle", phase=tasks[cyc[0]]["phase"])

    anc = {tid: ancestors(tid, deps) for tid in tasks}
    role_keys = {r["key"] for r in overlay.get("roles", [])}

    for tid, t in tasks.items():
        ph = t["phase"]
        ins = t["instructions"]
        # GR-01 / GR-24
        if t["exception"] is None:
            if not (0 < t["estimate_hours"] <= whd):
                R.add("GR-01", "blocker", tid, f"estimate {t['estimate_hours']}h is over the {whd}h working day",
                      "Split the task, or request a one-day exception", phase=ph)
        else:
            ex = t["exception"]
            days = {c["day"] for c in ex["checkpoints"]}
            if len(ex["checkpoints"]) != ex["days"] or days != set(range(1, ex["days"] + 1)):
                R.add("GR-24", "blocker", tid, "exception needs exactly one checkpoint per day", "Add one checkpoint for each day", phase=ph)
            if any(not c["visible_result"].strip() for c in ex["checkpoints"]):
                R.add("GR-24", "blocker", tid, "an exception checkpoint has no visible result", "Give each day a visible result", phase=ph)
        # GR-05
        for part in INSTRUCTION_PARTS:
            v = ins.get(part)
            if v in (None, "", []) and part != "prerequisites":
                R.add("GR-05", "blocker", tid, f"instructions are missing '{part}'", "Write that part for the assumed executor", phase=ph)
        # GR-07
        produced = {p["name"] for a in anc[tid] if a in tasks for p in tasks[a]["produces"]}
        for i, st in enumerate(ins["steps"], 1):
            for ref in st["refs"]:
                if ref.startswith("ev-"):
                    if ref not in ev_by_id:
                        R.add("GR-07", "blocker", tid, f"step {i} refers to evidence {ref}, which discovery did not find",
                              "Discover it, or remove the reference", phase=ph)
                elif ref not in produced:
                    R.add("GR-07", "blocker", tid, f"step {i} refers to '{ref}', which no earlier task produces",
                          "Point at evidence or at a dependency's produces", phase=ph)
            if st["from_evidence"] and st["from_evidence"] not in ev_by_id:
                R.add("GR-07", "blocker", tid, f"step {i} is marked as copied from {st['from_evidence']}, which does not exist",
                      "Fix from_evidence", phase=ph)
        for ref in t["evidence_refs"]:
            if ref not in ev_by_id:
                R.add("GR-07", "blocker", tid, f"evidence_refs names {ref}, which discovery did not find", "Discover it or remove it", phase=ph)
        # GR-27 (D-55): a change to something that exists says why it is needed, what it could break,
        # and which test or UAT task checks for that breakage.
        ch = t.get("changes_existing")
        if ch:
            if sp.get("kind") != "extends_existing":
                R.add("GR-27", "blocker", tid, "task changes an existing resource, but the plan says it starts from scratch",
                      "Record the existing resource in request.starting_point", phase=ph)
            for rid in ch["resources"]:
                if rid not in res_ids:
                    R.add("GR-27", "blocker", tid, f"changes {rid}, which request.starting_point does not list",
                          "List the resource, with the evidence that inspected it", phase=ph)
            if not ch["why_needed"].strip() or not any(c.strip() for c in ch["could_break"]):
                R.add("GR-27", "blocker", tid, "change to an existing resource has no reason or no 'could break' entry",
                      "Say why the change is needed and what it could break", phase=ph)
            for rc in ch["regression_check"]:
                if rc not in tasks or tasks[rc]["kind"] not in ("test", "uat"):
                    R.add("GR-27", "blocker", tid, f"regression check {rc} is not a test or UAT task in this plan",
                          "Point regression_check at the test or UAT task that checks for the breakage", phase=ph)
        # GR-10 / GR-11
        if t["production_change"]:
            if not t["test_tasks"]:
                R.add("GR-10", "blocker", tid, "production change with no test task", "Add a test task that comes before it", phase=ph)
            for tt in t["test_tasks"]:
                if tt not in anc[tid]:
                    R.add("GR-10", "blocker", tid, f"test task {tt} does not come before this production change",
                          "Make this task depend on the test task", phase=ph)
        if t["production_change"] or t["data_change"]:
            rb = t["rollback_task"]
            if not rb:
                R.add("GR-11", "blocker", tid, "production or data change with no rollback task", "Add a rollback task", phase=ph)
            elif rb not in tasks:
                R.add("GR-11", "blocker", tid, f"rollback task {rb} does not exist", "Fix rollback_task", phase=ph)
            elif rb not in anc[tid] and not (t["parallel_group"] and tasks[rb]["parallel_group"] == t["parallel_group"]):
                R.add("GR-11", "blocker", tid, f"rollback task {rb} neither comes before nor runs with this change",
                      "Make this task depend on the rollback task", phase=ph)
        # GR-14
        if role_keys and t["role_key"] not in role_keys:
            R.add("GR-14", "blocker", tid, f"role '{t['role_key']}' is not mapped in the overlay", "Map the role or pick a mapped one", phase=ph)
        # GR-16 (fields) and GR-23
        if not overlay.get("skills", {}).get("tracker", {}).get("field_map", {}).get("blocked") and (t["waits_on"] or t["depends_on"]):
            R.add("GR-23", "blocker", tid, "the overlay maps no blocked state, so waits and dependencies can't show",
                  "Map field_map.blocked in setup", phase=ph)
        for w in t["waits_on"]:
            if role_keys and w["owner_role_key"] not in role_keys:
                R.add("GR-16", "blocker", tid, f"wait '{w['what']}' is owned by unmapped role {w['owner_role_key']}", "Map the role", phase=ph)
        # GR-21 (minor)
        title = t["title"].strip()
        if len(title.split()) < 2 or not title[0].isupper() or title.endswith("."):
            R.add("GR-21", "minor", tid, f"title '{title}' does not follow '{overlay.get('naming', {}).get('task', '{verb} {object}')}'",
                  "Start with a verb and name the object", phase=ph)
        # Access ids
        for a in t["access"]:
            if a not in {x["id"] for x in plan["access_list"]}:
                R.add("GR-13", "blocker", tid, f"task needs access {a}, which is not on the access list", "Add it to the access list", phase=ph)

    # GR-04: open questions block tasks, their phases' offers and dependents
    blocked = set()
    for q in plan["open_questions"]:
        if q["status"] != "open":
            continue
        for b in q["blocks"]:
            if b in phases:
                blocked.update(phases[b]["task_ids"])
            elif b in tasks:
                blocked.add(b)
    # A deferred approach decision acts as an open question for every task that cites it,
    # except the design task that will settle it (GR-33).
    if gw_model.is_model_plan(plan):
        for d in plan.get("approach", {}).get("decisions", []):
            if d["chosen_option"] == "deferred":
                for tid, t in tasks.items():
                    if d["id"] in t.get("approach_refs", []) and tid != d["deferred_to_task"]:
                        blocked.add(tid)
    changed = True
    while changed:
        changed = False
        for tid in tasks:
            if tid not in blocked and set(deps[tid]) & blocked:
                blocked.add(tid)
                changed = True
    for tid in sorted(blocked):
        R.add("GR-04", "blocker", tid, "an open question or a deferred decision blocks this task",
              "Answer the question or settle the decision, or leave this phase out of the offer", phase=tasks[tid]["phase"])

    # GR-18: a task that relies on a system nobody inspected waits behind an open question
    uninspected = {u["name"] for u in overlay.get("skills", {}).get("unsupported_systems", [])}
    uninspected |= {c["system"] for c in plan["coverage"] if c["status"] == "not_inspected"}
    lines = {a["id"]: a for a in plan["access_list"]}
    for tid, t in tasks.items():
        relied = sorted({lines[a]["system"] for a in t["access"] if a in lines and lines[a]["system"] in uninspected})
        if relied and tid not in blocked:
            R.add("GR-18", "blocker", tid, f"relies on {', '.join(relied)}, which was not inspected",
                  "Park it behind an open question until that system is inspected or the question is answered", phase=t["phase"])

    # GR-09
    by_kind = {s["kind"]: s for s in plan["standard_work"]}
    for k in STANDARD_KINDS:
        s = by_kind.get(k)
        if not s or (not s["tasks"] and not (s["not_applicable_reason"] or "").strip()):
            R.add("GR-09", "blocker", None, f"standard work '{k}' has no task and no not-applicable reason",
                  f"Add a {k} task, or state why it does not apply")
        elif s["tasks"]:
            for st in s["tasks"]:
                if st not in tasks:
                    R.add("GR-09", "blocker", st, f"standard work '{k}' lists unknown task {st}", "Fix the list")

    # GR-13: access list is derived, and P0 (or a released phase's first task) requests each line
    derived = {}
    for tid, t in tasks.items():
        for a in t["access"]:
            derived.setdefault(a, set()).add(tid)
    requested = {}
    for tid, t in tasks.items():
        for p in t["produces"]:
            if p["type"] == "access_request":
                requested.setdefault(p["name"], set()).add(tid)
    for line in plan["access_list"]:
        if set(line["needed_by"]) != derived.get(line["id"], set()):
            R.add("GR-13", "blocker", line["id"], "access_list.needed_by does not match the tasks that use it (it is derived, never typed)",
                  "Regenerate the access list from task access")
        if line["role_key"] not in role_keys and role_keys:
            R.add("GR-14", "blocker", line["id"], f"access line for unmapped role {line['role_key']}", "Map the role")
        needers = [tasks[x] for x in line["needed_by"] if x in tasks]
        in_drafted = [x for x in needers if phases.get(x["phase"], {}).get("state") != "outline"]
        if not in_drafted:
            continue
        reqs = requested.get(line["id"], set())
        p0_req = any(tasks[r]["phase"] == "P0" for r in reqs)
        if not p0_req:
            first_phase = min(in_drafted, key=lambda x: porder[x["phase"]])["phase"]
            own = [r for r in reqs if tasks[r]["phase"] == first_phase and not deps[r]]
            if not own:
                R.add("GR-13", "blocker", line["id"], f"access {line['id']} is never requested in P0 (or in its phase's first task)",
                      "Add it to the P0 access request task's produces", phase=first_phase)
        for x in in_drafted:
            for r in reqs:
                if r != x["id"] and r not in anc[x["id"]] and tasks[r]["phase"] != "P0":
                    R.add("GR-13", "blocker", x["id"], f"access {line['id']} is requested by {r}, which does not come before this task",
                          "Request it earlier", phase=x["phase"])

    if gw_model.is_model_plan(plan):
        model_checks(R, plan, overlay, ev_by_id, tasks, phases, role_keys, restricted, done_tasks or set(), profile)

    # GR-17: no secrets, personal or financial data
    for src, blob in (("plan", plan), ("evidence", evidence)):
        for what, fix in gr17_scan(src, blob):
            R.add("GR-17", "blocker", None, what, fix)

    # GR-18: coverage lists every overlay instance, with read-only status
    cov = {(c["system"], c["instance"]) for c in plan["coverage"]}
    skills = overlay.get("skills", {})
    for s in skills.get("systems", []):
        plat = s["skill"].replace("groundwork-system-", "")
        for inst in s["instances"]:
            if (plat, inst["id"]) not in cov:
                R.add("GR-18", "blocker", None, f"coverage does not list {plat} instance {inst['id']}",
                      "Add a coverage row, with not_inspected and a reason if it was not inspected")
    tr = skills.get("tracker")
    if tr:
        plat = tr["skill"].replace("groundwork-tracker-", "")
        if (plat, tr["instance"]["id"]) not in cov:
            R.add("GR-18", "blocker", None, f"coverage does not list tracker {plat} instance {tr['instance']['id']}", "Add a coverage row")
    for u in skills.get("unsupported_systems", []):
        if not any(c["system"] == u["name"] for c in plan["coverage"]):
            R.add("GR-18", "blocker", None, f"coverage does not show unsupported system {u['name']} as not inspected", "Add it as not_inspected")
    for c in plan["coverage"]:
        if c["status"] != "inspected" and not c["reason"].strip():
            R.add("GR-18", "blocker", None, f"coverage row {c['system']}/{c['instance']} is {c['status']} with no reason", "Say why")

    # GR-20 (minor)
    for pid in drafted:
        n = len(phases[pid]["task_ids"])
        if n < 3 or n > 8:
            R.add("GR-20", "minor", pid, f"phase has {n} tasks; a phase is about 5 person-days (3 to 8 tasks)",
                  "Merge or split phases, or accept as is", phase=pid)

    # GR-25: restricted evidence never rendered beyond yes/no or a count
    restricted_vals = set()
    for item in evidence:
        if item.get("sensitivity") == "restricted":
            for _p, s in strings(item.get("facts", {})):
                if len(s) >= 6:
                    restricted_vals.add(s)
            for u in item.get("untrusted_text", []):
                if len(u.get("text", "")) >= 6:
                    restricted_vals.add(u["text"])
    public_vals = set()
    for item in evidence:
        if item.get("sensitivity") != "restricted":
            public_vals.update(s for _p, s in strings({"f": item.get("facts", {}), "s": item.get("subject", {})}))
    restricted_vals -= public_vals  # a value non-restricted evidence also shows is not a restricted fact
    rendered = [("plan", json.dumps({k: plan[k] for k in ("tasks", "scope", "epic", "open_questions")}, ensure_ascii=False))]
    if proposal_text:
        rendered.append(("proposal", proposal_text))
    if plan.get("review", {}).get("reviewer"):
        rendered.append(("review findings", json.dumps(plan["review"]["reviewer"]["findings"], ensure_ascii=False)))
    for where, text in rendered:
        for v in restricted_vals:
            if re.search(r"(?<![\w-])" + re.escape(v) + r"(?![\w-])", text):
                R.add("GR-25", "blocker", None, f"{where} shows a restricted evidence value", "Render restricted facts only as yes/no or a count")

    # GR-26: evidence age at approval time
    if now is not None:
        max_age = overlay.get("evidence_max_age_days", 7)
        for tid, t in tasks.items():
            if t["phase"] not in offered:
                continue
            refs = set(t["evidence_refs"]) | {r for s in t["instructions"]["steps"] for r in s["refs"] if r.startswith("ev-")}
            for r in refs:
                item = ev_by_id.get(r)
                if item and (now - parse_ts(item["collected_at"])).days > max_age:
                    R.add("GR-26", "blocker", tid, f"evidence {r} is older than {max_age} days", "Re-discover it before approval",
                          evidence_ids=[r], phase=t["phase"])

    # Stage gates
    if stage in ("proposal", "create"):
        rev = plan.get("review", {}).get("reviewer")
        if not rev or not rev.get("independent"):
            R.add("CR-03", "blocker", None, "no independent review is recorded", "Run the independent reviewer on the reviewer view")
        else:
            open_blockers = [f for f in rev["findings"] if f["severity"] == "blocker" and f["resolution"] not in ("fixed",)]
            for f in open_blockers:
                if f["resolution"] == "exception_requested":
                    continue
                R.add("REVIEW", "blocker", f["target"], f"reviewer blocker {f['id']} ({f['check']}) is {f['resolution']}",
                      "Resolve it in stage 6", phase=tasks[f["target"]]["phase"] if f["target"] in tasks else (f["target"] if f["target"] in phases else None))
    for pid in sorted(offered):
        if phases.get(pid, {}).get("state") == "outline":
            R.add("OFFER", "blocker", pid, "an outline phase cannot be offered", "Plan it in a later run", phase=pid)
    return R


def model_checks(R, plan, overlay, ev_by_id, tasks, phases, role_keys, restricted, done_tasks, profile):
    """GR-29, GR-31, GR-33 and GR-34 (plan format 2). GR-30 and GR-32 are reviewer checks."""
    for k in ("brief", "traits", "approach"):
        if k not in plan:
            R.add("GR-29" if k != "approach" else "GR-31", "blocker", None, f"plan format 2 needs '{k}'", f"Add {k} (plan-format.md)")
    if any(k not in plan for k in ("brief", "traits", "approach")):
        return
    brief = plan["brief"]
    by_id = {f["id"]: f for f in brief}
    by_key = {}
    questions = {q["id"]: q for q in plan["open_questions"]}

    # GR-29: brief structure
    found, missing = gw_model.pinned_traits(plan, overlay)
    for m in missing:
        R.add("GR-29", "blocker", None, f"pinned trait {m} is not a known core or overlay trait", "Pin a trait from reference/traits.yaml")
    if len(by_id) != len(brief):
        R.add("GR-29", "blocker", None, "duplicate brief field ids", "Brief ids are unique")
    for f in brief:
        if f["key"] in by_key:
            R.add("GR-29", "blocker", f["id"], f"brief key '{f['key']}' appears twice", "Keep one field per key")
        by_key[f["key"]] = f
    for key in gw_model.required_keys(plan, overlay):
        if key not in by_key:
            R.add("GR-29", "blocker", None, f"brief has no '{key}' field", "Ask it in Clarify, or mark it not applicable with a reason")
    for f in brief:
        fid, st = f["id"], f["status"]
        if st == "answered" and f["sensitivity"] == "normal" and not (f["value"] or "").strip():
            R.add("GR-29", "blocker", fid, "answered field has no value", "Record the answer")
        if st == "not_applicable" and not (f["na_reason"] or "").strip():
            R.add("GR-29", "blocker", fid, "not-applicable field has no reason", "Say why it does not apply")
        if st == "open":
            q = questions.get(f["open_question"] or "")
            if not q:
                R.add("GR-29", "blocker", fid, "open field names no open question", "Create the open question and name it")
            elif not q["blocks"] and profile != "assess":
                R.add("GR-29", "blocker", fid, f"open field's question {q['id']} blocks nothing", "Name the phases it affects in blocks")
            elif f["phase"] and f["phase"] not in q["blocks"]:
                R.add("GR-29", "blocker", fid, f"field is parked on {f['phase']} but {q['id']} does not block it", "Add the phase to blocks")
        elif f["phase"]:
            R.add("GR-29", "blocker", fid, "only an open field can be parked on a later phase", "Clear phase, or reopen the field")
        if f["source"] != "runner" and not f["basis_role_key"]:
            R.add("GR-29", "blocker", fid, f"field from source '{f['source']}' has no basis_role_key", "Record the role that confirmed it")
        if f["basis_role_key"] and role_keys and f["basis_role_key"] not in role_keys:
            R.add("GR-14", "blocker", fid, f"basis role '{f['basis_role_key']}' is not mapped in the overlay", "Map the role")
        if f["sensitivity"] == "restricted":
            if f["key"] in gw_model.UNRESTRICTABLE:
                R.add("GR-29", "blocker", fid, f"'{f['key']}' can never be restricted; approvers must see it",
                      "Write a normal paraphrase (source runner) and keep the original in restricted.json")
            if f["value"] is not None or not f["value_rev"]:
                R.add("GR-29", "blocker", fid, "restricted field must store value null and a value_rev",
                      "Move the value to the run folder's restricted.json")
        elif f["value_rev"] is not None:
            R.add("GR-29", "blocker", fid, "value_rev is only for restricted fields", "Remove value_rev")
        for d in f["derived_from"]:
            if d.startswith("ev-") and d not in ev_by_id:
                R.add("GR-29", "blocker", fid, f"derived_from names {d}, which discovery did not find", "Fix the reference")
    signoff = by_key.get("deliverable_signoffs")
    if signoff and signoff["status"] == "answered" and not any(t["kind"] == "signoff_prep" for t in tasks.values()):
        R.add("GR-29", "blocker", signoff["id"], "deliverable sign-offs are named but no signoff_prep task exists",
              "Add a signoff_prep task with a waits_on approval for each sign-off role")
    sm = by_key.get("success_measure")
    if sm and sm["status"] == "answered":
        n = sum(t["visible_result"]["type"] == "measurement" for t in tasks.values())
        outline = any(p["state"] == "outline" for p in phases.values())
        if n > 1 or (n == 0 and not outline):
            R.add("GR-29", "blocker", sm["id"], f"{n} measurement tasks; the success measure needs exactly one",
                  "Give exactly one task a visible_result of type measurement")

    # GR-31: approach structure
    ap = plan["approach"]
    opts = {o["id"]: o for o in ap["options"]}
    ads = {d["id"]: d for d in ap["decisions"]}
    kinds = {o["kind"] for o in ap["options"]}
    if "reuse_extend" not in kinds:
        R.add("GR-31", "blocker", None, "approach has no reuse or extend option", "Add the option that reuses or extends what exists")
    if not kinds & {"smaller", "do_nothing"}:
        R.add("GR-31", "blocker", None, "approach has no smaller or do-nothing option", "Add one")
    chosen = {d["chosen_option"] for d in ap["decisions"]}
    for oid, o in opts.items():
        for e in o["evidence"]:
            if e not in ev_by_id:
                R.add("GR-31", "blocker", oid, f"option cites {e}, which discovery did not find", "Fix the reference")
        if not o["evidence"] and not (o["not_inspected_reason"] or "").strip():
            R.add("GR-31", "blocker", oid, "option cites no evidence and gives no reason", "Cite evidence or say why it was not inspected")
        if oid in chosen and o["rejected_because"]:
            R.add("GR-31", "blocker", oid, "a chosen option is also marked rejected", "Clear rejected_because")
        if oid not in chosen:
            rb = o["rejected_because"]
            if not rb:
                R.add("GR-31", "blocker", oid, "option is neither chosen nor rejected with a reason", "Cite the brief field that rules it out")
            elif rb["brief_ref"] not in by_id:
                R.add("GR-31", "blocker", oid, f"rejection cites {rb['brief_ref']}, which is not a brief field", "Fix the reference")
    for aid, d in ads.items():
        if d["chosen_option"] == "deferred":
            if d["deferred_to_task"] not in tasks:
                R.add("GR-31", "blocker", aid, "deferred decision names no task that will settle it", "Name the design task")
        elif d["chosen_option"] not in opts:
            R.add("GR-31", "blocker", aid, f"decision chooses {d['chosen_option']}, which is not an option", "Fix the reference")
        elif d["deferred_to_task"]:
            R.add("GR-31", "blocker", aid, "a decided decision still names a deferred task", "Clear deferred_to_task")
        for b in d["brief_refs"]:
            if b not in by_id:
                R.add("GR-31", "blocker", aid, f"decision cites {b}, which is not a brief field", "Fix the reference")
        for e in d["evidence"]:
            if e not in ev_by_id:
                R.add("GR-31", "blocker", aid, f"decision cites {e}, which discovery did not find", "Fix the reference")
    for tid, t in tasks.items():
        for b in t.get("brief_refs", []):
            if b not in by_id:
                R.add("GR-31", "blocker", tid, f"brief_refs names {b}, which is not a brief field", "Fix the reference", phase=t["phase"])
        for a in t.get("approach_refs", []):
            if a not in ads:
                R.add("GR-31", "blocker", tid, f"approach_refs names {a}, which is not a decision", "Fix the reference", phase=t["phase"])
        if tid not in done_tasks and not gw_model.traces_to_brief(plan, t):
            R.add("GR-31", "blocker", tid, "task does not trace to the brief's outcome or scope", 
                  "Cite the outcome or scope field it serves, directly or through a decision", phase=t["phase"])
    sp = plan["request"]["starting_point"]
    res = {r["id"] for r in sp["resources"]}
    changed = {r for t in tasks.values() if t.get("changes_existing") for r in t["changes_existing"]["resources"]}
    for r in ap["unchanged"]:
        if r not in res:
            R.add("GR-31", "blocker", r, "approach.unchanged names a resource the starting point does not list", "Fix the reference")
    for r in sorted(res - changed - set(ap["unchanged"])):
        R.add("GR-31", "blocker", r, "existing resource is neither changed by a task nor listed as unchanged",
              "List it in approach.unchanged, or plan the change")

    # GR-33: trait standard work, trait roles and trait conflicts
    sw = {s["kind"]: s for s in plan["standard_work"]}
    for k in gw_model.trait_kinds(plan, overlay):
        s = sw.get(k)
        if not s or (not s["tasks"] and not (s["not_applicable_reason"] or "").strip()):
            R.add("GR-33", "blocker", None, f"trait standard work '{k}' has no task and no not-applicable reason",
                  f"Add a {k} task, or state why it does not apply")
        else:
            for st in s["tasks"]:
                if st not in tasks:
                    R.add("GR-33", "blocker", st, f"standard work '{k}' lists unknown task {st}", "Fix the list")
    pinned = {p["id"] for p, _t in found}
    for p, t in found:
        for role in t.get("roles", []):
            if role_keys and role not in role_keys:
                R.add("GR-14", "blocker", None, f"trait {p['id']} needs role '{role}', which the overlay does not map", "Map the role in setup")
        for c in t.get("conflicts", []):
            if c["with"] in pinned and p["id"] < c["with"]:
                if not any({p["id"], c["with"]} <= set(d.get("trait_conflict", [])) for d in ap["decisions"]):
                    R.add("GR-33", "blocker", None, f"traits {p['id']} and {c['with']} conflict ({c['about']}) and no decision settles it",
                          "Add an approach decision with trait_conflict naming both")

    # GR-34: restricted brief values never appear anywhere in the plan
    restricted_ids = [f["id"] for f in brief if f["sensitivity"] == "restricted"]
    if restricted_ids:
        if restricted is None:
            R.not_run.append("GR-34 value search: not run, restricted values unavailable in this session")
        else:
            text = [s for _p, s in strings(plan)]
            for fid in restricted_ids:
                v = (restricted.get(fid) or "").strip()
                if len(v) >= 3 and any(v.lower() in s.lower() for s in text):
                    R.add("GR-34", "blocker", fid, "a restricted brief value appears in the plan", "Remove it; refer to the field by id only")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--overlay", required=True)
    ap.add_argument("--evidence")
    ap.add_argument("--offer")
    ap.add_argument("--now")
    ap.add_argument("--stage", default="draft", choices=["draft", "proposal", "create"])
    ap.add_argument("--proposal")
    ap.add_argument("--out")
    ap.add_argument("--restricted", help="restricted.json from the run folder: {brief id: value}")
    ap.add_argument("--done", help="task ids the tracker reports done or closed_not_done, comma separated (revise)")
    ap.add_argument("--profile", default="plan", choices=["plan", "assess", "integrity"])
    a = ap.parse_args(argv)
    try:
        with open(a.plan, encoding="utf-8") as f:
            plan = json.load(f)
        overlay = gw_yaml.load(a.overlay) if a.overlay.endswith((".yaml", ".yml")) else json.load(open(a.overlay, encoding="utf-8"))
        evidence = load_evidence(a.evidence)
        proposal = open(a.proposal, encoding="utf-8").read() if a.proposal else None
        restricted = json.load(open(a.restricted, encoding="utf-8")) if a.restricted else None
    except (OSError, ValueError) as e:
        print(f"cannot read inputs: {e}", file=sys.stderr)
        return 2
    now = parse_ts(a.now) if a.now else None
    offer = [x.strip() for x in a.offer.split(",") if x.strip()] if a.offer is not None else None
    done = {x.strip() for x in a.done.split(",") if x.strip()} if a.done else None
    R = check(plan, overlay, evidence, offer, now, a.stage, proposal, restricted, done, a.profile)
    blockers = R.blocking()
    out = {"version": VERSION, "passed": not blockers, "results": R.export()}
    if R.not_run:
        out["not_run"] = R.not_run
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    minors = sum(1 for f in R.items if f["severity"] == "minor")
    print(f"validator {VERSION}: {len(blockers)} blocker(s) in offered phases, {minors} minor", file=sys.stderr)
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
