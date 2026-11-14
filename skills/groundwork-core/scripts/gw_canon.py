# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""RFC 8785 JSON Canonicalization Scheme (JCS) and SHA-256 helpers.

Every Groundwork hash is SHA-256 over the JCS form of a JSON value, computed
here and never by the model.
"""

import hashlib
import json
import math

__all__ = ["canonicalize", "sha256_hex", "hash_value", "short"]


def _number(x):
    if isinstance(x, bool):
        raise TypeError("bool is not a number")
    if isinstance(x, int):
        if abs(x) > 2 ** 53:
            raise ValueError("integer outside the IEEE 754 safe range; store it as a string")
        return str(x)
    if math.isnan(x) or math.isinf(x):
        raise ValueError("NaN and Infinity are not valid JSON")
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    # Shortest round-trip digits, as ECMAScript Number.prototype.toString.
    r = repr(x)
    sign = ""
    if r[0] == "-":
        sign, r = "-", r[1:]
    if "e" in r:
        mant, exp = r.split("e")
        exp = int(exp)
    else:
        mant, exp = r, 0
    if "." in mant:
        ip, fp = mant.split(".")
    else:
        ip, fp = mant, ""
    digits = (ip + fp).lstrip("0")
    lead_zeros = len(ip + fp) - len((ip + fp).lstrip("0"))
    point = len(ip) + exp - lead_zeros  # position of the decimal point relative to digits
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    n = point
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    es = ("+" if e > 0 else "-") + str(abs(e))
    if k == 1:
        return sign + digits + "e" + es
    return sign + digits[0] + "." + digits[1:] + "e" + es


def _string(s):
    return json.dumps(s, ensure_ascii=False)


def _utf16_key(s):
    return s.encode("utf-16-be")


def _canon(v, out):
    if v is None:
        out.append("null")
    elif v is True:
        out.append("true")
    elif v is False:
        out.append("false")
    elif isinstance(v, (int, float)):
        out.append(_number(v))
    elif isinstance(v, str):
        out.append(_string(v))
    elif isinstance(v, (list, tuple)):
        out.append("[")
        for i, item in enumerate(v):
            if i:
                out.append(",")
            _canon(item, out)
        out.append("]")
    elif isinstance(v, dict):
        out.append("{")
        for i, k in enumerate(sorted(v.keys(), key=_utf16_key)):
            if not isinstance(k, str):
                raise TypeError("object keys must be strings")
            if i:
                out.append(",")
            out.append(_string(k))
            out.append(":")
            _canon(v[k], out)
        out.append("}")
    else:
        raise TypeError(f"cannot canonicalize {type(v).__name__}")


def canonicalize(value):
    """Return the RFC 8785 canonical form of value as UTF-8 bytes."""
    out = []
    _canon(value, out)
    return "".join(out).encode("utf-8")


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_value(value):
    """SHA-256 hex of the canonical form of value."""
    return sha256_hex(canonicalize(value))


def short(h):
    """The short form shown to people: first 12 hex characters."""
    return h[:12]
