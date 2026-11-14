# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""One seeded defect per mechanical (V) blocker id, applied to golden G1.

Each mutation takes (plan, overlay, evidence) copies, breaks exactly one
thing, and names the check id the validator must report.
"""


def t(plan, tid):
    return next(x for x in plan["tasks"] if x["id"] == tid)


def m_gr01(p, o, e):
    t(p, "P1-T02")["estimate_hours"] = 7


def m_gr04(p, o, e):
    p["open_questions"].append({"id": "Q-1", "text": "Which shifts?", "blocks": ["P1-T03"], "status": "open",
                                "answer": None, "answered_by": None, "at": None})


def m_gr05(p, o, e):
    t(p, "P1-T03")["instructions"]["verify"] = []


def m_gr07_evidence(p, o, e):
    t(p, "P1-T02")["instructions"]["steps"][1]["refs"].append("ev-github-gh-deadbeef")


def m_gr07_produces(p, o, e):
    t(p, "P1-T03")["instructions"]["steps"][1]["refs"].append("nonexistent-helper")


def m_gr08_cycle(p, o, e):
    t(p, "P1-T01")["depends_on"].append({"task": "P1-T03", "satisfied_by": "merged"})


def m_gr08_later_phase(p, o, e):
    t(p, "P1-T02")["depends_on"].append({"task": "P2-T01", "satisfied_by": "done"})


def m_gr08_unknown(p, o, e):
    t(p, "P1-T02")["depends_on"].append({"task": "P1-T99", "satisfied_by": "done"})


def m_gr09(p, o, e):
    p["standard_work"] = [s for s in p["standard_work"] if s["kind"] != "handoff"]


def m_gr10(p, o, e):
    t(p, "P3-T01")["test_tasks"] = []


def m_gr10_order(p, o, e):
    t(p, "P3-T01")["test_tasks"] = ["P3-T05"]


def m_gr11(p, o, e):
    t(p, "P3-T01")["rollback_task"] = None


def m_gr13_not_requested(p, o, e):
    p0 = t(p, "P0-T01")
    p0["produces"] = [x for x in p0["produces"] if x["name"] != "A4"]


def m_gr13_not_derived(p, o, e):
    p["access_list"][0]["needed_by"] = ["P0-T02"]


def m_gr14(p, o, e):
    t(p, "P3-T04")["role_key"] = "trainer"


def m_gr15(p, o, e):
    t(p, "P1-T02")["points"] = 3  # schema rejects: points must be 1


def m_gr17_email(p, o, e):
    t(p, "P3-T05")["instructions"]["steps"][1]["text"] += " Copy jane.doe@realcompany.io."


def m_gr17_token(p, o, e):
    t(p, "P0-T02")["instructions"]["steps"][0]["text"] += " Use token ghp_abcdefghijklmnopqrstuvwxyz0123."


def m_gr18(p, o, e):
    p["coverage"] = [c for c in p["coverage"] if c["system"] != "github"]


def m_gr23(p, o, e):
    o["skills"]["tracker"]["field_map"]["blocked"] = ""


def m_gr24(p, o, e):
    x = t(p, "P1-T02")
    x["estimate_hours"] = 10
    x["exception"] = {"id": "X-1", "reason": "single job", "days": 2, "checkpoints": [{"day": 1, "visible_result": "half done"}]}


def m_gr25(p, o, e):
    item = next(i for i in e if i["sensitivity"] == "restricted")
    item["facts"]["reviewer_team"] = "release-gatekeepers"
    from gw_hash import item_hash
    item["hash"] = item_hash(item)
    t(p, "P3-T02")["instructions"]["steps"][4]["text"] += " Ask release-gatekeepers."


def m_gr26(p, o, e):
    for i in e:
        i["collected_at"] = "2026-10-01T00:00:00Z"
    from gw_hash import item_hash
    for i in e:
        i["hash"] = item_hash(i)


def m_evidence_hash(p, o, e):
    e[0]["facts"]["tampered"] = True


def m_cr12(p, o, e):
    p["overlay"]["id"] = "other-org"


def m_key(p, o, e):
    t(p, "P1-T02")["key"] = "gw:gw-01JCX7Q3RZ9V4N2T8K5M6P0ABC:P1-T09"


MUTATIONS = [
    ("GR-01", m_gr01), ("GR-04", m_gr04), ("GR-05", m_gr05), ("GR-07", m_gr07_evidence), ("GR-07", m_gr07_produces),
    ("GR-08", m_gr08_cycle), ("GR-08", m_gr08_later_phase), ("GR-08", m_gr08_unknown), ("GR-09", m_gr09),
    ("GR-10", m_gr10), ("GR-10", m_gr10_order), ("GR-11", m_gr11), ("GR-13", m_gr13_not_requested),
    ("GR-13", m_gr13_not_derived), ("GR-14", m_gr14), ("GR-15", m_gr15), ("GR-17", m_gr17_email),
    ("GR-17", m_gr17_token), ("GR-18", m_gr18), ("GR-23", m_gr23), ("GR-24", m_gr24), ("GR-25", m_gr25),
    ("GR-26", m_gr26), ("EVIDENCE-HASH", m_evidence_hash), ("CR-12", m_cr12), ("KEY", m_key),
]
