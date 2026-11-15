# Capabilities, configuration discovery and readiness (GitHub Issues)

## Capabilities

| Capability | GitHub Issues |
| --- | --- |
| Item types | Issue; issue types where the org has them |
| `work_type` | The org issue type in `field_map.work_types`, else a `gw-type:story` or `gw-type:task` label |
| Phase release | A milestone per phase (`phase_release: milestone`) |
| Epic | An issue labelled with the overlay's epic label |
| `task_to_epic: parent` | Sub-issue of the epic ([sub-issues API](https://docs.github.com/en/rest/issues/sub-issues)); the sub-issue must belong to the same repository owner as the parent |
| `task_to_epic: linked` | A "Part of" line in the owned body plus the key label |
| `steps_as: checklist` | Markdown task list inside the owned body |
| `steps_as: subtasks` | Sub-issues of the task with no points |
| Dependencies | "Blocked by" issue dependencies ([issue dependencies API](https://docs.github.com/en/rest/issues/issue-dependencies)) |
| Blocked state | An open "blocked by" dependency, plus the `gw-blocked` label while any `waits_on` is open |
| Points | A GitHub Projects number field named in `field_map.points`, or a `points:1` label |
| Hours | A Projects number field named in `field_map.hours`, or the owned body only |
| Labels | Yes |
| Comments | Yes, with `created_at` and `updated_at` ([comments API](https://docs.github.com/en/rest/issues/comments)) |
| Attachments | No API for issue attachments |
| Key slots | `label` (one label per item, `gw:<plan id short>:<task id>`) or `field` (an issue field, where the org has them) |
| Not-ready state | The overlay's `not_ready` label; GitHub has no workflow state, so a person can remove it early and release mode reports that |
| `search_consistency` | Search can lag new issues; preflight trusts the manifest and waits 60 seconds before treating a manifest item as missing |
| Plan store | `repo_path` only: files committed to a branch and folder the overlay names |

Size limits for issue bodies and comments are not stated in GitHub's docs as read on 2026-11-14; keep each body under 60,000 characters and split plan-store files rather than putting them in comments.

## discover_config

Read, read-only: labels (`gh label list --limit 500 --json name`), whether sub-issues and dependencies are enabled (read one existing issue's sub-issue and dependency endpoints), linked Projects and their fields if `field_map` names one, and the plan-store branch and folder. Free text (label descriptions, issue titles) is `untrusted_text`.

## readiness

| Need | Found when | Fallback | Create (setup, admin approval) |
| --- | --- | --- | --- |
| Key slot | Label slot always available | none needed | Labels are created as items are written |
| Not-ready label | Label exists | none | Create label `gw-not-ready` |
| Draft label | Label exists | none | Create label `gw-draft` |
| Blocked label | Label exists | none | Create label `gw-blocked` |
| Sub-issues | Endpoint answers | `task_to_epic: linked` | Not creatable by Groundwork |
| Dependencies | Endpoint answers | Dependencies listed in the owned body, blocked label | Not creatable by Groundwork |
| Points field | Projects field exists | `points:1` label | Projects field, by an admin |
| Plan store | Branch and folder exist and the runner can write contents | none: setup blocks | Folder, by an admin commit |
