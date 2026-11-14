#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Move a run between sessions before the draft epic exists.

Usage:
  run_bundle.py export RUN_DIR --out BUNDLE.json
  run_bundle.py import BUNDLE.json --overlay OVERLAY.yaml --runs RUNS_ROOT

export packs every text file in the run folder with its SHA-256 and a bundle
hash. import refuses a bundle that was made under a different overlay (id or
hash), whose hashes do not match, whose paths leave the run folder, or whose
run folder already exists; otherwise it writes runs/<overlay.id>/<plan.id>/.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402
from gw_canon import sha256_hex  # noqa: E402
from gw_hash import item_hash  # noqa: E402

TEXT = (".json", ".jsonl", ".md", ".yaml", ".yml", ".txt")


def export(run_dir):
    plan = json.load(open(os.path.join(run_dir, "plan.json"), encoding="utf-8"))
    files = []
    for root, dirs, names in os.walk(run_dir):
        dirs.sort()
        for n in sorted(names):
            if not n.endswith(TEXT):
                continue
            full = os.path.join(root, n)
            rel = os.path.relpath(full, run_dir).replace(os.sep, "/")
            text = open(full, encoding="utf-8").read()
            files.append({"path": rel, "sha256": sha256_hex(text.encode("utf-8")), "content": text})
    b = {"schema_version": "1.0", "kind": "groundwork-run-bundle", "overlay_id": plan["overlay"]["id"],
         "overlay_version": plan["overlay"]["version"], "overlay_hash": plan["overlay"]["hash"],
         "plan_id": plan["id"], "plan_version": plan["version"], "files": files}
    b["hash"] = item_hash(b)
    return b


def problems(bundle, overlay):
    probs = []
    if bundle.get("kind") != "groundwork-run-bundle":
        return ["not a Groundwork run bundle"]
    if item_hash(bundle) != bundle.get("hash"):
        probs.append("bundle hash does not match its contents; it was changed after export")
    if bundle["overlay_id"] != overlay["id"]:
        probs.append(f"bundle was made under overlay {bundle['overlay_id']!r}, not {overlay['id']!r} (CR-12); "
                     "start a new run under this org's overlay instead")
    elif overlay.get("hash") and bundle["overlay_hash"] != overlay["hash"]:
        probs.append("bundle was made under a different version of this overlay; re-run Draft against the current overlay")
    names = set()
    for f in bundle["files"]:
        p = f["path"]
        if p.startswith("/") or ".." in p.split("/") or "\\" in p:
            probs.append(f"file path {p!r} leaves the run folder")
        if p in names:
            probs.append(f"file {p} appears twice")
        names.add(p)
        if sha256_hex(f["content"].encode("utf-8")) != f["sha256"]:
            probs.append(f"file {p} does not match its hash")
        if p.startswith("evidence/") and p.endswith(".json"):
            try:
                d = json.loads(f["content"])
            except ValueError:
                probs.append(f"file {p} is not valid JSON")
                continue
            for item in d if isinstance(d, list) else [d]:
                if isinstance(item, dict) and item.get("overlay_id") not in (None, overlay["id"]):
                    probs.append(f"evidence in {p} was collected under overlay {item.get('overlay_id')!r}")
    if "plan.json" not in names:
        probs.append("bundle has no plan.json")
    else:
        plan = json.loads(next(f["content"] for f in bundle["files"] if f["path"] == "plan.json"))
        if plan.get("id") != bundle["plan_id"] or plan.get("overlay", {}).get("id") != bundle["overlay_id"]:
            probs.append("plan.json does not match the bundle's plan id or overlay id")
    return probs


def do_import(bundle, overlay, runs_root):
    probs = problems(bundle, overlay)
    dest = os.path.join(runs_root, overlay["id"], bundle["plan_id"])
    if not probs and os.path.exists(dest) and os.listdir(dest):
        probs.append(f"run folder {dest} already exists; resume it instead of importing over it")
    if probs:
        return {"ok": False, "problems": probs}
    for f in bundle["files"]:
        full = os.path.join(dest, *f["path"].split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(f["content"])
    return {"ok": True, "run_dir": dest, "files": len(bundle["files"])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["export", "import"])
    ap.add_argument("path")
    ap.add_argument("--out")
    ap.add_argument("--overlay")
    ap.add_argument("--runs")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        b = export(a.path)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(b, fh, indent=2, ensure_ascii=False)
        print(json.dumps({"ok": True, "hash": b["hash"], "files": len(b["files"])}, indent=2))
        return 0
    out = do_import(json.load(open(a.path, encoding="utf-8")), gw_yaml.load(a.overlay), a.runs)
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
