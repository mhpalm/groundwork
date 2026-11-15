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

## Planning model build 3, 2026-11-15

30. The approval grouping key is `(plan_id, plan_version, proposal_hash)`. An invalid-JSON approval block is now information rather than a problem: it can't be tied to any set, and failing every set on it would let one bad comment block all creates.
31. "Current version" is passed to verification as the latest plan-of-record version in the plan store (`--latest-version`). The plan file alone can't say whether a newer one was stored.
32. A phase proposal's session-dependent lines (validator `not_run`, reviewer `not_performed`) already live in the plan of record's review section, so only plan-level proposals need a proposal context file today. The context schema allows phase kinds so a later change can move those lines without a format change.
33. The integrity profile is the full validator with its findings filtered to schema, evidence integrity, CR-12, GR-17, GR-25 and GR-34, offering no phase. Running the same code and filtering keeps one implementation of each check.
34. Plan-level records must all name the same kind. Mixed kinds for one proposal mean approvers disagree about what they approve, so the set fails.

## Planning model build 4, 2026-11-15

35. Similar declined requests are found by word overlap of the restatements (Jaccard at least 0.5 over words longer than two letters) and only shown to the runner, never used to decide. The design rules out a text hash.
36. The write list binds a change-request entry as `{id, outcome, reason}`; create adds `decided_by` from the verified proposal. Binding `decided_by` would put the proposal's own hash inside the write list the proposal shows.
37. An outline cost with no new outline phase still counts one phase. A later outcome always adds at least one.
38. GR-17 now lives in one function, `validate_plan.gr17_scan`, used for the plan, evidence and the change-request log, so the patterns can't drift apart.

## Planning model build 5, 2026-11-15

