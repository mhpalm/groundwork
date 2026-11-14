# Correctness rules (Jira Cloud tracker)

| Id | Applies when | Check | Severity | Source |
| --- | --- | --- | --- | --- |
| `jira.no-description-only-key` | Choosing the key slot | The key is in a label or a dedicated field, never only in the description | blocker | [docs](https://developer.atlassian.com/cloud/jira/platform/jira-entity-properties/) |
| `jira.scoped-read-token` | Discovery or preflight from local Claude Code with an API token | Coverage says read_only enforced only when the token was created with read scopes alone | minor | [docs](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/) |

More Jira rules wait on the confirmations listed in VERIFY.md.
