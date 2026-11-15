# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Source of truth for the core JSON Schemas. Run to regenerate skills/groundwork-core/schemas/."""
import json, os

S = lambda **k: k
STR = {"type": "string", "minLength": 1}
ANYSTR = {"type": "string"}
HEX = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
TS = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"}
SEMVER = {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"}
MAJMIN = {"type": "string", "pattern": r"^\d+\.\d+$"}
PLAN_ID = {"type": "string", "pattern": "^gw-[0-9A-HJKMNP-TV-Z]{26}$"}
TASK_ID = {"type": "string", "pattern": r"^P\d+-T\d{2,}$"}
PHASE_ID = {"type": "string", "pattern": r"^P\d+$"}
EV_ID = {"type": "string", "pattern": r"^ev-[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}$"}
EXECUTORS = ["junior_no_context", "junior_with_context", "mid_no_context"]
ROLE_KEYS = ["developer", "admin", "analyst", "qa", "business_user", "trainer", "comms", "maintainer", "approver",
             "legal", "finance", "procurement", "security", "vendor_contact", "facilitator"]
# Overlays may add x- role keys; they can only add roles, never rename or remove the generic ones.
ROLE = {"anyOf": [{"enum": ROLE_KEYS}, {"type": "string", "pattern": "^x-[a-z0-9_]+$"}]}
B_ID = {"type": "string", "pattern": r"^B-\d+$"}
AD_ID = {"type": "string", "pattern": r"^AD-\d+$"}
O_ID = {"type": "string", "pattern": r"^O-\d+$"}
Q_ID = {"type": "string", "pattern": r"^Q-\d+$"}
R_ID = {"type": "string", "pattern": r"^R\d+$"}
REC_ID = {"type": "string", "pattern": r"^REC-\d+$"}
KIND = {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"}
TRAIT_ID = {"type": "string", "pattern": "^(x-)?[a-z][a-z0-9_]*$"}
SOURCES = ["runner", "role_confirmed", "evidence", "from_tracker", "pasted"]
SURFACES = ["claude-code-local", "claude-code-cloud", "claude-app"]
SLUG = {"type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"}

def obj(props, required=None, extra=False):
    o = {"type": "object", "properties": props, "additionalProperties": extra}
    o["required"] = list(props) if required is None else required
    return o

def arr(items, **k):
    return {"type": "array", "items": items, **k}

def nullable(s):
    return {"anyOf": [s, {"type": "null"}]}

stamps = obj({
    "release": STR, "core": STR, "contract": MAJMIN, "plan_format": MAJMIN,
    "skills": arr(obj({"name": STR, "version": SEMVER, "verified": {"enum": ["verified", "unverified", "mismatch"]}})),
    "overlay": obj({"id": SLUG, "version": {"type": "integer", "minimum": 1}, "hash": HEX, "format": MAJMIN}),
    "validator": SEMVER, "surface": {"enum": SURFACES}, "model": STR,
    "compat": arr({"$ref": "#/$defs/compat"}),
})
compat = obj({"skill": STR, "result": {"enum": ["accepted", "accepted_with_note", "refused"]},
              "verified": {"enum": ["verified", "unverified", "mismatch"]}, "notes": arr(ANYSTR)})

# code and lang (plan format 2.1): a command or exact text, shown as a code block under the step.
step = obj({"text": STR, "refs": arr(STR), "from_evidence": nullable(EV_ID),
            "code": STR, "lang": {"type": "string", "pattern": "^[a-z0-9+#-]+$"}},
           required=["text", "refs", "from_evidence"])
finding = obj({
    "id": STR, "check": STR, "severity": {"enum": ["blocker", "minor"]},
    "target": nullable(STR), "what": STR, "evidence_ids": arr(EV_ID), "suggested_fix": ANYSTR,
    "resolution": {"enum": ["open", "fixed", "accepted_minor", "exception_requested", "needs_person"]},
}, required=["id", "check", "severity", "target", "what", "evidence_ids", "suggested_fix", "resolution"])

task = obj({
    "id": TASK_ID, "order": {"type": "integer", "minimum": 1},
    "key": {"type": "string", "pattern": r"^gw:gw-[0-9A-HJKMNP-TV-Z]{26}:P\d+-T\d{2,}$"},
    "phase": PHASE_ID, "title": STR,
    "work_type": {"enum": ["story", "task"]},
    "kind": {"enum": ["setup", "design", "build", "config", "data", "test", "uat", "cutover", "rollback", "docs", "training", "comms", "signoff_prep", "handoff",
                      "spike", "measurement", "reconciliation"]},
    "role_key": ROLE, "points": {"const": 1},
    "estimate_hours": {"type": "number", "exclusiveMinimum": 0},
    "parallel_group": nullable(ANYSTR),
    "depends_on": arr(obj({"task": TASK_ID, "satisfied_by": {"enum": ["done", "merged", "deployed"]}})),
    "waits_on": arr(obj({"what": STR,
                         "kind": {"enum": ["approval", "review", "merge", "vendor", "job", "access", "availability", "elapsed", "external_event"]},
                         "owner_role_key": ROLE, "condition": nullable(STR), "legacy_ref": nullable(STR)},
                        required=["what", "kind", "owner_role_key"])),
    "access": arr({"type": "string", "pattern": r"^A\d+$"}),
    "evidence_refs": arr(EV_ID),
    "produces": arr(obj({"type": STR, "name": STR})),
    "instructions": obj({
        "purpose": STR, "prerequisites": arr(STR), "steps": arr(step),
        "acceptance_criteria": arr(STR), "verify": arr(STR), "done_today": STR,
        "cautions": arr(STR),  # plan format 2.1
    }, required=["purpose", "prerequisites", "steps", "acceptance_criteria", "verify", "done_today"]),
    "visible_result": obj({"type": {"enum": ["pr_opened", "merged_pr", "deployed_change", "record_created", "record_updated", "doc_submitted", "comment_posted",
                                             "document", "decision_record", "measurement"]}, "text": STR}),
    "production_change": {"type": "boolean"}, "data_change": {"type": "boolean"},
    "test_tasks": arr(TASK_ID), "rollback_task": nullable(TASK_ID),
    "exception": nullable(obj({"id": STR, "reason": STR, "days": {"type": "integer", "minimum": 2},
                               "checkpoints": arr(obj({"day": {"type": "integer", "minimum": 1}, "visible_result": STR}))})),
    "origin": obj({"pattern": nullable(STR), "rules_checked": arr(STR)}),
    "changes_existing": nullable(obj({"resources": arr({"type": "string", "pattern": r"^R\d+$"}, minItems=1), "why_needed": STR,
                                      "could_break": arr(STR, minItems=1), "regression_check": arr(TASK_ID, minItems=1)})),
    # plan format 2: what the task serves and relies on (required there by GR-31)
    "brief_refs": arr(B_ID), "approach_refs": arr(AD_ID), "derived_from_rec": nullable(REC_ID),
    # adopt by reference: a manual task on a legacy item (never written to; the key stays in code spans)
    "legacy_action": nullable(obj({"ref": STR, "action": {"enum": ["close", "split", "update", "sequence"]}})),
})
TASK_REQUIRED = [k for k in task["properties"] if k not in ("brief_refs", "approach_refs", "derived_from_rec", "legacy_action")]
task["required"] = TASK_REQUIRED

brief_field = obj({
    "id": B_ID, "key": KIND, "value": nullable(STR),
    "status": {"enum": ["answered", "not_applicable", "open"]},
    "na_reason": nullable(STR), "open_question": nullable(Q_ID), "phase": nullable(PHASE_ID),
    "source": {"enum": SOURCES}, "basis_role_key": nullable(ROLE), "derived_from": arr(STR),
    "sensitivity": {"enum": ["normal", "restricted"]}, "value_rev": nullable({"type": "integer", "minimum": 1}),
})
approach = obj({
    "options": arr(obj({"id": O_ID, "summary": STR,
                        "kind": {"enum": ["reuse_extend", "smaller", "do_nothing", "new", "other"]},
                        "evidence": arr(EV_ID), "not_inspected_reason": nullable(STR), "pros": arr(STR), "cons": arr(STR),
                        "rejected_because": nullable(obj({"brief_ref": B_ID, "why": STR}))}), minItems=2),
    "decisions": arr(obj({"id": AD_ID, "decision": STR,
                          "chosen_option": {"anyOf": [O_ID, {"const": "deferred"}]},
                          "deferred_to_task": nullable(TASK_ID), "brief_refs": arr(B_ID), "evidence": arr(EV_ID),
                          "trait_conflict": arr(TRAIT_ID)},
                         required=["id", "decision", "chosen_option", "deferred_to_task", "brief_refs", "evidence"]), minItems=1),
    "unchanged": arr(R_ID),
})

plan = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "groundwork/plan/1.0",
    "title": "Groundwork plan",
    "$defs": {"compat": compat, "finding": finding, "task": task, "stamps": stamps},
    **obj({
        "schema_version": {"const": "1.0"},
        "id": PLAN_ID,
        "version": {"type": "integer", "minimum": 1},
        "status": {"enum": ["draft", "in_review", "proposed", "active", "revising", "complete", "retired"]},
        "overlay": obj({"id": SLUG, "version": {"type": "integer", "minimum": 1}, "hash": HEX}),
        "title": STR,
        "request": obj({"original_text": STR, "restatement": STR,
                        "clarifications": arr(obj({"id": STR, "question": STR, "answer": STR, "answered_by": STR, "at": TS})),
                        "starting_point": obj({
                            "kind": {"enum": ["from_scratch", "extends_existing"]},
                            "resources": arr(obj({"id": {"type": "string", "pattern": r"^R\d+$"}, "name": STR,
                                                  "kind": {"enum": ["code", "pipeline", "doc", "ticket", "system_object", "other"]},
                                                  "location": STR, "inspected": arr(EV_ID), "not_inspected_reason": nullable(STR)}))})}),
        "scope": obj({"in": arr(STR), "out": arr(STR),
                      "assumptions": arr(obj({"text": STR, "basis": STR}))}),
        "epic": obj({"key": {"type": "string", "pattern": r"^gw:gw-[0-9A-HJKMNP-TV-Z]{26}:epic$"},
                     "tracker_ref": nullable(STR), "title": STR, "summary": STR,
                     "links": arr(obj({"relation": {"enum": ["precedes", "follows", "relates"]}, "epic_ref": STR}))}),
        "executor": obj({"profile": {"enum": ["junior_no_context", "junior_with_context", "mid_no_context"]},
                         "working_day_hours": {"type": "number", "minimum": 1, "maximum": 8}}),
        "open_questions": arr(obj({"id": {"type": "string", "pattern": r"^Q-\d+$"}, "text": STR,
                                   "blocks": arr(STR), "status": {"enum": ["open", "answered"]},
                                   "answer": nullable(ANYSTR), "answered_by": nullable(ANYSTR), "at": nullable(TS)})),
        "coverage": arr(obj({"system": STR, "instance": STR, "skill": nullable(STR), "skill_version": nullable(STR),
                             "surface": {"enum": SURFACES},
                             "status": {"enum": ["inspected", "partial", "not_inspected"]},
                             "read_only": {"enum": ["enforced", "instructed_only", "not_applicable"]},
                             "inspected": arr(ANYSTR), "not_inspected": arr(ANYSTR), "reason": ANYSTR})),
        "access_list": arr(obj({"id": {"type": "string", "pattern": r"^A\d+$"}, "role_key": ROLE,
                                "system": STR, "instance": STR, "level": STR, "needed_by": arr(TASK_ID, minItems=1)})),
        "phases": arr(obj({"id": PHASE_ID, "order": {"type": "integer", "minimum": 0}, "name": STR, "goal": STR,
                           "state": {"enum": ["outline", "drafted", "reviewed", "approved", "writing", "released"]},
                           "depends_on": arr(PHASE_ID), "task_ids": arr(TASK_ID),
                           "carries_questions": arr(STR)},
                          required=["id", "order", "name", "goal", "state", "depends_on", "task_ids"]), minItems=1),
        "tasks": arr({"$ref": "#/$defs/task"}),
        # v1 kinds plus kinds declared by the plan's pinned traits (GR-09, GR-33)
        "standard_work": arr(obj({"kind": KIND,
                                  "tasks": arr(TASK_ID), "not_applicable_reason": nullable(ANYSTR)})),
        "review": obj({
            "validator": nullable(obj({"version": SEMVER, "passed": {"type": "boolean"}, "results": arr({"$ref": "#/$defs/finding"}),
                                       "not_run": arr(STR)}, required=["version", "passed", "results"])),
            "reviewer": nullable(obj({"surface": {"enum": SURFACES}, "model": STR, "view_hash": HEX, "independent": {"type": "boolean"},
                                      "mode": {"enum": ["subagent", "fresh_conversation"]},
                                      "findings": arr({"$ref": "#/$defs/finding"}), "not_performed": arr(ANYSTR)})),
        }),
        "approvals": arr(STR),
        "stamps": {"$ref": "#/$defs/stamps"},
        "history": arr(obj({"version": {"type": "integer", "minimum": 1}, "at": TS, "change": STR, "by": STR})),
        # plan format 2 (planning model): the brief, the traits and the approach. Absent in format-1 plans.
        "traits": arr(obj({"id": TRAIT_ID, "version": SEMVER, "from_plan_version": {"type": "integer", "minimum": 1}})),
        "brief": arr({"$ref": "#/$defs/brief_field"}),
        "approach": {"$ref": "#/$defs/approach"},
        # adopt by reference: legacy items the plan refers to, as read by assess; legacy items are not tasks
        "legacy_refs": arr(obj({"key": STR, "status": {"enum": ["todo", "in_progress", "done", "closed_not_done"]},
                                "points": nullable({"type": "number", "minimum": 0}), "parent": nullable(STR),
                                "updated_at": TS, "read_at": TS})),
    }),
}
plan["required"] = [k for k in plan["properties"] if k not in ("traits", "brief", "approach", "legacy_refs")]
plan["$defs"]["brief_field"] = brief_field
plan["$defs"]["approach"] = approach

evidence = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/evidence/1.0", "title": "Groundwork evidence item",
    **obj({
        "schema_version": {"const": "1.0"}, "id": EV_ID, "run_id": PLAN_ID, "overlay_id": SLUG,
        "system": SLUG, "instance": STR, "skill": {"type": "string", "pattern": r"^groundwork-[a-z0-9-]+@\d+\.\d+\.\d+$"},
        "surface": {"enum": SURFACES}, "method": STR, "collected_at": TS, "recheck": {"type": "boolean"},
        "subject": obj({"type": SLUG, "name": STR}), "facts": {"type": "object"},
        "untrusted_text": arr(obj({"field": STR, "text": ANYSTR})),
        "sensitivity": {"enum": ["structure", "config", "count", "restricted"]}, "hash": HEX,
    }),
}

