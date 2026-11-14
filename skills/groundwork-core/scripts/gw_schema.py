# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""A small JSON Schema validator (draft 2020-12 subset), standard library only.

Supported keywords: type, enum, const, properties, required,
additionalProperties (bool or schema), patternProperties, items, minItems,
maxItems, uniqueItems, minLength, maxLength, pattern, minimum, maximum,
exclusiveMinimum, exclusiveMaximum, anyOf, oneOf, allOf, not, $ref (local
"#/$defs/..." only), $defs. Unknown keywords are an error, so a schema
cannot silently rely on something this validator ignores.
"""

import json
import os
import re

__all__ = ["validate", "load_schema", "SchemaError"]

_KNOWN = {
    "$schema", "$id", "$defs", "$ref", "$comment", "title", "description", "examples", "default",
    "type", "enum", "const", "properties", "required", "additionalProperties", "patternProperties",
    "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "anyOf", "oneOf", "allOf", "not",
}


class SchemaError(ValueError):
    pass


def _type_ok(v, t):
    if t == "null":
        return v is None
    if t == "boolean":
        return isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool) or (isinstance(v, float) and v.is_integer())
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "string":
        return isinstance(v, str)
    if t == "array":
        return isinstance(v, list)
    if t == "object":
        return isinstance(v, dict)
    raise SchemaError(f"unknown type {t}")


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise SchemaError(f"only local refs are supported: {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _walk(v, s, root, path, errors):
    if s is True:
        return
    if s is False:
        errors.append(f"{path}: not allowed")
        return
    unknown = set(s) - _KNOWN
    if unknown:
        raise SchemaError(f"schema at {path} uses unsupported keywords {sorted(unknown)}")
    if "$ref" in s:
        _walk(v, _resolve(root, s["$ref"]), root, path, errors)
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(v, t) for t in types):
            errors.append(f"{path}: expected {'/'.join(types)}, got {type(v).__name__}")
            return
    if "enum" in s and v not in s["enum"]:
        errors.append(f"{path}: {v!r} is not one of {s['enum']}")
    if "const" in s and v != s["const"]:
        errors.append(f"{path}: must be {s['const']!r}")
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]:
            errors.append(f"{path}: shorter than {s['minLength']}")
        if "maxLength" in s and len(v) > s["maxLength"]:
            errors.append(f"{path}: longer than {s['maxLength']}")
        if "pattern" in s and not re.search(s["pattern"], v):
            errors.append(f"{path}: {v!r} does not match {s['pattern']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errors.append(f"{path}: below {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errors.append(f"{path}: above {s['maximum']}")
        if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
            errors.append(f"{path}: must be above {s['exclusiveMinimum']}")
        if "exclusiveMaximum" in s and v >= s["exclusiveMaximum"]:
            errors.append(f"{path}: must be below {s['exclusiveMaximum']}")
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            errors.append(f"{path}: needs at least {s['minItems']} items")
        if "maxItems" in s and len(v) > s["maxItems"]:
            errors.append(f"{path}: allows at most {s['maxItems']} items")
        if s.get("uniqueItems"):
            seen = [json.dumps(x, sort_keys=True) for x in v]
            if len(seen) != len(set(seen)):
                errors.append(f"{path}: items must be unique")
        if "items" in s:
            for i, item in enumerate(v):
                _walk(item, s["items"], root, f"{path}[{i}]", errors)
    if isinstance(v, dict):
        for r in s.get("required", []):
            if r not in v:
                errors.append(f"{path}: missing required '{r}'")
        props = s.get("properties", {})
        pprops = s.get("patternProperties", {})
        for k, item in v.items():
            matched = False
            if k in props:
                _walk(item, props[k], root, f"{path}.{k}", errors)
                matched = True
            for pat, sub in pprops.items():
                if re.search(pat, k):
                    _walk(item, sub, root, f"{path}.{k}", errors)
                    matched = True
            if not matched and "additionalProperties" in s:
                ap = s["additionalProperties"]
                if ap is False:
                    errors.append(f"{path}: unknown field '{k}'")
                else:
                    _walk(item, ap, root, f"{path}.{k}", errors)
    for sub in s.get("allOf", []):
        _walk(v, sub, root, path, errors)
    if "anyOf" in s:
        if not any(not _collect(v, sub, root, path) for sub in s["anyOf"]):
            errors.append(f"{path}: matches none of the allowed shapes")
    if "oneOf" in s:
        n = sum(1 for sub in s["oneOf"] if not _collect(v, sub, root, path))
        if n != 1:
            errors.append(f"{path}: must match exactly one allowed shape, matched {n}")
    if "not" in s and not _collect(v, s["not"], root, path):
        errors.append(f"{path}: matches a forbidden shape")


def _collect(v, s, root, path):
    errs = []
    _walk(v, s, root, path, errs)
    return errs


def validate(value, schema):
    """Return a list of error strings; empty means valid."""
    return _collect(value, schema, schema, "$")


def load_schema(name):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "schemas", name if name.endswith(".json") else f"{name}.schema.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)
