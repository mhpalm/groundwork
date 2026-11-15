#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Build a release: stamp the tag, hash instruction files, zip each skill,
and assemble the Claude Code plugin with identical files.

Usage: build_release.py vX.Y.Z [--out dist]

Writes dist/<tag>/{<skill>.zip ..., SHA256SUMS, release-notes.md} and
dist/<tag>/plugin/ (a copy of plugin/ with skills/ filled in). The source
tree is never modified.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "skills", "groundwork-core", "scripts"))
import gw_yaml  # noqa: E402

SKIP = ("__pycache__", ".pyc")


def stamp(skill_dir, tag):
    man_p = os.path.join(skill_dir, "groundwork.yaml")
    man = gw_yaml.load(man_p)
    man["release"] = tag
    with open(man_p, "w", encoding="utf-8") as f:
        f.write(gw_yaml.dumps(man))
    md_p = os.path.join(skill_dir, "SKILL.md")
    text = open(md_p, encoding="utf-8").read()
    text = re.sub(r'("release": ")unreleased(")', rf"\g<1>{tag}\g<2>", text)
    open(md_p, "w", encoding="utf-8").write(text)
    return man


def main(argv):
    if not argv or not re.match(r"^v\d+\.\d+\.\d+$", argv[0]):
        print(__doc__)
        return 2
    tag = argv[0]
    out = os.path.join(ROOT, argv[argv.index("--out") + 1] if "--out" in argv else "dist", tag)
    if os.path.exists(out):
        print(f"{out} already exists; releases are never rebuilt in place")
        return 1
    stage = os.path.join(out, "skills")
    shutil.copytree(os.path.join(ROOT, "skills"), stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    sums, notes = [], [f"# Groundwork {tag}", "", "| Skill | Version | Contract |", "| --- | --- | --- |"]
    for name in sorted(os.listdir(stage)):
        d = os.path.join(stage, name)
        man = stamp(d, tag)
        notes.append(f"| {name} | {man['version']} | {man['contract']} |")
        for root, _dirs, files in os.walk(d):
            for f in sorted(files):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, stage).replace(os.sep, "/")
                sums.append(f"{hashlib.sha256(open(full, 'rb').read()).hexdigest()}  {rel}")
    sums.sort(key=lambda l: l.split("  ", 1)[1])
    open(os.path.join(out, "SHA256SUMS"), "w").write("\n".join(sums) + "\n")
    for name in sorted(os.listdir(stage)):
        shutil.copy(os.path.join(out, "SHA256SUMS"), os.path.join(stage, name, "SHA256SUMS"))
        d = os.path.join(stage, name)
        with zipfile.ZipFile(os.path.join(out, f"{name}.zip"), "w", zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, files in os.walk(d):
                for f in sorted(files):
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, stage))
        skill_mds = [n for n in zipfile.ZipFile(os.path.join(out, f"{name}.zip")).namelist()
                     if n.rsplit("/", 1)[-1].lower() == "skill.md"]
        if skill_mds != [f"{name}/SKILL.md"]:
            print(f"{name}.zip must hold exactly one SKILL.md, at {name}/SKILL.md; found {skill_mds}")
            return 1
    plugin = os.path.join(out, "plugin")
    shutil.copytree(os.path.join(ROOT, "plugin"), plugin)
    shutil.copytree(stage, os.path.join(plugin, "skills"))
    pj = os.path.join(plugin, ".claude-plugin", "plugin.json")
    data = json.load(open(pj))
    data["version"] = tag.lstrip("v")
    json.dump(data, open(pj, "w"), indent=2)
    notes += ["", "Install the same release on every surface your team uses. Verify downloads against SHA256SUMS.",
              "", "Per-surface smoke checklist results: (filled in by the maintainer before publishing)"]
    open(os.path.join(out, "release-notes.md"), "w").write("\n".join(notes) + "\n")
    print(f"built {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
