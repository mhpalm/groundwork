#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Run every deterministic check CI runs on a pull request."""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHECKS = [
    ["python3", "tools/gen/make_schemas.py", "--check"],
    ["python3", "tools/lint_boundaries.py"],
    ["python3", "tools/lint_no_org_data.py"],
    ["python3", "skills/groundwork-core/scripts/validate_overlay.py", "tests/golden/G1/overlay/overlay.yaml"],
    ["python3", "-m", "unittest", "discover", "-s", "tests/unit"],
]


def main():
    failed = []
    for cmd in CHECKS:
        print("$ " + " ".join(cmd), flush=True)
        if subprocess.call(cmd, cwd=ROOT) != 0:
            failed.append(" ".join(cmd))
    if failed:
        print("\nFailed:\n  " + "\n  ".join(failed))
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
