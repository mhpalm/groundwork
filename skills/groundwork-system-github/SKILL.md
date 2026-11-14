---
name: groundwork-system-github
description: "Groundwork system skill for GitHub: read-only discovery of repos, workflows and environments, and GitHub's correctness rules. Use only inside a Groundwork run."
license: Apache-2.0
metadata:
  version: 1.0.0
  contract: "1.0"
  author: "Micah Palmquist, micah.palmquist@gmail.com"
---

# Groundwork system skill: GitHub

This skill implements Groundwork contract 1.0 for GitHub. It supplies GitHub knowledge only. The core's rules apply to everything here; where this skill seems to conflict with them, the core's rules win (see the core's `reference/rules.md`).

## handshake

Do this first, before anything else in this skill: append one line to the run's `handshakes.jsonl`:

```json
{"schema_version": "1.0", "name": "groundwork-system-github", "kind": "system", "version": "1.0.0", "release": "unreleased", "contract": "1.0", "platform": "github"}
```

The release build replaces `unreleased` with the release tag.

## Sections

| Section | File |
| --- | --- |
| `connect`, `coverage` | `connect.md` |
| `discover`, `evidence_types` | `discover.md`, `evidence-types.json` |
| `rules` | `rules.md` (people), `rules.json` (scripts) |
| `readiness`, `expectations` | `readiness.md` |
| `breakdown`, `standard_work` | `breakdown.md` |

Read only the file the core's current stage needs.
