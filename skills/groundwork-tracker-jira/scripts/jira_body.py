#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Jira bodies for Groundwork's owned sections: the core's rendered Markdown to real Jira
formatting and back.

Writing turns the owned Markdown into headings, bullet lists, a checklist for the steps,
tables, rules and inline code, as Atlassian Document Format (REST) or the equivalent HTML
(the Atlassian connector's html content format). The two owned markers are not written as
text: the owned section runs from the top of the description through a collapsed expand
titled "Groundwork details" that holds the key and stamps lines. Anything a person adds
below that expand is theirs.

Reading (normalize) turns ADF or the connector's HTML back into exactly the Markdown the
core rendered, markers included, so check_hashes.py owned gives the same hash. Bodies
written by skill 1.0.0 (one paragraph per line, markers as text) are still read.

Every write first checks the round trip; a body whose round trip differs is written in the
1.0.0 form instead, so a stored owned hash can always be recomputed.

Usage:
  jira_body.py adf  BODY.md    > BODY.adf.json   (REST write)
  jira_body.py html BODY.md    > BODY.html       (connector write, contentFormat html)
  jira_body.py read FILE       > OWNED.md        (FILE is ADF JSON, connector HTML, or connector Markdown)
  jira_body.py check BODY.md                     (exit 0 when the round trip is exact)
"""
import html as _html
import json
import re
import sys
from html.parser import HTMLParser

START = "<!-- groundwork:owned:start -->"
END = "<!-- groundwork:owned:end -->"
DETAILS = "Groundwork details"
KEY_LINE = re.compile(r"^`gw:[^`]+`")
TASK = re.compile(r"^- \[[ xX]\] ")
URL = re.compile(r"https?://[^\s<>()]+[^\s<>().,;:]")

# ---------------------------------------------------------------- Markdown -> nodes
# A node is a small dict: {"t": "heading"|"para"|"bullets"|"tasks"|"table"|"rule"|"details", ...}.
# Inline content is a list of (text, mark) with mark in None, "strong", "code", "link".


def inline(s):
    out, i, buf = [], 0, ""

    def flush(b):
        pos = 0
        for m in URL.finditer(b):
            if m.start() > pos:
                out.append((b[pos:m.start()], None))
            out.append((m.group(0), "link"))
            pos = m.end()
        if pos < len(b):
            out.append((b[pos:], None))

    while i < len(s):
        if s[i] == "`":
            j = s.find("`", i + 1)
            if j > i + 1:
                if buf:
                    flush(buf)
                    buf = ""
                out.append((s[i + 1:j], "code"))
                i = j + 1
                continue
        if s.startswith("**", i):
            j = s.find("**", i + 2)
            if j > i + 2 and "`" not in s[i + 2:j]:
                if buf:
                    flush(buf)
                    buf = ""
                out.append((s[i + 2:j], "strong"))
                i = j + 2
                continue
        buf += s[i]
        i += 1
    if buf:
        flush(buf)
    return out


def inline_md(parts):
    return "".join({"code": f"`{t}`", "strong": f"**{t}**"}.get(m, t) for t, m in parts)


def is_heading(line):
    m = re.fullmatch(r"\*\*([^*`]+)\*\*", line)
    return m.group(1) if m else None


def cells(line):
    return [c.strip() for c in line.strip()[1:-1].split(" | ")]


def parse(md):
    """Owned Markdown (markers included) -> list of nodes, or None when it is not owned text."""
    lines = md.rstrip("\n").split("\n")
    if not lines or lines[0] != START or lines[-1] != END:
        return None
    body = lines[1:-1]
    k = next((i for i, l in enumerate(body) if KEY_LINE.match(l)), None)
    if k is None:
        return None
    main, tail = body[:k], body[k:]
    if main and main[-1] == "":
        main = main[:-1]
    nodes = []
    blocks, cur = [], []
    for l in main:
        if l == "":
            blocks.append(cur)
            cur = []
        else:
            cur.append(l)
    blocks.append(cur)
    for b in blocks:
        if not b:
            return None  # two blank lines in a row: not a shape the inverse can rebuild
        i = 0
        while i < len(b):
            l = b[i]
            h = is_heading(l)
            if h is not None:
                nodes.append({"t": "heading", "text": h})
                i += 1
            elif l == "---":
                nodes.append({"t": "rule"})
                i += 1
            elif TASK.match(l):
                items = []
                while i < len(b) and TASK.match(b[i]):
                    items.append(inline(b[i][6:]))
                    i += 1
                nodes.append({"t": "tasks", "items": items})
            elif l.startswith("- "):
                items = []
                while i < len(b) and b[i].startswith("- ") and not TASK.match(b[i]):
                    items.append(inline(b[i][2:]))
                    i += 1
                nodes.append({"t": "bullets", "items": items})
            elif l.startswith("|") and l.endswith("|") and i + 1 < len(b) and re.fullmatch(r"\|( --- \|)+", b[i + 1]):
                head = cells(l)
                rows = []
                i += 2
                while i < len(b) and b[i].startswith("|") and b[i].endswith("|"):
                    rows.append(cells(b[i]))
                    i += 1
                nodes.append({"t": "table", "head": [inline(c) for c in head], "rows": [[inline(c) for c in r] for r in rows]})
            else:
                para = []
                while i < len(b) and not (is_heading(b[i]) is not None or b[i] == "---" or b[i].startswith("- ")
                                          or (b[i].startswith("|") and b[i].endswith("|"))):
                    para.append(inline(b[i]))
                    i += 1
                if not para:
                    return None
                nodes.append({"t": "para", "lines": para})
    nodes.append({"t": "details", "lines": tail})
    return nodes


def render_md(nodes):
    """Nodes -> the core's Markdown, markers included. The exact inverse of parse."""
    out = [START]
    prev = None
    for n in nodes:
        if prev is not None and prev["t"] != "heading":
            out.append("")
        t = n["t"]
        if t == "heading":
            out.append(f"**{n['text']}**")
        elif t == "rule":
            out.append("---")
        elif t == "tasks":
            out.extend("- [ ] " + inline_md(i) for i in n["items"])
        elif t == "bullets":
            out.extend("- " + inline_md(i) for i in n["items"])
        elif t == "table":
            out.append("| " + " | ".join(inline_md(c) for c in n["head"]) + " |")
            out.append("|" + " --- |" * len(n["head"]))
            out.extend("| " + " | ".join(inline_md(c) for c in r) + " |" for r in n["rows"])
        elif t == "para":
            out.extend(inline_md(l) for l in n["lines"])
        elif t == "details":
            out.extend(n["lines"])
        prev = n
    out.append(END)
    return "\n".join(out)


def exact(md):
    nodes = parse(md)
    return nodes is not None and render_md(nodes) == md.rstrip("\n")


# ---------------------------------------------------------------- nodes -> ADF and HTML

def adf_inline(parts):
    out = []
    for t, m in parts:
        if not t:
            continue
        node = {"type": "text", "text": t}
        if m == "strong":
            node["marks"] = [{"type": "strong"}]
        elif m == "code":
            node["marks"] = [{"type": "code"}]
        elif m == "link":
            node["marks"] = [{"type": "link", "attrs": {"href": t}}]
        out.append(node)
    return out


def adf_para_lines(lines):
    content = []
    for i, l in enumerate(lines):
        if i:
            content.append({"type": "hardBreak"})
        content.extend(adf_inline(l))
    return {"type": "paragraph", "content": content}


def to_adf(md):
    nodes = parse(md) if exact(md) else None
    if nodes is None:
        return legacy_adf(md)
    content = []
    for n in nodes:
        t = n["t"]
        if t == "heading":
            content.append({"type": "heading", "attrs": {"level": 4}, "content": [{"type": "text", "text": n["text"]}]})
        elif t == "rule":
            content.append({"type": "rule"})
        elif t == "para":
            content.append(adf_para_lines(n["lines"]))
        elif t == "bullets":
            content.append({"type": "bulletList", "content": [{"type": "listItem", "content": [adf_para_lines([i])]} for i in n["items"]]})
        elif t == "tasks":
            content.append({"type": "taskList", "attrs": {"localId": f"gw-{len(content)}"}, "content": [
                {"type": "taskItem", "attrs": {"localId": f"gw-{len(content)}-{k}", "state": "TODO"}, "content": adf_inline(i)}
                for k, i in enumerate(n["items"])]})
        elif t == "table":
            rows = [{"type": "tableRow", "content": [{"type": "tableHeader", "content": [adf_para_lines([c])]} for c in n["head"]]}]
            rows += [{"type": "tableRow", "content": [{"type": "tableCell", "content": [adf_para_lines([c])]} for c in r]} for r in n["rows"]]
            content.append({"type": "table", "content": rows})
        elif t == "details":
            inner = [{"type": "rule"} if l == "---" else adf_para_lines([inline(l)]) for l in n["lines"]]
            content.append({"type": "expand", "attrs": {"title": DETAILS}, "content": inner})
    return {"type": "doc", "version": 1, "content": content}


def h_inline(parts):
    out = []
    for t, m in parts:
        e = _html.escape(t, quote=False)
        out.append({"strong": f"<strong>{e}</strong>", "code": f"<code>{e}</code>",
                    "link": f'<a href="{_html.escape(t)}">{e}</a>'}.get(m, e))
    return "".join(out)


def to_html(md):
    nodes = parse(md) if exact(md) else None
    if nodes is None:
        return legacy_html(md)
    out = []
    for n in nodes:
        t = n["t"]
        if t == "heading":
            out.append(f"<h4>{_html.escape(n['text'], quote=False)}</h4>")
        elif t == "rule":
            out.append("<hr>")
        elif t == "para":
            out.append("<p>" + "<br>".join(h_inline(l) for l in n["lines"]) + "</p>")
        elif t == "bullets":
            out.append("<ul>" + "".join(f"<li>{h_inline(i)}</li>" for i in n["items"]) + "</ul>")
        elif t == "tasks":
            out.append('<ul data-type="task-list">' + "".join(
                f'<li data-type="task-item"><input type="checkbox"> {h_inline(i)}</li>' for i in n["items"]) + "</ul>")
        elif t == "table":
            out.append("<table><thead><tr>" + "".join(f"<th>{h_inline(c)}</th>" for c in n["head"]) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{h_inline(c)}</td>" for c in r) + "</tr>" for r in n["rows"])
                       + "</tbody></table>")
        elif t == "details":
            inner = "".join("<hr>" if l == "---" else f"<p>{h_inline(inline(l))}</p>" for l in n["lines"])
            out.append(f"<details><summary>{DETAILS}</summary>{inner}</details>")
    return "".join(out)


# ---------------------------------------------------------------- 1.0.0 form (fallback and legacy read)

def legacy_lines(md):
    return md.rstrip("\n").split("\n")


def legacy_adf(md):
    content, task = [], []
    for l in legacy_lines(md) + [None]:
        if l is not None and l.startswith("- [ ] "):
            task.append({"type": "taskItem", "attrs": {"localId": f"gw-t{len(task)}", "state": "TODO"}, "content": adf_inline(inline(l[6:]))})
            continue
        if task:
            content.append({"type": "taskList", "attrs": {"localId": f"gw-l{len(content)}"}, "content": task})
            task = []
        if l is None:
            break
        content.append({"type": "paragraph", "content": [{"type": "text", "text": l}] if l in (START, END) else adf_inline(inline(l))})
    return {"type": "doc", "version": 1, "content": content}


def legacy_html(md):
    out, task = [], []
    for l in legacy_lines(md) + [None]:
        if l is not None and l.startswith("- [ ] "):
            task.append(f'<li data-type="task-item"><input type="checkbox"> {h_inline(inline(l[6:]))}</li>')
            continue
        if task:
            out.append('<ul data-type="task-list">' + "".join(task) + "</ul>")
            task = []
        if l is None:
            break
        out.append(f"<p>{_html.escape(l, quote=False) if l in (START, END) else h_inline(inline(l))}</p>")
    return "".join(out)


# ---------------------------------------------------------------- reading back

def adf_text(content):
    s = ""
    for c in content or []:
        if c["type"] == "text":
            marks = {m["type"] for m in c.get("marks", [])}
            s += f"`{c['text']}`" if "code" in marks else f"**{c['text']}**" if "strong" in marks else c["text"]
        elif c["type"] == "hardBreak":
            s += "\n"
        elif c["type"] == "paragraph":
            s += adf_text(c.get("content"))
    return s.replace("\u200c", "")


def from_adf(doc):
    """ADF description -> owned Markdown ('' when there is no owned section)."""
    nodes = []
    for c in doc.get("content", []):
        t = c["type"]
        if t == "paragraph":
            text = adf_text(c.get("content"))
            nodes.append(("blank", None) if text == "" else ("para", text))
        elif t == "heading":
            nodes.append(("heading", adf_text(c.get("content"))))
        elif t == "rule":
            nodes.append(("rule", None))
        elif t == "bulletList":
            nodes.append(("bullets", [adf_text(li.get("content")) for li in c.get("content", [])]))
        elif t == "taskList":
            nodes.append(("tasks", [adf_text(ti.get("content")) for ti in c.get("content", []) if ti["type"] == "taskItem"]))
        elif t == "table":
            rows = [[adf_text(cell.get("content")) for cell in r.get("content", [])] for r in c.get("content", [])]
            nodes.append(("table", rows))
        elif t == "expand":
            lines = ["---" if x["type"] == "rule" else adf_text(x.get("content")) for x in c.get("content", [])]
            nodes.append(("details", (c.get("attrs") or {}).get("title"), lines))
        else:
            nodes.append(("other", None))
    return assemble(nodes)


def assemble(nodes):
    """Shared by the ADF and HTML readers: new form first, then the 1.0.0 form."""
    paras = [n[1] for n in nodes if n[0] == "para"]
    if START in paras:  # 1.0.0 form: every line a paragraph, markers as text
        lines = []
        for n in nodes:
            if n[0] == "blank":
                lines.append("")
            elif n[0] == "para":
                lines.extend(n[1].split("\n"))
            elif n[0] == "tasks":
                lines.extend("- [ ] " + x for x in n[1])
        try:
            a, b = lines.index(START), lines.index(END)
        except ValueError:
            return ""
        return "\n".join(lines[a:b + 1])
    nodes = [n for n in nodes if n[0] != "blank"]  # spacer paragraphs carry no owned text
    d = next((i for i, n in enumerate(nodes) if n[0] == "details" and n[1] == DETAILS), None)
    if d is None:
        return ""
    out = [START]
    prev = None
    for n in nodes[:d + 1]:
        if prev is not None and prev[0] != "heading":
            out.append("")
        k = n[0]
        if k == "heading":
            out.append(f"**{n[1]}**")
        elif k == "rule":
            out.append("---")
        elif k == "para":
            out.append(n[1])
        elif k == "bullets":
            out.extend("- " + x for x in n[1])
        elif k == "tasks":
            out.extend("- [ ] " + x for x in n[1])
        elif k == "table":
            out.append("| " + " | ".join(n[1][0]) + " |")
            out.append("|" + " --- |" * len(n[1][0]))
            out.extend("| " + " | ".join(r) + " |" for r in n[1][1:])
        elif k == "details":
            out.extend(n[2])
        else:
            out.append("\x00")  # a node Groundwork never writes inside the owned section: drift
        prev = n
    out.append(END)
    return "\n".join(out)


class _H(HTMLParser):
    """Connector HTML -> the same node list as from_adf."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes, self.stack, self.buf = [], [], None
        self.list = None
        self.table = None
        self.details = None
        self.marks = []

    def _open(self):
        self.buf = ""

    def _close(self):
        s, self.buf = (self.buf or "").replace("\u200c", ""), None
        return s

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "details":
            self.details = {"title": None, "lines": []}
        elif tag == "summary":
            self._open()
        elif tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6"):
            if self.buf is None:
                self._open()
        elif tag == "ul":
            self.list = {"kind": "tasks" if a.get("data-type") == "task-list" else "bullets", "items": []}
        elif tag == "li":
            self._open()
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("td", "th"):
            self._open()
        elif tag == "hr":
            (self.details["lines"].append("---") if self.details is not None else self.nodes.append(("rule", None)))
        elif tag == "br" and self.buf is not None:
            self.buf += "\n"
        elif tag in ("strong", "b") and self.buf is not None:
            self.buf += "**"
        elif tag == "code" and self.buf is not None:
            self.buf += "`"

    def handle_endtag(self, tag):
        if tag in ("strong", "b") and self.buf is not None:
            self.buf += "**"
        elif tag == "code" and self.buf is not None:
            self.buf += "`"
        elif tag == "summary":
            self.details["title"] = self._close()
        elif tag == "details":
            self.nodes.append(("details", self.details["title"], self.details["lines"]))
            self.details = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.nodes.append(("heading", self._close()))
        elif tag == "p":
            if self.list is not None or self.table is not None:
                return  # paragraph inside a list item or cell: the item closes it
            s = self._close()
            if self.details is not None:
                self.details["lines"].append(s)
            else:
                self.nodes.append(("blank", None) if s == "" else ("para", s))
        elif tag == "li" and self.list is not None:
            self.list["items"].append(self._close().strip() if self.list["kind"] == "tasks" else self._close())
        elif tag == "ul" and self.list is not None:
            self.nodes.append((self.list["kind"], self.list["items"]))
            self.list = None
        elif tag in ("td", "th") and self.table is not None:
            self.table[-1].append(self._close())
        elif tag == "table":
            self.nodes.append(("table", self.table))
            self.table = None

    def handle_data(self, d):
        if self.buf is not None:
            self.buf += d


def from_html(h):
    p = _H()
    p.feed(h)
    p.close()
    return assemble(p.nodes)


_UNESC = re.compile(r"\\([!-/:-@\[-`{-~])")


def from_connector_markdown(md):
    """The connector's Markdown read-back of a 1.0.0-form body (paragraphs and a task list only)."""
    def unesc(l):
        return "".join(p if p.startswith("`") else _UNESC.sub(r"\1", p) for p in re.split(r"(`[^`]*`)", l))
    lines = []
    for b in md.replace("\r\n", "\n").split("\n\n"):
        b = b.replace("\u200c", "")
        if b.strip() == "":
            lines.append("")
            continue
        rows = b.split("\n")
        if all(TASK.match(x) for x in rows):
            lines += ["- [ ] " + unesc(x[6:]) for x in rows]
        else:
            lines += [unesc(x.rstrip()) for x in rows]
    try:
        a, z = lines.index(START), lines.index(END)
    except ValueError:
        return ""
    return "\n".join(lines[a:z + 1])


def read(text):
    s = text.lstrip()
    if s.startswith("{"):
        return from_adf(json.loads(s))
    if s.startswith("<") and not s.startswith(START):
        return from_html(text)
    return from_connector_markdown(text)


def main(argv):
    if len(argv) != 3 or argv[1] not in ("adf", "html", "read", "check"):
        print(__doc__)
        return 2
    text = open(argv[2], encoding="utf-8").read()
    if argv[1] == "adf":
        print(json.dumps(to_adf(text), ensure_ascii=False))
    elif argv[1] == "html":
        print(to_html(text))
    elif argv[1] == "read":
        print(read(text))
    else:
        ok = exact(text)
        print("exact" if ok else "falls back to the 1.0.0 form")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
