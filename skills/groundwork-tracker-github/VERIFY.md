<!-- SPDX-License-Identifier: Apache-2.0 -->
# GitHub behaviours to confirm before release

Each row must be confirmed on a real repository (and this file trimmed) before this skill's first release.

| Assumption | Used by | Confirmed |
| --- | --- | --- |
| `PATCH repos/{owner}/{repo}/issues/{n}` accepts `state: closed` with `state_reason` `completed`, `not_planned` or `duplicate`, and the issue reads back with that `state_reason` | close | no |
| A label containing a colon (`gw-closed:not_planned`) can be created and added | close labels | no |
| Adding a label to a closed issue is allowed (a person's close is never relabelled, but a resumed close may label first) | close resume | no |
| The `gw-blocked` label is added and read back by `gh issue view --json labels` | set_blocked | no |
| `search/issues` `total_count` counts issues only when the query has `is:issue` | read_scope | no |
