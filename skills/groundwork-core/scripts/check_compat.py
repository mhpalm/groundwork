#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Check each loaded skill's handshake against the overlay and the release.

Usage:
  check_compat.py --overlay OVERLAY.yaml --handshakes HANDSHAKES.jsonl
                  [--sums SHA256SUMS] [--skills-root DIR] [--out compat.json]

For every handshake: contract MAJOR equals the core's, version is inside the
overlay's range, rule ids carry the skill's prefix and don't collide, and the
skill's instruction files hash to the release's SHA256SUMS (verified),
can't be read on this surface (unverified), or differ (mismatch, refused).
Exit 0 when every tracker skill is accepted, 1 otherwise.
"""

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
INSTRUCTION_SUFFIXES = (".md", ".yaml", ".json", ".py")


def core_manifest():
    return gw_yaml.load(os.path.join(HERE, "..", "groundwork.yaml"))


def parse_version(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v.strip())
    if not m:
        raise ValueError(f"not a semver version: {v}")
    return tuple(int(x) for x in m.groups())


def in_range(version, spec):
    """spec is space-separated comparators, e.g. '>=1.0.0 <2.0.0'."""
    v = parse_version(version)
    for part in spec.split():
        m = re.match(r"^(>=|<=|>|<|=)?(\d+\.\d+\.\d+)$", part)
        if not m:
            raise ValueError(f"bad version range part: {part}")
        op, ref = m.group(1) or "=", parse_version(m.group(2))
        ok = {">=": v >= ref, "<=": v <= ref, ">": v > ref, "<": v < ref, "=": v == ref}[op]
        if not ok:
            return False
    return True


def read_sums(path):
    sums = {}
    if not path or not os.path.exists(path):
        return sums
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                digest, name = line.split(None, 1)
                sums[name.lstrip("*")] = digest
    return sums


def skill_files(skill_dir):
    for root, _d, files in os.walk(skill_dir):
        for n in sorted(files):
            if n.endswith(INSTRUCTION_SUFFIXES) and "__pycache__" not in root:
                full = os.path.join(root, n)
                yield os.path.relpath(full, os.path.dirname(skill_dir)).replace(os.sep, "/"), full


def verify_files(name, skills_root, sums):
    """verified | unverified | mismatch, plus notes."""
    if not sums:
        return "unverified", ["no SHA256SUMS available on this surface"]
    if not skills_root:
        return "unverified", ["skill files are not readable on this surface"]
    d = os.path.join(skills_root, name)
    if not os.path.isdir(d):
        return "unverified", [f"skill folder {name} not readable"]
    expected = {k: v for k, v in sums.items() if k.startswith(name + "/")}
    if not expected:
        return "mismatch", [f"the release lists no files for {name}"]
    seen = {}
    for rel, full in skill_files(d):
        with open(full, "rb") as f:
            seen[rel] = hashlib.sha256(f.read()).hexdigest()
    notes = []
    for rel, digest in expected.items():
        if rel.endswith("groundwork.yaml"):
            continue  # stamped by the release build; checked against the handshake instead
        if rel not in seen:
            notes.append(f"missing {rel}")
        elif seen[rel] != digest:
            notes.append(f"changed {rel}")
    for rel in seen:
        if rel not in expected:
            notes.append(f"unexpected {rel}")
    return ("mismatch" if notes else "verified"), notes


def check(overlay, handshakes, sums=None, skills_root=None, rules_by_skill=None):
    core = core_manifest()
    core_major, core_minor = (int(x) for x in core["contract"].split("."))
    results = []
    want = {}
    for s in overlay["skills"].get("systems", []):
        want[s["skill"]] = ("system", s["version"])
    tr = overlay["skills"].get("tracker")
    if tr:
        want[tr["skill"]] = ("tracker", tr["version"])
    core_ok = in_range(core["version"], overlay["skills"]["core"])
    results.append({"skill": core["name"], "result": "accepted" if core_ok else "refused", "verified": "unverified",
                    "notes": [] if core_ok else [f"core {core['version']} is outside the overlay's range {overlay['skills']['core']}"]})
    hs_schema = load_schema("handshake")
    by_name = {}
    for h in handshakes:
        name = h.get("name", "")
        if name.startswith("groundwork:"):
            name = name.split(":", 1)[1]  # plugin namespace
            h = dict(h, name=name)
        by_name[name] = h
    prefixes = {}
    for name, (kind, rng) in want.items():
        notes = []
        h = by_name.get(name)
        if not h:
            results.append({"skill": name, "result": "refused", "verified": "unverified", "notes": ["no handshake: the skill did not load"]})
            continue
        errs = validate(h, hs_schema)
        if errs:
            results.append({"skill": name, "result": "refused", "verified": "unverified", "notes": [f"handshake: {e}" for e in errs]})
            continue
        result = "accepted"
        if h["kind"] != kind:
            result = "refused"
            notes.append(f"overlay lists it as a {kind} skill but it says {h['kind']}")
        major, minor = (int(x) for x in h["contract"].split("."))
        if major != core_major:
            result = "refused"
            notes.append(f"contract {h['contract']} has a different MAJOR from the core's {core['contract']}")
        elif minor != core_minor:
            notes.append(f"contract MINOR {minor} differs from the core's {core_minor}; unknown optional sections are ignored")
            if result == "accepted":
                result = "accepted_with_note"
        if not in_range(h["version"], rng):
            result = "refused"
            notes.append(f"version {h['version']} is outside the overlay's range {rng}")
        verified, vnotes = verify_files(name, skills_root, sums or {})
        notes.extend(vnotes)
        if verified == "mismatch":
            result = "refused"
        for r in (rules_by_skill or {}).get(name, []):
            prefix = r["id"].split(".")[0]
            if prefix != h["platform"] and not prefix.startswith(h["platform"]):
                result = "refused"
                notes.append(f"rule {r['id']} does not start with the skill's prefix")
            if r["id"] in prefixes and prefixes[r["id"]] != name:
                result = "refused"
                notes.append(f"rule {r['id']} collides with {prefixes[r['id']]}")
            prefixes[r["id"]] = name
        results.append({"skill": name, "result": result, "verified": verified, "notes": notes})
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overlay", required=True)
    ap.add_argument("--handshakes", required=True, help="JSON lines, one handshake per line")
    ap.add_argument("--sums")
    ap.add_argument("--skills-root")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    overlay = gw_yaml.load(a.overlay)
    with open(a.handshakes, encoding="utf-8") as f:
        hs = [json.loads(line) for line in f if line.strip()]
    rules = {}
    if a.skills_root:
        for name in os.listdir(a.skills_root):
            p = os.path.join(a.skills_root, name, "rules.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    rules[name] = json.load(f).get("rules", [])
    res = check(overlay, hs, read_sums(a.sums), a.skills_root, rules)
    text = json.dumps(res, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    else:
        print(text)
    tr = overlay["skills"].get("tracker", {}).get("skill")
    bad = [r for r in res if r["result"] == "refused" and (r["skill"] == tr or r["skill"].startswith("groundwork-core"))]
    for r in res:
        print(f"{r['skill']}: {r['result']} ({r['verified']})", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
