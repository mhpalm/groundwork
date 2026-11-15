# Capabilities, configuration discovery and readiness (Jira Cloud)

Rows marked (verify) are listed in `VERIFY.md`.

| Capability | Jira Cloud |
| --- | --- |
| Item types | From the project: Epic, Story, Task, Sub-task, and others. Story and Task sit at the same level under an epic |
| `work_type` | Story or Task issue type, per `field_map.work_types` |
| Phase release | A fix version per phase (`phase_release: version`); team-managed projects need the Releases feature on (verify) |
| `task_to_epic: parent` | The task's `parent` is the epic (verify) |
| `task_to_epic: linked` | An issue link of the overlay's chosen type to the epic |
| `steps_as: checklist` | Task list inside the owned description |
| `steps_as: subtasks` | Sub-task issues with no points |
| Dependencies | `Blocks` issue links (verify) |
| Blocked state | The field or label named by `field_map.blocked` (`Flagged` by default), set once at create by `set_blocked` for each task with a `waits_on`, plus open Blocks links (verify) |
| Close | A workflow transition to the status named in `field_map.statuses`, with a resolution where the transition allows it; `closed_not_done` lists the statuses and resolutions that mean not done, such as Won't Do and Duplicate |
| Points | The field named in `field_map.points` ("Story Points" in company-managed projects; "Story point estimate" in team-managed, verify) |
| Hours | `timetracking.originalEstimate` when `field_map.hours` is "Original Estimate" |
| Labels | Yes, no spaces (verify) |
| Comments | Yes, with created and updated times (verify) |
| Attachments | Yes; deletable by permitted users |
| Key slots | `label` (default: `gw-<last 10 of plan id>-<task id>`), `field` (a dedicated text field), `item_property` (only when an app indexes it for JQL) |
| Not-ready state | The overlay's `not_ready` label, and a workflow status if the overlay maps one |
| `search_consistency` | Treat JQL as possibly lagging; preflight trusts the manifest and waits 30 seconds before treating a manifest item as missing |
| Plan store | `attachments` on the epic |

## discover_config

Read-only: `GET /rest/api/3/project/{key}`, the project's issue types and create metadata (fields per type), `GET /rest/api/3/issueLinkType`, the project's statuses, and the field list (`GET /rest/api/3/field`). Field and status names are `untrusted_text`.

## readiness

| Need | Found when | Fallback | Create (setup, admin approval, `configure`) |
| --- | --- | --- | --- |
| Key slot | Labels enabled, or a named text field | none: a description marker alone is never accepted | A text field, by a Jira admin |
| Points | The mapped field is on the Task screen | none | Add the field to the screen, by a Jira admin |
| Hours | Time tracking on | Owned description only | Turn on time tracking, by a Jira admin |
| Blocked | `Flagged` available | Label `gw-blocked` | none |
| Dependencies | A link type that means "blocks" | Dependencies listed in the owned description | A link type, by a Jira admin |
| Epic and parent | Epic type exists and Task can have a parent | `task_to_epic: linked` | none |
| Work types | A Story type and a Task type the epic can parent | Map both to Task | none |
| Phase releases | Versions (Releases) available in the project | `phase_release: label` | Turn on Releases, by a project admin |
| Not-ready | Labels enabled | none | none |
| Plan store | Attachments enabled | none: setup blocks | none |
