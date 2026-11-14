# Connect and coverage (GitHub Issues)

Per CR-08 and CR-12. The tracker instance is a repository (`owner/repo`) named in the overlay's `skills.tracker.instance.project`; the instance URL is the org.

| Surface | Method | Identity check |
| --- | --- | --- |
| claude-code-local | GitHub CLI (`gh`) signed in by the runner | `gh api user --jq .login`; `gh api repos/{owner}/{repo} --jq .full_name` |
| claude-code-cloud | The session's GitHub tools | The tools' "get me" call and a read of the repo |
| claude-app | A GitHub connector | Its identity tool; otherwise coverage `partial` |

Discovery and preflight need read access to issues and contents. Create needs write access to issues (and contents, for the plan store). Each person uses their own account; approvals are only valid from the approver's own account.

Disclosure: "The GitHub CLI (or connector) keeps your sign-in in its own store: your system credential store when one is available, otherwise a plain-text file in its config folder. Groundwork never reads, copies or saves it."

Coverage reports what configuration was read (labels, issue types, sub-issue and dependency support, projects) and `read_only` status.
