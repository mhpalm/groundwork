<!-- SPDX-License-Identifier: Apache-2.0 -->
# Plan format (1.0)

The plan is one JSON document, `plan.json`, validated against `groundwork-core/schemas/plan.schema.json`. Everything a person reads (the proposal, the snapshot, the tracker items) is rendered from it by a script, so wording can vary between runs but structure cannot. Every persisted file (plan, evidence item, approval, journal line, manifest) starts with `schema_version`, and all hashes are SHA-256 over RFC 8785 canonical JSON, computed by `scripts/`, never by the model. The schema is shown as YAML for readability.

## Schema

```yaml
plan:
  schema_version: "1.0"
  id: gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC   # ULID made at Intake; never reused
  version: 3                          # +1 on every change after the first proposal
  status: draft | in_review | proposed | active | revising | complete
  overlay: {id, version, hash}        # the overlay this plan is bound to
  title: string
  request:
    original_text: string
    restatement: string               # confirmed by the runner at Intake
    clarifications: [{id, question, answer, answered_by, at}]
  scope: {in: [string], out: [string], assumptions: [{text, basis: evidence id | clarification id}]}
  epic:
    key: gw:<plan.id>:epic
    tracker_ref: string | null        # set when the draft epic is created
    title: string
    summary: string
    links: [{relation: precedes | follows | relates, epic_ref}]
  executor: {profile: string, working_day_hours: number}   # copied from the overlay
  starting_point:                   # inside request (D-55)
    kind: from_scratch | extends_existing
    resources: [{id: R1, name, kind: code | pipeline | doc | ticket | system_object | other, location, inspected: [evidence ids], not_inspected_reason}]
  open_questions: [{id: Q-1, text, blocks: [task or phase ids], status: open | answered, answer, answered_by, at}]
  coverage: [{system, instance, skill, skill_version, surface, status: inspected | partial | not_inspected,
              read_only: enforced | instructed_only, inspected: [string], not_inspected: [string], reason}]
  access_list: [{id: A1, role_key, system, instance, level, needed_by: [task ids]}]   # derived, never typed
  phases:
    - id: P1                          # append-only, never renumbered or reused
      order: 1
      name: string
      goal: string
      state: outline | drafted | reviewed | approved | writing | released
      depends_on: [phase ids]
      task_ids: [task ids]
  tasks:
    - id: P1-T03                      # append-only: a split or insert takes the next free number
      order: 3                        # display order, may change
      key: gw:<plan.id>:P1-T03        # idempotency key, stable for the life of the epic
      phase: P1
      title: string
      changes_existing: {resources: [R ids], why_needed, could_break: [..], regression_check: [test or uat task ids]} | null
      work_type: story | task          # story: user-facing value; task: everything else
      kind: setup | design | build | config | data | test | uat | cutover | rollback | docs | training | comms | signoff_prep | handoff
      role_key: generic role key      # name looked up in the overlay at render time
      points: 1
      estimate_hours: number          # > 0 and <= executor.working_day_hours unless exception
      parallel_group: string
      depends_on: [{task, satisfied_by: done | merged | deployed}]
      waits_on: [{what, kind: approval | review | merge | vendor | job | access | availability, owner_role_key}]
      access: [access_list ids]
      evidence_refs: [evidence ids]
      produces: [{type, name}]         # things this task creates that later tasks may reference
      instructions:
        purpose: string
        prerequisites: [string]
        steps: [{text, refs: [evidence ids or produces names], from_evidence: evidence id | null}]
        acceptance_criteria: [string]
        verify: [string]
        done_today: string
      visible_result: {type: pr_opened | merged_pr | deployed_change | record_created | record_updated | doc_submitted | comment_posted, text}
      production_change: boolean
      data_change: boolean
      test_tasks: [task ids]          # required when production_change
      rollback_task: task id          # required when production_change or data_change
      exception: null | {id, reason, days, checkpoints: [{day, visible_result}]}
      origin: {pattern, rules_checked: [rule ids]}
  standard_work: [{kind: test | uat | cutover | rollback | docs | handoff, tasks: [task ids], not_applicable_reason}]
  review: {validator: {version, passed, results}, reviewer: {surface, view_hash, independent, findings: [finding]}}
  approvals: [approval ids]           # records live in the tracker; ids here for reference
  stamps: stamps
  history: [{version, at, change, by}]
```

