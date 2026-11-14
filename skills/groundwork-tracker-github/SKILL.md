---
name: groundwork-tracker-github
description: "Groundwork tracker skill for GitHub Issues: maps approved plans to issues, sub-issues and dependencies, with idempotent writes. Use only inside a Groundwork run."
license: Apache-2.0
metadata:
  version: 1.0.0
  contract: "1.0"
  author: "Micah Palmquist, micah.palmquist@gmail.com"
---

# Groundwork tracker skill: GitHub Issues

This skill implements Groundwork contract 1.0 for GitHub Issues. It supplies GitHub Issues knowledge only; the core's rules govern every step (see the core's `reference/rules.md`). It writes only from a numbered write list an approver approved, and only through the core's create procedure.

## handshake

Do this first: append one line to the run's `handshakes.jsonl`:

```json
{"schema_version": "1.0", "name": "groundwork-tracker-github", "kind": "tracker", "version": "1.0.0", "release": "unreleased", "contract": "1.0", "platform": "github"}
```

## Sections

| Section | File |
| --- | --- |
| `connect`, `coverage` | `connect.md` |
| `capabilities`, `discover_config`, `readiness` | `capabilities.md` |
| `map`, `normalize` | `map.md` |
| `find_by_key`, `list_children`, `read_epic`, `write`, `plan_store`, `lock`, `configure` | `write.md` |
| `rules` | `rules.md`, `rules.json` |
