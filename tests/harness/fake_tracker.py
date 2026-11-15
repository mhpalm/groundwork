# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""A file-free, in-memory tracker implementing the tracker contract's read and
write procedures, plus a create driver that follows the core's procedure
(lock, verify, preflight, write in batches with manifests, freeze).

Used to test idempotency, partial failure, search lag, drift, lock contention
and freeze resume without any real tracker.
"""
import copy
import datetime as dt
import itertools

import create_steps
from check_hashes import owned_hash
from render_proposal import task_body

T0 = dt.datetime(2026, 11, 15, 12, 0, 0, tzinfo=dt.timezone.utc)


class WriteFailed(RuntimeError):
    pass


class FakeTracker:
    def __init__(self, search_lag_writes=0):
        self.items = {}       # tracker_id -> item
        self.comments = []    # epic comments
        self.store = {}       # plan store name -> object
        self.writes = 0
        self.fail_at = None
        self.ids = itertools.count(100)
        self.search_lag = search_lag_writes
        self._recent = []     # keys not yet visible to search
        self.clock = T0
        self.epic_state = {}  # epic key -> open | closed (open when absent)
        self.epic_labels = {}  # epic key -> set of labels

    def tick(self, seconds=1):
        self.clock += dt.timedelta(seconds=seconds)
        return self.clock

    def _write(self):
        self.writes += 1
        if self.fail_at is not None and self.writes == self.fail_at:
            raise WriteFailed(f"write {self.writes} failed")
        self.tick()

    # write procedures
    def create_item(self, key, title, body, role_key, phase, points=1):
        self._write()
        tid = f"VOL-{next(self.ids)}"
        self.items[tid] = {"tracker_id": tid, "key": key, "title": title, "body": body, "role_key": role_key,
                           "phase": phase, "points": points, "not_ready": True, "parent": None, "links": [],
                           "state": "open", "category": "todo", "closed_as": [], "labels": [], "blocked": False}
        self._recent.append(key)
        return tid

    def link_parent(self, tid, epic):
        self._write()
        self.items[tid]["parent"] = epic

    def link_dependency(self, tid, other):
        self._write()
        self.items[tid]["links"].append(other)

    def clear_not_ready(self, tid):
        self._write()
        self.items[tid]["not_ready"] = False

    def set_blocked(self, tid, on=True):
        self._write()
        self.items[tid]["blocked"] = on

    def add_label(self, tid, label):
        self._write()
        if label not in self.items[tid]["labels"]:
            self.items[tid]["labels"].append(label)

    def close(self, tid, closed_as):
        """The tracker's own close: GitHub state_reason, or a Jira status or resolution."""
        self._write()
        self.items[tid]["state"] = "closed"
        self.items[tid]["closed_as"] = [closed_as]

    def reopen(self, tid):
        self._write()
        self.items[tid]["state"] = "open"
        self.items[tid]["closed_as"] = []

    def remove_epic_label(self, epic, label):
        self._write()
        self.epic_labels.setdefault(epic, set()).discard(label)

    def close_epic(self, epic):
        self._write()
        self.epic_state[epic] = "closed"

    def raw(self, tid):
        i = self.items[tid]
        return {"key": i["key"], "state": i["state"], "category": i["category"], "closed_as": list(i["closed_as"]),
                "labels": list(i["labels"])}

    def comment(self, account, body):
        self._write()
        c = {"ref": f"c{len(self.comments) + 1}", "author_account_id": account, "created_at": create_steps.fmt(self.clock),
             "updated_at": create_steps.fmt(self.clock), "body": body}
        self.comments.append(c)
        return c

    def comment_item(self, tid, account, body):
        self._write()
        self.items[tid].setdefault("comments", []).append({"author_account_id": account, "body": body})

    def put(self, name, obj):
        self._write()
        if name in self.store:
            raise WriteFailed(f"plan store file {name} already exists; Groundwork never overwrites")
        self.store[name] = copy.deepcopy(obj)

    # read procedures
    def normalize(self, item):
        body = item["body"]
        start, end = body.find("<!-- groundwork:owned:start -->"), body.find("<!-- groundwork:owned:end -->")
        owned = body[start:end + len("<!-- groundwork:owned:end -->")] if start >= 0 and end >= 0 else ""
        return {"title": item["title"], "body_owned": owned, "role_key": item["role_key"], "phase": item["phase"], "key": item["key"]}

    def find_by_key(self, key):
        lagging = set(self._recent[-self.search_lag:]) if self.search_lag else set()
        return [i for i in self.items.values() if i["key"] == key and key not in lagging]

    def list_children(self, epic):
        return [i for i in self.items.values() if i["parent"] == epic]

    def settle(self):
        self._recent = []