approval = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/approval/1.0", "title": "Groundwork approval record",
    **obj({
        "schema_version": {"const": "1.0"}, "id": {"type": "string", "pattern": r"^A-\d+$"},
        "kind": {"enum": ["initial", "release", "revision", "exception", "decline", "own_epic", "retire", "later"]},
        # phases (default) or plan_level: a plan-level record has phases [] (planning model 4.3)
        "scope": {"enum": ["phases", "plan_level"]},
        "plan_id": PLAN_ID, "plan_version": {"type": "integer", "minimum": 1}, "plan_hash": HEX,
        "plan_store_ref": STR, "phases": arr(PHASE_ID), "phase_hashes": {"type": "object", "patternProperties": {r"^P\d+$": HEX}, "additionalProperties": False},
        "write_list_hash": HEX, "proposal_hash": HEX, "review_hash": HEX, "view_hash": HEX,
        "accept_unverified_writer": {"type": "boolean"}, "gate": STR,
        "approver": obj({"account_id": STR, "name": STR}),
        "minors_accepted": arr(STR), "exceptions_accepted": arr(STR),
        # optional: the approver's decision on each review blocker Resolve handed to a person (needs_person)
        "decisions": arr(obj({"finding": STR, "decision": STR})),
        "artifact": nullable(obj({"tracker_comment_ref": STR, "author_account_id": STR, "verified_at": TS})),
    }),
}
approval["required"] = [k for k in approval["properties"] if k not in ("scope", "decisions")]

