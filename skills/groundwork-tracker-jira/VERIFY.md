# Jira behaviours to confirm before release

Checked 2026-11-14. Atlassian's REST reference pages render client-side, so these could not be read by the fetch tool used. Each must be confirmed (and this file trimmed) before this skill's first release.

| Assumption | Used by | Confirmed |
| --- | --- | --- |
| `POST /rest/api/3/issue` accepts `labels` and `parent` in the create call | write: key and not-ready set at create | no |
| Descriptions in v3 are Atlassian Document Format; the owned markers survive as paragraph text | map, normalize | partly: ADF is the stored format for comments and textarea fields ([ADF structure](https://developer.atlassian.com/cloud/jira/platform/apis/document/structure)) |
| Comments carry `created`, `updated` and `author.accountId` | approval edit check, lock | no |
| `accountId` is the stable user id | approval records, gates | no |
| `POST /rest/api/3/issueLink` creates a Blocks link | dependencies | no |
| Attachments: `POST /rest/api/3/issue/{id}/attachments` with `X-Atlassian-Token: no-check`; size limit | plan store | no; attachments can be deleted by permitted users (a `delete:attachment:jira` scope exists, [scopes](https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/)), so tampering is detected by hashes, not prevented |
| `POST /rest/api/3/version` with `name` and `projectId` creates a version; `GET /rest/api/3/project/{key}/versions` lists them; names are unique per project | ensure_release | no |
| `fixVersions` can be set in the create call by name or id | create item | no |
| Team-managed projects expose versions only when the Releases feature is on | readiness | no |
| Labels may not contain spaces | key label format | no (Groundwork's labels never contain spaces) |
| JQL search may lag new issues | search_consistency | no |
| Team-managed projects name the points field "Story point estimate" | readiness | no |
| Text field size limits | body size | no |
| Flagged field marks an issue as impeded, and can be set by `PUT /rest/api/3/issue/{key}` | blocked state, set_blocked | no |
| `GET /rest/api/3/issue/{key}/transitions` lists each transition's target status and required fields; a resolution can be set only on transitions whose screen has it | close | no |
| A label may contain a colon (`gw-closed:not_planned`) | close labels | no; if not, setup sets `close_label_prefix` to `gw-closed-` |
| `POST /rest/api/3/search/approximate-count` returns a count for a JQL query | read_scope | no |
| The connector's HTML read-back of a heading, bullet list, task list, table, rule and expand parses with `jira_body.py read` to the Markdown that was written | normalize | no; the round trip is tested against the writer's own HTML, not yet against Jira's echo |
| An `expand` node in a description is kept when a person edits text above or below it in the Jira editor | owned section boundary | no |
| Issue properties set by REST are not JQL-searchable without an app's index module | key slot choice | partly ([entity properties](https://developer.atlassian.com/cloud/jira/platform/jira-entity-properties/)) |

Confirmed: scoped API tokens exist and can be limited to read scopes such as `read:jira-work` ([manage API tokens](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/)).
