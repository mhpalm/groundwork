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
| Labels may not contain spaces | key label format | no (Groundwork's labels never contain spaces) |
| JQL search may lag new issues | search_consistency | no |
| Team-managed projects name the points field "Story point estimate" | readiness | no |
| Text field size limits | body size | no |
| Flagged field marks an issue as impeded | blocked state | no |
| Issue properties set by REST are not JQL-searchable without an app's index module | key slot choice | partly ([entity properties](https://developer.atlassian.com/cloud/jira/platform/jira-entity-properties/)) |

Confirmed: scoped API tokens exist and can be limited to read scopes such as `read:jira-work` ([manage API tokens](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/)).
