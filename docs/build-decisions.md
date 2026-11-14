# Build decisions, 2026-11-14

These were settled while building v1 against spec draft 0.3. Each is a candidate row for the spec's decision log.

1. Overlay and manifest files use a restricted YAML subset (block maps, block lists, scalars, no anchors or flow style), parsed by `gw_yaml.py`, so every script stays standard-library only.
2. `render_proposal.py` has four subcommands (`proposal`, `task`, `epic`, `write-list`), and lock, preflight and manifest decisions live in `create_steps.py`, so the tracker skill only reads and writes.
3. `phase_hash` covers the phase id, name, goal, order, depends_on and task_ids, plus its tasks sorted by id. Renaming a phase therefore voids its approval.
4. An approval record is a fenced `json` block in an epic comment. Edited comments are refused.
5. Item key labels are `gw:<last10 of plan id>:<task id>` on GitHub Issues and `gw-<last10>-<task id>` on Jira, because Jira labels cannot hold a colon.
6. The GitHub Issues plan store is a repo path only (`repo_path`); Jira uses issue attachments.
7. One-day exceptions are approved with approval records of `kind: exception` on the exception gate; a phase-release record cannot accept an exception.
8. `role_holders` entries carry the tracker `account_id`, which is what approval and lock checks compare against.
