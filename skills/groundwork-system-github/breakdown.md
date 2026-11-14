# Breakdown patterns and standard work (GitHub)

Sizes are relative: S fits about a third of a day, M about half, L most of a day for the overlay's assumed executor. The core converts sizes to hours. An L that won't fit one day must be split.

## Patterns

| Pattern | Use when | Steps | Size | Verify | Roles | Visible result |
| --- | --- | --- | --- | --- | --- | --- |
| `github.local-setup` | First task touching a repo | Clone, install per README, run lint and tests, run locally | M | Test summary | developer | comment_posted |
| `github.code-change` | One cohesive code change with its tests | Branch from base, change, add tests, run lint and tests, open PR with the template, link it | M or L | Required checks green | developer | pr_opened |
| `github.docs-change` | Docs or changelog edit | Branch, edit, open PR | S | Rendered preview | developer | pr_opened |
| `github.staging-test` | After a merge deploys to staging | Record deployed SHA, exercise the change, record results | S or M | Comment with SHA and results | developer, qa | comment_posted |
| `github.rollback-rehearsal` | Before any production change | Write runbook, rehearse on staging by redeploying the previous ref, restore | M | Run links | developer | comment_posted |
| `github.tag-release` | Release by tag | Compare tested SHA with main, tag, push, confirm deploy run waits for review | S | Tag exists, run waiting | developer | deployed_change |
| `github.verify-release` | After an approved deploy | Read-only checks against production, or roll back | S | Checks recorded | developer | deployed_change |

A code task's visible result is the pull request open with green required checks and review requested. The merge is the next task's dependency (`satisfied_by: merged`), with the reviewer's review in `waits_on`.

## Standard work on GitHub

| Kind | How it usually works |
| --- | --- |
| test | Tests run in the required CI check on every pull request; a staging test task follows the merge |
| uat | Business users test on the staging environment; the UAT task records the staging commit SHA |
| cutover | Push a release tag or merge to the deploy branch; the production environment's reviewer approves the deploy run |
| rollback | Redeploy the previous tag or ref with `workflow_dispatch` (when the deploy workflow has it), or revert the merge and redeploy |
| docs | Docs in the repo ship with a deploy when the app serves them; otherwise a docs PR plus a publish step |
| handoff | A comment or doc for the code owners: what shipped, tests, runbook, known limits |
