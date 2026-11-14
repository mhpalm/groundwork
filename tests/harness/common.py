# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Shared paths and loaders for the Groundwork test suite."""
import copy
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CORE = os.path.join(ROOT, "skills", "groundwork-core")
SCRIPTS = os.path.join(CORE, "scripts")
GOLDEN = os.path.join(ROOT, "tests", "golden")
for p in (SCRIPTS, os.path.join(ROOT, "tests", "mutations"), os.path.join(ROOT, "tests", "harness")):
    if p not in sys.path:
        sys.path.insert(0, p)

import gw_yaml  # noqa: E402
import validate_plan  # noqa: E402


def load_golden(name):
    d = os.path.join(GOLDEN, name)
    with open(os.path.join(d, "expected", "plan.json"), encoding="utf-8") as f:
        plan = json.load(f)
    overlay = gw_yaml.load(os.path.join(d, "overlay", "overlay.yaml"))
    evidence = validate_plan.load_evidence(os.path.join(d, "evidence"))
    return plan, overlay, evidence


def fresh(name):
    return copy.deepcopy(load_golden(name))


NOW = validate_plan.parse_ts("2026-11-15T00:00:00Z")