def planned_items(plan, overlay, phases):
    out = []
    for t in sorted(plan["tasks"], key=lambda t: t["order"]):
        body = task_body(plan, overlay, t)
        fields = {"title": t["title"], "body_owned": body, "role_key": t["role_key"], "phase": t["phase"], "key": t["key"]}
        deps = [f"gw:{plan['id']}:{d['task']}" for d in t["depends_on"]]
        out.append({"key": t["key"], "phase": t["phase"], "owned_hash": owned_hash(fields), "points": 1,
                    "depends_on": deps, "waits": bool(t.get("waits_on")), "task": t, "body": body})
    return out


def latest_manifest(tr, plan_id):
    ms = [v for k, v in tr.store.items() if k.startswith(f"{plan_id}-manifest-")]
    from check_hashes import verify_chain
    latest, probs = verify_chain(ms)
    if probs:
        raise RuntimeError("; ".join(probs))
    return copy.deepcopy(latest)


def run_create(tr, plan, overlay, phases, run="run-1", account="acct-dev", epic="VOL-1", hard_crash=False):
    fm = overlay["skills"]["tracker"]["field_map"]
    """Follow the core's create procedure. Returns the preflight result."""
    decision = create_steps.lock_decision(tr.comments, run, account, tr.clock)
    if decision["decision"] == "claim":
        tr.comment(account, decision["post"])
        decision = create_steps.lock_decision(tr.comments, run, account, tr.clock)
    if decision["decision"] != "held":
        return {"ok": False, "lock": decision}
    planned = [p for p in planned_items(plan, overlay, phases)]
    found = []
    children = {i["key"] for i in tr.list_children(epic)}
    for p in planned:
        hits = tr.find_by_key(p["key"])
        for h in hits:
            found.append({"key": h["key"], "tracker_id": h["tracker_id"], "owned_hash": owned_hash(tr.normalize(h)),
                          "under_epic": h["key"] in children, "points": h["points"]})
    manifest = latest_manifest(tr, plan["id"])
    written = {i["key"]: i for i in (manifest or {}).get("items", [])}
    for f in found:
        f["status"] = create_steps.read_status(tr.raw(f["tracker_id"]), written.get(f["key"]), fm)["status"]
    pf = create_steps.preflight([{k: p[k] for k in ("key", "phase", "owned_hash", "points", "depends_on", "waits")}
                                 for p in planned], found, manifest, phases)
    if not pf["ok"]:
        tr.comment(account, create_steps.lock_line("release", run, account, tr.clock))
        return pf
    items = {i["key"]: i for i in (manifest or {}).get("items", [])}
    by_key = {p["key"]: p for p in planned}
    seq = (manifest or {}).get("seq", 0)
    prev = manifest
    pending = 0

    def checkpoint():
        nonlocal seq, prev, pending
        m = create_steps.make_manifest(prev, sorted(items.values(), key=lambda i: i["key"]), plan["id"], run, seq + 1, tr.clock, [])
        tr.put(f"{plan['id']}-manifest-{seq + 1}", m)
        seq += 1
        prev = m
        pending = 0

    try:
        for a in pf["actions"]:
            p = by_key[a["key"]]
            if a["action"] == "create":
                t = p["task"]
                tid = tr.create_item(t["key"], t["title"], p["body"], t["role_key"], t["phase"])
                items[t["key"]] = {"key": t["key"], "tracker_id": tid, "owned_hash": p["owned_hash"], "links": [], "not_ready": True}
                pending += 1
            elif a["action"] == "comment_split":
                tr.comment_item(a["tracker_id"], account, "Groundwork: this task now carries more than 1 point. "
                                "The points are kept; consider splitting it into one-day tasks in a revise run.")
                items[a["key"]]["split_comment"] = True
                pending += 1
            elif a["action"] == "adopt":
                items[a["key"]] = {"key": a["key"], "tracker_id": a["tracker_id"], "owned_hash": p["owned_hash"], "links": [], "not_ready": True}
            if pending >= create_steps.BATCH:
                checkpoint()
        for p in planned:
            if p["phase"] not in phases:
                continue
            it = items[p["key"]]
            if not any(l["type"] == "parent" for l in it["links"]):
                tr.link_parent(it["tracker_id"], epic)
                it["links"].append({"type": "parent", "to_key": plan["epic"]["key"]})
                pending += 1
            for d in p["task"]["depends_on"]:
                dk = f"gw:{plan['id']}:{d['task']}"
                if not any(l["type"] == "blocked_by" and l["to_key"] == dk for l in it["links"]) and dk in items:
                    tr.link_dependency(it["tracker_id"], items[dk]["tracker_id"])
                    it["links"].append({"type": "blocked_by", "to_key": dk})
                    pending += 1
            if pending >= create_steps.BATCH:
                checkpoint()
        for a in pf["actions"]:
            if a["action"] == "set_blocked" and not items[a["key"]].get("blocked_set"):
                tr.set_blocked(items[a["key"]]["tracker_id"])
                items[a["key"]]["blocked_set"] = True
                pending += 1
                if pending >= create_steps.BATCH:
                    checkpoint()
        checkpoint()
        # freeze: flip item by item, recording each in the manifest
        for p in planned:
            if p["phase"] in phases and items[p["key"]]["not_ready"]:
                tr.clear_not_ready(items[p["key"]]["tracker_id"])
                items[p["key"]]["not_ready"] = False
                pending += 1
                if pending >= create_steps.BATCH:
                    checkpoint()
        checkpoint()
    except WriteFailed as e:
        tr.fail_at = None
        if hard_crash:
            return {"ok": False, "failed": str(e), "crashed": True}  # no manifest, no release: the session died
        try:
            checkpoint()
        except WriteFailed:
            pass
        tr.comment(account, create_steps.lock_line("release", run, account, tr.clock))
        return {"ok": False, "failed": str(e)}
    tr.comment(account, create_steps.lock_line("release", run, account, tr.clock))
    return pf


