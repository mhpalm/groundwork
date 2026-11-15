# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist
"""Builds golden projects G2 to G6, G8 and G9 from G1 (run make_g1.py first).

Each project is a variant of the same fictional org and repo, so the only thing
that differs is what the project is testing:

  G2  too big for one pass: later phases stay outline and cannot be offered
  G3  mostly non-development work under the same rules
  G4  reduced coverage: a system with no skill is reported and its task is parked
  G5  ambiguity: an open question pauses one task and its dependents only
  G6  revise mode: a baseline epic with human edits and a scope change
  G8  cross-org: wrong sign-in stops a system; a foreign run bundle is refused
  G9  release on a live-like baseline: normal work is not drift, points are kept,
      a hand-deleted task is never recreated

Hashes are computed by the core's scripts, exactly as a real run would.
"""
import copy
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "skills", "groundwork-core", "scripts"))
import gw_yaml  # noqa: E402
import run_bundle  # noqa: E402
from gw_hash import item_hash  # noqa: E402
from revise_diff import rendered_hash  # noqa: E402
from validate_overlay import overlay_hash  # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "golden")
G1 = os.path.join(GOLDEN, "G1")
AT = "2026-11-14T19:02:11Z"
DIRECTOR = "acct-program-director"
OTHER_ORG = "second-org"


def load_g1():
    plan = json.load(open(os.path.join(G1, "expected", "plan.json"), encoding="utf-8"))
    overlay = gw_yaml.load(os.path.join(G1, "overlay", "overlay.yaml"))
    ev = {}
    for n in sorted(os.listdir(os.path.join(G1, "evidence"))):
        ev[n[:-5]] = json.load(open(os.path.join(G1, "evidence", n), encoding="utf-8"))
    return plan, overlay, ev


def new_id(n):
    return f"gw-01JCX7Q3RZ9V4N2T8K5M6P0G{n:02d}"


def rekey(plan, pid):
    plan["id"] = pid
    plan["epic"]["key"] = f"gw:{pid}:epic"
    for t in plan["tasks"]:
        t["key"] = f"gw:{pid}:{t['id']}"
    return plan


def rerun_evidence(ev, pid):
    out = {}
    for label, item in ev.items():
        item = copy.deepcopy(item)
        item["run_id"] = pid
        item["hash"] = item_hash(item)
        out[label] = item
    return out


def set_overlay(plan, overlay):
    overlay["hash"] = None
    overlay["hash"] = overlay_hash(overlay)
    plan["overlay"]["hash"] = overlay["hash"]
    plan["stamps"]["overlay"]["hash"] = overlay["hash"]


def derive_access(plan):
    need = {a["id"]: [] for a in plan["access_list"]}
    for t in sorted(plan["tasks"], key=lambda t: t["id"]):
        for a in t["access"]:
            need[a].append(t["id"])
    for a in plan["access_list"]:
        a["needed_by"] = need[a["id"]]


def task_by(plan, tid):
    return next(t for t in plan["tasks"] if t["id"] == tid)


def step(text, refs=(), from_evidence=None):
    return {"text": text, "refs": list(refs), "from_evidence": from_evidence}


def task(pid, tid, order, title, kind, role, hours, deps, steps, purpose, accept, verify, done_today, visible,
         prereq=(), waits=(), access=(), evidence=(), produces=(), pattern="core.generic"):
    return {
        "id": tid, "order": order, "key": f"gw:{pid}:{tid}", "phase": tid.split("-")[0], "title": title,
        "work_type": "story" if kind == "build" else "task", "kind": kind,
        "role_key": role, "points": 1, "estimate_hours": hours, "parallel_group": None,
        "depends_on": [{"task": d, "satisfied_by": s} for d, s in deps], "waits_on": list(waits), "access": list(access),
        "evidence_refs": list(evidence), "produces": [{"type": ty, "name": nm} for ty, nm in produces],
        "instructions": {"purpose": purpose, "prerequisites": list(prereq), "steps": steps, "acceptance_criteria": accept,
                         "verify": verify, "done_today": done_today},
        "visible_result": {"type": visible[0], "text": visible[1]},
        "production_change": False, "data_change": False, "test_tasks": [], "rollback_task": None, "exception": None,
        "origin": {"pattern": pattern, "rules_checked": []}, "changes_existing": None,
        "brief_refs": ["B-3"], "approach_refs": [], "derived_from_rec": None,
    }


def bf(n, key, value=None, status="answered", na=None, source="runner", basis=None, derived=()):
    return {"id": f"B-{n}", "key": key, "value": value if status == "answered" else None, "status": status,
            "na_reason": na, "open_question": None, "phase": None, "source": source, "basis_role_key": basis,
            "derived_from": list(derived), "sensitivity": "normal", "value_rev": None}


