#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Fail if any commit in BASE..HEAD lacks a Signed-off-by line matching its author."""
import subprocess
import sys


def main(base, head):
    shas = subprocess.check_output(["git", "rev-list", f"{base}..{head}"], text=True).split()
    bad = []
    for sha in shas:
        author = subprocess.check_output(["git", "show", "-s", "--format=%an <%ae>", sha], text=True).strip()
        body = subprocess.check_output(["git", "show", "-s", "--format=%B", sha], text=True)
        if f"Signed-off-by: {author}" not in body:
            bad.append(f"{sha[:10]} ({author})")
    for b in bad:
        print(f"missing DCO sign-off: {b}. Fix with: git rebase --signoff {base}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