def run_close(tr, plan, overlay, closes, run="run-c", account="acct-dev", crash_after=None):
    """Follow the core's close procedure. crash_after: 'intent' | 'label' | 'transition' stops the session there."""
    fm = overlay["skills"]["tracker"]["field_map"]
    manifest = latest_manifest(tr, plan["id"])
    written = {i["key"]: copy.deepcopy(i) for i in (manifest or {}).get("items", [])}
    found = []
    for k, w in written.items():
        st = create_steps.read_status(tr.raw(w["tracker_id"]), w, fm)
        found.append({"key": k, "tracker_id": w["tracker_id"], "status": st["status"], "close_pending": st["close_pending"]})
    plan_steps = create_steps.close_steps(closes, manifest, found)
    if not plan_steps["ok"]:
        return plan_steps
    seq = (manifest or {}).get("seq", 0)
    prev = manifest

    def put():
        nonlocal seq, prev
        m = create_steps.make_manifest(prev, sorted(written.values(), key=lambda i: i["key"]), plan["id"], run, seq + 1,
                                       tr.clock, [])
        tr.put(f"{plan['id']}-manifest-{seq + 1}", m)
        seq += 1
        prev = m

    prefix = fm.get("close_label_prefix", create_steps.DEFAULT_CLOSE_PREFIX)
    tracker_reason = {"not_planned": "not_planned", "superseded": "not_planned", "duplicate": "duplicate", "completed": "completed"}
    for st in plan_steps["steps"]:
        if st["step"] == "manifest_intent":
            for it in st["items"]:
                written[it["key"]]["close"] = {"reason": it["reason"], "state": "intent"}
            put()
            if crash_after == "intent":
                return {"ok": False, "crashed": "intent"}
        elif st["step"] == "add_label":
            tr.add_label(st["tracker_id"], prefix + st["reason"])
            if crash_after == "label":
                return {"ok": False, "crashed": "label"}
        elif st["step"] == "transition":
            tr.close(st["tracker_id"], tracker_reason[st["reason"]])
            if crash_after == "transition":
                return {"ok": False, "crashed": "transition"}
        elif st["step"] == "manifest_closed":
            for k in st["keys"]:
                written[k]["close"]["state"] = "closed"
            put()
    return {"ok": True, **plan_steps}