change_requests = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/change-requests/1.0",
    "title": "Groundwork change-request log (change-requests-<n>.json; outside plan_hash)",
    **obj({
        "schema_version": {"const": "1.0"}, "plan_id": PLAN_ID, "n": {"type": "integer", "minimum": 1},
        "entries": arr(obj({
            "id": {"type": "string", "pattern": r"^CR-\d+$"},
            "restatement": STR,                      # the runner-confirmed restatement; never restricted
            "source": {"enum": ["runner", "pasted"]},
            "derived_from": arr(STR),                # evidence ids of pasted text (system: runner)
            "origin_role_key": ROLE,                 # who asked, as a role, never a name
            "outcome": {"enum": ["pending", "added", "later", "own_epic", "declined"]},
            "reason": nullable(STR),
            "base": obj({"plan_version": {"type": "integer", "minimum": 1}, "manifest_seq": {"type": "integer", "minimum": 0}}),
            "decided_by": nullable(obj({"plan_version": {"type": "integer", "minimum": 1}, "proposal_hash": HEX})),
        })),
        "prev_hash": nullable(HEX),                  # the previous log file's hash; null for the first
        "hash": HEX,                                 # item_hash of the file without this field
    }),
}

plan_status = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/plan-status/1.0",
    "title": "Groundwork plan status (status-<n>.json; the latest wins over plan.status)",
    **obj({
        "schema_version": {"const": "1.0"}, "plan_id": PLAN_ID, "n": {"type": "integer", "minimum": 1},
        "status": {"enum": ["retired"]},
        "set_by": obj({"plan_version": {"type": "integer", "minimum": 1}, "proposal_hash": HEX}),
        "at": TS, "hash": HEX,
    }),
}

