# Correctness rules (GitHub Issues tracker)

| Id | Applies when | Check | Severity | Source |
| --- | --- | --- | --- | --- |
| `github.sub-issue-same-owner` | task_to_epic is parent | The epic and every task issue are in repositories with the same owner | blocker | [docs](https://docs.github.com/en/rest/issues/sub-issues) |
| `github.approval-from-own-account` | Any approval | Approval records are read from issue comments by the numeric user id of the comment's author, and a comment with updated_at different from created_at is refused | blocker | [docs](https://docs.github.com/en/rest/issues/comments) |
