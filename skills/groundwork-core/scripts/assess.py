#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Assess an existing, unplanned project read-only, and seed adopt by reference (planning model 5 and 6).

Usage:
  assess.py split ITEMS.json --overlay OVERLAY.yaml --read-at TS --out-dir RUN_DIR
  assess.py recommend RUN_DIR --overlay OVERLAY.yaml
  assess.py report RUN_DIR
  assess.py leaks RUN_DIR FILE...
  assess.py seed RUN_DIR DECISIONS.json

ITEMS.json is what the tracker skill's read_scope returned, after `create_steps.py scope`
allowed the count: [{key, title, raw: {state, category, closed_as, labels}, points, parent,
links: [{type: blocked_by|relates, to}], updated_at, body, comments: [text]}].

split writes legacy-refs.json (structure only: key, status, points, parent, updated_at,
read_at) and working-text.json (titles, bodies and comments as WT-n entries). Working
text is not evidence: it stays in the run folder, travels in a run bundle marked
restricted, and is never written to a plan store, a proposal or a tracker. Everything
Groundwork writes from it is its own wording, with derived_from naming the WT ids.

recommend turns what v1's rules would refuse (more than one point, no done criteria,
dependency cycles, dependencies on work closed without being done) into
recommendations, never blockers. The runner accepts or rejects each one (seed).
The report is a file for the runner's own thread; it is never posted to a tracker.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import create_steps  # noqa: E402
import gw_yaml  # noqa: E402

KINDS = ("change", "add", "remove", "sequence", "block", "clarify")
DONE_HINTS = re.compile(r"(acceptance|done when|definition of done|- \[[ x]\]|expected result|verify)", re.I)
LEAK_MIN = 24  # a copied run of working text this long or longer is a leak


def split(items, overlay, read_at):
    fm = overlay["skills"]["tracker"]["field_map"]
    refs, wt = [], []

    def add(key, field, text):
        if text and text.strip():
            wt.append({"id": f"WT-{len(wt) + 1}", "key": key, "field": field, "text": text})

    for it in sorted(items, key=lambda i: i["key"]):
        st = create_steps.read_status(dict(it["raw"], key=it["key"]), None, fm)["status"]
        refs.append({"key": it["key"], "status": st, "points": it.get("points"), "parent": it.get("parent"),
                     "updated_at": it["updated_at"], "read_at": read_at,
                     "links": [{"type": link["type"], "to": link["to"]} for link in it.get("links", [])]})
        add(it["key"], "title", it.get("title"))
        add(it["key"], "body", it.get("body"))
        for c in it.get("comments", []):
            add(it["key"], "comment", c)
    return refs, {"schema_version": "1.0", "read_at": read_at, "entries": wt}


def plan_refs(refs):
    """legacy_refs as the plan stores them (no links: those are working structure for assess only)."""
    return [{k: r[k] for k in ("key", "status", "points", "parent", "updated_at", "read_at")} for r in refs]


def cycles(refs):
    graph = {r["key"]: [link["to"] for link in r["links"] if link["type"] == "blocked_by"] for r in refs}
    seen, stack, out = set(), [], []

    def visit(k):
        if k in stack:
            cyc = stack[stack.index(k):]
            if sorted(cyc) not in [sorted(c) for c in out]:
                out.append(cyc)
            return
        if k in seen or k not in graph:
            return
        seen.add(k)
        stack.append(k)
        for n in graph[k]:
            visit(n)
        stack.pop()

    for k in sorted(graph):
        visit(k)
    return out


def recommend(refs, wt):
    by_key = {r["key"]: r for r in refs}
    texts = {}
    for e in wt["entries"]:
        texts.setdefault(e["key"], []).append(e)
    recs = []

    def rec(kind, target, why, derived, cost, role="developer"):
        recs.append({"id": f"REC-{len(recs) + 1}", "kind": kind, "target": target, "why": why,
                     "derived_from": sorted(derived), "source": "from_tracker", "cost": cost, "owner_role_key": role,
                     "decision": "pending"})

    for r in refs:
        if r["status"] in ("done", "closed_not_done"):
            continue
        own = [e["id"] for e in texts.get(r["key"], [])]
        if (r["points"] or 0) > 1:
            rec("change", r["key"], f"`{r['key']}` carries {r['points']:g} points; split it into one-day tasks.", own,
                {"kind": "outline", "tasks_about": int(r["points"])})
        body = " ".join(e["text"] for e in texts.get(r["key"], []) if e["field"] in ("body", "comment"))
        if not DONE_HINTS.search(body):
            rec("clarify", r["key"], f"`{r['key']}` has no done criteria; ask its owner what finished looks like.", own,
                {"kind": "unknown"}, role="business_user")
        for link in r["links"]:
            dep = by_key.get(link["to"])
            if link["type"] == "blocked_by" and dep and dep["status"] == "closed_not_done":
                rec("sequence", r["key"], f"`{r['key']}` waits on `{dep['key']}`, which was closed without being done; "
                                          "re-point or drop the dependency.", own, {"kind": "drafted", "tasks": 0})
    for cyc in cycles(refs):
        keys = ", ".join(f"`{k}`" for k in cyc)
        rec("sequence", cyc[0], f"{keys} block each other in a cycle; break it so one can start.",
            [e["id"] for k in cyc for e in texts.get(k, [])], {"kind": "drafted", "tasks": 0})
    return recs