proposal_context = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/proposal-context/1.0",
    "title": "Groundwork proposal context (stored at Proposal; create renders only from stored inputs)",
    **obj({
        "schema_version": {"const": "1.0"}, "plan_id": PLAN_ID, "plan_version": {"type": "integer", "minimum": 1},
        "kind": {"enum": ["initial", "release", "revision", "decline", "own_epic", "retire", "later"]},
        "summary": ANYSTR, "degraded": arr(STR),
        "items": arr(obj({"key": STR, "status": {"enum": ["todo", "in_progress", "done", "closed_not_done"]},
                          "person_added": {"type": "boolean"}})),
        "voided_sets": arr(STR),
    }),
}

manifest = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/manifest/1.0", "title": "Groundwork create manifest",
    **obj({
        "schema_version": {"const": "1.0"}, "plan_id": PLAN_ID, "seq": {"type": "integer", "minimum": 1},
        "prev_hash": nullable(HEX), "written_at": TS, "run_id": STR,
        "relies_on": arr(obj({"ref": STR, "hash": HEX})),
        # retire: the status intent is recorded before status-<n>.json is written, then the final
        # manifest records that file's hash; a status file the manifest neither intends nor records is a stop
        "status_file": nullable(obj({"state": {"enum": ["intent", "recorded"]}, "n": {"type": "integer", "minimum": 1},
                                     "hash": HEX, "at": TS,
                                     "set_by": obj({"plan_version": {"type": "integer", "minimum": 1},
                                                    "proposal_hash": HEX})})),
        # the epic's draft label came off; carried forward once set
        "draft_label_removed": {"const": True},
        "epic_owned_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "items": arr(obj({"key": STR, "tracker_id": STR, "owned_hash": HEX,
                          "links": arr(obj({"type": STR, "to_key": STR})), "not_ready": {"type": "boolean"},
                          "split_comment": {"type": "boolean"},
                          # set_blocked applied once at create (key + "blocked"); never reapplied after a person clears it
                          "blocked_set": {"type": "boolean"},
                          # each approved clear_blocked, and each set_blocked after a clear, in order (append only)
                          "blocked_changes": arr(obj({"state": {"enum": ["cleared", "set"]},
                                                      "plan_version": {"type": "integer", "minimum": 1}})),
                          # close intent is recorded before the gw-closed label; state becomes closed after the transition
                          "close": obj({"reason": {"enum": ["not_planned", "superseded", "duplicate", "completed"]},
                                        "state": {"enum": ["intent", "closed", "finished", "missing"]}})},
                         required=["key", "tracker_id", "owned_hash", "links", "not_ready"])),
        "hash": HEX,
    }),
}