def write(name, header, request, overlay, ev, plan, assertions, fixtures=None):
    out = os.path.join(GOLDEN, name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    for sub in ("overlay", "evidence", "expected"):
        os.makedirs(os.path.join(out, sub))
    with open(os.path.join(out, "overlay", "overlay.yaml"), "w", encoding="utf-8") as f:
        f.write(f"# Golden project {name} overlay (same fictional org as G1)\n" + gw_yaml.dumps(overlay))
    for label, item in ev.items():
        with open(os.path.join(out, "evidence", f"{label}.json"), "w", encoding="utf-8") as f:
            json.dump(item, f, indent=2)
            f.write("\n")
    with open(os.path.join(out, "expected", "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(out, "request.md"), "w", encoding="utf-8") as f:
        f.write(request.strip() + "\n")
    with open(os.path.join(out, "assertions.yaml"), "w", encoding="utf-8") as f:
        f.write(f"# Structural assertions for golden project {name} ({header}). Never exact text.\n" + gw_yaml.dumps(assertions))
    for rel, obj in (fixtures or {}).items():
        full = os.path.join(out, "fixtures", rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
    print(f"{name} written")


BASE_ASSERT = {
    "schema_version": "1.0", "validator_blockers": 0, "allowed_minors": ["GR-20"], "min_tasks": 12, "max_tasks": 20,
    "phases_required": ["P0"], "standard_work": ["test", "uat", "cutover", "rollback", "docs", "handoff"],
    "production_change_tasks_min": 1,
    "roles_used_subset_of": ["developer", "maintainer", "admin", "business_user", "comms", "approver"],
    "every_task": {"points": 1, "max_hours": 6, "has_visible_result": True},
    "must_wait_on_kinds": ["review", "approval", "availability", "access"], "no_external_recipients": True,
    "starting_point": "extends_existing", "changes_existing_tasks_min": 1, "changes_justified": True,
}


def history(plan, change):
    plan["history"] = [{"version": 1, "at": AT, "change": change, "by": "groundwork-core"}]


# G2: too big for one pass ----------------------------------------------------

def g2(plan, overlay, ev):
    pid = new_id(2)
    plan = rekey(plan, pid)
    plan["request"]["original_text"] = ("Create project: let coordinators download an event's sign-ups as a CSV, send them a weekly "
                                        "digest of upcoming events, and give them a dashboard of sign-up trends.")
    plan["request"]["restatement"] = ("Add a coordinator-only CSV download of an event's sign-ups, then a weekly digest email and a "
                                      "sign-up trends dashboard. The export is planned in detail; the digest and dashboard are "
                                      "outline phases for later runs.")
    plan["scope"]["in"].append("Weekly digest and trends dashboard, as outline phases planned in later runs")
    plan["phases"] += [
        {"id": "P4", "order": 4, "name": "Weekly digest", "goal": "Coordinators get a weekly email of upcoming events and open shifts.",
         "state": "outline", "depends_on": ["P3"], "task_ids": [],
         "carries_questions": ["Which day and time should the digest go out?", "Who may unsubscribe, and how?"]},
        {"id": "P5", "order": 5, "name": "Sign-up trends dashboard",
         "goal": "Coordinators see sign-ups per week and per event on one page.", "state": "outline", "depends_on": ["P3"],
         "task_ids": [], "carries_questions": ["Which date range does the dashboard show by default?"]},
    ]
    history(plan, "drafted")
    a = dict(BASE_ASSERT, outline_phases=["P4", "P5"], proposable_phases=["P0", "P1", "P2", "P3"],
             unproposable_phases=["P4", "P5"])
    write("G2", "too big for one pass", plan["request"]["original_text"], overlay, rerun_evidence(ev, pid), plan, a)


# G3: mostly non-development work ----------------------------------------------

def g3(plan, overlay, ev):
    pid = new_id(3)
    plan = rekey(plan, pid)
    E = rerun_evidence({k: v for k, v in ev.items() if k in ("gh-0004", "gh-0006", "gh-0011", "jira-0001")}, pid)
    GUIDE, TEMPLATE, DEPLOY = E["gh-0011"]["id"], E["gh-0006"]["id"], E["gh-0004"]["id"]
    review = {"what": "Portal Maintainer code owner review", "kind": "review", "owner_role_key": "maintainer"}
    coord_time = {"what": "Two coordinators free for an hour", "kind": "availability", "owner_role_key": "business_user"}
    signoff = {"what": "Program Director sign-off", "kind": "approval", "owner_role_key": "approver"}
    access_wait = {"what": "A3 granted (staging coordinator login)", "kind": "access", "owner_role_key": "admin"}
    T = [
        task(pid, "P0-T01", 1, "Request access for every role in this plan", "setup", "comms", 1, [],
             [step("Open the Access list table in the epic description. It has three lines, A1 to A3."),
              step("Open the access request link in the epic description and submit one request per line, naming the person "
                   "the epic's role-holders list gives for that role. Paste this task's key into the reason."),
              step("If the form says the person already has that access, note 'already granted' for that line."),
              step("Post one comment on this task with three lines: the access id, then the request reference or 'already granted'.")],
             "Get every account and permission this plan needs requested on day one.",
             ["All three lines have a request reference or 'already granted'."],
             ["The comment on this task has three lines, A1 to A3."],
             "The comment is posted. Waiting for grants is tracked on the tasks that need them.",
             ("comment_posted", "Comment listing A1 to A3 with request references"),
             produces=[("access_request", "A1"), ("access_request", "A2"), ("access_request", "A3")],
             pattern="core.access-request"),
        task(pid, "P1-T01", 2, "Write the check-in section of the coordinator guide", "docs", "developer", 4,
             [("P0-T01", "done")],
             [step("Run git checkout main, git pull, then git checkout -b docs/check-in-guide."),
              step("Open docs/user-guide/coordinators/ and add check-in.md: how to open an event's check-in list, mark a "
                   "volunteer arrived, and undo a mistaken check-in.", [GUIDE]),
              step("Link the new page from the coordinators index page."),
              step("Push, open a pull request to main with the template sections and this task's key, and link it here.",
                   [TEMPLATE])],
             "Coordinators need one written place to learn the new check-in steps.",
             ["The guide has a check-in page linked from the index.", "The ci check is green."],
             ["Preview the Markdown on the pull request and check every step reads in order."],
             "The pull request is open with green CI and review requested, linked on this task.",
             ("pr_opened", "PR opened, CI green"), prereq=["A1 is granted."], waits=[review], access=["A1"],
             evidence=[GUIDE, TEMPLATE], produces=[("doc", "check-in guide page")], pattern="github.docs-change"),
        task(pid, "P1-T02", 3, "Build the check-in training slides", "training", "comms", 5, [("P1-T01", "merged")],
             [step("Make a copy of the team's slide template in the shared training folder and name it 'Check-in training'.",
                   ["A2"]),
              step("Make one slide per step of the check-in guide page, in the same order.", ["check-in guide page"]),
              step("Add a last slide with the help link /help and who to ask in the announcements channel.", [GUIDE]),
              step("Share the deck link in a comment on this task.")],
             "A 20-minute session needs slides that match the guide exactly.",
             ["One slide per guide step, in order, plus a help slide."],
             ["Open the deck and the guide side by side; every guide step has its slide."],
             "The deck link is posted on this task.", ("doc_submitted", "Training deck shared"),
             prereq=["P1-T01 is merged.", "A2 is granted."], access=["A2"], evidence=[GUIDE],
             produces=[("doc", "training slides")], pattern="core.training-material"),
        task(pid, "P1-T03", 4, "Dry-run the training with two coordinators", "test", "business_user", 2, [("P1-T02", "done")],
             [step("Book an hour with two coordinators who have not seen the new check-in screen."),
              step("Present the training slides, then have each coordinator check in a test volunteer on staging using only "
                   "the guide.", ["training slides", "check-in guide page", DEPLOY]),
              step("Write down every place either of them hesitated or asked a question."),
              step("Post the list as a comment on this task.")],
             "Find the confusing parts before the real session.",
             ["Both coordinators finished a check-in on staging.", "Every hesitation is listed."],
             ["The comment names both coordinators' roles and lists the hesitations."],
             "The dry-run notes are posted on this task.", ("comment_posted", "Dry-run notes posted"),
             prereq=["A3 is granted."], waits=[coord_time, access_wait], access=["A3"], evidence=[DEPLOY],
             produces=[("note", "dry-run notes")], pattern="core.dry-run"),
        task(pid, "P1-T04", 5, "Revise the slides and guide from the dry run", "docs", "comms", 3, [("P1-T03", "done")],
             [step("Open the dry-run notes and the training slides.", ["dry-run notes", "training slides"]),
              step("Change each slide the notes point at, and reply under each note with what changed."),
              step("Where the guide itself was unclear, open a small pull request to the guide page and link it here.",
                   ["check-in guide page", TEMPLATE])],
             "Fix what confused people before the real session.",
             ["Every dry-run note has a reply saying what changed or why not."],
             ["Re-read the changed slides against the notes."],
             "The revised deck is shared and every note is answered.", ("doc_submitted", "Revised deck shared"),
             access=["A2"], evidence=[TEMPLATE], produces=[("doc", "final training slides")], pattern="core.revise-material"),
        task(pid, "P2-T01", 6, "Schedule the training session and invite coordinators", "comms", "comms", 1, [("P1-T04", "done")],
             [step("Pick a 30-minute slot in the next two weeks that the coordinator lead agrees to."),
              step("Post the invitation in the announcements channel with the date, time, call link and the help link /help.",
                   ["A3", GUIDE]),
              step("Paste the message link into a comment on this task.")],
             "Coordinators need the date and link well before the session.",
             ["The invitation is posted with date, time, call link and help link."],
             ["Open the posted message and check every detail is there."],
             "The invitation is posted and linked here.", ("comment_posted", "Invitation link posted"),
             access=["A3"], evidence=[GUIDE], produces=[("message", "training invitation")], pattern="core.announce"),
        task(pid, "P2-T02", 7, "Run the training session", "training", "comms", 2, [("P2-T01", "done")],
             [step("Open the call five minutes early and share the final training slides.", ["final training slides"]),
              step("Walk through each slide, then have attendees check in a test volunteer on staging while you watch.",
                   [DEPLOY]),
              step("Post a comment on this task with the number of attendees and any question you could not answer.")],
             "Coordinators learn the new check-in steps together, with time to try them.",
             ["The session ran and every attendee tried a check-in."],
             ["The comment has the attendee count and open questions."],
             "Attendance and open questions are posted here.", ("comment_posted", "Attendance posted"),
             waits=[{"what": "Coordinators attend the session", "kind": "availability", "owner_role_key": "business_user"}],
             evidence=[DEPLOY], produces=[("note", "session notes")], pattern="core.training-session"),
        task(pid, "P2-T03", 8, "Check in a test volunteer on staging using only the guide", "uat", "business_user", 1,
             [("P2-T02", "done")],
             [step("Sign in to staging with your coordinator login and open event 1's check-in list.", ["A3", DEPLOY]),
              step("Follow the check-in guide page alone, without the slides, to check in and then undo one test volunteer.",
                   ["check-in guide page"]),
              step("Comment on this task 'passed' or the step where you got stuck.")],
             "Prove a coordinator can do it from the written guide alone.",
             ["A coordinator checked in and undid a test volunteer from the guide alone."],
             ["The comment says 'passed' or names the step."],
             "The result is posted on this task.", ("comment_posted", "UAT result posted"),
             prereq=["A3 is granted."], access=["A3"], evidence=[DEPLOY], pattern="core.uat"),
        task(pid, "P2-T04", 9, "Prepare the sign-off packet for the Program Director", "signoff_prep", "comms", 2,
             [("P2-T03", "done")],
             [step("Make one page with links to the guide page, the final training slides, the session notes and the UAT result.",
                   ["check-in guide page", "final training slides", "session notes"]),
              step("Add one line: 'Approve check-in training as complete?'"),
              step("Attach the page to this task and mention the Program Director.")],
             "The Program Director signs off from one page, not five links in different places.",
             ["The page links all four items and asks one question."],
             ["Open every link on the page."],
             "The packet is attached and the Program Director is asked.", ("doc_submitted", "Sign-off packet attached"),
             waits=[signoff], produces=[("doc", "sign-off packet")], pattern="core.signoff"),
        task(pid, "P2-T05", 10, "Hand the training material to the coordinator lead", "handoff", "comms", 1, [("P2-T04", "done")],
             [step("Move the final training slides into the coordinators' shared folder.", ["final training slides", "A2"]),
              step("Comment on this task with where the slides, guide page and sign-off packet live, and mention the "
                   "coordinator lead.", ["sign-off packet", "check-in guide page"])],
             "The coordinator lead owns the material for the next new coordinator.",
             ["The coordinator lead has acknowledged the handoff on this task."],
             ["The comment names all three locations."],
             "The handoff comment is posted.", ("comment_posted", "Handoff comment posted"),
             access=["A2"], pattern="core.handoff"),
    ]
    plan["tasks"] = T
    plan["title"] = "Check-in training for coordinators"
    plan["epic"]["title"] = "Check-in training for coordinators"
    plan["epic"]["summary"] = ("Coordinators are trained on the new event check-in steps from a written guide, with a dry run, a "
                               "session, a guide-only check, and the Program Director's sign-off.")
    plan["request"] = {
        "original_text": "Create project: train coordinators on the new event check-in process and get the Program Director's sign-off.",
        "restatement": ("Write the check-in guide page, build and dry-run training slides, run one session, check a "
                        "coordinator can do it from the guide alone, and get sign-off."),
        "clarifications": [
            {"id": "C-1", "question": "Is the check-in screen already on staging?", "answer": "Yes, it ships next month.",
             "answered_by": DIRECTOR, "at": AT},
            {"id": "C-2", "question": "Live session or recording?", "answer": "One live session; slides kept for later.",
             "answered_by": DIRECTOR, "at": AT},
            {"id": "C-3", "question": "Does anything already exist that this builds on, or is it from scratch?",
             "answer": "The coordinator guide exists; the training material is new.", "answered_by": DIRECTOR, "at": AT}],
        "starting_point": {"kind": "extends_existing", "resources": [
            {"id": "R1", "name": "Coordinator guide", "kind": "doc", "location": "docs/user-guide/coordinators in the portal repo",
             "inspected": [E["gh-0011"]["id"]], "not_inspected_reason": None}]}}
    plan["scope"] = {"in": ["Guide page", "Training slides, dry run and one session", "Guide-only check and sign-off"],
                     "out": ["Changes to the check-in screen", "A recorded video"],
                     "assumptions": [{"text": "The guide ships with each deploy because the app serves docs at /help.",
                                      "basis": GUIDE}]}
    plan["access_list"] = [
        {"id": "A1", "role_key": "developer", "system": "github", "instance": "gh",
         "level": "write on example-org/volunteer-portal (docs pull request)", "needed_by": []},
        {"id": "A2", "role_key": "comms", "system": "files", "instance": "training-folder",
         "level": "edit in the shared training folder", "needed_by": []},
        {"id": "A3", "role_key": "comms", "system": "github", "instance": "gh",
         "level": "coordinator login on staging and post in the announcements channel", "needed_by": []},
    ]
    derive_access(plan)
    plan["phases"] = [
        {"id": "P0", "order": 0, "name": "Setup", "goal": "Every access request is in.", "state": "drafted",
         "depends_on": [], "task_ids": ["P0-T01"]},
        {"id": "P1", "order": 1, "name": "Material and dry run",
         "goal": "The guide page is merged and the slides are revised after a dry run.", "state": "drafted",
         "depends_on": ["P0"], "task_ids": ["P1-T01", "P1-T02", "P1-T03", "P1-T04"]},
        {"id": "P2", "order": 2, "name": "Train and sign off",
         "goal": "Coordinators are trained, one passes a guide-only check, and the Program Director signs off.",
         "state": "drafted", "depends_on": ["P1"], "task_ids": ["P2-T01", "P2-T02", "P2-T03", "P2-T04", "P2-T05"]},
    ]
    plan["standard_work"] = [
        {"kind": "test", "tasks": ["P1-T03"], "not_applicable_reason": None},
        {"kind": "uat", "tasks": ["P2-T03"], "not_applicable_reason": None},
        {"kind": "cutover", "tasks": [], "not_applicable_reason": "Nothing is switched over; the guide ships with the next regular deploy."},
        {"kind": "rollback", "tasks": [], "not_applicable_reason": "This project changes no production system or data."},
        {"kind": "docs", "tasks": ["P1-T01", "P1-T04"], "not_applicable_reason": None},
        {"kind": "handoff", "tasks": ["P2-T05"], "not_applicable_reason": None},
    ]
    # Planning model: a training project pins changes_how_people_work, which needs the trainer role.
    overlay["roles"].append({"key": "trainer", "name": "Coordinator Trainer"})
    plan["traits"] = [{"id": "changes_how_people_work", "version": "1.0.0", "from_plan_version": 1}]
    plan["brief"] = [
        bf(1, "outcome", "Coordinators check volunteers in correctly using the guide, without asking anyone."),
        bf(2, "success_measure", "A coordinator checks in a test volunteer on staging using only the guide."),
        bf(3, "scope_in", "The guide page, training slides with a dry run, one session, a guide-only check and sign-off."),
        bf(4, "non_goals", "Changes to the check-in screen; a recorded video."),
        bf(5, "starting_point", "Extends the existing coordinator guide.", source="evidence", basis="comms", derived=[GUIDE]),
        bf(6, "consumers", "Volunteer coordinators."),
        bf(7, "constraints", "The guide ships with the next regular deploy."),
        bf(8, "risks", "Coordinators miss the session; the guide drifts from the screen."),
        bf(9, "deliverable_signoffs", "The Program Director signs off the training material."),
        bf(10, "run_owner_after_handoff", "The coordinator lead."),
        bf(11, "external_dependencies", status="not_applicable", na="Everything is inside the portal and the shared training folder."),
        bf(12, "budget", status="not_applicable", na="No spend; existing team time only."),
        bf(13, "legal_duties", status="not_applicable", na="No personal data is collected or moved."),
        bf(14, "nonfunctional", "The guide page reads well on a phone."),
        bf(15, "comms_audiences", "Coordinators, through the session invitation."),
        bf(16, "affected_people", "All volunteer coordinators."),
        bf(17, "training_need", "How to check a volunteer in, in one live session with slides."),
        bf(18, "support_after", "The coordinator lead answers questions after handoff."),
    ]
    plan["approach"] = {
        "options": [
            {"id": "O-1", "summary": "Add a check-in section to the existing coordinator guide and train from it.", "kind": "reuse_extend",
             "evidence": [GUIDE], "not_inspected_reason": None, "pros": ["One source of truth"], "cons": ["Needs a docs pull request"],
             "rejected_because": None},
            {"id": "O-2", "summary": "Send coordinators a one-page note instead of training them.", "kind": "smaller", "evidence": [],
             "not_inspected_reason": "Nothing exists to inspect; it would be new text.", "pros": ["Faster"], "cons": ["No practice"],
             "rejected_because": {"brief_ref": "B-1", "why": "Without practice coordinators are unlikely to check volunteers in correctly first time."}},
        ],
        "decisions": [{"id": "AD-1", "decision": "Extend the coordinator guide and run one live session from it.", "chosen_option": "O-1",
                       "deferred_to_task": None, "brief_refs": ["B-1", "B-3"], "evidence": [GUIDE]}],
        "unchanged": [],
    }
    plan["stamps"]["plan_format"] = "2.0"
    task_by(plan, "P1-T01")["changes_existing"] = {
        "resources": ["R1"], "why_needed": "The guide has no check-in section today.",
        "could_break": ["Links into the existing guide sections"], "regression_check": ["P2-T03"]}
    task_by(plan, "P1-T01")["approach_refs"] = ["AD-1"]
    chk = task_by(plan, "P2-T03")
    chk["visible_result"] = {"type": "measurement", "text": chk["visible_result"]["text"]}
    chk["brief_refs"] = ["B-2", "B-3"]
    plan["standard_work"] += [
        {"kind": "training", "tasks": ["P1-T02", "P2-T02"], "not_applicable_reason": None},
        {"kind": "support_handoff", "tasks": ["P2-T05"], "not_applicable_reason": None},
    ]
    set_overlay(plan, overlay)
    history(plan, "drafted")
    a = dict(BASE_ASSERT, changes_existing_tasks_min=0, min_tasks=8, max_tasks=14, production_change_tasks_min=0, production_change_tasks_max=0,
             standard_work=["test", "uat", "docs", "handoff"], standard_work_not_applicable=["cutover", "rollback"],
             non_dev_share_min=0.8)
    write("G3", "mostly non-development work", plan["request"]["original_text"], overlay, E, plan, a)


# G4: reduced coverage ----------------------------------------------------------

def g4(plan, overlay, ev):
    pid = new_id(4)
    plan = rekey(plan, pid)
    overlay["skills"]["unsupported_systems"] = [
        {"name": "mailing-list", "note": "The coordinators' mailing list tool has no Groundwork skill yet."}]
    set_overlay(plan, overlay)
    plan["request"]["original_text"] = ("Create project: let coordinators download an event's sign-ups as a CSV, and tell them "
                                        "about it on the coordinators' mailing list as well as the channel.")
    plan["coverage"].append({"system": "mailing-list", "instance": "coordinators", "skill": None, "skill_version": None,
                             "surface": "claude-code-local", "status": "not_inspected", "read_only": "not_applicable",
                             "inspected": [], "not_inspected": ["the mailing list tool"],
                             "reason": "The overlay lists it as an unsupported system; no skill can read it."})
    plan["access_list"].append({"id": "A6", "role_key": "comms", "system": "mailing-list", "instance": "coordinators",
                                "level": "send to the coordinators' mailing list", "needed_by": []})
    t0 = task_by(plan, "P0-T01")
    t0["produces"].append({"type": "access_request", "name": "A6"})
    for s in t0["instructions"]["steps"]:
        s["text"] = s["text"].replace("five lines, A1 to A5", "six lines, A1 to A6").replace("five lines", "six lines")
    t0["instructions"]["acceptance_criteria"] = ["All six lines have a request reference or 'already granted'."]
    t0["instructions"]["verify"] = ["The comment on this task has six lines, A1 to A6."]
    t0["visible_result"]["text"] = "Comment listing A1 to A6 with request references"
    t = task_by(plan, "P3-T04")
    t["access"].append("A6")
    t["instructions"]["steps"].append(step("Send the same text to the coordinators' mailing list.", ["A6"]))
    plan["open_questions"] = [{
        "id": "Q-1", "status": "open", "answer": None, "answered_by": None, "at": None, "blocks": ["P3-T04"],
        "text": ("Which mailing list reaches all coordinators, and who may send to it? Groundwork could not inspect the "
                 "mailing list tool, so this task waits until someone answers.")}]
    derive_access(plan)
    history(plan, "drafted")
    a = dict(BASE_ASSERT, proposable_phases=["P0", "P1", "P2"], unproposable_phases=["P3"], blocked_tasks=["P3-T04"],
             coverage_not_inspected=["mailing-list"])
    write("G4", "reduced coverage", plan["request"]["original_text"], overlay, rerun_evidence(ev, pid), plan, a)


# G5: ambiguity -----------------------------------------------------------------

def g5(plan, overlay, ev):
    pid = new_id(5)
    plan = rekey(plan, pid)
    plan["open_questions"] = [{
        "id": "Q-1", "status": "open", "answer": None, "answered_by": None, "at": None, "blocks": ["P3-T03"],
        "text": "Who confirms the export in production: the coordinator lead, or any coordinator who runs an event that week?"}]
    history(plan, "drafted")
    a = dict(BASE_ASSERT, proposable_phases=["P0", "P1", "P2"], unproposable_phases=["P3"],
             blocked_tasks=["P3-T03", "P3-T04"])
    write("G5", "ambiguity", plan["request"]["original_text"], overlay, rerun_evidence(ev, pid), plan, a)


# G6: revise mode ---------------------------------------------------------------

def g6(plan, overlay, ev):
    pid = new_id(6)
    base = rekey(plan, pid)
    for p in base["phases"]:
        p["state"] = "released" if p["id"] in ("P0", "P1") else "drafted"
    history(base, "drafted")
    new = copy.deepcopy(base)
    new["version"] = 2
    new["history"].append({"version": 2, "at": "2026-11-20T15:00:00Z", "change": "revised: empty events, guide title adopted, "
                           "production confirmation dropped", "by": "groundwork-core"})
    new["request"]["clarifications"].append({
        "id": "C-6", "question": "What should the export do for an event with no sign-ups?",
        "answer": "Download a file with only the header row, and say so in the guide.", "answered_by": DIRECTOR,
        "at": "2026-11-20T15:00:00Z"})
    seed = ev["gh-0014"]["id"]
    # 1. A person retitled P1-T04 in the tracker. The tracker wins: the revised plan adopts it.
    guide = task_by(new, "P1-T04")
    guide["title"] = "Add the CSV section and FAQ to the coordinator guide"
    # 2. Scope change. P1-T01 (the serializer) is done, so the change is a follow-up task with a new id.
    follow = task(pid, "P1-T06", 4, "Handle events with no sign-ups in the CSV export", "build", "developer", 3,
                  [("P1-T01", "merged")],
                  [step("Run git checkout main, git pull, then git checkout -b feat/signups-csv-empty."),
                   step("In the sign-ups CSV serializer, return only the header row when the event has no sign-ups.",
                        [seed]),
                   step("Add a test for seeded event 2, which has no sign-ups, expecting exactly one line.", [seed]),
                   step("Push, open a pull request to main with the template sections and this task's key, and link it here.")],
                  "An event with no sign-ups must still download a valid file.",
                  ["Event 2 exports a file with only the header row.", "The ci check is green."],
                  ["Run npm test locally and see the new test pass."],
                  "The pull request is open with green CI and review requested, linked on this task.",
                  ("pr_opened", "PR opened, CI green"), prereq=["P1-T01 is merged."],
                  waits=[{"what": "Portal Maintainer code owner review", "kind": "review", "owner_role_key": "maintainer"}],
                  access=["A1"], evidence=[seed], produces=[("code", "empty-event CSV handling")], pattern="github.code-change")
    new["tasks"].append(follow)
    next(p for p in new["phases"] if p["id"] == "P1")["task_ids"].insert(1, "P1-T06")
    task_by(new, "P1-T02")["depends_on"].append({"task": "P1-T06", "satisfied_by": "merged"})
    test = task_by(new, "P1-T05")
    test["instructions"]["steps"].insert(-1, step("Export event 2, which has no sign-ups, and check the file has only the header row.",
                                                  [seed]))
    test["evidence_refs"] = sorted(set(test["evidence_refs"] + [seed]))
    for s in new["standard_work"]:
        if s["kind"] == "test":
            s["tasks"].append("P1-T06")
    # 3. The production confirmation is dropped: closed, never deleted.
    new["tasks"] = [t for t in new["tasks"] if t["id"] != "P3-T03"]
    next(p for p in new["phases"] if p["id"] == "P3")["task_ids"].remove("P3-T03")
    task_by(new, "P3-T04")["depends_on"] = [{"task": "P3-T02", "satisfied_by": "done"}]
    # The success measure moves to the production checks, so exactly one task still measures it.
    next(f for f in new["brief"] if f["key"] == "success_measure")["value"] = "The production checks on the verification task pass."
    verify = task_by(new, "P3-T02")
    verify["visible_result"] = {"type": "measurement", "text": verify["visible_result"]["text"]}
    verify["brief_refs"] = ["B-2", "B-3"]
    follow["approach_refs"] = ["AD-1"]
    derive_access(new)
    # The tracker as read_epic returns it: P0 and P1 were created; three tasks are done; P1-T04 was retitled.
    tracker = []
    for i, t in enumerate(sorted(base["tasks"], key=lambda t: t["order"])):
        if t["phase"] not in ("P0", "P1"):
            continue
        h = rendered_hash(new, overlay, guide) if t["id"] == "P1-T04" else rendered_hash(base, overlay, t)
        tracker.append({"key": t["key"], "tracker_id": f"VOL-{200 + i}", "owned_hash": h,
                        "status": "done" if t["id"] in ("P0-T01", "P0-T02", "P1-T01") else "todo",
                        "updated_at": f"2026-11-1{8 if t['id'] == 'P1-T04' else 6}T10:00:00Z", "points": 1})
    expected = {"added": ["P1-T06"], "close": ["P3-T03"], "drift": ["P1-T04"],
                "deps_changed": {"P1-T02": {"added": ["P1-T06"], "removed": []},
                                 "P3-T04": {"added": ["P3-T02"], "removed": ["P3-T03"]}},
                "changed_include": ["P1-T05"], "changed_exclude": ["P0-T01", "P0-T02", "P1-T01", "P1-T04"], "refused": []}
    write("G6", "revise mode", "Revise project: also handle events with no sign-ups; drop the production confirmation task.",
          overlay, rerun_evidence(ev, pid), new, dict(BASE_ASSERT),
          fixtures={"base-plan.json": base, "tracker.json": tracker, "expected-diff.json": expected})


# G8: cross-org -----------------------------------------------------------------

def g8(plan, overlay, ev):
    pid = new_id(8)
    plan = rekey(plan, pid)
    history(plan, "drafted")
    E = rerun_evidence(ev, pid)
    tracker_ok = {"skill": "groundwork-tracker-jira", "instance": "main", "url": overlay["skills"]["tracker"]["instance"]["url"],
                  "account": "acct-dev", "identity": {"project": "VOL"}}
    gh_ok = {"skill": "groundwork-system-github", "instance": "gh", "url": "https://github.com/example-org",
             "account": "dev-login", "identity": {"org": "example-org"}}
    gh_other = dict(gh_ok, url=f"https://github.com/{OTHER_ORG}", identity={"org": OTHER_ORG})
    tracker_other = dict(tracker_ok, identity={"project": "OPS"})
    # A run made under a different org's overlay, exported as a bundle.
    tmp = tempfile.mkdtemp()
    try:
        foreign = copy.deepcopy(plan)
        foreign["overlay"] = {"id": OTHER_ORG, "version": 1, "hash": "0" * 64}
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(foreign, f)
        os.makedirs(os.path.join(tmp, "evidence"))
        item = copy.deepcopy(E["gh-0002"])
        item["overlay_id"] = OTHER_ORG
        item["hash"] = item_hash(item)
        with open(os.path.join(tmp, "evidence", "gh-0002.json"), "w", encoding="utf-8") as f:
            json.dump(item, f)
        bundle = run_bundle.export(tmp)
    finally:
        shutil.rmtree(tmp)
    stray = copy.deepcopy(E["gh-0002"])
    stray["overlay_id"] = OTHER_ORG
    stray["hash"] = item_hash(stray)
    fixtures = {
        "connect-ok.json": [gh_ok, tracker_ok],
        "connect-wrong-org.json": [gh_other, tracker_ok],
        "connect-wrong-tracker.json": [gh_ok, tracker_other],
        "foreign-bundle.json": bundle,
        "foreign-evidence.json": stray,
        "expected.json": {
            "connect-ok.json": {"run": "continue", "stopped": []},
            "connect-wrong-org.json": {"run": "continue", "stopped": ["groundwork-system-github/gh"]},
            "connect-wrong-tracker.json": {"run": "stop", "stopped": ["groundwork-tracker-jira/main"]},
            "foreign-bundle.json": {"import": "refused", "reason_contains": "CR-12"},
            "foreign-evidence.json": {"validator_check": "CR-12"},
        },
    }
    write("G8", "cross-org", plan["request"]["original_text"], overlay, E, plan, dict(BASE_ASSERT), fixtures=fixtures)


# G9: release on a live-like baseline -------------------------------------------

def g9(plan, overlay, ev):
    pid = new_id(9)
    plan = rekey(plan, pid)
    history(plan, "drafted")
    scenario = {
        "written_phases": ["P0", "P1"],
        "release_phase": "P2",
        "human_changes": {
            "status": {"P0-T01": "done", "P0-T02": "done", "P1-T01": "in_progress"},
            "ticked_steps": {"P0-T02": [1, 2, 3]},
            "notes_outside_markers": {"P1-T02": "Coordinator lead: please keep the button grey."},
            "points": {"P1-T03": 3},
            "deleted": ["P1-T05"],
        },
        "expected_first_release": {"ok": False, "stops": ["P2-T01"], "warnings_include": ["P1-T05"],
                                   "no_drift": True, "comment_split": ["P1-T03"]},
        "revise_then_release": {"repoint": {"P2-T01": {"from": "P1-T05", "to": "P1-T04"}},
                                "expected": {"ok": True, "created_phase": "P2", "points_kept": {"P1-T03": 3},
                                             "split_comments": {"P1-T03": 1}, "recreated": []}},
    }
    write("G9", "release on a live-like baseline", "Release phase P2.", overlay, rerun_evidence(ev, pid), plan,
          dict(BASE_ASSERT), fixtures={"scenario.json": scenario})


def main():
    for build in (g2, g3, g4, g5, g6, g8, g9):
        plan, overlay, ev = load_g1()
        build(plan, overlay, ev)


if __name__ == "__main__":
    main()
