# Changelog

## Unreleased

- Fixed: `groundwork-core.zip` was rejected by the Claude app because the overlay template's `SKILL.md` made two in one ZIP. The template is now `templates/overlay-skill/SKILL.template.md`; the release build, boundary lint and release tests all refuse a skill with more than one `SKILL.md`.
- First implementation of the approved Groundwork v1 spec (draft 0.3, approved 2026-11-14): core skill, contract 1.0, plan format 1.0, overlay format 1.0, GitHub system skill, GitHub Issues and Jira Cloud tracker skills, golden project G1.