manifest["required"] = [k for k in manifest["properties"] if k not in ("status_file", "draft_label_removed", "epic_owned_hash")]

journal = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/journal/1.0", "title": "Groundwork journal line",
    **obj({
        "schema_version": {"const": "1.0"}, "at": TS, "run_id": STR, "stage": {"type": "integer", "minimum": 1, "maximum": 10},
        "event": {"enum": ["stage_started", "stage_done", "stopped", "write_done", "write_failed", "handshake", "resumed"]},
        "write_no": nullable({"type": "integer", "minimum": 1}), "detail": ANYSTR,
    }),
}

handshake = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/handshake/1.0", "title": "Groundwork skill handshake",
    **obj({"schema_version": {"const": "1.0"}, "name": {"type": "string", "pattern": "^groundwork-[a-z0-9-]+$", "maxLength": 64},
           "kind": {"enum": ["system", "tracker"]}, "version": SEMVER, "release": STR, "contract": MAJMIN, "platform": SLUG}),
}

skill_manifest = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/skill-manifest/1.0", "title": "groundwork.yaml",
    **obj({
        "schema_version": {"const": "1.0"}, "kind": {"enum": ["core", "system", "tracker"]},
        "name": {"type": "string", "pattern": "^groundwork-[a-z0-9-]+$", "maxLength": 64},
        "platform": nullable(SLUG), "version": SEMVER, "release": STR, "contract": MAJMIN,
        "surfaces": {"type": "object", "properties": {s: obj({"connect": arr(STR), "coverage": {"enum": ["full", "partial", "none"]}}) for s in SURFACES},
                     "required": SURFACES, "additionalProperties": False},
        "rule_prefix": nullable(SLUG), "sections": arr(STR),
    }),
}

