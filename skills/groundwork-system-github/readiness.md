# Readiness and expectations (GitHub)

System skills only report in v1; they never write.

## Readiness checks

| Check | What it looks for | If missing |
| --- | --- | --- |
| `github.required-ci-check` | The default branch requires at least one status check | Report; plans that change code then carry a minor "no required CI check" and add a test task that runs the suite locally |
| `github.default-branch-protected` | The default branch has branch protection or a ruleset requiring a pull request | Report; plans must not assume review before merge |
| `github.environments-defined` | Deploy workflows target named environments | Report; cutover tasks name the workflow and branch instead |

## Expectations to propose at setup

| Id | Check | How to confirm |
| --- | --- | --- |
| `default-branch-protected` | The default branch requires a pull request with at least one approval | R2 or R3 |
| `ci-required` | At least one required status check on the default branch | R2 or R3 |
| `codeowners-present` | A CODEOWNERS file exists | R4 |
| `production-reviewed` | A production environment requires at least one reviewer | R6 |