def rec_problems(recs, refs, wt):
    keys = {r["key"] for r in refs}
    ids = {e["id"] for e in wt["entries"]}
    probs = []
    for r in recs:
        if r["kind"] not in KINDS:
            probs.append(f"{r['id']}: kind {r['kind']} is not one of {', '.join(KINDS)}")
        if r["target"] is not None and r["target"] not in keys:
            probs.append(f"{r['id']}: target {r['target']} was not read")
        for d in r["derived_from"]:
            if d.startswith("WT-") and d not in ids:
                probs.append(f"{r['id']}: derived_from {d} is not in working-text.json")
        if r["source"] != "from_tracker":
            probs.append(f"{r['id']}: a recommendation from tracker text has source from_tracker")
    return probs


def leaks(blob_text, wt):
    """Working text that was copied into something Groundwork writes (a plan, proposal, report)."""
    out = []
    low = blob_text.lower()
    for e in wt["entries"]:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", e["text"]):
            s = sentence.strip()
            if len(s) >= LEAK_MIN and s.lower() in low:
                out.append(f"{e['id']} ({e['key']} {e['field']}) is copied: \"{s[:40]}...\"")
                break
    return out


def report(refs, recs):
    """The runner's report. It names working text by id and never quotes it."""
    open_items = [r for r in refs if r["status"] not in ("done", "closed_not_done")]
    out = ["# Assessment", "",
           f"Read {len(refs)} items ({len(open_items)} open). This report is for the runner only and is never posted to a tracker.",
           "", "## Items read", "| Key | Status | Points | Parent | Updated |", "| --- | --- | --- | --- | --- |"]
    for r in refs:
        out.append(f"| `{r['key']}` | {r['status'].replace('_', ' ')} | {r['points'] if r['points'] is not None else '-'} | "
                   f"{('`' + r['parent'] + '`') if r['parent'] else '-'} | {r['updated_at']} |")
    out += ["", "## Recommendations", ""]
    if not recs:
        out.append("None.")
    for r in recs:
        out.append(f"- **{r['id']}** ({r['kind']}, {r['owner_role_key']}): {r['why']} Based on {', '.join(r['derived_from']) or 'structure only'}. "
                   f"Decision: {r['decision']}.")
    splits = [r for r in recs if r["kind"] == "change" and "split" in r["why"]]
    if splits:
        out += ["", f"**Split recommendations:** {', '.join(r['id'] for r in splits)}."]
    out += ["", "Accept or reject each recommendation one at a time. Accepted ones seed a new plan that refers to these "
            "items by key and never writes to them (adopt by reference).", ""]
    return "\n".join(out)


def seed(recs, decisions, refs):
    """Apply the runner's one-at-a-time decisions; accepted recommendations and the legacy refs seed Intake."""
    by_id = {r["id"]: r for r in recs}
    probs = [f"no recommendation {d}" for d in decisions if d not in by_id]
    probs += [f"{d}: decision must be accepted or rejected" for d, v in decisions.items() if v not in ("accepted", "rejected")]
    for d, v in decisions.items():
        if d in by_id:
            by_id[d]["decision"] = v
    accepted = [r for r in recs if r["decision"] == "accepted"]
    return {"ok": not probs, "problems": probs, "accepted": accepted, "legacy_refs": plan_refs(refs),
            "pending": sorted(r["id"] for r in recs if r["decision"] == "pending")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["split", "recommend", "report", "leaks", "seed"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--overlay")
    ap.add_argument("--read-at")
    ap.add_argument("--out-dir")
    a = ap.parse_args(argv)
    J = lambda p: json.load(open(p, encoding="utf-8"))

    def W(d, name, obj):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False))

    if a.cmd == "split":
        items = J(a.files[0])
        overlay = gw_yaml.load(a.overlay)
        gate = create_steps.scope_decision(len(items), overlay)
        if not gate["ok"]:
            print(json.dumps(gate, indent=2))
            return 1
        refs, wt = split(items, overlay, a.read_at)
        W(a.out_dir, "legacy-refs.json", refs)
        W(a.out_dir, "working-text.json", wt)
        out = {"ok": True, "items": len(refs), "working_text": len(wt["entries"])}
    elif a.cmd == "recommend":
        d = a.files[0]
        refs, wt = J(os.path.join(d, "legacy-refs.json")), J(os.path.join(d, "working-text.json"))
        recs = recommend(refs, wt)
        probs = rec_problems(recs, refs, wt) + leaks(json.dumps(recs, ensure_ascii=False), wt)
        W(d, "recommendations.json", recs)
        out = {"ok": not probs, "recommendations": len(recs), "problems": probs}
    elif a.cmd == "report":
        d = a.files[0]
        refs, recs, wt = (J(os.path.join(d, n)) for n in ("legacy-refs.json", "recommendations.json", "working-text.json"))
        text = report(refs, recs)
        probs = leaks(text, wt)
        if not probs:
            W(d, "assessment.md", text)
        out = {"ok": not probs, "problems": probs}
    elif a.cmd == "leaks":
        wt = J(os.path.join(a.files[0], "working-text.json"))
        probs = [f"{p}: {x}" for p in a.files[1:] for x in leaks(open(p, encoding="utf-8").read(), wt)]
        out = {"ok": not probs, "problems": probs}
    else:
        d = a.files[0]
        out = seed(J(os.path.join(d, "recommendations.json")), J(a.files[1]), J(os.path.join(d, "legacy-refs.json")))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
