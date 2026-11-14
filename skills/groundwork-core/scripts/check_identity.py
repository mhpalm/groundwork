#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Intake identity check (CR-12): does each sign-in reach the org the overlay names?

Run at Intake, after every system and tracker skill's `connect` has reported,
and before any discovery call.

Usage:
  check_identity.py --overlay OVERLAY.yaml --connect CONNECT.json

CONNECT.json is a list of what each skill's connect step reported:
  [{skill, instance, url, account, identity: {...}}]
  - skill:    the skill name, e.g. groundwork-system-github
  - instance: the overlay instance id the skill was asked to reach
  - url:      the instance URL the signed-in session actually reaches
  - account:  the signed-in account (a login or account id, never a credential)
  - identity: platform facts the skill read back, e.g. {"org": "example-org"} or {"project": "VOL"}

Prints {ok, results: [{skill, instance, decision: proceed|stop, why}], run: continue|stop}.
A stopped system is not inspected (record it in coverage) and the run continues.
A stopped tracker stops the run. Exit code 1 when the run must stop.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gw_yaml  # noqa: E402


def norm_url(u):
    return (u or "").strip().rstrip("/").lower()


def expected_instances(overlay):
    """Yield (skill, instance_id, url, expected_identity, is_tracker)."""
    sk = overlay.get("skills", {})
    for s in sk.get("systems", []):
        for inst in s["instances"]:
            yield s["skill"], inst["id"], inst["url"], inst.get("expected_identity", {}), False
    tr = sk.get("tracker")
    if tr:
        inst = tr["instance"]
        exp = {"project": inst["project"]} if inst.get("project") else {}
        exp.update(inst.get("expected_identity", {}))
        yield tr["skill"], inst["id"], inst["url"], exp, True


def check(overlay, reports):
    by = {}
    for r in reports:
        by.setdefault((r.get("skill", "").replace("groundwork:", ""), r.get("instance")), []).append(r)
    results = []
    run = "continue"
    for skill, inst, url, exp, is_tracker in expected_instances(overlay):
        got = by.pop((skill, inst), [])
        why = None
        if not got:
            why = "connect did not report an identity for this instance"
        elif len(got) > 1:
            why = "more than one identity was reported for this instance; sign in to one account"
        else:
            r = got[0]
            ident = r.get("identity") or {}
            if not r.get("account"):
                why = "connect reported no signed-in account"
            elif norm_url(r.get("url")) != norm_url(url):
                why = f"the session reaches {r.get('url')}, not the overlay's {url}"
            else:
                wrong = [k for k, v in exp.items() if str(ident.get(k, "")).lower() != str(v).lower()]
                if wrong:
                    k = wrong[0]
                    why = f"signed in to {k} {ident.get(k)!r}, but the overlay names {exp[k]!r}"
        decision = "stop" if why else "proceed"
        if why and is_tracker:
            run = "stop"
        results.append({"skill": skill, "instance": inst, "decision": decision,
                        "why": why or "matches the overlay"})
    for (skill, inst), _ in sorted(by.items()):
        results.append({"skill": skill, "instance": inst, "decision": "stop",
                        "why": "this instance is not in the overlay; Groundwork only reads what the overlay names"})
    return {"ok": all(r["decision"] == "proceed" for r in results), "run": run, "results": results}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overlay", required=True)
    ap.add_argument("--connect", required=True)
    a = ap.parse_args(argv)
    out = check(gw_yaml.load(a.overlay), json.load(open(a.connect, encoding="utf-8")))
    print(json.dumps(out, indent=2))
    return 1 if out["run"] == "stop" else 0


if __name__ == "__main__":
    sys.exit(main())