39. Assess keeps item links in `legacy-refs.json` for cycle and dependency checks, but `legacy_refs` in the plan drops them: the forward plan refers to items, not to the old dependency graph.
40. "No done criteria" is a heuristic (no acceptance, done-when, checklist, expected-result or verify wording in the body or comments). It only ever produces a clarify recommendation, which the runner can reject.
41. A copy of working text is a sentence of at least 24 characters appearing verbatim. Shorter runs give false hits on common phrases; the reviewer's GR-19 check covers paraphrase.
42. A tracker-derived brief field still needs `basis_role_key` (the existing GR-29 rule): someone confirmed that reading of the ticket.
43. A provisional bundle may carry only `system: runner` evidence with an intact hash; import lists it under `reconfirm` for the runner to confirm against the approved overlay.
44. Retire is terminal. A status file can only say `retired`, and the gate refuses a second retire; a plan that should continue after a retire is a new plan.
45. The manifest names the status file (`status_file`: state, number, hash, `at`, `set_by`) and every later manifest carries it forward. The manifest chain is already verified on every read, so it is the one place a status file can be checked against; a status file the chain doesn't name is a stop, not a status.
46. The retire write list binds the status file as `{schema_version, plan_id, status}` only. Its number is allocated under the lock and `set_by` names the verified set's `proposal_hash`, which the write list can't contain without naming its own proposal (the same rule as the change-request log's `decided_by`). The intent manifest records the full record's inputs, so a resume rebuilds the identical file.
47. Retire re-derives its closes from the items at write time. An item finished since the proposal is skipped; any other difference (an item started after approval, a changed choice) stops with "propose again" rather than closing work someone picked up.
48. A plan key under the epic that no manifest records (a create cut short) stops retire with "resume that create first". The close procedure closes only items a manifest records, and calling such an item person-added would leave plan work open with no owner.
49. The resume of a retire runs under the crashed run's own lock, like every other resume, and the gate matches it on the exact `(plan_version, proposal_hash)` in the manifest's `status_file.set_by`. Any other resume, including one of an earlier set at the same version, is refused.
50. The retire gate runs inside approval verification, not only as a separate step, and the CLI refuses without its inputs. A separate step the model could skip is not a gate; the approvals check is the one step create can't skip.
51. `--latest-version` is required at the CLI, so voiding by a newer stored version fails closed. The library keeps the parameter optional for unit tests of other rules.
52. Only retire closes items, writes the status file or touches the epic. A decline or own-epic decision that also needs a close is a revision, so the close is reviewed with the plan.
53. An edit binds the new plan-owned hash in its phase's scope, so the edited task's phase must be offered and re-approved, which its changed phase hash already requires. A dependent whose body names a retitled dependency counts as edited.
54. A crash after an update reaches the tracker but before the manifest is adopted only when the tracker holds exactly the planned text and the write list names the key; any other mismatch is drift, so a person's edit is never overwritten.
55. Deferred, with reasons: GR-33 counting standard work only in phases created at or after a trait's `from_plan_version` needs each phase's creation version, which the plan doesn't record yet; the reviewer bundle carrying restricted values for GR-30 and GR-32, and recording those checks as degraded when it can't, needs a restricted-bundle format; goldens for change requests, assess and retire are covered by unit tests through the fake tracker, and the G7 ticket and recommendation variants are not built. Each is listed for the next build.
56. The proposal approvers sign is always re-rendered at create and compared byte for byte, for phase and plan-level sets alike. A proposal file is never trusted, because it is the only thing an approver reads.
57. A plan-level review bundle is rebuilt by the verifier from stored inputs; no bundle file is an input to verification. Anything the verifier would accept from a file could differ from what is stored.
58. Expired records are information, as superseded ones are. A problem would block fresh records for the same proposal and leave a crashed create, or a retire in progress, with no way forward.
59. Revise needs the latest manifest, because the tracker read alone can't tell a task never written from one that moved out of the epic. Without it nothing is dropped.
60. Adopted tracker text is recorded through an `update_item` write that preflight carries out as `adopt_update`. The tracker already holds the text, so nothing is written to the item; only the manifest moves.
61. A phase write list is rebuilt from the plan of record and compared by hash, not only scope-checked. Scope rules said which phase a write belongs to, but not whether Groundwork would ever emit it, so a hand-added write that every approver bound would have run.
62. The approved review must be the one the plan of record records. Otherwise a clean review of a different view could be bound while the proposal showed the recorded one.
63. The reviewer view drops what is set after review without changing what was reviewed: the epic key, plan status, phase states, and evidence `collected_at` and record hash. Facts still count, so a re-read that finds different facts still voids.
64. Each approval record covers the whole offer. Partial approval would leave a write list whose phases are only partly approved, which create can't carry out safely; the approver asks for a smaller offer instead.
65. A change-request decision binds the logged entry, not a free-standing id, outcome and reason. Approvers were shown an id; without the restatement in the bound entry, a different request under the same id could have been decided.
66. Manifests are append-only per item. Clearing `blocked_set` would reapply a block a person cleared; clearing `split_comment` would repeat the comment; dropping a close would let a resume treat a closed item as open.
67. `relies_on` is checked on the first preflight of a revise apply only. A resume of the same apply would see its own writes as changes; the per-item drift rules cover the resume.
68. Plan-level sets write no manifest. They write nothing to the tracker, and the change-request log and status files carry their own numbering under the lock. The doc said otherwise and is corrected.
69. A renew extends a lock claim only while it is live. Reviving an expired claim let a stalled run win back the lock by claim time while the run that claimed after it was already writing.
70. An offer may include a phase whose tasks depend on an unwritten earlier phase only together with that phase. Preflight stops otherwise, because the dependency link has no target and nothing would ever add it later.
71. Append-only rules are checked when a manifest or change-request log is read, not only when one is written. File hashes have no secret, so only the rules stop a consistent hand edit. A deleted newest file is still not detectable without an external anchor; that residual is accepted, because recovering from it needs a fresh approved set, which is visible on the epic.
72. The change-request log is a hash chain like the manifests, and the CLI takes every log file rather than a "latest" one, so the latest is derived, never asserted.
73. `decided_by.proposal_hash` is computed by `decide` from the verified proposal file, never typed.
74. A revise never closes as `completed`. That reason reads back as done and would satisfy dependents with no work done.
75. Plan-level write lists are rebuilt like phase write lists. For a retire the rebuild takes the leave-open choices and the voided sets from the write list (both are shown to approvers and bind only what stays open or what is declared void) and derives every close from the stored items.
76. Split comments are named in phase write lists as a procedure, since the items they go on are found only at write time.
77. Accepted, not changed: `--relies-on` is passed on the first preflight of a revise apply and left out on resume (the drift and status rules still hold); a record's `kind` is a label, since plan version and proposal hash already bind it to its set; `accept_unverified_writer` follows the plan's stamps from proposal time; `changed_unwritten` ignores the manifest, which fails closed at create. Guards a mutation can remove with no test failing but that another check makes redundant: author versus approver (the anchored-gate check), `view_hash` (inside `review_hash`), `set_by` (inside the status hash), the phase scope check and the two-entry check (both inside the rebuild).