## Field rules that matter most

- `points` is always 1. If a person later sets a larger value in the tracker, revise and release keep it and propose a split in a comment.
- `estimate_hours` is for the overlay's assumed executor, not an expert, and is recorded so estimate-versus-actual can be added later (out of scope for v1).
- `visible_result` must be something the executor can produce alone, today. Anything that needs another person (a review, a merge, an approval) goes in `waits_on` of this task or `depends_on` of the next one.
- `depends_on.satisfied_by` says what the next task needs: the earlier task done, its PR merged, or its change deployed. The tracker shows the dependency as blocking until that state is reached.
- `request.starting_point` records the runner's answer to "does anything already exist that this builds on?" (D-55). Each existing resource is inspected read-only through a system skill, recorded from a document the runner supplied, or marked not inspected with the reason.
- A task that changes an existing resource sets `changes_existing`: why the change is needed (nothing existing already does it), what it could break, and the test or UAT task that checks for that breakage. A task that only adds something new leaves it null.
- `work_type` is `story` when the task delivers something a user of the product can see or use, and `task` for everything else (setup, config, tests, docs, release, comms). It sets the tracker item type. A story is still one task: 1 point, one day. There is no level between the epic and its tasks.
- Each phase is released as one release container in the tracker (a Jira fix version, a GitHub milestone, or a label), named `<epic title> <phase id> <phase name>` and created by an `ensure_release` write before the phase's first item.
- `waits_on` is how waiting is tracked. It is never a task; it shows as blocked in the tracker until cleared.
- `instructions.steps` become a checklist inside the task, or sub-tasks if the overlay chose `subtasks`. Sub-tasks carry no points and no estimate.
- Every name a step relies on (a file, command, field, environment, URL) is listed in that step's `refs`, pointing at evidence or at an earlier task's `produces`. A step copied from text found in a system carries `from_evidence`; the proposal lists those steps so the approver sees which commands came from the org's own files.
- `access_list` is derived from every task's `access`. P0 must request every line for drafted phases.
- Task and phase ids are append-only. Revise never renumbers; a split closes the old task and creates new ids.

## Discovery evidence

Every fact the plan relies on is an evidence item in `evidence/`, validated against `evidence.schema.json` and the producing skill's `evidence_types`.

```yaml
- schema_version: "1.0"
  id: ev-github-gh-3f9a12c0            # platform, instance, 8 hex of the subject
  run_id: gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC
  overlay_id: example-org
  system: github
  instance: gh
  skill: groundwork-system-github@1.2.0
  surface: claude-code-local
  method: "read package.json on the default branch"
  collected_at: 2026-11-14T19:02:11Z
  recheck: false
  subject: {type: file, name: "example-org/volunteer-portal:package.json@main"}
  facts: {scripts: [build, lint, test, dev, seed, db_up], test_runner: jest, framework: express}
  untrusted_text: []                   # any other free text copied from the system
  sensitivity: structure | config | count | restricted
  hash: sha256 of the item without this field
```

Evidence holds structure, configuration and counts only. Counts are never grouped by a field that identifies a person or a payment. Credentials, tokens and passwords are never recorded, even fixture passwords found in a README. `restricted` marks security-relevant configuration (protection rules, reviewer identities, secret names); restricted facts are used by the reviewer but rendered into proposals and snapshots only as a yes/no or a count.

**Evidence bundles.** A discovery-only run in local Claude Code can export `evidence/` with a manifest (run id, overlay id and hash, instance URLs, item hashes, collection time). Importing a bundle checks that the overlay id and instances match the current run and that items are within `evidence_max_age_days` (overlay, default 7). Imported items keep their original `surface`.

## Approval record

