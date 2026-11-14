<!-- SPDX-License-Identifier: Apache-2.0 -->
# Release and revise modes

## Release mode

"Release phase P2" takes the lock, allocates the next plan version, and loads the plan of record and evidence file. Restricted evidence and anything older than `evidence_max_age_days` is re-discovered by the runner. If any fact a P2 task relies on changed, P2 goes back through Draft and Gap review, including the independent reviewer; otherwise the validator reruns and the phase goes to approval with `kind: release`, then create and freeze as above. New access for the phase is requested in its own first task (GR-13).

## Revise mode

- **Finding the epic.** The runner gives the epic's tracker key or link; the core never finds an epic by title.
- **Baseline.** The tracker's current state from `read_epic` plus the latest plan of record. Where a person changed a plan-owned field, the tracker wins, the change is listed as drift, and the adopted text is marked `from_tracker` (untrusted), shown in the proposal, and checked by the reviewer like evidence text.
- **Diff.** Added tasks, changed plan-owned fields, tasks to close (never deleted), dependency changes and phases newly offered, computed by `revise_diff.py` against the tracker's current state. The whole resulting plan is gap-reviewed.
- **Done work is not edited.** A change to a finished task becomes a new follow-up task with a new id.
- **Concurrency.** Revise holds the lock from version allocation through apply, and the diff records each item's last-updated time; apply refuses if any changed.
- **Release on a worked epic.** Status changes, ticked steps and notes outside the plan-owned markers are normal work, not drift. Points a person raised are kept, and Groundwork posts one split recommendation on that task, recorded in the manifest so it is never repeated. A task a person deleted is never recreated; a task in the phase being released that depends on it stops create until a revise re-points the dependency.
- **Approval.** Same gates and records, with `kind: revision`; create applies the diff with the same keys, manifest and preflight.
