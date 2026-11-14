#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Validate an org overlay, and compute or check its hash.

Usage:
  validate_overlay.py OVERLAY.yaml            check schema, rules and hash
  validate_overlay.py OVERLAY.yaml --set-hash print the overlay with its hash set

Exit 0 when valid, 1 when not, 2 when unreadable. An overlay can never
loosen a core rule: the schema rejects unknown keys (except x-*), bounds the
working day to 1 to 8 hours, and makes the executor an enum.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402
from gw_hash import item_hash  # noqa: E402
from gw_schema import load_schema, validate  # noqa: E402

CORE_FORMAT_MAJOR = 1
CORE_FORMAT_MINOR = 0
SECRETISH = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key)")


def problems(ov):
    out = []
    fmt = str(ov.get("overlay_format", ""))
    try:
        major, minor = (int(x) for x in fmt.split("."))
    except ValueError:
        return [f"overlay_format '{fmt}' is not MAJOR.MINOR"]
    if major < CORE_FORMAT_MAJOR:
        return [f"overlay format {fmt} is older than this core's {CORE_FORMAT_MAJOR}.x; run 'migrate the overlay'"]
    if major > CORE_FORMAT_MAJOR:
        return [f"overlay format {fmt} is newer than this core understands; upgrade groundwork-core"]
    schema = load_schema("overlay")
    errs = validate(ov, schema)
    if minor > CORE_FORMAT_MINOR:
        # A newer MINOR may add keys this core doesn't know; ignore those, say so.
        known = set(schema["properties"])
        extra = [k for k in ov if k not in known and not k.startswith("x-")]
        errs = [e for e in errs if not any(f"unknown field '{k}'" in e for k in extra)]
        out.extend(f"note: ignoring key '{k}' from overlay format {fmt}" for k in extra)
    out.extend(errs)
    if errs:
        return out
    roles = {r["key"] for r in ov["roles"]}
    if len(roles) != len(ov["roles"]):
        out.append("roles: a role key is listed twice")
    if "approver" not in roles:
        out.append("roles: no 'approver' role is mapped, so no phase can ever be approved")
    for rh in ov.get("role_holders", []):
        if rh["role_key"] not in roles:
            out.append(f"role_holders: '{rh['role_key']}' is not a mapped role")
    gates = {g["id"]: g for g in ov["approval_gates"]}
    if not any(g["applies_to"] == "all_phases" for g in gates.values()):
        out.append("approval_gates: no gate applies to all_phases, so no phase can be approved")
    for g in gates.values():
        n = g.get("min_approvers", 1)
        if n > len(g["approvers"]):
            out.append(f"approval_gates.{g['id']}: min_approvers {n} is more than its {len(g['approvers'])} approvers")
        ids = [a["account_id"] for a in g["approvers"]]
        if len(ids) != len(set(ids)):
            out.append(f"approval_gates.{g['id']}: an approver is listed twice")
    inst_ids = []
    for s in ov["skills"].get("systems", []):
        inst_ids.extend(f"{s['skill']}:{i['id']}" for i in s["instances"])
    if len(inst_ids) != len(set(inst_ids)):
        out.append("skills.systems: an instance id is used twice for the same skill")
    for path, s in _strings(ov):
        if SECRETISH.search(path.split(".")[-1]) or re.search(r"\b(ghp|github_pat|xox[abprs])[_-]", s):
            out.append(f"{path}: looks like a credential; overlays never hold credentials (CR-08)")
    if ov.get("hash") and ov["hash"] != overlay_hash(ov):
        out.append("hash does not match the overlay's contents; it was edited outside setup mode")
    return out


def _strings(obj, path="$"):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def overlay_hash(ov):
    body = dict(ov)
    body["hash"] = None
    return item_hash(body)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("overlay")
    ap.add_argument("--set-hash", action="store_true")
    a = ap.parse_args(argv)
    try:
        ov = gw_yaml.load(a.overlay)
    except (OSError, ValueError) as e:
        print(f"cannot read overlay: {e}", file=sys.stderr)
        return 2
    if a.set_hash:
        ov["hash"] = overlay_hash(ov)
        sys.stdout.write(gw_yaml.dumps(ov))
        return 0
    probs = problems(ov)
    errors = [p for p in probs if not p.startswith("note:")]
    for p in probs:
        print(p)
    if not ov.get("hash"):
        print("note: overlay has no hash yet; setup mode sets it with --set-hash after admin approval")
    print(f"overlay {ov.get('id')} v{ov.get('version')}: {'valid' if not errors else f'{len(errors)} problem(s)'}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
