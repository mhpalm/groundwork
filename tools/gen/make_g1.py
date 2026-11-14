# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Builds golden project G1 (the spec's worked example) from readable source.

Writes tests/golden/G1/{request.md, overlay/overlay.yaml, evidence/*.json,
expected/plan.json, assertions.yaml}. Hashes are computed by the core's
scripts, exactly as a real run would.
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "skills", "groundwork-core", "scripts"))
import gw_yaml  # noqa: E402
from gw_hash import evidence_id, item_hash  # noqa: E402

OUT = os.path.join(ROOT, "tests", "golden", "G1")
PLAN_ID = "gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC"
AT = "2026-11-14T19:02:11Z"
SKILL = "groundwork-system-github@1.0.0"
JSKILL = "groundwork-tracker-jira@1.0.0"

ZERO = "0" * 64
ACCT = lambda n: {"account_id": f"acct-{n}", "name": n.replace("-", " ").title()}

overlay = {
    "schema_version": "1.0", "overlay_format": "1.0", "id": "example-org", "version": 1, "hash": None,
    "org_name": "Example Org",
    "admins": [ACCT("program-director")],
    "skills": {
        "core": ">=1.0.0 <2.0.0",
        "systems": [{
            "skill": "groundwork-system-github", "version": ">=1.0.0 <2.0.0",
            "instances": [{"id": "gh", "url": "https://github.com/example-org", "expected_identity": {"org": "example-org"}}],
            "expectations": [{"id": "default-branch-protected", "check": "github.branch-protection-required", "confirmed_value": True}],
            "readiness": [{"check": "github.required-ci-check", "status": "ok", "note": "ci"}],
        }],
        "unsupported_systems": [],
        "tracker": {
            "skill": "groundwork-tracker-jira", "version": ">=1.0.0 <2.0.0",
            "instance": {"id": "main", "url": "https://example-org.atlassian.net", "project": "VOL"},
            "field_map": {"key": {"slot": "label"}, "points": "Story Points", "hours": "Original Estimate",
                          "phase": "label", "blocked": "Flagged", "depends_on": "Blocks", "not_ready": "label", "role": "label"},
        },
    },
    "working_day_hours": 6, "assumed_executor": "junior_no_context",
    "roles": [{"key": "developer", "name": "Developer"}, {"key": "maintainer", "name": "Portal Maintainer"},
              {"key": "admin", "name": "Portal Admin"}, {"key": "business_user", "name": "Volunteer Coordinator"},
              {"key": "comms", "name": "Comms Lead"}, {"key": "approver", "name": "Program Director"}],
    "task_hierarchy": {"task_to_epic": "parent", "steps_as": "checklist"},
    "approval_gates": [
        {"id": "phase-release", "applies_to": "all_phases", "approvers": [ACCT("program-director")], "min_approvers": 1},
        {"id": "exception", "applies_to": "one_day_exceptions", "approvers": [ACCT("program-director")]},
        {"id": "overlay", "applies_to": "overlay_changes", "approvers": [ACCT("program-director")]},
    ],
    "evidence_max_age_days": 7, "create_window_days": 3,
    "anchor": {"tracker_ref": "VOL-1"},
    "role_holders": [
        {"role_key": "developer", "display": "Portal developers", "handle": "@portal-devs"},
        {"role_key": "maintainer", "display": "Portal maintainers", "handle": "@example-org/portal-maintainers"},
        {"role_key": "admin", "display": "Portal admin", "handle": "@portal-admin"},
        {"role_key": "business_user", "display": "Volunteer coordinators", "handle": "@coordinators"},
        {"role_key": "comms", "display": "Comms lead", "handle": "@comms"},
        {"role_key": "approver", "display": "Program director", "handle": "@program-director"},
    ],
    "tracker_access_assumed": True,
    "environments": [{"name": "staging", "shared": True}, {"name": "production", "shared": True}],
    "labels": {"draft": "gw-draft", "not_ready": "gw-not-ready"},
    "plan_store": {"mode": "attachments", "repo": None, "path": None},
    "naming": {"epic": "{title}", "task": "{verb} {object}", "label": "groundwork"},
    "access_requests": {"how": "Use the IT access form; any team member may request for any role.",
                        "link": "https://example.org/access", "on_behalf_allowed": True},
    "channels": {"release": "#portal-releases", "announcements": "#coordinators"},
    "run_storage": {"claude-code-local": "~/groundwork/runs"},
}

EV = {}  # label -> evidence item


def ev(label, stype, name, method, facts, sensitivity="structure", untrusted=None, recheck=False, system="github", inst="gh", skill=SKILL):
    subject = {"type": stype, "name": name}
    item = {
        "schema_version": "1.0", "id": evidence_id(system, inst, subject), "run_id": PLAN_ID, "overlay_id": "example-org",
        "system": system, "instance": inst, "skill": skill, "surface": "claude-code-local", "method": method,
        "collected_at": AT, "recheck": recheck, "subject": subject, "facts": facts,
        "untrusted_text": untrusted or [], "sensitivity": sensitivity,
    }
    item["hash"] = item_hash(item)
    EV[label] = item
    return item["id"]


R = "example-org/volunteer-portal"
ev("gh-0001", "repo", R, "read repo settings and branch protection for main",
   {"default_branch": "main", "required_approving_reviews": 1, "code_owner_review": True, "required_checks": ["ci"], "tag_protection": False},
   sensitivity="restricted", recheck=True)
ev("gh-0002", "file", f"{R}:CODEOWNERS@main", "read CODEOWNERS on main", {"owners": [{"pattern": "*", "team": "example-org/portal-maintainers"}]})
ev("gh-0003", "workflow", f"{R}:.github/workflows/ci.yml@main", "read workflow ci.yml",
   {"triggers": ["pull_request"], "steps": ["npm ci", "npm run lint", "npm run db:up", "npm run seed", "npm test"], "check_name": "ci"})
ev("gh-0004", "workflow", f"{R}:.github/workflows/deploy.yml@main", "read workflow deploy.yml and environments",
   {"push_main_deploys": "staging", "tag_pattern_deploys": {"pattern": "v*", "environment": "production"},
    "environments": {"staging": {"url": "https://staging.portal.example.org", "required_reviewers": 0},
                     "production": {"url": "https://portal.example.org", "required_reviewers": 1}},
    "run_summary_shows_sha": True, "workflow_dispatch_inputs": ["ref", "environment"]}, recheck=True)
ev("gh-0005", "file", f"{R}:README.md@main", "read README.md",
   {"node": "20", "setup": ["npm ci", "cp .env.example .env", "npm run db:up", "npm run seed", "npm run dev"], "dev_port": 3000,
    "db": "docker postgres", "sections": ["Local logins"], "credentials_recorded": False},
   untrusted=[{"field": "Local logins", "text": "Seeded coordinator and volunteer users are listed in this section."}])
ev("gh-0006", "file", f"{R}:.github/pull_request_template.md@main", "read pull request template", {"sections": ["Summary", "Testing", "Jira"]})
ev("gh-0007", "file", f"{R}:package.json@main", "read package.json on the default branch",
   {"framework": "express@4", "test_runner": "jest", "http_test": "supertest", "scripts": ["build", "lint", "test", "dev", "seed", "db:up"], "csv_library": False})
ev("gh-0008", "file", f"{R}:src/routes/events.ts@main", "read src/routes/events.ts",
   {"routes": [{"method": "GET", "path": "/events/:id/signups", "guard": "requireRole('coordinator')", "handler": "signupsPage"}],
    "not_found_helper": "notFound(res)", "loader": "getEvent(id)"})
ev("gh-0009", "file", f"{R}:tests/routes/events.signups.test.ts@main", "read the sign-ups route test",
   {"helper": "loginAs(role)", "helper_file": "tests/helpers/auth.ts", "seeded_events": [1, 2], "setup_file": "tests/setup.ts", "setup_runs": "npm run seed"})
ev("gh-0010", "tags", f"{R}:tags", "list tags and read CHANGELOG.md and CONTRIBUTING.md",
   {"latest_tag": "v2.13.0", "changelog_unreleased_section": True, "feature_release_bumps": "minor"})
ev("gh-0011", "file", f"{R}:docs/user-guide/coordinators/signups.md@main", "read the coordinator guide and docs serving config",
   {"exists": True, "served_at": "/help", "ships_with_deploy": True, "requires_sign_in": False})
ev("gh-0012", "file", f"{R}:src/auth/roles.ts@main", "read src/auth/roles.ts",
   {"requireRole": {"signed_out": "redirect /login", "wrong_role": 403}})
ev("gh-0013", "file", f"{R}:src/db/signups.ts@main", "read src/db/signups.ts",
   {"function": "getSignups(eventId)", "returns": "Signup", "fields": ["firstName", "lastName", "email", "shiftName", "createdAt"]})
ev("gh-0014", "seed", f"{R}:seed", "read seed script structure (counts only)", {"events": [{"id": 1, "signups": 3}, {"id": 2, "signups": 0}]}, sensitivity="count")
ev("jira-0001", "project", "VOL", "read Jira project configuration",
   {"issue_types": ["Epic", "Task"], "labels": True, "story_points_on": ["Task"], "link_types": ["Blocks"], "flagged_field": True},
   sensitivity="config", system="jira", inst="main", skill=JSKILL)
E = {k: v["id"] for k, v in EV.items()}


def step(text, refs=(), from_ev=None):
    return {"text": text, "refs": list(refs), "from_evidence": from_ev}


def task(tid, order, title, kind, role, hours, steps, ac, verify, done, vr_type, vr_text, purpose, prereq=(),
         depends=(), waits=(), access=(), evrefs=(), produces=(), group=None, prod=False, data=False, tests=(), rollback=None, pattern=None):
    return {
        "id": tid, "order": order, "key": f"gw:{PLAN_ID}:{tid}", "phase": tid.split("-")[0], "title": title, "kind": kind,
        "role_key": role, "points": 1, "estimate_hours": hours, "parallel_group": group,
        "depends_on": [{"task": t, "satisfied_by": s} for t, s in depends],
        "waits_on": [{"what": w, "kind": k, "owner_role_key": o} for w, k, o in waits],
        "access": list(access), "evidence_refs": [E[x] for x in evrefs],
        "produces": [{"type": t, "name": n} for t, n in produces],
        "instructions": {"purpose": purpose, "prerequisites": list(prereq), "steps": steps,
                         "acceptance_criteria": ac, "verify": verify, "done_today": done},
        "visible_result": {"type": vr_type, "text": vr_text},
        "production_change": prod, "data_change": data, "test_tasks": list(tests), "rollback_task": rollback,
        "exception": None, "origin": {"pattern": pattern, "rules_checked": []},
    }


REV = ("Portal Maintainer code owner review", "review", "maintainer")
T = []
T.append(task("P0-T01", 1, "Request access for every role in this plan", "setup", "developer", 1.5, [
    step("Open the Access list table in the epic description. It has five lines, A1 to A5."),
    step("Open the access request link in the epic description."),
    step("Submit one request per line, naming the person the epic's role-holders list gives for that role, and paste this task's key into the reason."),
    step("If the form says the person already has that access, note 'already granted' for that line."),
    step("Post one comment on this task with five lines: the access id, then the request reference or 'already granted'."),
    step("If any request is refused, add that to the comment and mention the Program Director."),
], ["All five lines have a request reference or 'already granted'."], ["The comment on this task has five lines, A1 to A5."],
    "The comment is posted. Waiting for grants is tracked on the tasks that need them.", "comment_posted", "Comment listing A1 to A5 with request references",
    "Get every account and permission this plan needs requested on day one, so no one is blocked later.",
    produces=[("access_request", a) for a in ("A1", "A2", "A3", "A4", "A5")], pattern="core.access-request"))
T.append(task("P0-T02", 2, "Set up the portal locally and run the tests", "setup", "developer", 4, [
    step("Install Node 20 and Docker if they are not already installed.", [E["gh-0005"]]),
    step("Clone example-org/volunteer-portal and check out main.", [E["gh-0001"]]),
    step("Run npm ci, then cp .env.example .env.", [E["gh-0005"]], E["gh-0005"]),
    step("Run npm run db:up, then npm run seed.", [E["gh-0005"]], E["gh-0005"]),
    step("Run npm run lint and npm test, and copy the final summary lines.", [E["gh-0007"]]),
    step("Run npm run dev and open http://localhost:3000; sign in with the coordinator from the README's Local logins section.", [E["gh-0005"]]),
    step("Post a comment on this task with the test summary and 'local app runs'."),
], ["npm test passes on a clean checkout of main.", "The app runs locally and the seeded coordinator can sign in."],
    ["The comment shows the passing test summary."], "The comment with the test summary is posted.", "comment_posted", "Comment with the test summary",
    "Prove the developer can build, test and run the portal before any change is made.",
    ["A1 is granted.", "Node 20 and Docker on the developer's machine."], depends=[("P0-T01", "done")],
    waits=[("A1 granted", "access", "maintainer")], access=["A1"], evrefs=["gh-0005", "gh-0007"], pattern="github.local-setup"))
T.append(task("P1-T01", 3, "Add the sign-ups CSV serializer", "build", "developer", 5, [
    step("Run git checkout main, git pull, then git checkout -b feat/signups-csv-serializer."),
    step("Create src/lib/csv.ts exporting toSignupCsv(signups), which takes the Signup list returned by getSignups.", [E["gh-0013"]]),
    step("Write the header row First name,Last name,Email,Shift,Signed up (UTC) and one row per sign-up, with createdAt as ISO 8601 UTC.", [E["gh-0013"]]),
    step("Quote cells per RFC 4180, start the file with a UTF-8 byte-order mark, and prefix any cell starting with =, +, - or @ with an apostrophe."),
    step("Create tests/lib/csv.test.ts with cases for the header, quoting, the formula prefix, an empty list and the byte-order mark.", [E["gh-0007"]]),
    step("Run npm run lint and npm test until both pass.", [E["gh-0007"]]),
    step("Push the branch, open a pull request to main using the template's Summary, Testing and Jira sections, and put this task's Jira key in the title.", [E["gh-0006"]]),
    step("Paste the pull request link into a comment on this task."),
], ["toSignupCsv returns the five columns in order with RFC 4180 quoting and the formula prefix.", "New tests pass and the ci check is green.", "No new dependency is added."],
    ["The ci check on the pull request is green."], "The pull request is open with green CI and review requested, linked on this task.",
    "pr_opened", "PR opened, CI green", "Turn a list of sign-ups into a safe CSV file body, tested on its own before any route uses it.",
    ["P0-T02 is done."], depends=[("P0-T02", "done")], access=["A1"], evrefs=["gh-0013", "gh-0007", "gh-0006"],
    produces=[("function", "toSignupCsv")], pattern="github.code-change"))
T.append(task("P1-T02", 4, "Add the CSV export endpoint", "build", "developer", 5, [
    step("Run git checkout main, git pull, then git checkout -b feat/signups-csv-endpoint."),
    step("Open src/routes/events.ts, find the signups route and read signupsPage: it calls getEvent(id) and returns notFound(res) when the result is null.", [E["gh-0008"]], E["gh-0008"]),
    step("Below that line, add router.get('/events/:id/signups.csv', requireRole('coordinator'), signupsCsv).", [E["gh-0008"], E["gh-0012"]]),
    step("Write signupsCsv next to signupsPage: call getEvent(id) and return notFound(res) if null; then call getSignups(id) and pass the result to toSignupCsv.", [E["gh-0008"], E["gh-0013"], "toSignupCsv"]),
    step("Set Content-Type to text/csv; charset=utf-8 and Content-Disposition to attachment with filename event-<id>-signups-<YYYY-MM-DD>.csv, using today's UTC date."),
    step("Create tests/routes/events.signups-csv.test.ts, copying the setup lines and the loginAs import from tests/routes/events.signups.test.ts.", [E["gh-0009"]]),
    step("Add six tests: coordinator on event 1 gets 200, text/csv, the header row First name,Last name,Email,Shift,Signed up (UTC) and 3 data rows; event 2 returns only the header; event 999 returns 404; volunteer gets 403; signed-out is redirected to /login; the file name header matches the pattern.", [E["gh-0009"], E["gh-0012"], E["gh-0014"]]),
    step("Run npm run lint and npm test until both pass.", [E["gh-0007"]]),
    step("Run npm run db:up, npm run seed and npm run dev; sign in as the README's seeded coordinator, open http://localhost:3000/events/1/signups.csv, check the columns First name, Last name, Email, Shift, Signed up (UTC) in order with 3 rows, then delete the file.", [E["gh-0005"], E["gh-0014"]]),
    step("Push the branch and open a pull request to main with the template's Summary, Testing and Jira sections; put this task's Jira key (like VOL-12) in the title.", [E["gh-0006"], E["gh-0002"]]),
    step("Paste the pull request link into a comment on this task."),
], ["The route returns the plan's five columns in order, for coordinators only.", "Volunteers get 403, signed-out users go to /login, unknown events get 404.",
    "Six new tests pass, the existing suite passes, and the ci check is green.", "No new dependency is added."],
    ["The ci check on the pull request is green, and the local check showed the right columns and row count."],
    "The pull request is open with green CI and review requested, linked on this task. The merge is P1-T03's dependency.",
    "pr_opened", "PR opened, CI green", "Coordinators need to download an event's sign-ups as a file. This task adds the server route that returns the CSV.",
    ["P1-T01 is merged, so toSignupCsv exists in src/lib/csv.ts.", "Your local setup from P0-T02 works."],
    depends=[("P1-T01", "merged")], waits=[REV], access=["A1"],
    evrefs=["gh-0008", "gh-0012", "gh-0013", "gh-0009", "gh-0014"], produces=[("route", "/events/:id/signups.csv")], pattern="github.code-change"))
T.append(task("P1-T03", 5, "Add the Download CSV button", "build", "developer", 4, [
    step("Run git checkout main, git pull, then git checkout -b feat/signups-csv-button."),
    step("Open the sign-ups page template rendered by signupsPage and add a Download CSV link to /events/<id>/signups.csv, shown only to coordinators.", [E["gh-0008"], "/events/:id/signups.csv"]),
    step("Add a test to tests/routes/events.signups.test.ts that the coordinator's page contains the link and the volunteer's does not.", [E["gh-0009"]]),
    step("Run npm run lint and npm test until both pass.", [E["gh-0007"]]),
    step("Run the app locally, sign in as the seeded coordinator, open /events/1/signups and click Download CSV; check a file downloads.", [E["gh-0005"]]),
    step("Push, open a pull request to main with the template sections and this task's Jira key in the title, and link it on this task.", [E["gh-0006"]]),
], ["Coordinators see a Download CSV link on the sign-ups page; others do not.", "Tests pass and the ci check is green."],
    ["The ci check is green and the local click downloaded the file."], "The pull request is open with green CI and review requested, linked on this task.",
    "pr_opened", "PR opened, CI green", "Give coordinators a visible way to download the file from the page they already use.",
    ["P1-T02 is merged."], depends=[("P1-T02", "merged")], waits=[REV], access=["A1"], evrefs=["gh-0008", "gh-0009"],
    produces=[("ui", "Download CSV button")], pattern="github.code-change"))
T.append(task("P1-T04", 6, "Add the CSV section to the coordinator guide", "docs", "developer", 3, [
    step("Run git checkout main, git pull, then git checkout -b docs/signups-csv."),
    step("Open docs/user-guide/coordinators/signups.md and add a section 'Download sign-ups as a CSV': where the button is, the five columns, and the file name.", [E["gh-0011"], "Download CSV button"]),
    step("Add the handling guidance: the file holds volunteers' personal data; delete it after the event and don't forward it."),
    step("Add a line under Unreleased in CHANGELOG.md.", [E["gh-0010"]]),
    step("Push, open a pull request to main with the template sections and this task's Jira key, and link it on this task.", [E["gh-0006"]]),
], ["The guide has the new section with columns, file name and handling guidance.", "The ci check is green."],
    ["Preview the Markdown on the pull request and check the section renders."], "The pull request is open with green CI and review requested, linked on this task.",
    "pr_opened", "PR opened, CI green", "Coordinators need to know the export exists and how to handle the file safely.",
    ["P1-T03 is merged."], depends=[("P1-T03", "merged")], waits=[REV], access=["A1"], evrefs=["gh-0011", "gh-0010"],
    produces=[("doc", "CSV guide section")], pattern="github.docs-change"))
T.append(task("P1-T05", 7, "Test the export on staging", "test", "developer", 3, [
    step("Open the latest staging deploy run in the Actions tab and copy the deployed commit SHA from its summary; check it is main's head after P1-T04's merge.", [E["gh-0004"]]),
    step("Open https://staging.portal.example.org and sign in with the staging coordinator test account (A2).", [E["gh-0004"]]),
    step("Open an event with sign-ups, click Download CSV, and check the columns First name, Last name, Email, Shift, Signed up (UTC) and the file name pattern.", ["Download CSV button"]),
    step("Sign out and open /events/1/signups.csv directly; check you are redirected to /login.", [E["gh-0012"]]),
    step("Open /help and check the coordinator guide shows the new section.", [E["gh-0011"], "CSV guide section"]),
    step("Delete the downloaded file, then post a test record comment on this task: the tested commit SHA and the result of each check."),
], ["Every check passed on staging, or each failure is recorded.", "The comment records the tested commit SHA."],
    ["The comment lists the SHA and each check's result."], "The test record comment with the tested commit is posted.",
    "comment_posted", "Test record comment with the tested commit", "Prove the merged change works on staging before anyone else tests it.",
    ["P1-T04 is merged and deployed to staging.", "A2 is granted."], depends=[("P1-T04", "deployed")],
    waits=[REV, ("A2 granted", "access", "admin")], access=["A1", "A2"], evrefs=["gh-0004", "gh-0012", "gh-0011"],
    produces=[("record", "tested commit")], pattern="github.staging-test"))
T.append(task("P2-T01", 8, "Write the UAT script", "uat", "developer", 2, [
    step("Write five numbered UAT steps a coordinator can follow on staging: open an event, click Download CSV, open the file, check the columns, delete the file.", ["Download CSV button"]),
    step("For each step, write the expected result in one line."),
    step("Add the staging URL https://staging.portal.example.org and the place to record pass or fail.", [E["gh-0004"]]),
    step("Post the script as a comment on this task and mention the Volunteer Coordinator for P2-T02."),
], ["The script has five steps, each with an expected result."], ["The comment holds the full script."], "The script is posted.",
    "comment_posted", "Script posted as a comment", "Give the coordinator a short script so UAT is quick and repeatable.",
    ["P1-T05's test record shows every check passed."], depends=[("P1-T05", "done")], access=["A1"], evrefs=["gh-0004"],
    produces=[("doc", "UAT script")], pattern="core.uat-script"))
T.append(task("P2-T02", 9, "Run UAT on staging", "uat", "business_user", 2, [
    step("Open the UAT script on P2-T01 and https://staging.portal.example.org.", ["UAT script", E["gh-0004"]]),
    step("Sign in with your staging coordinator login (A3) and follow each step, marking pass or fail.", ["UAT script"]),
    step("Delete the downloaded file when done."),
    step("Copy the deployed commit SHA shown in the footer of staging's /help page into your comment.", [E["gh-0011"]]),
    step("Post a sign-off comment on this task: each step's result, the staging commit, and 'approved' or what must change."),
], ["Every step has a pass or fail.", "The comment says approved, or lists what must change."], ["The sign-off comment is on this task."],
    "The sign-off comment is posted.", "comment_posted", "UAT sign-off comment with the staging commit",
    "The people who will use the export confirm it does what they need.", ["P2-T01's script.", "A3 is granted."],
    depends=[("P2-T01", "done")], waits=[("Volunteer Coordinator availability", "availability", "business_user"), ("A3 granted", "access", "admin")],
    access=["A3"], evrefs=["gh-0004"], produces=[("record", "UAT sign-off")], pattern="core.uat-run"))
T.append(task("P2-T03", 10, "Rehearse the rollback on staging and post the runbook", "rollback", "developer", 3, [
    step("Write a runbook comment: to roll back, run the deploy workflow by workflow_dispatch with ref set to the previous tag and environment set to the target.", [E["gh-0004"]], E["gh-0004"]),
    step("Rehearse it on staging: dispatch the deploy workflow with ref v2.13.0 and environment staging, and wait for it to finish.", [E["gh-0004"], E["gh-0010"]]),
    step("Open https://staging.portal.example.org/events/1/signups and check the Download CSV link is gone.", [E["gh-0004"]]),
    step("Restore staging: dispatch the deploy workflow with ref main and environment staging, and check the link is back.", [E["gh-0004"]]),
    step("Copy the deployed commit SHA from that run's summary and add it, with the rehearsal log, to the runbook comment.", [E["gh-0004"]]),
], ["The runbook comment is posted with both rehearsal runs linked.", "Staging runs main again, with its SHA recorded."],
    ["Both run links open successful runs, and staging shows the button."], "The runbook and rehearsal log comment is posted, ending with staging restored.",
    "comment_posted", "Runbook and rehearsal log comment, ending with the staging commit restored",
    "Make sure the team can undo the release quickly if production checks fail.", ["P2-T02's sign-off is posted, so changing staging won't disturb UAT."],
    depends=[("P2-T02", "done")], access=["A1", "A2"], evrefs=["gh-0004", "gh-0010"], produces=[("doc", "rollback runbook")], group="B", pattern="github.rollback-rehearsal"))
T.append(task("P2-T04", 11, "Prepare the release notes", "docs", "developer", 2, [
    step("Run git checkout main, git pull, then git checkout -b docs/release-notes-csv."),
    step("In CHANGELOG.md, rename Unreleased to the new version: raise the middle number of the latest tag by one and set the last to 0 (v2.13.0 becomes v2.14.0).", [E["gh-0010"]], E["gh-0010"]),
    step("Under it, write one line for the export and one for the guide section."),
    step("Push, open a pull request to main with the template sections and this task's Jira key, and link it on this task.", [E["gh-0006"]]),
], ["CHANGELOG.md has the new version heading with the two lines.", "The ci check is green."], ["The pull request diff shows only CHANGELOG.md."],
    "The pull request is open with green CI and review requested, linked on this task.", "pr_opened", "PR opened, CI green",
    "Record what this release contains so the tag and the changelog agree.", ["P2-T02's sign-off is posted."],
    depends=[("P2-T02", "done")], waits=[REV], access=["A1"], evrefs=["gh-0010"], produces=[("doc", "release notes")], group="B", pattern="github.docs-change"))
T.append(task("P3-T01", 12, "Start the production release", "cutover", "developer", 1.5, [
    step("Run git checkout main, git pull, git fetch --tags."),
    step("Copy the tested commit SHA from P1-T05 and run git log --oneline <that SHA>..main. Only the release-notes merge should be listed; if anything else appears, do not tag: comment the list, set this task to Flagged, mention the Program Director, and stop.", ["tested commit"]),
    step("Open the latest staging deploy run and copy the deployed SHA from its summary; it must equal git rev-parse main. If not, handle it as in step 2.", [E["gh-0004"]]),
    step("Work out the new version as in CONTRIBUTING.md (v2.13.0 becomes v2.14.0) and check CHANGELOG.md uses it; if not, handle it as in step 2.", [E["gh-0010"], "release notes"]),
    step("Run git tag -a <new version> -m 'Sign-ups CSV export', then git push origin <new version>.", [E["gh-0004"]]),
    step("Open the Actions tab, find the deploy run for the tag, and confirm it waits for the production environment review.", [E["gh-0004"]]),
    step("Post the run link in the release channel and on this task, and mention the Portal Admin to review the deploy."),
], ["The tag is on the tested commit plus the release-notes merge, and staging runs that same commit.",
    "Or, if extra commits appeared, no tag was pushed and the task is blocked with the list in a comment.",
    "A production deploy run for the tag is waiting for review, and its link is on this task."],
    ["git ls-remote --tags origin <new version> returns the tag, and the run link opens the waiting run."],
    "The tag is pushed and the run waits for the Portal Admin's approval, or the task is blocked with a comment explaining why.",
    "deployed_change", "Comment with tag and deploy run link, or a blocked comment", "Start the production deploy of the version that passed staging tests and UAT.",
    ["P2-T02 sign-off records the staging commit.", "P2-T03 says main was redeployed to staging.", "P2-T04 is merged."],
    depends=[("P2-T03", "done"), ("P2-T04", "merged"), ("P1-T05", "done")], waits=[REV, ("A5 granted", "access", "admin")],
    access=["A1", "A5"], evrefs=["gh-0004", "gh-0010"], produces=[("record", "production deploy run")], prod=True,
    tests=["P1-T05", "P2-T02"], rollback="P2-T03", pattern="github.tag-release"))
T.append(task("P3-T02", 13, "Verify the production release", "cutover", "developer", 1.5, [
    step("Open the deploy run from P3-T01. If it failed, go to step 5.", ["production deploy run"]),
    step("Run curl -sI https://portal.example.org/events/1/signups.csv while signed out and expect a redirect to /login.", [E["gh-0004"], E["gh-0012"]]),
    step("Open https://portal.example.org/help and check the coordinator guide shows the Download sign-ups as a CSV section.", [E["gh-0011"]]),
    step("If both checks pass, comment the results here and mention the Volunteer Coordinator for P3-T03. You are done."),
    step("If the run or a check failed, follow the runbook from P2-T03 to redeploy the previous tag to production, comment what failed, mention the Portal Admin for the second approval, and set this task to Flagged until it is given.", ["rollback runbook"]),
], ["Either both checks passed on the new version, or the rollback was started and recorded."], ["The comment shows the run result and both check results."],
    "The change is live and checked, or the rollback is started with the reason recorded.", "deployed_change", "Deployed change, checks recorded",
    "Confirm the approved deploy worked without touching any volunteer's data, or roll it back.", ["The Portal Admin approved P3-T01's deploy run.", "P2-T03's runbook."],
    depends=[("P3-T01", "done")], waits=[("Portal Admin production deploy approval", "approval", "admin"),
                                          ("Second Portal Admin approval if a rollback is needed", "approval", "admin")],
    access=["A1"], evrefs=["gh-0004", "gh-0011", "gh-0012"], produces=[("record", "production checks")], prod=True,
    tests=["P1-T05", "P2-T02"], rollback="P2-T03", pattern="github.verify-release"))
T.append(task("P3-T03", 14, "Confirm the export in production", "uat", "business_user", 0.5, [
    step("Open https://portal.example.org, sign in with your usual coordinator account, and open one of your events' sign-ups pages.", [E["gh-0004"]]),
    step("Click Download CSV and check the file opens with the five columns.", ["Download CSV button"]),
    step("Delete the file, then comment 'confirmed' on this task, or what went wrong."),
], ["The coordinator confirms the export works in production."], ["The confirmation comment is on this task."], "The confirmation comment is posted.",
    "comment_posted", "Confirmation comment", "The people who use the export confirm it works for real.", ["P3-T02 reports both checks passed."],
    depends=[("P3-T02", "done")], waits=[("Volunteer Coordinator availability", "availability", "business_user")], evrefs=["gh-0004"], pattern="core.prod-confirm"))
T.append(task("P3-T04", 15, "Announce the export to coordinators", "comms", "comms", 1.5, [
    step("Open https://portal.example.org/help and copy the link to the Download sign-ups as a CSV section.", [E["gh-0011"]]),
    step("Write an announcement of no more than 150 words: what's new, the guide link, and the handling guidance (delete the file after the event, don't forward it)."),
    step("Post it in the announcements channel named in the epic. Discovery did not inspect that channel; if you can't post there, comment here and mention the Program Director."),
    step("Paste the announcement link into a comment on this task."),
], ["The announcement is posted, links to the guide section, and includes the handling guidance."], ["The link on this task opens the posted announcement."],
    "The announcement is posted and linked.", "comment_posted", "Announcement link comment",
    "Tell coordinators the export exists, where the guide is, and how to handle a file that holds volunteers' personal data.",
    ["P3-T03 confirms the export works in production."], depends=[("P3-T03", "done")], waits=[("A4 granted", "access", "admin")],
    access=["A4"], evrefs=["gh-0011"], pattern="core.announcement"))
T.append(task("P3-T05", 16, "Hand off to the portal maintainers", "handoff", "developer", 2, [
    step("Write a handoff note: what shipped (the route, button and guide section), where the tests live, the rollback runbook link, and known limits (no enforced deletion).", ["/events/:id/signups.csv", "rollback runbook"]),
    step("Post it as a comment on this task and mention the Portal Maintainers.", [E["gh-0002"]]),
], ["The note covers what shipped, tests, rollback and known limits."], ["The comment is on this task with the maintainers mentioned."],
    "The handoff note is posted.", "comment_posted", "Handoff note comment", "Leave the maintainers everything they need to own the feature.",
    ["P3-T02 reports the release is live."], depends=[("P3-T02", "done")], access=["A1"], evrefs=["gh-0002"], pattern="core.handoff"))

access_list = [
    {"id": "A1", "role_key": "developer", "system": "github", "instance": "gh", "level": "write on example-org/volunteer-portal (Actions and tag push)"},
    {"id": "A2", "role_key": "developer", "system": "github", "instance": "gh", "level": "coordinator test account on staging"},
    {"id": "A3", "role_key": "business_user", "system": "github", "instance": "gh", "level": "coordinator login on staging"},
    {"id": "A4", "role_key": "comms", "system": "channels", "instance": "announcements", "level": "post in the announcements channel"},
    {"id": "A5", "role_key": "developer", "system": "channels", "instance": "release", "level": "post in the release channel"},
]
for a in access_list:
    a["needed_by"] = sorted(t["id"] for t in T if a["id"] in t["access"])

phases = [
    {"id": "P0", "order": 0, "name": "Setup", "goal": "Every access request is in and the portal runs locally.", "state": "drafted", "depends_on": [], "task_ids": ["P0-T01", "P0-T02"]},
    {"id": "P1", "order": 1, "name": "Build and staging test", "goal": "The export, button and guide are merged and tested on staging.", "state": "drafted", "depends_on": ["P0"], "task_ids": [t["id"] for t in T if t["phase"] == "P1"]},
    {"id": "P2", "order": 2, "name": "UAT and release prep", "goal": "Coordinators sign off and the rollback and release notes are ready.", "state": "drafted", "depends_on": ["P1"], "task_ids": [t["id"] for t in T if t["phase"] == "P2"]},
    {"id": "P3", "order": 3, "name": "Release and handoff", "goal": "The export is live, confirmed, announced and handed off.", "state": "drafted", "depends_on": ["P2"], "task_ids": [t["id"] for t in T if t["phase"] == "P3"]},
]

plan = {
    "schema_version": "1.0", "id": PLAN_ID, "version": 1, "status": "draft",
    "overlay": {"id": "example-org", "version": 1, "hash": ZERO},
    "title": "CSV export of event sign-ups",
    "request": {"original_text": "Create project: let coordinators download an event's sign-ups as a CSV.",
                "restatement": "Add a coordinator-only CSV download of an event's sign-ups to the volunteer portal, with docs, UAT, release and handoff.",
                "clarifications": [
                    {"id": "C-1", "question": "Which columns, in what order?", "answer": "First name, Last name, Email, Shift, Signed up (UTC), ISO 8601 UTC.", "answered_by": "acct-program-director", "at": AT},
                    {"id": "C-2", "question": "Who may export which events?", "answer": "Any coordinator, any event, as for the sign-ups page today.", "answered_by": "acct-program-director", "at": AT},
                    {"id": "C-3", "question": "File format details?", "answer": "UTF-8 with BOM, comma-separated, RFC 4180 quoting, formula prefix on =, +, -, @.", "answered_by": "acct-program-director", "at": AT},
                    {"id": "C-4", "question": "Database changes or deletion enforcement?", "answer": "No database change; handling guidance only.", "answered_by": "acct-program-director", "at": AT},
                    {"id": "C-5", "question": "Does the announcement need review?", "answer": "No.", "answered_by": "acct-program-director", "at": AT},
                ]},
    "scope": {"in": ["CSV serializer, route and button", "Coordinator guide section", "Staging test, UAT, release, rollback, announcement and handoff"],
              "out": ["Enforcing file deletion", "Database changes", "Exports for non-coordinators"],
              "assumptions": [{"text": "Docs ship with each deploy because the app serves docs/user-guide at /help.", "basis": E["gh-0011"]}]},
    "epic": {"key": f"gw:{PLAN_ID}:epic", "tracker_ref": None, "title": "CSV export of event sign-ups",
             "summary": "Coordinators can download an event's sign-ups as a CSV from the sign-ups page, documented, tested, released and handed off.", "links": []},
    "executor": {"profile": "junior_no_context", "working_day_hours": 6},
    "open_questions": [],
    "coverage": [
        {"system": "github", "instance": "gh", "skill": "groundwork-system-github", "skill_version": "1.0.0", "surface": "claude-code-local",
         "status": "inspected", "read_only": "enforced", "inspected": ["repo settings", "workflows", "environments", "source files", "tags"],
         "not_inspected": ["release and announcements channels"], "reason": ""},
        {"system": "jira", "instance": "main", "skill": "groundwork-tracker-jira", "skill_version": "1.0.0", "surface": "claude-code-local",
         "status": "partial", "read_only": "enforced", "inspected": ["project VOL configuration"], "not_inspected": ["issues"],
         "reason": "Configuration only; issues are not needed for planning."},
    ],
    "access_list": access_list, "phases": phases, "tasks": T,
    "standard_work": [
        {"kind": "test", "tasks": ["P1-T01", "P1-T02", "P1-T05"], "not_applicable_reason": None},
        {"kind": "uat", "tasks": ["P2-T02"], "not_applicable_reason": None},
        {"kind": "cutover", "tasks": ["P3-T01", "P3-T02"], "not_applicable_reason": None},
        {"kind": "rollback", "tasks": ["P2-T03"], "not_applicable_reason": None},
        {"kind": "docs", "tasks": ["P1-T04"], "not_applicable_reason": None},
        {"kind": "handoff", "tasks": ["P3-T05"], "not_applicable_reason": None},
    ],
    "review": {"validator": None, "reviewer": None},
    "approvals": [],
    "stamps": {"release": "unreleased", "core": "groundwork-core@1.0.0", "contract": "1.0", "plan_format": "1.0",
               "skills": [{"name": "groundwork-system-github", "version": "1.0.0", "verified": "unverified"},
                          {"name": "groundwork-tracker-jira", "version": "1.0.0", "verified": "unverified"}],
               "overlay": {"id": "example-org", "version": 1, "hash": ZERO, "format": "1.0"},
               "validator": "1.0.0", "surface": "claude-code-local", "model": "unknown", "compat": []},
    "history": [{"version": 1, "at": AT, "change": "drafted", "by": "groundwork-core"}],
}


def main():
    from gw_hash import item_hash as ih
    ov = dict(overlay)
    ov["hash"] = None
    ov["hash"] = ih({k: v for k, v in ov.items()})  # hash of the file without its hash field
    plan["overlay"]["hash"] = ov["hash"]
    plan["stamps"]["overlay"]["hash"] = ov["hash"]
    os.makedirs(os.path.join(OUT, "overlay"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "evidence"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "expected"), exist_ok=True)
    with open(os.path.join(OUT, "overlay", "overlay.yaml"), "w") as f:
        f.write("# Golden project G1 overlay (fictional org; reserved example domains only)\n")
        f.write(gw_yaml.dumps(ov))
    for label, item in EV.items():
        with open(os.path.join(OUT, "evidence", f"{label}.json"), "w") as f:
            json.dump(item, f, indent=2)
            f.write("\n")
    with open(os.path.join(OUT, "expected", "plan.json"), "w") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(OUT, "request.md"), "w") as f:
        f.write("Create project: let coordinators download an event's sign-ups as a CSV.\n")
    print("G1 written:", len(T), "tasks,", len(EV), "evidence items")


if __name__ == "__main__":
    main()
