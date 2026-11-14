# Connect and coverage (GitHub)

Per CR-08 and CR-12. Use the runner's own GitHub access on every surface. Prefer the least privilege that covers discovery.

## Methods by surface

| Surface | Method | How to check identity and instance |
| --- | --- | --- |
| claude-code-local | GitHub CLI (`gh`), signed in by the runner with `gh auth login` | `gh auth status` for the account; `gh api user --jq .login`; `gh api orgs/<org> --jq .login` for each overlay instance |
| claude-code-local | A GitHub MCP server the runner configured | The server's "get me" tool, then read the org |
| claude-code-cloud | The session's GitHub connection (MCP tools or `gh` provided by the environment) | Same as above; the session may only reach repositories attached to it |
| claude-app | A GitHub connector the runner connected | The connector's identity tool, if it has one; otherwise coverage is `partial` with the reason |

## Least privilege

- Best: a fine-grained personal access token limited to the overlay's org and the repositories in scope, with read-only repository permissions (Contents, Metadata, Actions, Administration, Environments, Pull requests: read). With such a token, coverage records `read_only: enforced`.
- Otherwise the runner's normal sign-in, with Groundwork's read-call list as the only calls made. Coverage records `read_only: instructed_only`.
- Never ask the runner to paste a token into the conversation, and never write one to a file.

## Disclosure to show at Authenticate

"The GitHub CLI (or connector) keeps your sign-in in its own store: your system credential store when one is available, otherwise a plain-text file in its config folder. Groundwork never reads, copies or saves it. To remove it, run `gh auth logout` or disconnect the connector."

## Identity check

Report `{account: <login>, instance: <org url>, org_reached: <org login>}` for each overlay instance. The core compares `org_reached` with the instance's `expected_identity.org`. If the signed-in account can't see the expected org, report that; never switch to another org.

## Coverage

For each instance, report what was read, what could not be and why (for example "branch protection: needs admin read on the repo", "environments: connector has no environments tool"), and `read_only: enforced` or `instructed_only`. Branch protection, rulesets and environment reviewers often need admin-level read access; when they can't be read, say so rather than assuming defaults.
