#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Fail on org-specific content in the shared repo.

- No overlay files outside tests/golden and the core's template.
- No email addresses except in attribution fields (SPDX headers, frontmatter
  author, NOTICE) and reserved example domains.
- No hostnames except reserved example domains and an allow-list of
  platform documentation and service hosts.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKIP_DIRS = {".git", "__pycache__", "dist", "plugin"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
URL_HOST = re.compile(r"https?://([A-Za-z0-9.-]+)")
EXAMPLE = re.compile(r"((^|\.)example\.(com|org|net|edu)|^example(-org)?\.atlassian\.net)$")  # placeholder Jira site used in docs and fixtures
ALLOWED_HOSTS = {
    "docs.github.com", "cli.github.com", "github.com", "api.github.com", "developer.atlassian.com", "support.atlassian.com",
    "code.claude.com", "support.claude.com", "claude.ai", "claude.com", "www.apache.org", "apache.org", "opensource.org",
    "developercertificate.org", "polyformproject.org", "json-schema.org", "www.rfc-editor.org", "datatracker.ietf.org",
    "localhost", "anthropic.com",
}
ATTRIBUTION = re.compile(r"(Copyright 2026|author:|Co-Authored-By|noreply@anthropic.com)")
TEXT_EXT = (".md", ".py", ".json", ".yaml", ".yml", ".txt", ".j2", "")


def main():
    errors = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_root = os.path.relpath(root, ROOT)
        for f in files:
            if not f.endswith(TEXT_EXT) or f in ("LICENSE",):
                continue
            rel = os.path.normpath(os.path.join(rel_root, f))
            if f == "overlay.yaml" and not (rel.startswith("tests/golden/") or rel.startswith("skills/groundwork-core/templates/")):
                errors.append(f"{rel}: overlay files never belong in the shared repo")
            try:
                text = open(os.path.join(root, f), encoding="utf-8").read()
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for m in EMAIL.finditer(line):
                    dom = m.group(0).split("@", 1)[1].lower()
                    if EXAMPLE.search(dom) or ATTRIBUTION.search(line) or rel in ("NOTICE", ".github/CODEOWNERS"):
                        continue
                    if rel.startswith("tests/") or rel.startswith("tools/lint"):
                        continue  # seeded defects and lint patterns
                    errors.append(f"{rel}:{n}: email address outside an attribution field")
                for m in URL_HOST.finditer(line):
                    host = m.group(1).lower().rstrip(".")
                    if EXAMPLE.search(host) or host in ALLOWED_HOSTS:
                        continue
                    errors.append(f"{rel}:{n}: host '{host}' is not a reserved example domain or an allowed platform host")
    for e in errors:
        print(e)
    print(f"lint_no_org_data: {len(errors)} problem(s)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