```yaml
- schema_version: "1.0"
  id: A-1
  kind: initial | release | revision
  plan_id: gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC
  plan_version: 3
  plan_hash: sha256 of canonical plan.json without approvals and history
  plan_store_ref: "<plan.id>-v3-plan"
  phases: [P0, P1]
  phase_hashes: {P0: sha256, P1: sha256}
  write_list_hash: sha256 of the numbered write list shown with the offer
  proposal_hash: sha256 of the rendered proposal
  review_hash: sha256 of the reviewer's findings
  view_hash: sha256 of the reviewer view
  accept_unverified_writer: boolean
  gate: overlay gate id
  approver: {account_id, name}        # account id is the tracker's immutable user id
  minors_accepted: [finding ids]
  exceptions_accepted: [exception ids]
  artifact: {tracker_comment_ref, author_account_id, verified_at}
```

The approval is valid only as a comment on the epic authored by the approver's own tracker account, containing this record. Create verifies through the tracker's API, before writing anything, that the comment's author id is on the gate and that the comment was never edited (approval-create.md). Each approver posts their own record; quorum and exceptions are in approval-create.md.

## Version stamps

```yaml
stamps:
  release: v1.4.0                     # repo release tag
  core: groundwork-core@1.0.0
  contract: "1.0"
  plan_format: "1.0"
  skills: [{name: groundwork-system-github, version: 1.2.0, verified: verified}, {name: groundwork-tracker-jira, version: 1.0.1, verified: unverified}]
  overlay: {id: example-org, version: 4, hash: sha256, format: "1.0"}
  validator: 1.0.0
  surface: claude-code-local
  model: model id as the surface reports it, or "unknown"
  compat: [handshake check results]
```

Every rendered artifact (proposal, snapshot, epic description) prints the stamps in a footer.

## Worked example: CSV export of event sign-ups

This example is fictional, uses only v1 skills (GitHub system skill, Jira Cloud tracker skill), and is golden project G1. The org is "Example Org". Its overlay sets a 6-hour day, a junior developer with no access to the original team as the executor, the `checklist` hierarchy, and roles Developer (`developer`), Portal Maintainer (`maintainer`), Portal Admin (`admin`, the `production` environment reviewer), Volunteer Coordinator (`business_user`), Comms Lead (`comms`) and Program Director (`approver`). Its `role_holders` name who fills each role, and its `tracker_access_assumed` is true, so every role holder can already open and comment on VOL issues. Its access-request process lets any team member request access for any role. In the tasks below, "mention the Program Director" (or any role) means mention the holder `role_holders` lists for that role.

**Request.** "Create project: let coordinators download an event's sign-ups as a CSV."

**Settled in Clarify.**

