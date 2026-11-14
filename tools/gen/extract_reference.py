# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""One-time helper: draft reference/*.md from the approved spec export.

Usage: extract_reference.py SPEC.md OUTDIR
Strips decision-log ids, open-question ids and anything about the spec's
own authorship, and maps "section N" to the reference file that holds it.
The output is then edited by hand; this script is kept for provenance.
"""
import re
import sys

spec, outdir = sys.argv[1], sys.argv[2]
text = open(spec, encoding="utf-8").read()


def section(n):
    m = re.search(rf"^## {n}\. .*?$(.*?)(?=^## \d+\. |\Z)", text, re.S | re.M)
    return m.group(1).strip("\n")


def sub(body, title):
    m = re.search(rf"^### {re.escape(title)}.*?$(.*?)(?=^### |\Z)", body, re.S | re.M)
    return m.group(1).strip("\n")


MAP = {"2": "contract.md (loading)", "3": "contract.md", "4": "plan-format.md", "5": "pipeline.md", "6": "setup-mode.md",
       "7": "gap-review.md", "8": "approval-create.md", "9": "the repo README", "10": "the repo's tests"}


def clean(s):
    s = re.sub(r",? per D-\d+ and D-\d+", "", s)
    s = re.sub(r" ?\((?:D-\d+(?:, )?)+\)", "", s)
    s = re.sub(r",? D-\d+\)", ")", s)
    s = re.sub(r" \(D-\d+\)", "", s)
    s = re.sub(r"PENDING [^.]*\.", "", s)
    s = re.sub(r"This follows D-05[^.]*\.", "", s)
    s = re.sub(r"\(section (\d+)\)", lambda m: f"({MAP.get(m.group(1), 'section ' + m.group(1))})", s)
    s = re.sub(r"\bsection (\d+)\b", lambda m: MAP.get(m.group(1), m.group(0)), s)
    s = re.sub(r"^Verdict on the claim in the brief.*?$\n?", "", s, flags=re.M)
    s = s.replace("The spec reads CR-08 as", "Groundwork reads CR-08 as")
    s = s.replace("Contract v1.0.0 is defined here.", "This file defines contract 1.0.")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"


HDR = "<!-- SPDX-License-Identifier: Apache-2.0 -->\n"
files = {
    "contract.md": "# The skill contract (1.0)\n\n" + section(3) + "\n\n## How the core loads system and tracker skills\n\n" + sub(section(2), "How the core loads system and tracker skills") + "\n\n## Boundaries\n\n" + sub(section(2), "Boundaries"),
    "plan-format.md": "# Plan format (1.0)\n\n" + section(4),
    "pipeline.md": "# The pipeline\n\n" + section(5),
    "setup-mode.md": "# Setup mode and the org overlay (format 1.0)\n\n" + section(6),
    "gap-review.md": "# Gap review\n\n" + section(7),
}
s8 = section(8)
cut = s8.index("### Release mode")
files["approval-create.md"] = "# Approval, create and freeze\n\n" + s8[:cut]
files["revise-mode.md"] = "# Release and revise modes\n\n" + s8[cut:]
files["hashing.md"] = "# What is hashed\n\n" + sub(s8, "What is hashed")
for name, body in files.items():
    body = re.sub(r"^### ", "## ", body, flags=re.M)
    open(f"{outdir}/{name}", "w", encoding="utf-8").write(HDR + clean(body))
print("wrote", ", ".join(files))
