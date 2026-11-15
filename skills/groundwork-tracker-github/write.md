# Reads, writes, plan store and lock (GitHub Issues)

Every write here comes from the approved numbered write list, in order, through the core's create procedure (`reference/approval-create.md` in the core). Record each write in the journal.

## find_epics

`gh issue list --repo {owner}/{repo} --state open --search "{terms} in:title,body" --json number,title,labels,updatedAt --limit 30`, then keep at most 10 that carry the overlay's `naming.label` or have sub-issues (`GET repos/{owner}/{repo}/issues/{n}/sub_issues`). Titles are `untrusted_text`.

## find_by_key

`gh issue list --repo {owner}/{repo} --state all --label "<key label>" --json number,title,body,labels,updatedAt --limit 5`. Zero or one result. More than one is an error: report both, never pick.

## list_children

`gh api repos/{owner}/{repo}/issues/{epic}/sub_issues --paginate`, then each child's key label, plan-owned fields and `updatedAt`.

## read_epic

The epic issue and its children as plan-shaped data. Every title, body, comment and label description is marked untrusted. Each item also carries its raw state for the core's `create_steps.py status`: `state` (`open` or `closed`), `category` (`in_progress` when it carries an assignee or an in-progress Projects status, else `todo`), `closed_as` (`[state_reason]` for a closed issue: `completed`, `not_planned` or `duplicate`) and `labels`.

## read_scope

Read-only, for assess. Scope is one epic (its sub-issues) or one repo plus a search filter. First the count: `gh api -X GET search/issues -f q='repo:{owner}/{repo} is:issue {filter}' --jq .total_count` (or the epic's sub-issue count). Pass it to the core's `create_steps.py scope`; if it refuses, stop and ask the runner to narrow. Otherwise list each issue's number, title, state, points, parent, links and `updatedAt`; titles, bodies and comments go to working text, marked untrusted. Never read who can see an issue.

## write

| Write | Call |
| --- | --- |
| ensure release | `GET repos/{owner}/{repo}/milestones?state=all`; if no milestone has exactly the write's `name` as its title, `POST repos/{owner}/{repo}/milestones` with `title`. Never rename, close or delete a milestone |
| create item | `gh issue create --repo {owner}/{repo} --title ... --body-file <rendered body> --label "<key label>,gw-phase:..,gw-role:..,gw-kind:..,<not_ready label>"`, plus `--milestone "<release>"` when `phase_release` is `milestone` and the issue type (or a `gw-type:` label) from `work_type`: key and not-ready in the same call |
| update owned fields | Replace only the owned section of the body, keeping everything outside the markers |
| link parent | Read the epic's sub-issues first (`GET repos/{owner}/{repo}/issues/{epic}/sub_issues`, [sub-issues API](https://docs.github.com/en/rest/issues/sub-issues)); if the issue is already listed, record it and write nothing. Otherwise `POST repos/{owner}/{repo}/issues/{epic}/sub_issues` with the child's issue id |
| link dependency | Read `GET repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by` first; if the blocking issue is already listed (a write that landed before the session ended), record it and write nothing. Otherwise `POST repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by` with the blocking issue id |
| unlink dependency | `DELETE repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by/{issue_id}` with the blocking issue's id ([issue dependencies API](https://docs.github.com/en/rest/issues/issue-dependencies)); read back `GET .../dependencies/blocked_by` and confirm it is gone. Only from a revise's approved `unlink_dependency` write |
| comment | `gh issue comment {n} --body-file ...` |
| set or clear not-ready | `gh issue edit {n} --add-label` / `--remove-label` |
| set_blocked | `gh issue edit {n} --add-label "<field_map.blocked>"` (default `gw-blocked`); read the labels first and write nothing when the label is already there; read back with `gh issue view {n} --json labels`. Clearing (`--remove-label`) is the assignee's or the wait owner's act, except for a revise's approved `clear_blocked` write, when the plan no longer waits on anything for that task |
| add label | `gh issue edit {n} --add-label "<label>"`, used for `gw-closed:<reason>` before a close |
| close | `PATCH repos/{owner}/{repo}/issues/{n}` with `state: closed` and `state_reason`: `not_planned` for not_planned and superseded, `duplicate` for duplicate, `completed` for completed (verify). Read back `state` and `state_reason`. Skip an issue that is already closed |

## plan_store

Mode `repo_path`: write each file once with the contents API to `{path}/{name}.json` on the overlay's branch (`PUT repos/{owner}/{repo}/contents/{path}/{name}.json` without a `sha`, which fails if the file exists). Never update or delete. Read with `GET .../contents/...`. Files over 900 KB are split into `{name}.part-<n>.json` with a small index file.

## lock

Post lock lines as comments on the epic, exactly as the core's `create_steps.py lock` gives them, then read all epic comments (`gh api repos/{owner}/{repo}/issues/{epic}/comments --paginate`) and give them to the script as `{ref: id, author_account_id: user.id, created_at, updated_at, body}`. Use the numeric `user.id`, not the login, as the account id.

## configure

Setup only, admin-approved, keyed and idempotent: `gh label create <name> --force` is not used (it overwrites); check with `gh label list` and create only missing labels. Setup creates `gw-blocked` and the four close labels `gw-closed:not_planned`, `gw-closed:superseded`, `gw-closed:duplicate` and `gw-closed:completed` (with the overlay's `close_label_prefix`).