- Columns, in order: First name, Last name, Email, Shift, Signed up (UTC). Signed-up time is ISO 8601 in UTC.
- Any coordinator may export any event, exactly as any coordinator can view any event's sign-ups page today.
- File: UTF-8 with a byte-order mark, comma-separated, RFC 4180 quoting. Any cell starting with `=`, `+`, `-` or `@` gets a leading apostrophe so spreadsheets don't run it as a formula.
- File name: `event-<id>-signups-<YYYY-MM-DD>.csv`.
- No database change. Handling guidance (delete the file after the event, don't forward it) goes in the coordinator guide and the announcement; enforcing deletion is out of scope.
- The announcement needs no review.

**Evidence used.** GitHub instance `gh` inspected from local Claude Code with `read_only: enforced` (fine-grained read-only token). Jira instance `main` inspected for configuration only. Ids are shown as short labels here; real ids are derived from each subject.

| Id | Fact |
| --- | --- |
| gh-0001 | Repo `example-org/volunteer-portal`, default branch `main`; protection requires 1 approving review including a code owner, and the `ci` check; no tag protection rules |
| gh-0002 | `CODEOWNERS`: `* @example-org/portal-maintainers` |
| gh-0003 | `ci.yml` runs `npm ci`, `npm run lint`, `npm run db:up`, `npm run seed`, `npm test` on every pull request |
| gh-0004 | `deploy.yml`: push to `main` deploys to `staging` (environment URL `https://staging.portal.example.org`); each run's summary shows the deployed commit SHA; tags matching `v*` deploy to `production` (environment URL `https://portal.example.org`); `production` requires 1 environment reviewer (restricted: identity not recorded); `workflow_dispatch` takes `ref` and `environment` to redeploy any ref |
| gh-0005 | README: Node 20; `npm ci`; `cp .env.example .env`; `npm run db:up` (Docker Postgres); `npm run seed`; `npm run dev` on port 3000; section "Local logins" documents seeded coordinator and volunteer users (credentials not recorded) |
| gh-0006 | Pull request template with sections Summary, Testing, Jira |
| gh-0007 | `package.json`: Express 4, Jest with supertest, scripts build, lint, test, dev, seed, db:up; no CSV library |
| gh-0008 | `src/routes/events.ts`: `router.get('/events/:id/signups', requireRole('coordinator'), signupsPage)`; the handler calls `getEvent(id)` and returns `notFound(res)` when it is null |
| gh-0009 | `tests/routes/events.signups.test.ts` uses `loginAs(role)` from `tests/helpers/auth.ts` and reads events 1 and 2 from the seeded test database (`tests/setup.ts` runs `npm run seed` before the suite) |
| gh-0010 | Latest tag `v2.13.0`; `CHANGELOG.md` keeps an "Unreleased" section; `CONTRIBUTING.md` says a release with a new feature raises the middle version number and sets the last to 0 |
| gh-0011 | `docs/user-guide/coordinators/signups.md` exists; the app serves `docs/user-guide` at `/help`, so docs ship with each deploy; `/help` needs no sign-in |
| gh-0012 | `src/auth/roles.ts`: `requireRole` redirects signed-out users to `/login` and returns 403 to signed-in users without the role |
| gh-0013 | `src/db/signups.ts`: `getSignups(eventId)` returns `Signup {firstName, lastName, email, shiftName, createdAt: Date}` |
| gh-0014 | Seed data: event 1 with 3 sign-ups, event 2 with none |
| jira-0001 | Project VOL: Epic and Task types, labels on, Story Points on Task, link type Blocks, Flagged field available |

Coverage: GitHub `gh` inspected; Jira `main` configuration only. The release and announcements channels named in the overlay were not inspected; tasks that post there say so. No other system is in scope.

**Phases and tasks.** Every task is 1 point and within 6 hours. "after X merged" means `depends_on` with `satisfied_by: merged`; every merge waits on a Portal Maintainer review, recorded in `waits_on`. A Jira key looks like `VOL-12`.

| Task | Title | Role | Hours | Depends on | Visible result |
| --- | --- | --- | --- | --- | --- |
| P0-T01 | Request access for every role in this plan | Developer | 1.5 | none | Comment listing A1 to A5 with request references |
| P0-T02 | Set up the portal locally and run the tests | Developer | 4 | waits on A1 | Comment with the test summary |
| P1-T01 | Add the sign-ups CSV serializer | Developer | 5 | P0-T02 | PR opened, CI green |
| P1-T02 | Add the CSV export endpoint | Developer | 5 | P1-T01 merged; waits on maintainer review | PR opened, CI green |
| P1-T03 | Add the Download CSV button | Developer | 4 | P1-T02 merged; waits on maintainer review | PR opened, CI green |
| P1-T04 | Add the CSV section to the coordinator guide | Developer | 3 | P1-T03 merged; waits on maintainer review | PR opened, CI green |
| P1-T05 | Test the export on staging | Developer | 3 | P1-T04 merged and deployed to staging; waits on maintainer review and A2 | Test record comment with the tested commit |
| P2-T01 | Write the UAT script | Developer | 2 | P1-T05 | Script posted as a comment |
| P2-T02 | Run UAT on staging | Volunteer Coordinator | 2 | P2-T01; waits on availability and A3 | UAT sign-off comment with the staging commit |
| P2-T03 | Rehearse the rollback on staging, restore `main`, and post the runbook | Developer | 3 | P2-T02 | Runbook and rehearsal log comment, ending with the staging commit restored |
| P2-T04 | Prepare the release notes | Developer | 2 | P2-T02 | PR opened, CI green |
| P3-T01 | Start the production release | Developer | 1.5 | P2-T03, P2-T04 merged; waits on maintainer review and A5 | Comment with tag and deploy run link, or a blocked comment |
| P3-T02 | Verify the production release | Developer | 1.5 | P3-T01; waits on Portal Admin deploy approval, and on a second Portal Admin approval if a rollback is needed | Deployed change, checks recorded |
| P3-T03 | Confirm the export in production | Volunteer Coordinator | 0.5 | P3-T02; waits on availability | Confirmation comment |
| P3-T04 | Announce the export to coordinators | Comms Lead | 1.5 | P3-T03; waits on A4 | Announcement link comment |
| P3-T05 | Hand off to the portal maintainers | Developer | 2 | P3-T02 | Handoff note comment |

Standard work: testing in P1-T01, P1-T02 and P1-T05; UAT in P2-T02; rollback in P2-T03; cutover in P3-T01 and P3-T02; docs in P1-T04; handoff in P3-T05. P2-T03 and P2-T04 run in parallel group B. They wait for UAT so that nothing changes staging while the coordinator is testing; P2-T03 ends by redeploying `main` to staging, and P2-T02 and P3-T01 both record the staging commit so the release can be compared with what was tested. P0 has 2 tasks, so GR-20 (task count only) raises a minor finding, which the approver accepts. P0-T02 also needs Node 20 and Docker on the developer's machine; it lists them as prerequisites and A1 covers the repo.

Elapsed time is longer than task count: P1-T02 to P1-T05 and P3-T01 each wait on a merge, so the plan holds five review round trips. The proposal shows this as "review waits on the critical path: 5".

**Access list (derived).**

| Id | Role | Access | Needed by |
| --- | --- | --- | --- |
| A1 | Developer | Write on `example-org/volunteer-portal` (includes Actions and tag push) | P0-T02 to P3-T05 |
| A2 | Developer | Coordinator test account on staging | P1-T05, P2-T03 |
| A3 | Volunteer Coordinator | Coordinator login on staging | P2-T02 |
| A4 | Comms Lead | Post in the overlay's announcements channel | P3-T04 |
| A5 | Developer | Post in the overlay's release channel | P3-T01 |

Jira access is not listed: the overlay's `tracker_access_assumed` says every role holder can already comment on VOL issues.

Production needs no new access: the coordinator uses their existing account, and the deploy approval is given by the Portal Admin, the existing `production` environment reviewer named in `role_holders`.

Five tasks are shown in full below.

#### P0-T01 Request access for every role in this plan

- **Purpose:** Get every account and permission this plan needs requested on day one, so no one is blocked later.
- **Prerequisites:** None.
- **Access needed:** The Jira project for this epic.
- **Steps:**
  1. Open the "Access list" table in the epic description. It has five lines, A1 to A5.
  2. Open the access request link in the epic description.
  3. Submit one request per line, naming the person the epic's role-holders list gives for that role and pasting this task's key into the reason.
  4. If the form says the person already has that access, note "already granted" for that line.
  5. Post one comment on this task with five lines: the access id, then the request reference or "already granted".
  6. If any request is refused, add that to the comment and mention the Program Director.
- **Acceptance criteria:**
  - All five lines have a request reference or "already granted".
- **How to verify:** The comment on this task has five lines, A1 to A5.
- **Done today:** The comment is posted. Waiting for grants is tracked on the tasks that need them.

#### P1-T02 Add the CSV export endpoint

- **Purpose:** Coordinators need to download an event's sign-ups as a file. This task adds the server route that returns the CSV; the button comes in P1-T03.
- **Prerequisites:** P1-T01 is merged, so `toSignupCsv(signups)` exists in `src/lib/csv.ts`. Your local setup from P0-T02 works.
- **Access needed:** A1.
- **Steps:**
  1. Run `git checkout main`, `git pull`, then `git checkout -b feat/signups-csv-endpoint`.
  2. Open `src/routes/events.ts`. Find the line `router.get('/events/:id/signups', requireRole('coordinator'), signupsPage)` and read `signupsPage`: it calls `getEvent(id)` and returns `notFound(res)` when the result is null.
  3. Below that line, add `router.get('/events/:id/signups.csv', requireRole('coordinator'), signupsCsv)`.
  4. Write `signupsCsv` next to `signupsPage`: call `getEvent(id)` and return `notFound(res)` if null, exactly as `signupsPage` does; then call `getSignups(id)` from `src/db/signups.ts` and pass the result to `toSignupCsv`.
  5. Before sending, set `Content-Type` to `text/csv; charset=utf-8` and `Content-Disposition` to `attachment; filename="event-<id>-signups-<YYYY-MM-DD>.csv"`, using today's date in UTC.
  6. Create `tests/routes/events.signups-csv.test.ts`. Copy the setup lines from `tests/routes/events.signups.test.ts`, including the `loginAs` import.
  7. Add six tests: `loginAs('coordinator')` on event 1 gets 200, `text/csv`, the header row `First name,Last name,Email,Shift,Signed up (UTC)`, and 3 data rows (the seeded test database has 3 sign-ups on event 1); event 2 returns only the header row; event 999 returns 404; `loginAs('volunteer')` gets 403; a signed-out request is redirected to `/login`; the file name header matches the pattern.
  8. Run `npm run lint` and `npm test`. Fix anything that fails until both pass.
  9. Run `npm run db:up`, `npm run seed` and `npm run dev`. Sign in with the coordinator from the README's "Local logins" section and open `http://localhost:3000/events/1/signups.csv`. Open the file in a spreadsheet app and check the columns are First name, Last name, Email, Shift, Signed up (UTC), in that order, with 3 rows. Delete the file.
  10. Push the branch and open a pull request to `main`. Fill in the template's Summary, Testing and Jira sections; put this task's Jira key (like `VOL-12`) in the title. Code owner review is requested automatically.
  11. Paste the pull request link into a comment on this task.
- **Acceptance criteria:**
  - The route returns the plan's five columns in order, for coordinators only.
  - Volunteers get 403, signed-out users go to `/login`, unknown events get 404.
  - Six new tests pass, the existing suite passes, and the `ci` check is green.
  - No new dependency is added.
- **How to verify:** The `ci` check on the pull request is green, and step 9 showed the right columns and row count.
- **Done today:** The pull request is open with green CI and review requested, linked on this task. The merge is P1-T03's dependency, not part of this task.

#### P3-T01 Start the production release

- **Purpose:** Start the production deploy of the version that passed staging tests and UAT.
- **Prerequisites:** P2-T02 has a UAT sign-off comment that records the staging commit. P2-T03 has the runbook comment and says `main` was redeployed to staging. P2-T04's release-notes pull request is merged.
- **Access needed:** A1 and A5.
- **Steps:**
  1. Run `git checkout main`, `git pull`, `git fetch --tags`.
  2. Open P1-T05's test record and copy the tested commit SHA. Run `git log --oneline <that SHA>..main`. The only commit listed should be the release-notes merge from P2-T04. If anything else appears, do not tag. Comment here with the list, set this task to blocked (Flagged), mention the Program Director, and stop: the extra commits need a staging retest the Program Director decides on, and this task's result today is the blocked comment.
  3. Open the latest `staging` deploy run in the Actions tab and copy the deployed commit SHA from its summary. It must equal `main`'s current head (`git rev-parse main`). If not, handle it as in step 2.
  4. Run `git tag --list 'v*' --sort=-v:refname | head -1` to see the latest tag. `CONTRIBUTING.md` says a feature release raises the middle number by one and sets the last to 0 (for example, `v2.13.0` becomes `v2.14.0`). Check that the heading P2-T04 added to `CHANGELOG.md` uses the same version. If not, handle it as in step 2.
  5. Run `git tag -a <new version> -m "Sign-ups CSV export"`, then `git push origin <new version>`.
  6. Open the repo's Actions tab and find the deploy run for the new tag. Confirm it shows as waiting for the `production` environment review.
  7. Post the run link in the release channel and in a comment on this task, and mention the Portal Admin to review the deploy.
- **Acceptance criteria:**
  - The tag exists on the commit P1-T05 tested plus the release-notes merge, and staging runs that same commit.
  - Or, if extra commits appeared, no tag was pushed and the task is blocked with the list in a comment.
  - A production deploy run for the tag is waiting for review, and its link is on this task.
- **How to verify:** `git ls-remote --tags origin <new version>` returns the tag, and the run link opens the waiting run.
- **Done today:** The tag is pushed and the run is waiting for the Portal Admin's approval, which is P3-T02's `waits_on`. Or the task is blocked with a comment explaining why.

#### P3-T02 Verify the production release

- **Purpose:** Confirm the approved deploy worked, without touching any volunteer's data, or roll it back.
- **Prerequisites:** The deploy run from P3-T01 has been approved by the Portal Admin. P2-T03's runbook.
- **Access needed:** A1.
- **Steps:**
  1. Open the deploy run from P3-T01. If it failed, go to step 5.
  2. Run `curl -sI https://portal.example.org/events/1/signups.csv` while signed out. Expect a redirect to `/login`. This proves the route exists without exposing data.
  3. Open `https://portal.example.org/help` and check the coordinator guide shows the new "Download sign-ups as a CSV" section.
  4. If steps 2 and 3 pass, comment here with both results and mention the Volunteer Coordinator for P3-T03. You are done.
  5. If the run failed or a check failed, follow the runbook from P2-T03 to redeploy the previous tag to production, then comment here with what failed. The redeploy needs a second Portal Admin approval: mention the Portal Admin and set this task to blocked until it is given. This wait is already in this task's `waits_on`.
- **Acceptance criteria:**
  - Either both checks passed on the new version, or the rollback was started and recorded.
- **How to verify:** The comment on this task shows the run result and both check results.
- **Done today:** The change is live and checked, or the rollback is started with the reason recorded.

#### P3-T04 Announce the export to coordinators

- **Purpose:** Tell coordinators the export exists, where the guide is, and how to handle a file that holds volunteers' personal data.
- **Prerequisites:** P3-T03 confirms the export works in production.
- **Access needed:** A4. Commenting on VOL issues is covered by `tracker_access_assumed`.
- **Steps:**
  1. Open `https://portal.example.org/help` and copy the link to the "Download sign-ups as a CSV" section.
  2. Write an announcement of no more than 150 words: what's new, the guide link, and the handling guidance from the guide (delete the file after the event, don't forward it).
  3. Post it in the announcements channel named in the epic. Discovery did not inspect that channel; if you can't post there, comment here and mention the Program Director.
  4. Paste the announcement link into a comment on this task.
