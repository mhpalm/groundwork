# Groundwork

Groundwork is a set of Claude skills that turns "create project X" into one reviewed, approved epic in your organization's tracker. Every task in the epic is one point, fits in one working day, and carries instructions a junior developer can follow without asking anyone.

The plan is grounded in read-only evidence from your real systems, checked by a validator and an independent reviewer before anyone sees it, approved phase by phase, and only then written to the tracker.

## What is in this repo

| Skill | What it does |
| --- | --- |
| `groundwork-core` | The pipeline, core rules, plan format, gap review, setup, release and revise modes, the skill contract, and the scripts that validate, hash and render plans |
| `groundwork-system-github` | Read-only discovery of GitHub repos, workflows and environments, and GitHub's own correctness rules |
| `groundwork-tracker-github` | Writes approved plans to GitHub Issues |
| `groundwork-tracker-jira` | Writes approved plans to Jira Cloud |

Your organization's overlay (systems, roles, approvers, naming) is a separate skill that setup mode creates for you. It stays with your organization and never belongs in this repo.

## Install

Every skill folder under `skills/` is a standalone skill. Install the same release on every surface your team uses.

- **Claude app and Claude Code cloud sessions.** Download the skill ZIPs from a release and upload each one in Customize > Skills. Org owners can provision them to every member. Skills on your claude.ai account also load in Claude Code cloud sessions, including project threads.
- **Claude Code, local.** Sign in with the claude.ai account that has the skills, or add the marketplace and install the plugin:

  ```
  /plugin marketplace add <owner>/groundwork#vX.Y.Z
  /plugin install groundwork@groundwork
  ```

Code execution must be on: Groundwork's validation, hashing and rendering are done by scripts, never by the model, and without them it can clarify and discover but cannot propose or create.

## First use

Ask Claude to "set up Groundwork". Setup mode asks which systems and tracker you use, connects to each with your own sign-in, inspects them read-only, checks that every tracker field it needs exists, and asks an admin to confirm everything before anything is written. The result is your overlay skill.

Then ask "create project <what you want>".

## Rules that never change

Groundwork is read-only until a person approves a numbered list of writes. It never saves credentials. Text read from your systems is treated as data, never as instructions. Evidence records structure, configuration and counts, never personal or financial records. See `skills/groundwork-core/reference/rules.md`.

## Contributing

See `CONTRIBUTING.md`. Every commit needs a DCO sign-off. The maintainer reviews and merges every change.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