def latest_status(tr, plan_id):
    ss = [v for k, v in tr.store.items() if k.startswith(f"{plan_id}-status-")]
    return copy.deepcopy(max(ss, key=lambda s: s["n"])) if ss else None


def retire_items(tr, plan, overlay, epic):
    fm = overlay["skills"]["tracker"]["field_map"]
    manifest = latest_manifest(tr, plan["id"])
    written = {i["key"]: i for i in (manifest or {}).get("items", [])}
    plan_keys = {t["key"] for t in plan["tasks"]}
    found = {it["key"]: it for it in tr.list_children(epic)}
    for k in sorted(plan_keys - set(found)):  # written but not yet linked under the epic
        for it in tr.find_by_key(k):
            found[k] = it
    out = []
    for k, it in sorted(found.items()):
        w = written.get(k)
        out.append({"key": k, "person_added": k not in plan_keys, "unrecorded": k in plan_keys and w is None,
                    "status": create_steps.read_status(tr.raw(it["tracker_id"]), w, fm)["status"]})
    return out


def run_retire(tr, plan, overlay, approved, choices, proposal_hash, run="run-r", account="acct-dev", epic="VOL-1",
               resuming=None, crash_after=None, draft_label=None):
    """Follow the retire write order. approved: the retire plan the runner approved (retire.plan_retire).
    crash_after: 'closes' | 'intent' | 'status' | 'recorded' | 'snapshot' | 'epic' stops the session there."""
    import retire
    manifest, status = latest_manifest(tr, plan["id"]), latest_status(tr, plan["id"])
    g = retire.gate("resume" if resuming else "retire", plan, manifest, status, tr.epic_state.get(epic, "open"), resuming)
    if not g["ok"]:
        return g
    probs = retire.recheck(approved, retire_items(tr, plan, overlay, epic), choices)
    if probs:
        return {"ok": False, "problems": probs}
    decision = create_steps.lock_decision(tr.comments, run, account, tr.clock)
    if decision["decision"] == "claim":
        tr.comment(account, decision["post"])
        decision = create_steps.lock_decision(tr.comments, run, account, tr.clock)
    if decision["decision"] != "held":
        return {"ok": False, "lock": decision}
    if draft_label and draft_label in tr.epic_labels.get(epic, set()):
        tr.remove_epic_label(epic, draft_label)
    res = run_close(tr, plan, overlay, approved["closes"], run=run, account=account)
    if not res["ok"]:
        return res
    if crash_after == "closes":
        return {"ok": False, "crashed": "closes"}
    manifest = latest_manifest(tr, plan["id"])

    def put(sf):
        nonlocal manifest
        m = create_steps.make_manifest(manifest, manifest["items"], plan["id"], run, manifest["seq"] + 1, tr.clock, [],
                                       status_file=sf)
        tr.put(f"{plan['id']}-manifest-{m['seq']}", m)
        manifest = m

    sf = manifest.get("status_file")
    if sf is None:
        n = (status["n"] + 1) if status else 1
        sf = retire.status_intent(retire.status_record(plan, n, proposal_hash, create_steps.fmt(tr.clock)))
        put(sf)
    if crash_after == "intent":
        return {"ok": False, "crashed": "intent"}
    if latest_status(tr, plan["id"]) is None:
        tr.put(f"{plan['id']}-status-{sf['n']}", retire.rebuild_status(plan["id"], sf))
    if crash_after == "status":
        return {"ok": False, "crashed": "status"}
    if sf["state"] != "recorded":
        put(dict(sf, state="recorded"))
    if crash_after == "recorded":
        return {"ok": False, "crashed": "recorded"}
    snap = f"{plan['id']}-snapshot-retire"
    if snap not in tr.store:
        tr.put(snap, {"plan_id": plan["id"], "manifest_seq": manifest["seq"], "status_n": sf["n"]})
    if crash_after == "snapshot":
        return {"ok": False, "crashed": "snapshot"}
    if tr.epic_state.get(epic, "open") != "closed":
        tr.close_epic(epic)
    if crash_after == "epic":
        return {"ok": False, "crashed": "epic"}
    tr.comment(account, create_steps.lock_line("release", run, account, tr.clock))
    return {"ok": True, "status_n": sf["n"]}