rules = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/rules/1.0", "title": "Skill correctness rules",
    **obj({"schema_version": {"const": "1.0"},
           "rules": arr(obj({"id": {"type": "string", "pattern": r"^[a-z0-9]+(-[a-z0-9]+)*\.[a-z0-9]+(-[a-z0-9]+)*$"},
                             "applies_when": STR, "check": STR, "severity": {"enum": ["blocker", "minor"]},
                             "source": {"type": "string", "pattern": "^https://"}}))}),
}

review = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/review/1.0", "title": "Independent reviewer output",
    "$defs": {"finding": finding},
    **obj({"schema_version": {"const": "1.0"}, "view_hash": HEX, "surface": {"enum": SURFACES}, "model": STR,
           "mode": {"enum": ["subagent", "fresh_conversation"]},
           "findings": arr({"$ref": "#/$defs/finding"}), "not_performed": arr(ANYSTR)}),
}

ROLE_HOLDER = obj({"role_key": ROLE, "display": STR, "handle": nullable(STR), "account_id": nullable(STR)},
                  required=["role_key", "display"])
ACCOUNT = obj({"account_id": STR, "name": STR})
overlay = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "groundwork/overlay/1.0", "title": "Groundwork org overlay",
    "patternProperties": {"^x-": True},
    **obj({
        "schema_version": {"const": "1.0"}, "overlay_format": {"type": "string", "pattern": r"^1\.\d+$"},
        "id": SLUG, "version": {"type": "integer", "minimum": 1}, "hash": nullable(HEX), "org_name": STR,
        "admins": arr(ACCOUNT),
        "provisional": {"type": "boolean"},
        "skills": obj({
            "core": STR,
            "systems": arr(obj({"skill": {"type": "string", "pattern": "^groundwork-system-[a-z0-9-]+$"}, "version": STR,
                                "instances": arr(obj({"id": STR, "url": {"type": "string", "pattern": "^https://"},
                                                      "expected_identity": {"type": "object"}}), minItems=1),
                                "expectations": arr(obj({"id": STR, "check": STR, "confirmed_value": {}})),
                                "readiness": arr(obj({"check": STR, "status": {"enum": ["ok", "gap_reported"]}, "note": ANYSTR}))})),
            "unsupported_systems": arr(obj({"name": STR, "note": ANYSTR})),
            "tracker": obj({"skill": {"type": "string", "pattern": "^groundwork-tracker-[a-z0-9-]+$"}, "version": STR,
                            "instance": obj({"id": STR, "url": {"type": "string", "pattern": "^https://"}, "project": STR}),
                            "field_map": obj({"key": obj({"slot": {"enum": ["label", "field", "item_property"]}, "name": STR}, required=["slot"]),
                                              "points": STR, "hours": nullable(STR), "phase": STR, "blocked": STR,
                                              "depends_on": STR, "not_ready": STR, "role": nullable(STR),
                                              "work_types": obj({"story": STR, "task": STR}),
                                              "phase_release": {"enum": ["version", "milestone", "label"]},
                                              # Tracker statuses, resolutions or close reasons that mean "closed, not done";
                                              # required so a person's not-planned close never reads as done (section 2).
                                              "statuses": obj({"done": arr(STR, minItems=1), "closed_not_done": arr(STR, minItems=1)}),
                                              "close_label_prefix": {"type": "string", "pattern": "^[a-z][a-z0-9-]*:$"}},
                                             required=["key", "points", "phase", "blocked", "depends_on", "not_ready", "statuses"]),
                            # Upper bound on items read_scope returns before the runner must narrow (assess, at most 200).
                            "read_scope_limit": {"type": "integer", "minimum": 1, "maximum": 200}},
                           required=["skill", "version", "field_map"]),
        }),
        "working_day_hours": {"type": "number", "minimum": 1, "maximum": 8},
        "assumed_executor": {"enum": EXECUTORS},
        "roles": arr(obj({"key": ROLE, "name": STR}), minItems=1),
        # Per-role executor profiles; a role not listed uses assumed_executor (GR-02, GR-06).
        "executor_profiles": {"type": "object", "patternProperties": {"^(x-)?[a-z][a-z0-9_]*$": {"enum": EXECUTORS}}, "additionalProperties": False},
        # Org-only traits; they may only add questions, standard work and roles (validate_overlay.py).
        "traits": arr(obj({"id": {"type": "string", "pattern": "^x-[a-z][a-z0-9_]*$"}, "version": SEMVER, "summary": STR,
                           "questions": arr(obj({"key": KIND, "text": STR})), "standard_work": arr(KIND), "roles": arr(ROLE),
                           "conflicts": arr(obj({"with": TRAIT_ID, "about": STR}))})),
        # Org processes (change freezes, change boards, spend approval) shown in proposals; never asked per run.
        "org_process": arr(obj({"name": STR, "note": STR})),
        "task_hierarchy": obj({"task_to_epic": {"enum": ["parent", "linked"]}, "steps_as": {"enum": ["checklist", "subtasks"]}}),
        "approval_gates": arr(obj({"id": STR, "applies_to": {"enum": ["all_phases", "one_day_exceptions", "overlay_changes"]},
                                   "approvers": arr(ACCOUNT, minItems=1), "min_approvers": {"type": "integer", "minimum": 1}},
                                  required=["id", "applies_to", "approvers"])),
        "evidence_max_age_days": {"type": "integer", "minimum": 1, "maximum": 90},
        "create_window_days": {"type": "integer", "minimum": 1, "maximum": 30},
        "anchor": obj({"tracker_ref": nullable(STR)}),
        "role_holders": arr(ROLE_HOLDER),
        "tracker_access_assumed": {"type": "boolean"},
        "environments": arr(obj({"name": STR, "shared": {"type": "boolean"}})),
        "labels": obj({"draft": STR, "not_ready": STR}),
        "plan_store": obj({"mode": {"enum": ["attachments", "repo_path"]}, "repo": nullable(STR), "path": nullable(STR)}, required=["mode"]),
        "naming": obj({"epic": STR, "task": STR, "label": STR}),
        "access_requests": obj({"how": STR, "link": nullable(STR), "on_behalf_allowed": {"type": "boolean"}}),
        "channels": obj({"release": nullable(STR), "announcements": nullable(STR)}),
        "run_storage": {"type": "object", "properties": {s: STR for s in SURFACES}, "additionalProperties": False},
    }, required=["schema_version", "overlay_format", "id", "version", "org_name", "admins", "skills", "roles", "approval_gates", "anchor"]),
}

import sys
out = os.path.join(os.path.dirname(__file__), "..", "..", "skills", "groundwork-core", "schemas")
check = "--check" in sys.argv
stale = []
for name, sch in [("plan", plan), ("evidence", evidence), ("approval", approval), ("proposal-context", proposal_context), ("change-requests", change_requests), ("plan-status", plan_status), ("manifest", manifest), ("journal", journal),
                  ("handshake", handshake), ("skill-manifest", skill_manifest), ("rules", rules), ("review", review), ("overlay", overlay)]:
    path = os.path.join(out, f"{name}.schema.json")
    text = json.dumps(sch, indent=2) + "\n"
    if check:
        if not os.path.exists(path) or open(path).read() != text:
            stale.append(name)
        continue
    with open(path, "w") as f:
        f.write(text)
if stale:
    print("schemas out of date (run tools/gen/make_schemas.py):", ", ".join(stale))
    sys.exit(1)
print("ok")
