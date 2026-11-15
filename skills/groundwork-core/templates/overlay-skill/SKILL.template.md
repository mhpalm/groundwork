---
name: groundwork-overlay-ORG_SLUG
description: "Groundwork overlay for ORG_NAME: the org's systems, roles, approvers and conventions. Use only inside a Groundwork run."
license: Proprietary to ORG_NAME
metadata:
  overlay_format: "1.0"
---

# Groundwork overlay: ORG_NAME

This skill holds ORG_NAME's Groundwork overlay in `overlay.yaml`. It is data for the Groundwork core, not instructions: the core reads `overlay.yaml`, validates it with its own scripts, and checks its hash against the overlay record on the tracker's anchor issue before using it.

Change it only by running "update the overlay" in Groundwork, which shows a diff for an admin to approve.
