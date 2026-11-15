<!-- SPDX-License-Identifier: Apache-2.0 -->
# The skill contract (1.0)

The contract is a versioned list of sections and structured outputs that every system or tracker skill MUST provide, defined in `groundwork-core/reference/contract.md` with JSON Schemas in `groundwork-core/schemas/`. Skills are instructions, not code, so each "interface" is a required section of the skill plus the exact shape of what Claude produces when following it. The core supplies the rules every section runs under (CR-01 to CR-12); a skill refers to them by id and never restates them. This file defines contract 1.0.

## Manifest (both kinds)

Every system and tracker skill ships a `groundwork.yaml` next to its `SKILL.md`. The handshake block repeats the same fields so surfaces that cannot read sibling files still get them, and CI checks that frontmatter, manifest and handshake agree.

```yaml
schema_version: "1.0"
kind: system            # system | tracker
name: groundwork-system-github
platform: github        # lowercase slug, unique per kind
version: 1.2.0          # semver of this skill
release: v1.4.0         # repo release tag that shipped this copy (set by the release build)
contract: "1.0"         # contract MAJOR.MINOR this skill meets
surfaces:               # what works where; honest, not aspirational
  claude-code-local: {connect: [cli, mcp], coverage: full}
  claude-code-cloud: {connect: [mcp], coverage: partial}
  claude-app: {connect: [mcp], coverage: partial}
rule_prefix: github     # prefix for its correctness rule ids
```

Attribution and license live in `SKILL.md` frontmatter under `license` and `metadata`, never in the instruction text.

## System skill interface

| Section | Required output | Notes |
| --- | --- | --- |
| `handshake` | Handshake record (contract.md (loading)) | First thing the skill does |
| `connect` | Per surface: methods, the least privilege that suffices (read-only scoped tokens where the platform has them), how to report the signed-in identity and instance, and the disclosure text about any sign-in the platform's own tool stores | Feeds the CR-12 identity check and the CR-08 disclosure |
| `discover` | Evidence items (plan-format.md) for the scope the core passes in | Lists its read calls as call templates with scope bounds (for example, "read file X in each repo listed") before running them; declares which items must be re-checked before create (`recheck: true`) |
| `evidence_types` | A JSON Schema for the `facts` of each subject type it produces | Strings in `facts` are enums or ids; any other text goes in `untrusted_text` |
| `coverage` | For the current surface, per instance: what was inspected, what could not be and why, and `read_only: enforced` or `instructed_only` | Feeds the coverage table |
| `rules` | Correctness rules: `id`, `applies_when`, `check`, `severity`, `source` (platform docs link) | Ids are `<rule_prefix>.<slug>`, stable across versions |
| `readiness` | Checks that an org's instance has what plans on it will need (for example, a required CI check) | Report only in v1; system skills never write |
| `expectations` | Expectations setup mode proposes to the admin (for example, "default branch is protected") with how to check each | Confirmed values go in the overlay |
| `breakdown` | Task patterns: name, when to use, steps, relative size (S, M or L), verify method, generic roles, visible result type | The planner converts size to hours for the overlay's executor; an L pattern must still fit one day |
| `standard_work` | How testing, UAT, cutover, rollback, documentation and handoff work on this platform | E.g. how a deploy is rolled back |

## Tracker skill interface

