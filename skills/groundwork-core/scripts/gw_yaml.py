# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Groundwork YAML subset: a small, strict parser and writer.

Groundwork scripts use the Python standard library only, so they run in the
Claude app's sandbox, cloud sessions and locally with nothing installed. The
standard library has no YAML parser, so Groundwork files that people edit
(overlay.yaml, groundwork.yaml) use this documented subset:

- Block mappings (`key: value`) and block sequences (`- item`), indented with
  spaces only.
- Flow mappings `{a: 1, b: [x, y]}` and flow sequences `[a, b]`, nestable.
- Scalars: plain, 'single' or "double" quoted; null/~, true/false, integers,
  decimals. Everything else is a string.
- `#` comments, at line start or after whitespace outside quotes.
- No anchors, aliases, tags, multi-line strings or multiple documents.

Anything outside the subset is an error with a line number, never a guess.
"""

import json
import re

__all__ = ["loads", "load", "dumps", "YamlError"]


class YamlError(ValueError):
    def __init__(self, msg, line=None):
        self.line = line
        super().__init__(f"line {line}: {msg}" if line else msg)


_INT = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")
_FLOAT = re.compile(r"^[-+]?(0|[1-9][0-9]*)\.[0-9]+$")
_KEY = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*|\"[^\"]*\"|'[^']*')\s*:(\s|$)")
_FORBIDDEN_START = ("&", "*", "!", "|", ">", "%", "@", "`")


def _strip_comment(text):
    out = []
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        else:
            if c in "\"'":
                quote = c
            elif c == "#" and (i == 0 or text[i - 1] in " \t"):
                break
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _scalar(tok, line):
    tok = tok.strip()
    if tok == "" or tok in ("null", "~", "Null", "NULL"):
        return None
    if tok[0] == '"':
        if len(tok) < 2 or tok[-1] != '"':
            raise YamlError("unterminated double-quoted string", line)
        try:
            return json.loads(tok)
        except ValueError as e:
            raise YamlError(f"bad double-quoted string: {e}", line)
    if tok[0] == "'":
        if len(tok) < 2 or tok[-1] != "'":
            raise YamlError("unterminated single-quoted string", line)
        return tok[1:-1].replace("''", "'")
    if tok.startswith(_FORBIDDEN_START):
        raise YamlError(f"'{tok[0]}' (anchors, aliases, tags, block scalars) is outside the Groundwork YAML subset", line)
    if tok in ("true", "True", "TRUE"):
        return True
    if tok in ("false", "False", "FALSE"):
        return False
    if _INT.match(tok):
        return int(tok)
    if _FLOAT.match(tok):
        return float(tok)
    if tok.startswith(("{", "[")):
        raise YamlError("unbalanced flow collection", line)
    return tok


class _Flow:
    def __init__(self, text, line):
        self.s = text
        self.i = 0
        self.line = line

    def err(self, msg):
        raise YamlError(f"{msg} in flow value", self.line)

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self):
        self.ws()
        if self.i >= len(self.s):
            self.err("missing value")
        c = self.s[self.i]
        if c == "{":
            return self.mapping()
        if c == "[":
            return self.sequence()
        return _scalar(self.token(), self.line)

    def token(self):
        self.ws()
        start = self.i
        if self.i < len(self.s) and self.s[self.i] in "\"'":
            q = self.s[self.i]
            self.i += 1
            while self.i < len(self.s):
                if q == '"' and self.s[self.i] == "\\":
                    self.i += 2
                    continue
                if self.s[self.i] == q:
                    if q == "'" and self.s[self.i + 1:self.i + 2] == "'":
                        self.i += 2
                        continue
                    self.i += 1
                    return self.s[start:self.i]
                self.i += 1
            self.err("unterminated string")
        while self.i < len(self.s) and self.s[self.i] not in ",]}":
            if self.s[self.i] == ":" and (self.i + 1 >= len(self.s) or self.s[self.i + 1] in " \t"):
                break
            self.i += 1
        return self.s[start:self.i].strip()

    def mapping(self):
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            key = self.token()
            if key == "":
                self.err("empty key")
            k = _scalar(key, self.line)
            if not isinstance(k, str):
                k = key
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
                self.ws()
                if self.i < len(self.s) and self.s[self.i] in ",}":
                    v = None
                else:
                    v = self.value()
            else:
                v = None  # {a, b} shorthand: keys with null values
            if k in out:
                self.err(f"duplicate key '{k}'")
            out[k] = v
            self.ws()
            if self.i >= len(self.s):
                self.err("unclosed '{'")
            if self.s[self.i] == ",":
                self.i += 1
            elif self.s[self.i] != "}":
                self.err("expected ',' or '}'")

    def sequence(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.ws()
            if self.i >= len(self.s):
                self.err("unclosed '['")
            if self.s[self.i] == ",":
                self.i += 1
            elif self.s[self.i] != "]":
                self.err("expected ',' or ']'")


def _inline(text, line):
    text = text.strip()
    if text.startswith(("{", "[")):
        f = _Flow(text, line)
        v = f.value()
        f.ws()
        if f.i != len(text):
            raise YamlError("trailing text after flow value", line)
        return v
    return _scalar(text, line)


def loads(text):
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError("tabs are not allowed for indentation", n)
        s = _strip_comment(raw)
        if s.strip() == "" or s.strip() == "---":
            continue
        if s.strip() == "...":
            break
        lines.append((n, len(s) - len(s.lstrip(" ")), s.strip()))
    if not lines:
        return None
    pos = [0]

    def parse_block(indent):
        n, ind, s = lines[pos[0]]
        if s.startswith("- ") or s == "-":
            return parse_seq(ind)
        if _KEY.match(s):
            return parse_map(ind)
        pos[0] += 1
        return _inline(s, n)

    def parse_seq(indent):
        out = []
        while pos[0] < len(lines):
            n, ind, s = lines[pos[0]]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("unexpected indentation", n)
            if not (s.startswith("- ") or s == "-"):
                break
            rest = s[1:].strip()
            if rest == "":
                pos[0] += 1
                if pos[0] < len(lines) and lines[pos[0]][1] > indent:
                    out.append(parse_block(lines[pos[0]][1]))
                else:
                    out.append(None)
            elif _KEY.match(rest) and not rest.startswith(("{", "[")):
                # "- key: value" starts a mapping indented at the dash + 2
                child = indent + (len(s) - len(rest))
                lines[pos[0]] = (n, child, rest)
                out.append(parse_map(child))
            else:
                pos[0] += 1
                out.append(_inline(rest, n))
        return out

    def parse_map(indent):
        out = {}
        while pos[0] < len(lines):
            n, ind, s = lines[pos[0]]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("unexpected indentation", n)
            m = _KEY.match(s)
            if not m:
                if s.startswith("- "):
                    break
                raise YamlError(f"expected 'key: value', got '{s}'", n)
            key = m.group(1)
            if key[0] in "\"'":
                key = key[1:-1]
            if key in out:
                raise YamlError(f"duplicate key '{key}'", n)
            rest = s[m.end():].strip()
            pos[0] += 1
            if rest == "":
                if pos[0] < len(lines) and (lines[pos[0]][1] > indent or (lines[pos[0]][1] == indent and lines[pos[0]][2].startswith("- "))):
                    out[key] = parse_block(lines[pos[0]][1])
                else:
                    out[key] = None
            else:
                out[key] = _inline(rest, n)
        return out

    result = parse_block(lines[0][1])
    if pos[0] != len(lines):
        n = lines[pos[0]][0]
        raise YamlError("could not parse from here (check indentation)", n)
    return result


def load(path):
    with open(path, encoding="utf-8") as f:
        return loads(f.read())


_PLAIN_OK = re.compile(r"^[A-Za-z_./][A-Za-z0-9_./@+\- ]*$")


def _dump_scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    s = str(v)
    if (_PLAIN_OK.match(s) and s.strip() == s and _scalar(s, None) == s
            and ": " not in s and " #" not in s):
        return s
    return json.dumps(s, ensure_ascii=False)


def dumps(data, indent=0):
    """Write data in the Groundwork YAML subset (block style)."""
    pad = " " * indent
    lines = []
    if isinstance(data, dict):
        if not data:
            return pad + "{}\n"
        for k, v in data.items():
            key = _dump_scalar(str(k))
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key}:\n" + dumps(v, indent + 2))
            elif isinstance(v, dict):
                lines.append(f"{pad}{key}: {{}}\n")
            elif isinstance(v, list):
                lines.append(f"{pad}{key}: []\n")
            else:
                lines.append(f"{pad}{key}: {_dump_scalar(v)}\n")
        return "".join(lines)
    if isinstance(data, list):
        if not data:
            return pad + "[]\n"
        for v in data:
            if isinstance(v, dict) and v:
                body = dumps(v, indent + 2)
                lines.append(pad + "- " + body[indent + 2:])
            elif isinstance(v, list) and v:
                lines.append(pad + "-\n" + dumps(v, indent + 2))
            else:
                lines.append(pad + "- " + (_dump_scalar(v) if not isinstance(v, (dict, list)) else ("{}" if isinstance(v, dict) else "[]")) + "\n")
        return "".join(lines)
    return pad + _dump_scalar(data) + "\n"
