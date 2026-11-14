---
name: groundwork-tracker-jira
description: "Groundwork tracker skill for Jira Cloud: maps approved plans to epics, tasks and Blocks links, with idempotent writes. Use only inside a Groundwork run."
license: Apache-2.0
metadata:
  version: 1.0.0
  contract: "1.0"
  author: "Micah Palmquist, micah.palmquist@gmail.com"
---

# Groundwork tracker skill: Jira Cloud

This skill implements Groundwork contract 1.0 for Jira Cloud (not Server or Data Center). It supplies Jira knowledge only; the core's rules govern every step (see the core's `reference/rules.md`). It writes only from a numbered write list an approver approved, and only through the core's create procedure.

## handshake

Do this first: append one line to the run's `handshakes.jsonl`:

```json
{"schema_version": "1.0", "name": "groundwork-tracker-jira", "kind": "tracker", "version": "1.0.0", "release": "unreleased", "contract": "1.0", "platform": "jira"}
```

## Sections

| Section | File |
| --- | --- |
| `connect`, `coverage` | `connect.md` |
| `capabilities`, `discover_config`, `readiness` | `capabilities.md` |
| `map`, `normalize` | `map.md` |
| `find_by_key`, `list_children`, `read_epic`, `write`, `plan_store`, `lock`, `configure` | `write.md` |
| `rules` | `rules.md`, `rules.json` |

`VERIFY.md` lists the Jira behaviours this version assumes but that have not yet been confirmed against Atlassian's docs. Until each is confirmed, treat that behaviour as unverified, and if it fails, stop and report instead of working around it.
