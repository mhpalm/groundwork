# Capabilities, configuration discovery and readiness (Jira Cloud)

Rows marked (verify) are listed in `VERIFY.md`.

| Capability | Jira Cloud |
| --- | --- |
| Item types | From the project: Epic, Task, Sub-task, and others |
| `task_to_epic: parent` | The task's `parent` is the epic (verify) |
| `task_to_epic: linked` | An issue link of the overlay's chosen type to the epic |
| `steps_as: checklist` | Task list inside the owned description |
| `steps_as: subtasks` | Sub-task issues with no points |
| Dependencies | `Blocks` issue links (verify) |
| Blocked state | The `Flagged` field while any `waits_on` is open, plus open Blocks links (verify) |
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
| Not-ready | Labels enabled | none | none |
| Plan store | Attachments enabled | none: setup blocks | none |