- **Acceptance criteria:**
  - The announcement is posted, links to the guide section, and includes the handling guidance.
- **How to verify:** The link on this task opens the posted announcement.
- **Done today:** The announcement is posted and linked.

## Conventions the validator relies on

- **Access requests.** Each `access_list` line is requested by a task that lists `{type: access_request, name: A<n>}` in `produces`. For drafted phases that task is in P0. A phase released later that needs new access requests it in its own first task (a task with no dependencies). `access_list.needed_by` is derived from task `access` and must match it exactly.
- **Step references.** Each entry in a step's `refs` is either an evidence id (`ev-...`) or the `name` of something an earlier task in its dependency chain `produces`. Anything else is a GR-07 blocker.
- **Copied steps.** A step whose wording or command came from text in the org's systems carries `from_evidence` with that evidence id. The proposal lists those steps under "Commands taken from the org's own files".
- **Phase sizes.** Drafted phases outside 3 to 8 tasks raise the GR-20 minor. P0 is usually small and the approver accepts that minor.
- **Overlay files.** Overlay and skill manifests are YAML written in the Groundwork YAML subset (`scripts/gw_yaml.py`): block mappings and sequences, flow `{}` and `[]`, plain or quoted scalars, comments. No anchors, aliases, tags or multi-line strings.
