<!-- SPDX-License-Identifier: Apache-2.0 -->
# Setup mode and the org overlay (format 1.0)

Setup mode builds an org's overlay on first use: it asks which systems the user works with, connects to each with the user's own sign-in, inspects read-only, checks that every field Groundwork needs exists, and confirms every value with an admin before anything is written. The overlay is itself a small skill folder, `groundwork-overlay-<org-slug>/`, so it installs and loads on every surface the same way the shared skills do. It is kept in the org's own storage and never in the shared repo.

## When it runs and who does what

A skill cannot run at install time on any surface, so "first use" means the first Groundwork request in a session where no overlay loads. The core then offers setup mode before anything else. The same pass reruns when an overlay update adds a system or tracker. Any user may run setup; what they produce is an overlay draft. Only an admin listed in the draft (or, for a brand-new overlay, the person the runner names as admin, confirmed by them in their own session) approves its writes.

| # | Step | Who | Writes |
| --- | --- | --- | --- |
| 1 | **Identify.** Ask which systems and which tracker the org uses, and their instances. Match each to an installed skill; a system with no skill is `unsupported` and every plan touching it says it was not inspected | Runner | None |
| 2 | **Authenticate.** Follow each skill's `connect` from the current surface with the runner's own sign-in, preferring read-only scoped tokens. Show the skill's disclosure about any sign-in the platform's own tool stores. Record identity and instance | Runner | None by Groundwork |
| 3 | **Inspect.** Tracker `discover_config`; each system's structural inventory (repos, environments, objects; never records) | Runner | None |
| 4 | **Field readiness pass.** Compare each skill's `readiness` against what was found. For each gap, a card with three choices: map to an existing field (candidates listed), use the skill's declared fallback, or create it | Runner proposes, admin decides | None yet |
| 5 | **Propose expectations.** Each system skill's `expectations` (for example, "default branch is protected", "CI check required"), with what inspection found for each | Runner proposes, admin decides | None yet |
| 6 | **Propose the rest.** Day length, executor, roles, hierarchy (from the tracker's item types, including which item type a story and a task become, and how phases are released: a version, a milestone or a label), gates and approver account ids, naming (patterns from existing titles, which are untrusted and shown only as suggestions) | Runner proposes, admin decides | None yet |
| 7 | **Write.** Show the numbered write list: overlay files and where they go, plus any field or label to create through the tracker's `configure`. Hold it for the admin. On approval, write, run `validate_overlay.py`, record an overlay approval record, and package a ZIP | Admin approves; created fields use the admin's access | Held writes only |
| 8 | **Show where things live.** A table of each overlay piece, its file and key, and who changes it | Runner | None |

Re-running setup on an existing overlay ("update the overlay") inspects again, shows a diff, and on approval bumps `version` and recomputes `hash`. Everything setup learns goes into the overlay only; nothing is written back to a shared skill.

**Tension 1: "authenticates" versus CR-08.** Groundwork never asks for, stores, or writes a token, password or key into the overlay, plan, evidence or run folder. The platform tools it relies on may keep a sign-in on their own (a CLI token in the OS keychain, a claude.ai connector's authorization). Groundwork reads CR-08 as: Groundwork saves no credentials and uses only sign-ins each person made with their own account; what the platform's tool stores is outside Groundwork and is disclosed in every `connect` section. CI sandbox credentials are CI secrets, never in the repo. 

**Tension 2: "or should they be created" versus CR-01.** Creating a field is a configuration write to the org's tracker. In v1 it is allowed only in the tracker, only through the tracker skill's keyed `configure` procedure, only as a numbered write an admin approves, and only with the admin's own access. System skills never create fields in v1; their readiness gaps are reported for a person to fix. Setup prefers mapping or a fallback and recommends creation only when neither exists. 

## Overlay format 1.0

```yaml
# groundwork-overlay-<org-slug>/overlay.yaml
schema_version: "1.0"
overlay_format: "1.0"
id: example-org                      # slug; stamped on every plan and epic
version: 1                           # +1 on every approved change
hash: sha256                         # of this file without this field, set by the script
org_name: Example Org
admins: [{account_id, name}]
skills:
  core: ">=1.0.0 <2.0.0"
  systems:
    - skill: groundwork-system-github
      version: ">=1.0.0 <2.0.0"
      instances: [{id: gh, url: "https://github.com/example-org", expected_identity: {org: example-org}}]
      expectations: [{id, check, confirmed_value}]
      readiness: [{check, status: ok | gap_reported, note}]
  unsupported_systems: [{name, note}]
  tracker:
    skill: groundwork-tracker-jira
    version: ">=1.0.0 <2.0.0"
    instance: {id: main, url: "https://example-org.atlassian.net", project: VOL}
    field_map:
      key: {slot: label}             # label | field | item_property; never description only
      points: "Story Points"
      hours: "Original Estimate"
      phase: label
      blocked: "Flagged"
      depends_on: "Blocks"
      not_ready: label
      work_types: {story: Story, task: Task}   # tracker item type per work_type
      phase_release: version         # version (Jira fix version) | milestone (GitHub) | label
working_day_hours: 6                 # default 6; allowed 1 to 8
assumed_executor: junior_no_context   # enum, see below
roles:                               # generic key -> org name
  - {key: developer, name: Developer}
  - {key: approver, name: Program Director}
task_hierarchy:
  task_to_epic: parent               # parent (default) | linked
  steps_as: checklist                # checklist (default) | subtasks
approval_gates:
  - {id: phase-release, applies_to: all_phases, approvers: [{account_id, name}], min_approvers: 1}
  - {id: exception, applies_to: one_day_exceptions, approvers: [{account_id, name}]}
evidence_max_age_days: 7             # measured at approval
create_window_days: 3                # create must start within this many days of approval
anchor: {tracker_ref: "VOL-1"}       # issue holding admin-authored overlay records
role_holders:                        # who fills each role, for requests and mentions; not assignees
  - {role_key: developer, display: "Dev team", handle: "@portal-devs"}
tracker_access_assumed: true         # everyone in role_holders can open and comment on epics
environments: [{name: staging, shared: true}]
labels: {draft: gw-draft, not_ready: gw-not-ready}
plan_store: {mode: attachments}     # attachments (default) | repo_path {repo, path}; the tracker skill says which it supports
naming: {epic: "{title}", task: "{verb} {object}", label: groundwork}
access_requests: {how: "text shown in P0 tasks", link: url, on_behalf_allowed: true}
channels: {release: name or url, announcements: name or url}
run_storage: {claude-code-local: "~/groundwork/runs"}
```

**Executor profiles.** `assumed_executor` is an enum, so an overlay cannot weaken the one-day rule by describing an expert: `junior_no_context` (default: a junior developer with no access to the original team), `junior_with_context`, `mid_no_context`. Instructions for non-developer roles are written to the same standard: someone new to the task, with no one to ask.

**Hierarchy options.** The brief's "sub-tasks or linked tasks" covers two separate choices. `task_to_epic` says how a task attaches to its epic: as a child (`parent`) or through an issue link (`linked`), whichever the org's tracker uses. `steps_as` says how a task's numbered steps appear: as a `checklist` inside the task, which the tracker skill knows how to render and read back, or as `subtasks` with no points and no estimate, all inside the parent's one day. Either way a step is never a separate unit of work.

**Defaults** apply when a value is missing: 6-hour day, `junior_no_context`, `checklist`, roles mapped one to one from the generic keys, naming `{verb} {object}`, label `groundwork`, evidence age 7 days. There is no default approver; an overlay without one cannot approve anything.

**What an overlay cannot change.** The core rules, the one-day rule, points, instruction parts and gap-review blockers. `validate_overlay.py` rejects unknown keys at the overlay's own format version, except keys starting `x-`. A core that reads a newer MINOR format ignores keys it doesn't know and says so.

**Where it is kept.** The org's private repo holds the source. For cloud threads and the Claude app it is uploaded as a skill, provisioned to the org by an owner, or enabled per person on their claude.ai account. For local Claude Code it can also sit in `~/.claude/skills/`.

**The overlay anchor (root of trust).** The overlay file names the approvers, so the file alone cannot be trusted: anyone who can upload a ZIP could add themselves. Setup therefore creates, as a held write, one anchor issue in the tracker (`anchor.tracker_ref`). Every approved overlay version is recorded there as a comment authored by an admin's own account, holding the overlay id, version and the hash of the whole overlay folder (`overlay.yaml` and `SKILL.md`). The first record's author is the founding admin; each later record must be authored by an admin listed in the previous recorded version. At Intake and again at create, the core compares the loaded overlay's version and hash with the latest anchored record and refuses a mismatch, an older version, or an edited record comment. Approver authority is always checked against the anchored version, so removing an approver takes effect at the next run, and two admins cannot both publish a different "version 5". This is also the overlay approval record setup writes in step 7.

**Role holders.** `role_holders` names who fills each role (a person, a team handle or a channel) so tasks can say whom to request access for or mention without guessing. They are not assignees; the team still schedules and assigns work. `tracker_access_assumed` records that setup confirmed every role holder can open and comment on epics, so plans don't request it.

**Migrations.** A MAJOR change to the overlay format ships with `migrations/overlay/<from>-to-<to>.md` and a script in the core. An overlay with an older MAJOR is refused for planning, and the core offers "migrate the overlay", which produces a diff for an admin to approve like any overlay update.

## Producing the overlay skill

1. Start from `templates/overlay-skill/`: copy it to `groundwork-overlay-<org-slug>/`, rename `SKILL.template.md` to `SKILL.md`, fill `overlay.yaml` with the confirmed values, and keep the template's wording (it only says which overlay this is and that it is used inside Groundwork runs). The template is not named `SKILL.md` in the core because the Claude app rejects a skill ZIP that holds more than one `SKILL.md`.
2. Run `validate_overlay.py overlay.yaml` until it reports valid, then show the numbered write list to the admin.
3. After the admin approves, set the hash with `validate_overlay.py overlay.yaml --set-hash`, write the files, and post the overlay record on the anchor issue from the admin's own account: a fenced `json` block `{overlay_id, version, hash, gates: {gate_id: [account ids]}}`.
4. Package the folder as a ZIP whose root is the folder, for upload as a skill.