| Section | Required output | Notes |
| --- | --- | --- |
| `handshake`, `connect`, `coverage` | As for system skills |  |
| `capabilities` | Item types; hierarchy options and how each renders (`checklist`, `subtasks`); dependency links; how "blocked" is shown; points and hours fields; labels; comments and size limits; attachments and size limits; key slot types it supports; a not-ready state for new items; `search_consistency` with a wait in seconds | Read at setup and checked on every run |
| `discover_config` | Item types, fields, workflow states, link types, as evidence marked untrusted | Used by setup and create preflight |
| `map` | How every plan field lands in the tracker: title, phase, role, kind, points, hours, parallel group, dependencies, blocked state and `waits_on`, steps, acceptance criteria, visible result, key, plan-owned hash, not-ready flag | The readiness list is derived from this map; a companion normalize procedure reads written fields back for the plan-owned hash |
| `readiness` | The fields and settings `map` needs, found or missing, from `discover_config` | Drives the setup field readiness pass |
| `configure` | Procedure to create a missing field or label, as a keyed, idempotent, held write | Only in setup mode, only with an admin's approval |
| `list_children` | Every item under an epic with its tracker id, key, plan-owned hash and last-updated time | Cross-checks find\_by\_key and lists an epic |
| `find_epics` | Up to 10 open epics in the overlay's project whose title or summary matches the given terms: tracker key, title (untrusted), status, last updated | Intake only, read-only; the runner picks, never the core |
| `find_by_key` | Zero or one item for a key, `searched across the whole tracker project` | More than one is an error, never a pick |
| `read_epic` | The epic and its items as plan-shaped data, every free-text field marked untrusted | Used by release, revise and preflight |
| `write` | Ensure a phase's release container exists by exact name (a version, milestone or label; never renamed, released or deleted), create item (work type, release container, key and not-ready flag set in the same call), update plan-owned fields, add link, add comment, set or clear not-ready | Only after approval, from the numbered write list |
| `plan_store` | Put and get immutable, versioned files for the epic (plan of record, snapshots, manifest), with size limits and chunking | `Naming in approval-create.md; never overwritten by Groundwork, tampering detected by hashes` |
| `lock` | Claim and release a run lock on the epic with runner id and expiry | Protocol in approval-create.md |
| `rules` | Tracker correctness rules, same shape as system rules | E.g. hierarchy depth limits |

A description marker is never accepted as the only key slot, because a person editing the description can remove it. If the tracker has no robust key slot (a label, a dedicated field or an item property) available to the org, the readiness pass blocks setup.

## Generic role keys

Skills name roles with generic keys: `developer`, `admin`, `analyst`, `qa`, `business_user`, `trainer`, `comms`, `maintainer`, `approver`. The overlay maps each key to the org's role name. Plans store the key; the name is looked up at render time, so renaming a role in the overlay does not leave stale names. A pattern that needs a role the overlay doesn't map is a gap-review blocker.

## Contract versioning and compatibility checks

The contract uses semver. A MINOR release only adds optional sections or optional fields. A MAJOR release removes, renames or changes the meaning of anything, and ships with a migration note for skill authors and, if overlays are affected, an overlay migration (setup-mode.md).

The core runs these checks on every handshake, before discovery:

1. The core's version is inside the overlay's `skills.core` range.
2. The skill's contract MAJOR equals the core's. If not, the skill is refused.
3. The skill's `version` is inside the overlay's range for it. If not, it is refused and the plan reports which version loaded.
4. The manifest and the `rules` list validate against their schemas, and every required section for its kind is present.
5. Rule ids start with its `rule_prefix` and don't collide with another loaded skill.
6. Instruction hashes match `SHA256SUMS` for the declared release (`verified`), cannot be read (`unverified`), or differ (`mismatch`, refused).
7. A skill whose contract MINOR is higher or lower than the core's is accepted, because MINOR changes are optional by definition; sections one side doesn't know are ignored and noted.

A refused system skill means that system is not inspected. A refused tracker skill stops the run before Proposal. Every result goes into `stamps.compat`.

## How the core loads system and tracker skills

