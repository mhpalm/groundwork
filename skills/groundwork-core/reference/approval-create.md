<!-- SPDX-License-Identifier: Apache-2.0 -->
# Approval, create and freeze

Approval releases specific phases at a specific plan version, authenticated by the approvers' own tracker accounts, and create writes exactly those phases. Create is safe to rerun at any point: every item carries a stable key, a chained manifest in the plan store records what was written, preflight adopts or stops instead of guessing, and a phase only becomes visible as ready once every item in it is written.

## What is hashed

Hashes are SHA-256 over RFC 8785 canonical JSON, computed by `check_hashes.py`. The hashed subset is normative and listed below and defined by `scripts/gw_hash.py`:

- `phase_hash`: the phase's id, name, goal, order, `depends_on` and `task_ids`, plus every field of each of its tasks (role by `role_key`, evidence by id). It excludes phase `state`, plan `status` and `version`, `stamps`, `review`, `history`, `coverage`, `epic.tracker_ref` and approvals, so moving a phase through its states never changes it.
- `plan_hash`: every `phase_hash`, plus `scope`, `epic.title`, `epic.summary`, `open_questions` and `access_list`.
- `proposal_hash`: the bytes of `proposal.md` as rendered from the plan by `render_proposal.py`; create re-renders and compares.
- `write_list_hash`: the numbered write list, which names every write including lock comments, plan store files, manifest updates and labels.

Evidence ids are derived from the subject (`ev-<platform>-<instance>-<8 hex of subject>`), so re-reading the same subject keeps its id and an approval survives a refresh that finds the same facts. Mutation tests confirm that a state change leaves `phase_hash` alone and any task edit changes it.

## The draft epic

At Proposal the core offers one held write: create the epic with the overlay's draft label (default `gw-draft`), the overlay id, version and hash, and the rendered proposal in its description. The plan store gets the plan of record and an evidence file holding every non-restricted evidence item. The draft epic holds no tasks, and everything on it is safe for its viewers under CR-11. The draft label is removed by a listed write at the first freeze.

## Plan store, lock and manifest

**Plan store.** Files are put through the tracker skill as `<plan.id>-plan-v<N>`, `<plan.id>-evidence-v<N>`, `<plan.id>-manifest-<seq>` and `<plan.id>-snapshot-<seq>-<YYYY-MM-DD>`. Groundwork never overwrites a file. Trackers may let people edit what is stored, so immutability is detected, not enforced: every approval and manifest records the hashes of the files it relies on, and a file that no longer matches stops the run.

**Lock.** Neither GitHub nor Jira offers an atomic claim, so the lock is a protocol. To claim, post a `gw-lock` comment on the epic with the runner's account id, run id and an expiry 30 minutes out; then list lock comments, and the earliest unexpired claim wins. A loser posts a release and stops. The holder renews by posting at least every 10 writes, and posts a release when it stops for any reason, success or failure. The same account resuming the same run may take over its own lock. Lock comments are housekeeping writes on the write list. The lock is required for allocating a new plan version or manifest sequence (plan phase, release, revise), for create and for freeze.

**Manifest.** Each manifest file lists every written key with its tracker id, its plan-owned hash, its links and its not-ready state, plus `prev_hash` of the previous manifest. The latest manifest is the highest sequence whose `prev_hash` chain is intact. Create writes a new manifest after every batch of at most 10 writes, so a crash loses at most one batch of bookkeeping, which preflight then adopts.

## Phase-by-phase approval

1. The proposal offers phases with no unresolved blocker and no blocking open question. Outline phases and phases with open questions are shown but cannot be offered.
2. With the offer, the core posts the numbered write list for those phases.
3. Each approver posts one approval record (plan-format.md) as a comment on the epic from their own tracker account. In a Groundwork session, the core shows the approver the phases, the short forms of `plan_hash`, `proposal_hash`, `review_hash` and `write_list_hash`, and the full write list, and posts only after the approver confirms. Elsewhere it gives the exact text to paste.
4. Every gate whose `applies_to` is `all_phases` must reach its own quorum for each phase: `min_approvers` records from distinct accounts with the same `plan_hash` and `phase_hashes`. Exceptions need their own record on the `exception` gate; a phase-release record cannot accept an exception.
5. The drafter may approve their own plan, and it is not flagged. The record names the approver's account.
6. If a write-capable tracker skill is `unverified` on the surface, the proposal and write list say so, and each record must carry `accept_unverified_writer: true` or create refuses.
7. Any later change to an approved phase changes its `phase_hash` and voids that phase's approvals. Create must start within `create_window_days` (overlay, default 3) of the last approval; after that, approvers post fresh records for the same hashes.

## Create

**Lock**, then **verify** (read-only):

