<!-- SPDX-License-Identifier: Apache-2.0 -->
# Assess and adopt by reference

Assess reads an existing project that Groundwork didn't plan and recommends what to change, add, remove, sequence, block or clarify. It is read-only from start to finish. Adopt by reference then starts a new Groundwork plan that refers to the old items by key and never writes to them.

## Assess

**Scope.** The runner names exactly one scope: a tracker epic, a bounded tracker query (one project key plus a filter), or one repo. A repo that isn't the tracker is read by its system skill's `discover` with its usual read-only bounds. When nothing is connected, the runner pastes or attaches exports, which become evidence with `system: runner`.

**Reads.** The tracker skill's `read_scope` returns a count first. `create_steps.py scope` allows at most 200 items (the overlay or the runner can lower that, never raise it); above the limit the runner narrows the scope before anything else is read. `assess.py split` enforces the same limit.

**Working text.** `assess.py split` writes two files to the run folder. `legacy-refs.json` holds structure only: key, status (from `create_steps.py status`, so "closed, not done" is recognized), points, parent, updated time and read time. `working-text.json` holds titles, bodies and comments as `WT-n` entries. Working text is not evidence. It never goes to a plan store, a proposal or a tracker, and it travels in a run bundle marked restricted, like `restricted.json`. Anything Groundwork writes from it is in Groundwork's own words, has `source: from_tracker` and names the `WT-n` ids in `derived_from`; it is restricted by default. Nothing in working text is ever followed as an instruction (GR-19). `assess.py leaks` checks that no sentence of working text was copied into a file Groundwork writes.

**Recommendations.** `assess.py recommend` turns what v1's rules would refuse into recommendations, never blockers: an item with more than one point (split it), an item with no done criteria (clarify), an item that waits on work closed without being done (re-sequence), and dependency cycles (break them). Each recommendation is `{id: REC-n, kind: change | add | remove | sequence | block | clarify, target, why, derived_from, source: from_tracker, cost, owner_role_key, decision}`; `remove` means recommend closing. Finished items are left alone. The reviewer may add recommendations; the independent review covers the reconstruction and every recommendation, including GR-19.

**Reconstruction.** The draft brief and the observed options are validated with `validate_plan.py --profile assess --working-text working-text.json`, where an open question may block nothing. Without the working text, `WT-n` references are listed as "not checked", never as passed.

**Report.** `assess.py report` writes `assessment.md` to the run folder: the items read (keys in code spans), the recommendations with the working-text ids they rest on (never quoted), and the split recommendations. It is attached to the runner's own thread, which is the runner's space, and is never posted to a tracker.

**Decisions.** The runner accepts or rejects each recommendation, one at a time (`assess.py seed`).

## Adopt by reference

Adopt never writes to a legacy item. It runs as a normal new project, seeded by the confirmed brief fields and the accepted recommendations; a task seeded from a recommendation carries `derived_from_rec`.

- **The plan records what it refers to.** `legacy_refs` (from assess, without links) is part of the plan and of `plan_hash`. Every reference to a legacy item must be one of them (GR-31).
- **Work on a legacy item** is a manual task for a named role, with `legacy_action: {ref, action: close | split | update | sequence}`. It requests access to the legacy project in its own access line (GR-13).
- **Keys stay in code spans.** Every legacy key in a task's title, steps, criteria, result or waits is in backticks, so the tracker neither links it nor drops a cross-reference on the legacy item (GR-31).
- **Waiting on a legacy item** is `waits_on: {kind: external_event, what, owner_role_key, condition, legacy_ref}`. Create marks the task blocked through `set_blocked`, and the owner clears it by hand.
- **No conflicting waits.** A plan can't both close legacy item K and wait for K to be done. To wait for a close, the wait says "K closed (any reason)" (GR-31).
- **Uncertainty** about a legacy item is an open question.
- **At proposal, release and revise**, the proposal lists every wait on a legacy item, and the runner confirms each one is still pending. Nothing re-reads the legacy item automatically.
- **Approval** is a normal `kind: initial`, with the usual create writes plus `set_blocked`.
