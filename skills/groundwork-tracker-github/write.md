# Reads, writes, plan store and lock (GitHub Issues)

Every write here comes from the approved numbered write list, in order, through the core's create procedure (`reference/approval-create.md` in the core). Record each write in the journal.

## find_epics

`gh issue list --repo {owner}/{repo} --state open --search "{terms} in:title,body" --json number,title,labels,updatedAt --limit 30`, then keep at most 10 that carry the overlay's `naming.label` or have sub-issues (`GET repos/{owner}/{repo}/issues/{n}/sub_issues`). Titles are `untrusted_text`.

## find_by_key

`gh issue list --repo {owner}/{repo} --state all --label "<key label>" --json number,title,body,labels,updatedAt --limit 5`. Zero or one result. More than one is an error: report both, never pick.

## list_children

`gh api repos/{owner}/{repo}/issues/{epic}/sub_issues --paginate`, then each child's key label, plan-owned fields and `updatedAt`.

## read_epic

The epic issue and its children as plan-shaped data. Every title, body, comment and label description is marked untrusted.

## write

| Write | Call |
| --- | --- |
| ensure release | `GET repos/{owner}/{repo}/milestones?state=all`; if no milestone has exactly the write's `name` as its title, `POST repos/{owner}/{repo}/milestones` with `title`. Never rename, close or delete a milestone |
| create item | `gh issue create --repo {owner}/{repo} --title ... --body-file <rendered body> --label "<key label>,gw-phase:..,gw-role:..,gw-kind:..,<not_ready label>"`, plus `--milestone "<release>"` when `phase_release` is `milestone` and the issue type (or a `gw-type:` label) from `work_type`: key and not-ready in the same call |
| update owned fields | Replace only the owned section of the body, keeping everything outside the markers |
| link parent | `POST repos/{owner}/{repo}/issues/{epic}/sub_issues` with the child's issue id |
| link dependency | `POST repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by` with the blocking issue id |
| comment | `gh issue comment {n} --body-file ...` |
| set or clear not-ready | `gh issue edit {n} --add-label` / `--remove-label` |

## plan_store

Mode `repo_path`: write each file once with the contents API to `{path}/{name}.json` on the overlay's branch (`PUT repos/{owner}/{repo}/contents/{path}/{name}.json` without a `sha`, which fails if the file exists). Never update or delete. Read with `GET .../contents/...`. Files over 900 KB are split into `{name}.part-<n>.json` with a small index file.

## lock

Post lock lines as comments on the epic, exactly as the core's `create_steps.py lock` gives them, then read all epic comments (`gh api repos/{owner}/{repo}/issues/{epic}/comments --paginate`) and give them to the script as `{ref: id, author_account_id: user.id, created_at, updated_at, body}`. Use the numeric `user.id`, not the login, as the account id.

## configure

Setup only, admin-approved, keyed and idempotent: `gh label create <name> --force` is not used (it overwrites); check with `gh label list` and create only missing labels.