1. **Every Groundwork skill is a standalone skill folder.** The same folder works as a claude.ai account skill, a Claude app ZIP, a personal or project skill in Claude Code, and inside the optional plugin. No skill depends on a file path inside another skill.
2. **The overlay names what to load.** `skills` lists each system and tracker skill by name with a version range (setup-mode.md).
3. **The core asks for each skill by name.** In Claude Code it invokes the skill by name. Elsewhere it names the skill in its instructions and relies on Claude using several skills together. Every Groundwork description starts with "Groundwork" and says the skill is used only inside a Groundwork run, which keeps it from firing in unrelated chats and inside the 200-character app limit.
4. **Each loaded skill performs a handshake.** The first instruction in every system and tracker SKILL.md is to write a handshake record into the run log: name, version, release tag, contract version, platform.
5. **The core verifies the handshake with a script.** `check_compat.py` hashes each skill's instruction files where the surface lets it read them and compares against the release's published `SHA256SUMS` (the repo README). The result is `verified`, `unverified` (files not readable on this surface) or `mismatch`. A mismatch is refused, which also catches a lookalike skill with the same name. A write-capable tracker skill that is unverified may write only if every approval record accepts that explicitly (approval-create.md). Every result goes into `stamps.compat`.
6. **No scripts, no proposal.** Hashing, validation and rendering are done by scripts, never by the model. On a surface where scripts cannot run (for example, the Claude app with code execution off), the core says so in plain words and can still clarify and discover, but it cannot propose or create.
7. **Compatibility check (contract.md).** A missing or refused system skill marks that system "not inspected" with the reason, and the run continues with reduced coverage. A missing or refused tracker skill stops the run before Proposal.
8. **One org per run (CR-12).** If more than one overlay is visible, the core asks the runner which org this run is for and uses only that overlay. At Intake, before any discovery call, every system and tracker skill's `connect` reports the signed-in identity and the instance it reaches, and the core checks each against the overlay's instances. A mismatch stops that system. Run folders are namespaced `runs/<overlay.id>/<plan.id>/`, and the epic carries the overlay id so later runs refuse a different overlay.
9. **Read-only is enforced where the surface allows it (CR-01).** In local Claude Code the core shows a recommended permission profile that denies the platforms' write tools until stage 9, and the runner applies it if they choose (it is a settings change, so it is the runner's write, not Groundwork's). Each `connect` section prefers read-only scoped tokens. Where neither is possible, coverage records `read_only: instructed_only` for that system so the approver can see it.
10. **Nothing at runtime edits an installed skill.** Shared skills change only by pull request. Overlays change only through setup mode with an admin's approval.

Shadowing risk: a stale personal copy of a skill outranks a newer project copy in local Claude Code. The handshake's version and hash checks report which copy actually loaded.

**Cards on every surface.** Where question cards are available, the core uses them. Elsewhere it asks the same questions as a numbered list with the recommended answer marked, and records answers the same way.

## Boundaries

| Skill | Holds | Must not hold | Changes through |
| --- | --- | --- | --- |
| `groundwork-core` | Pipeline, core rules CR-01 to CR-12, all schemas, gap review checklist, setup, release and revise modes, the contract, validator, hashing and renderer scripts, migrations | Anything about one platform beyond what the contract defines; any org fact | PR to the shared repo |
| `groundwork-system-<platform>` | Connecting from each surface, read-only discovery, typed evidence shapes, the platform's correctness rules, readiness checks, expectations to propose at setup, one-day breakdown patterns | Core rule text, org facts, credentials, any write procedure | PR to the shared repo |
| `groundwork-tracker-<tracker>` | Connecting, capabilities and limits, field mapping, read procedures, idempotent write, configure, plan store and lock procedures, the tracker's correctness rules | Core rule text, org facts, credentials | PR to the shared repo |
| `groundwork-overlay-<org>` | The org's systems and instances, working day, assumed executor, roles, hierarchy, gates and approver account ids, naming, expectations, field maps, which skills to load | Anything that loosens a core rule, credentials, record-level data | Setup mode, approved by an admin; kept in the org's own storage |

A system or tracker skill MAY add checks that make gap review stricter for its platform. It MUST NOT relax or redefine a core rule. The boundary lint (the repo's tests) fails any skill that contains one of the normative sentences listed in `reference/rules.md`.
