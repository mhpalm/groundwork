# Connect and coverage (Jira Cloud)

Per CR-08 and CR-12.

| Surface | Method | Identity check |
| --- | --- | --- |
| claude-code-local | Jira REST API with the runner's own scoped API token, held in the runner's environment or a tool's own store (never pasted into the conversation) | `GET /rest/api/3/myself` for `accountId`; the instance URL must equal the overlay's |
| claude-code-local, claude-code-cloud, claude-app | An Atlassian MCP connector the runner connected with their own account | The connector's "current user" tool and the site URL it reaches |

Least privilege: for discovery and preflight, a scoped API token with read scopes only (for example `read:jira-work`) gives `read_only: enforced`. Create needs write scopes, used only after approval.

Disclosure: "Your Jira API token or connector sign-in stays in the place you put it (your environment, a credential store, or the connector). Groundwork never reads, copies or saves it."

Coverage reports which configuration was read (project, issue types, fields, link types, workflow states) and `read_only` status. Groundwork never reads issues' free text during discovery.