- Connect with the runner's own access; confirm the instance and project match the overlay, the epic's overlay id matches, and the runner's overlay hash matches the latest anchored overlay record (setup-mode.md) (CR-12).
- Only approval records whose `plan_version` equals the plan of record's version count. Records for earlier versions were used or voided when that version was replaced; they are listed as superseded and never stop create, so releasing P2 after P1 was created works.
- For each approval comment, read through the API that its author's account id is on the gate in the anchored overlay and that the comment has never been edited (its updated time equals its created time). Recompute `plan_hash` and `phase_hashes` from the plan of record, `proposal_hash` by re-rendering, and `write_list_hash`. Rerun `validate_plan.py`. Any mismatch stops create.
- Re-read evidence marked `recheck`. If a fact changed, stop; the phase goes back through Draft and Gap review as a new plan version.

**Preflight** (read-only). `find_by_key` searches the key slot across the whole tracker project, not only the epic's children; `list_children` cross-checks. Items in the phases being written:

| Found | Latest manifest says | Action |
| --- | --- | --- |
| No item with this key | Never written | Create |
| Item with this key | Written, same plan-owned hash | Skip |
| Item with this key | Never written | Adopt if its plan-owned hash matches the planned item (the crash-before-manifest case); otherwise stop as drift |
| Item with this key, not under the epic | Any | Adopt and add the missing parent link as the next write |
| Item with this key | Written, different plan-owned hash | Stop: drift |
| No item with this key | Written | Stop: drift, deleted or moved; never recreate silently |
| Item with this key, larger points | Any | Keep the points; add a held comment recommending a split |

Items in other phases are compared too, but differences there are reported as warnings, not stops, so a person adding notes to an earlier task doesn't block a release.

**Plan-owned hash.** Covers the title, the sections of the body Groundwork wrote, the role key, the phase and the key. Each tracker skill provides a `normalize` procedure that reads those fields back into the same form they were written in (Jira ADF and GitHub Markdown differ), with mutation tests. The hash is kept in the manifest, not in the item, so no extra field is needed. Status, checklist ticks, assignee, comments, people's labels and points are excluded. Links are checked against the manifest separately.

**Writes.** Tasks in phase and dependency order, each created with its key and the not-ready marker in the same call; parent links and dependency links next; a new manifest after every batch. On partial failure, create stops, writes the manifest, releases the lock, and the phase stays not-ready. "Resume create" reruns lock, verify and preflight; preflight's adopt rule covers anything written after the last manifest. Created items are never deleted automatically; abandoning a phase means a held write that closes its items.

## Freeze

With every task and link written, the phase moves to `writing` and the not-ready markers are cleared item by item, each recorded in the manifest, so an interrupted flip resumes where it stopped. When the manifest shows every item ready, the phase becomes `released`, the snapshot is stored, the first freeze also removes the draft label from the epic, and the lock is released. Where the tracker supports it, the not-ready marker is a workflow state as well as a label, so a person removing the label alone doesn't make an item look ready; release mode reports any item found ready early. The epic description lists unreleased phases as "planned, not released" or "outline, needs a planning run". `plan.status` is `active` while any phase is not `released` and `complete` when all are.

## Formats on the tracker

- **Approval comment.** A comment whose body contains the approval record as a fenced block that starts with three backticks and `json`. Any other text in the comment is ignored. `check_hashes.py approvals` reads every epic comment, keeps only records for this plan id, and refuses any comment whose updated time differs from its created time.
- **Lock comment.** One line: `gw-lock claim|renew|release run=<run id> account=<account id> expires=<UTC time>` (no `expires` on release). `create_steps.py lock` decides the holder. A lock line counts only when its account matches the comment's author.
- **Owned section.** Every item body Groundwork writes keeps the plan-owned text between `<!-- groundwork:owned:start -->` and `<!-- groundwork:owned:end -->`. People may add anything outside the markers; it is never drift.
- **Plan store names.** `<plan.id>-plan-v<N>`, `<plan.id>-evidence-v<N>`, `<plan.id>-manifest-<seq>`, `<plan.id>-snapshot-<seq>-<YYYY-MM-DD>`, never overwritten.

## The create procedure, step by step

1. `create_steps.py lock` with the epic's lock comments. If it says `claim`, post the line it gives, read the comments again and repeat. Continue only on `held`. On `lost`, post the release it gives if you posted a claim, and stop.
2. Read the latest anchored overlay record from the anchor issue, the epic's comments, the plan of record, the proposal, the write list and the review. Run `check_hashes.py approvals`. Any problem stops create.
3. Run `validate_plan.py --stage create --offer <approved phases> --now <now>`. Re-read every evidence item marked `recheck`; if a fact changed, stop and send the phase back through Draft and Gap review.
4. For each planned item render its body with `render_proposal.py task`, compute its plan-owned hash, then `find_by_key` across the tracker project and `list_children` on the epic. Read each found item back through the tracker skill's `normalize` and hash it with `check_hashes.py owned`. Run `create_steps.py preflight`.
5. Carry out the preflight actions in order: create (key and not-ready marker in the same call), adopt, skip, add missing parent links, then dependency links, writing a manifest with `create_steps.py manifest` after every 10 writes and at the end. Post a held split-recommendation comment for each `comment_split`.
6. Renew the lock at least every 10 writes. On any failed write: write the manifest, release the lock, report which write failed. "Resume create" starts again at step 1.
