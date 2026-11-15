# Reads, writes, plan store and lock (Jira Cloud)

Every write comes from the approved numbered write list, through the core's create procedure.

## find_epics

JQL `project = {project} AND issuetype = Epic AND statusCategory != Done AND text ~ "{terms}" ORDER BY updated DESC`, `maxResults=10`, `fields=summary,status,updated`. Summaries are `untrusted_text`. Terms are the runner's own words, quoted and with JQL reserved characters escaped.

## find_by_key

JQL `project = {project} AND labels = "{key label}"` with `fields=summary,description,labels,updated,{points field}`. Zero or one result. More than one is an error: report both.

## list_children

JQL `parent = {epic key}` (or the link type for `linked`), with the same fields.

## read_epic

The epic and its children as plan-shaped data, every summary, description and comment marked untrusted. Each item also carries its raw state for the core's `create_steps.py status`: `state` (`closed` when its status category is Done, else `open`), `category` (`in_progress` or `todo`, from the status category), `closed_as` (the status name and the resolution name) and `labels`.

## read_scope

Read-only, for assess. Scope is one epic (`parent = {epic}`) or one project key plus a JQL filter the runner gives (quoted, reserved characters escaped). First the count: `POST /rest/api/3/search/approximate-count` with the JQL (verify), or a search with `maxResults=0`. Pass it to the core's `create_steps.py scope`; if it refuses, stop and ask the runner to narrow. Otherwise page through `fields=summary,status,resolution,parent,issuelinks,updated,{points field}`; summaries, descriptions and comments go to working text, marked untrusted. Never read who can see an issue.

## write

| Write | Call |
| --- | --- |
| ensure release | `GET /rest/api/3/project/{project}/versions`; if no version has exactly the write's `name`, `POST /rest/api/3/version` with `name` and `projectId` (verify). Never rename, release or delete a version: releasing it is the team's act |
| create item | `POST /rest/api/3/issue` with `issuetype` from `work_type`, `fixVersions` set to the write's `release` when `phase_release` is `version` (verify), `summary`, ADF `description`, `labels` (key, phase, role, kind, not-ready), points field, `timetracking`, and `parent` when `task_to_epic` is parent: key and not-ready in the same call |
| update owned fields | Replace only the owned section of the description, keeping all other content |
| link dependency | `POST /rest/api/3/issueLink` with type Blocks, `inwardIssue` the task, `outwardIssue` the dependency |
| comment | `POST /rest/api/3/issue/{key}/comment` |
| set or clear not-ready | `PUT /rest/api/3/issue/{key}` with `update.labels` add or remove |
| set_blocked | When `field_map.blocked` is `Flagged`: `PUT /rest/api/3/issue/{key}` setting the Flagged field to Impediment (verify); when it is a label: `update.labels` add. Read it back. Clearing is the assignee's or the wait owner's act |
| add label | `PUT /rest/api/3/issue/{key}` with `update.labels` add `gw-closed:<reason>` |
| close | `GET /rest/api/3/issue/{key}/transitions`, pick the first transition whose target status (or the resolution it sets) is listed in `field_map.statuses.done` for completed, or in `closed_not_done` for the other reasons. If none, if it needs a screen field, or if it takes more than one hop, stop with "needs a person" naming the item; it stays close pending. `POST .../transitions` with that id, and set `resolution` only if the transition accepts it (verify). Read back status and resolution. Skip an item already in a Done category |

## plan_store

Attach each file to the epic once (`POST /rest/api/3/issue/{epic}/attachments`, header `X-Atlassian-Token: no-check`), named as the core specifies. Before attaching, list the epic's attachments; if a file with that name exists, do not attach again. Never delete an attachment.

## lock

Post lock lines as epic comments exactly as the core's `create_steps.py lock` gives them, then read all epic comments and pass them as `{ref: id, author_account_id: author.accountId, created_at: created, updated_at: updated, body: plain text of the ADF}`.

## configure

Setup only, admin-approved, keyed and idempotent: check the field, screen or link type first and change nothing that already exists. Field creation uses the admin's own account.
