#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Boundary and hygiene lint for every skill folder.

- System and tracker skills never restate a core rule (normative sentences in
  the core's reference/rules.md).
- Exactly one SKILL.md per skill folder, at its root.
- Frontmatter: name <= 64 chars and equal to the folder, description <= 200
  chars and starting "Groundwork", license and metadata.version/contract set.
- groundwork.yaml validates and agrees with frontmatter and the handshake block.
- rules.json validates and every rule id starts with the skill's rule_prefix.
"""
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "skills", "groundwork-core", "scripts"))
import gw_yaml  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return gw_yaml.loads(m.group(1)) if m else None


def normative_sentences():
    text = open(os.path.join(ROOT, "skills", "groundwork-core", "reference", "rules.md"), encoding="utf-8").read()
    part = text.split("## Normative sentences", 1)[1]
    return [l[2:].strip() for l in part.splitlines() if l.startswith("- ")]


def main():
    errors = []
    sentences = normative_sentences()
    skills_dir = os.path.join(ROOT, "skills")
    for name in sorted(os.listdir(skills_dir)):
        d = os.path.join(skills_dir, name)
        if not os.path.isdir(d):
            continue
        skill_md = os.path.join(d, "SKILL.md")
        extra = [os.path.relpath(os.path.join(r, f), d) for r, _ds, fs in os.walk(d) for f in fs
                 if f.lower() == "skill.md" and os.path.join(r, f) != skill_md]
        if extra:
            errors.append(f"{name}: only the root SKILL.md may exist (the Claude app rejects the ZIP); found {', '.join(sorted(extra))}")
        if not os.path.exists(skill_md):
            errors.append(f"{name}: no SKILL.md")
            continue
        text = open(skill_md, encoding="utf-8").read()
        fm = frontmatter(text)
        if not fm:
            errors.append(f"{name}: SKILL.md has no frontmatter")
            continue
        if fm.get("name") != name or len(name) > 64:
            errors.append(f"{name}: frontmatter name must equal the folder name and be at most 64 characters")
        desc = fm.get("description", "")
        if len(desc) > 200 or not desc.startswith("Groundwork"):
            errors.append(f"{name}: description must start 'Groundwork' and be at most 200 characters (is {len(desc)})")
        if "Groundwork run" not in desc and "Groundwork requests" not in desc:
            errors.append(f"{name}: description must say it is used only inside Groundwork")
        if fm.get("license") != "Apache-2.0":
            errors.append(f"{name}: license must be Apache-2.0")
        meta = fm.get("metadata") or {}
        manifest_p = os.path.join(d, "groundwork.yaml")
        man = gw_yaml.load(manifest_p) if os.path.exists(manifest_p) else None
        if not man:
            errors.append(f"{name}: no groundwork.yaml")
            continue
        for e in validate(man, load_schema("skill-manifest")):
            errors.append(f"{name}/groundwork.yaml: {e}")
        if meta.get("version") != man.get("version") or str(meta.get("contract")) != str(man.get("contract")):
            errors.append(f"{name}: frontmatter metadata and groundwork.yaml disagree on version or contract")
        body = text[text.index("---", 3) + 3:]
        if "author" in body.lower() and "micah" in body.lower():
            errors.append(f"{name}: attribution belongs in frontmatter, not instructions")
        if man["kind"] in ("system", "tracker"):
            m = re.search(r"```json\n(\{.*?\})\n```", text, re.S)
            if not m:
                errors.append(f"{name}: SKILL.md has no handshake block")
            else:
                hs = json.loads(m.group(1))
                for e in validate(hs, load_schema("handshake")):
                    errors.append(f"{name} handshake: {e}")
                for k in ("name", "kind", "version", "release", "contract", "platform"):
                    if str(hs.get(k)) != str(man.get(k)):
                        errors.append(f"{name}: handshake {k} '{hs.get(k)}' differs from groundwork.yaml '{man.get(k)}'")
            for root, _dirs, files in os.walk(d):
                for f in files:
                    if f.endswith(".md"):
                        t = open(os.path.join(root, f), encoding="utf-8").read().lower()
                        for s in sentences:
                            if s.lower() in t:
                                errors.append(f"{name}/{f}: restates core rule text '{s}'; refer to the rule id")
            rp = os.path.join(d, "rules.json")
            if not os.path.exists(rp):
                errors.append(f"{name}: no rules.json")
            else:
                rules = json.load(open(rp, encoding="utf-8"))
                for e in validate(rules, load_schema("rules")):
                    errors.append(f"{name}/rules.json: {e}")
                for r in rules.get("rules", []):
                    if not r["id"].startswith(man["rule_prefix"] + "."):
                        errors.append(f"{name}: rule {r['id']} does not start with '{man['rule_prefix']}.'")
                    if "Groundwork" in r["check"] and "core" in r["check"]:
                        pass
    for e in errors:
        print(e)
    print(f"lint_boundaries: {len(errors)} problem(s)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
