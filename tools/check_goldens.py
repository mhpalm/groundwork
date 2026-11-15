#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Fails when a golden on disk differs from what the generators produce.

Regenerates every golden, compares each file with what was there before, then
puts the original files back, so the check never changes the working tree. Some golden
files are hand-written inputs (G1 assertions), so a file the generators no longer
write is not detected; remove a retired golden by hand.
"""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GOLDEN = os.path.join(ROOT, "tests", "golden")
GENERATORS = ["make_g1.py", "make_goldens.py", "make_trait_goldens.py", "make_adopt_golden.py"]


def snapshot():
    out = {}
    for d, _dirs, files in os.walk(GOLDEN):
        if "__pycache__" in d:
            continue
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, GOLDEN)] = fh.read()
    return out


def restore(before, after):
    for rel in set(after) - set(before):
        os.remove(os.path.join(GOLDEN, rel))
    for rel, data in before.items():
        p = os.path.join(GOLDEN, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)


def main():
    before = snapshot()
    try:
        for g in GENERATORS:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen", g)], cwd=ROOT, check=True,
                           stdout=subprocess.DEVNULL)
        after = snapshot()
    finally:
        current = snapshot()
        restore(before, current)
    stale = sorted(r for r in set(before) | set(after) if before.get(r) != after.get(r))
    if stale:
        print("Goldens are stale; run the generators in tools/gen and commit:\n  " + "\n  ".join(stale))
        return 1
    print(f"ok ({len(before)} golden files match the generators)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
