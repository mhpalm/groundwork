<!-- SPDX-License-Identifier: Apache-2.0 -->
# What is hashed

Hashes are SHA-256 over RFC 8785 canonical JSON, computed by `check_hashes.py`. The hashed subset is normative and listed below and defined by `scripts/gw_hash.py`:

- `phase_hash`: the phase's id, name, goal, order, `depends_on` and `task_ids`, plus every field of each of its tasks (role by `role_key`, evidence by id). It excludes phase `state`, plan `status` and `version`, `stamps`, `review`, `history`, `coverage`, `epic.tracker_ref` and approvals, so moving a phase through its states never changes it.
- `plan_hash`: every `phase_hash`, plus `scope`, `request.starting_point`, `epic.title`, `epic.summary`, `open_questions` and `access_list`; in plan format 2 also `traits`, the full `brief` (a restricted field contributes its `value_rev`, never its value) and the full `approach`. A format-1 plan hashes exactly as before.
- `basis_hash` (informational, never an approval binding): what one phase relies on without its own tasks, namely the brief fields and decisions its tasks cite, all approach options when any decision is cited, the brief fields their rejections cite, the open questions blocking the phase or its tasks, and its access lines. Revise compares it at release and now to list "basis changed after release".
- The change-request log (`change-requests-<n>.json`) is outside `plan_hash`: a decline must not change the plan or void pending approvals. Its entry is bound through the write list instead.
- `proposal_hash`: the bytes of `proposal.md` as rendered from the plan by `render_proposal.py`; create re-renders and compares.
- `write_list_hash`: the numbered write list, which names every write including lock comments, plan store files, manifest updates and labels. Every write carries its `scope` (`phase:<id>` or `plan`), so the hash also binds which set authorizes it. A plan-level record binds `plan_hash`, `proposal_hash`, `write_list_hash` and `review_hash` with no phase hashes. A `plan.status` change made without a new version lives in the status file, bound through the write list, never through `plan_hash`.

Evidence ids are derived from the subject (`ev-<platform>-<instance>-<8 hex of subject>`), so re-reading the same subject keeps its id and an approval survives a refresh that finds the same facts. Mutation tests confirm that a state change leaves `phase_hash` alone and any task edit changes it.

## Exact fields

The scripts in `scripts/gw_hash.py` are the definition; this list mirrors them.

- `phase_hash` covers `{phase: {id, name, goal, order, depends_on, task_ids}, tasks: [every field of each task in the phase, sorted by id]}`.
- `plan_hash` covers `{phase_hashes, scope, starting_point, epic: {title, summary}, open_questions, access_list}`, plus `traits`, `brief` and `approach` when the plan has them.
- `basis_hash` covers `gw_model.basis_subset(plan, phase_id)`: `{brief, decisions, options, open_questions, access}`.
- `write_list_hash` covers the whole write list rendered by `render_proposal.py write-list`.
- `proposal_hash` is SHA-256 of the UTF-8 bytes of `proposal.md` exactly as rendered.
- `view_hash` covers the reviewer bundle `{schema_version, plan: reviewer view, evidence (sorted by id), checklist_version, rules (sorted by id)}`.
- `review_hash` covers `{findings, view_hash}` of the reviewer's output.
- Evidence, manifest, overlay and status-file hashes cover the record without its own `hash` field. A manifest's `status_file` is part of the manifest, so the chain binds it; the status file's own hash covers `{schema_version, plan_id, n, status, set_by, at}`. A retire write list binds only `{schema_version, plan_id, status}` of the status file, since `set_by` names the proposal's own hash.
- The plan-owned hash of a tracker item covers `{title (whitespace collapsed), body_owned (the text between the groundwork owned markers, trailing spaces trimmed), role_key, phase, key}` as the tracker skill's `normalize` reads them back.
