# Build decisions, 2026-11-14

These were settled while building v1 against spec draft 0.3. Each is a candidate row for the spec's decision log.

1. Overlay and manifest files use a restricted YAML subset (block maps, block lists, scalars, no anchors or flow style), parsed by `gw_yaml.py`, so every script stays standard-library only.
2. `render_proposal.py` has four subcommands (`proposal`, `task`, `epic`, `write-list`), and lock, preflight and manifest decisions live in `create_steps.py`, so the tracker skill only reads and writes.
3. `phase_hash` covers the phase id, name, goal, order, depends_on and task_ids, plus its tasks sorted by id. Renaming a phase therefore voids its approval.
4. An approval record is a fenced `json` block in an epic comment. Edited comments are refused.
5. Item key labels are `gw:<last10 of plan id>:<task id>` on GitHub Issues and `gw-<last10>-<task id>` on Jira, because Jira labels cannot hold a colon.
6. The GitHub Issues plan store is a repo path only (`repo_path`); Jira uses issue attachments.
7. One-day exceptions are approved with approval records of `kind: exception` on the exception gate; a phase-release record cannot accept an exception.
8. `role_holders` entries carry the tracker `account_id`, which is what approval and lock checks compare against.

## Added while building golden projects G2 to G9

9. Intake identity is checked by a script, `check_identity.py`. Each connect report's URL and identity facts must match the overlay instance. A system that doesn't match stops and is recorded as not inspected; a tracker that doesn't match stops the run. A missing report counts as a mismatch.
10. Run bundles are made and checked by `run_bundle.py`. Import refuses a bundle from another overlay id or overlay hash, a changed file or bundle, a path that leaves the run folder, evidence collected under another overlay, and an existing run folder.
11. Revise mode's diff is computed by `revise_diff.py`. When a person changed a plan-owned field, the revised plan must carry exactly the tracker's text, or the diff is refused. A done task can't be edited or removed; the change becomes a follow-up task.
12. GR-18 now also blocks a task that needs access to a system nobody inspected (an unsupported system, or a coverage row marked not inspected), unless an open question parks it.
13. Preflight stops a task in the phase being written when it depends on a task a person deleted by hand. The split recommendation for a task whose points a person raised is posted once, whatever phase is being written, and recorded in the manifest (`split_comment`).
14. Offering an outline phase is refused at every stage, not only at Proposal.
15. G2 details P0 to P3 and leaves P4 and P5 as outline, because the shared G1 base puts its release in P3. The spec's "P0 to P2" is read as an example of the rule, not a fixed count.

## Found in the first sandbox run, 2026-11-15

16. A skill folder holds exactly one `SKILL.md`, at its root. The Claude app's skill upload rejects a ZIP with more than one ("Zip must contain exactly one SKILL.md file"), so templates that become skills are named `SKILL.template.md` and setup mode renames the copy. Enforced by `build_release.py`, `lint_boundaries.py` and `test_release.py`.
17. Planning needs no connection (D-54). `validate_overlay.py` accepts a provisional overlay (id `provisional`, no admins, approvers, instances or anchor) and reserves that id. `check_identity.py` treats a tracker reported `not_connected` as deferred (`run: plan_only`) but still stops on a connected tracker that reaches the wrong org or project, and on a missing report. Approvals and the write list refuse a provisional overlay.
18. Existing resources (D-55). `request.starting_point` is required; runner-supplied documents become evidence with `system: runner` and their text only in `untrusted_text`. GR-27 is mechanical (starting point consistent, resources inspected or explained, every `changes_existing` complete, regression check is a test or UAT task); GR-28 is the reviewer's necessity and breakage challenge.
19. Approval verification counts only records for the current plan version and requires quorum on every all-phases gate. Found in design review on 2026-11-15; tests in `tests/unit/test_approvals.py`.

## Planning model build 1, 2026-11-15

20. Plan format 2.0 is opt-in by `stamps.plan_format`. A format-1 plan keeps format 1 for life, skips GR-29 to GR-34, and its `plan_hash` is byte-for-byte unchanged, because `plan_subset` adds the brief, traits and approach keys only when the plan has them. Upgrading a format-1 plan is out of scope for v1.
21. Brief completeness is structural, not a gate on knowing everything: an unknown field is `open` with an open question that blocks only what it must, and Clarify stops after three rounds. The four keys approvers must read (outcome, success_measure, scope_in, non_goals) can never be restricted.
22. The GR-34 value search runs only when the restricted values are supplied (`--restricted`). Without them it is listed under `not_run` in the validator output and the proposal's review section, never reported as passed.
23. A deferred decision blocks every task that cites it except its `deferred_to_task`, inside the GR-04 computation, so a phase that depends on an unsettled design choice cannot be offered.
24. `executor_profiles` values use the same enum as `assumed_executor`. Free text was refused because a profile describing an expert would weaken the one-day rule.
25. Trait goldens are generated from G1 by `tools/gen/make_trait_goldens.py`, with traits pinned in the fixtures so golden runs do not vary on trait choice. GT-combined pins the conflicting pair and settles it with decision AD-2.

## Planning model build 2, 2026-11-15

26. `field_map.statuses` is required, with no default. A missing or short `closed_not_done` list would let a person's not-planned close read as done and satisfy a dependency, and that error is silent.
27. A Groundwork close counts when the manifest records it and either its `gw-closed:` label is on the item or the manifest records the transition as done. Requiring the label alone would let a person undo a close by removing it; trusting the intent alone would turn a person's real "Done", made after a close crashed before its label, into not done.
28. The fake tracker applies `set_blocked` after the links, in the same order as the write list, so existing crash-point tests keep their meaning.
29. The tracker contract stays at 1.0 although `read_scope`, `set_blocked` and `close` are new required sections: no tracker skill has been released, so nothing depends on the old shape.

