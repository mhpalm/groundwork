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
# Lines that repeat what Jira already shows as fields (type, points, estimate, fix version, labels)
# or as Blocks links. They move into the collapsed details so they are not shown twice.
FIELD_LINE = re.compile(r"^\*\*(Type|Depends on):\*\* ")
# Body layout 2 (plan format 2.1): the lines that repeat fields, links and plan bookkeeping form
# the last block before the key, and every task body has a "Done when" heading.
DETAIL_LINE = re.compile(r"^\*\*(Type|Depends on|Access needed|Done today|Visible result|From the org's own files):\*\* ")
LAYOUT2 = "Done when"
CAUTION = "**Caution.** "
FENCE = "  ```"
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
    hidden = []
    if f"**{LAYOUT2}**" in main and len(blocks) > 1 and blocks[-1] and all(DETAIL_LINE.match(l) for l in blocks[-1]):
        hidden = blocks.pop()
    elif len(blocks) > 1 and blocks[1] and FIELD_LINE.match(blocks[1][0]):
        while blocks[1] and FIELD_LINE.match(blocks[1][0]):
            hidden.append(blocks[1].pop(0))
        if not blocks[1]:
            blocks.pop(1)
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
                items, code = [], []
                while i < len(b) and TASK.match(b[i]):
                    items.append(inline(b[i][6:]))
                    i += 1
                    c = None
                    if i < len(b) and b[i].startswith(FENCE):
                        lang, body = b[i][len(FENCE):], []
                        i += 1
                        while i < len(b) and b[i] != FENCE:
                            if not b[i].startswith("  "):
                                return None
                            body.append(b[i][2:])
                            i += 1
                        if i == len(b) or not body:
                            return None
                        i += 1
                        c = (lang, "\n".join(body))
                    code.append(c)
                nodes.append({"t": "tasks", "items": items, "code": code})
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
    nodes.append({"t": "details", "lines": hidden + tail})
    return nodes


def render_md(nodes):
    """Nodes -> the core's Markdown, markers included. The exact inverse of parse."""
    nodes = list(nodes)
    det = nodes[-1] if nodes and nodes[-1]["t"] == "details" else None
    if det is not None:
        k = next((i for i, l in enumerate(det["lines"]) if KEY_LINE.match(l)), len(det["lines"]))
        hidden = det["lines"][:k]
        if hidden:
            nodes[-1] = dict(det, lines=det["lines"][k:])
            lead = [inline(l) for l in hidden]
            if any(n["t"] == "heading" and n["text"] == LAYOUT2 for n in nodes):
                nodes.insert(len(nodes) - 1, {"t": "para", "lines": lead})
            elif len(nodes) > 1 and nodes[1]["t"] == "para":
                nodes[1] = dict(nodes[1], lines=lead + nodes[1]["lines"])
            else:
                nodes.insert(1, {"t": "para", "lines": lead})
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
            for i, c in zip(n["items"], n.get("code") or [None] * len(n["items"])):
                out.append("- [ ] " + inline_md(i))
                if c:
                    out.append(FENCE + c[0])
                    out.extend("  " + x for x in c[1].split("\n"))
                    out.append(FENCE)
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


def code_runs(n):
    """A step list with code: runs of steps, each run ending at a step whose code block follows it.
    A task list holds no code block, so the list is split after each step that has one."""
    run = []
    for i, c in zip(n["items"], n["code"]):
        run.append(i)
        if c:
            yield run, c
            run = []
    if run:
        yield run, None


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
        elif t == "para" and len(n["lines"]) == 1 and inline_md(n["lines"][0]).startswith(CAUTION):
            content.append({"type": "panel", "attrs": {"panelType": "warning"}, "content": [adf_para_lines(n["lines"])]})
        elif t == "para":
            content.append(adf_para_lines(n["lines"]))
        elif t == "tasks" and any(n.get("code") or []):
            for run, c in code_runs(n):
                content.append({"type": "taskList", "attrs": {"localId": f"gw-{len(content)}"}, "content": [
                    {"type": "taskItem", "attrs": {"localId": f"gw-{len(content)}-{k}", "state": "TODO"}, "content": adf_inline(i)}
                    for k, i in enumerate(run)]})
                if c:
                    content.append({"type": "codeBlock", "attrs": {"language": c[0]} if c[0] else {}, "content": [{"type": "text", "text": c[1]}]})
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
        elif t == "para" and len(n["lines"]) == 1 and inline_md(n["lines"][0]).startswith(CAUTION):
            out.append('<div data-type="panel-warning"><p>' + h_inline(n["lines"][0]) + "</p></div>")
        elif t == "para":
            out.append("<p>" + "<br>".join(h_inline(l) for l in n["lines"]) + "</p>")
        elif t == "tasks" and any(n.get("code") or []):
            for run, c in code_runs(n):
                out.append('<ul data-type="task-list">' + "".join(
                    f'<li data-type="task-item"><input type="checkbox"> {h_inline(i)}</li>' for i in run) + "</ul>")
                if c:
                    cls = f' class="language-{_html.escape(c[0])}"' if c[0] else ""
                    out.append(f"<pre><code{cls}>{_html.escape(c[1], quote=False)}</code></pre>")
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
        elif t == "codeBlock":
            nodes.append(("code", (c.get("attrs") or {}).get("language") or "", "".join(x.get("text", "") for x in c.get("content") or [])))
        elif t == "panel" and (c.get("attrs") or {}).get("panelType") == "warning" and len(c.get("content") or []) == 1 \
                and c["content"][0]["type"] == "paragraph" and adf_text(c["content"][0].get("content")).startswith(CAUTION):
            nodes.append(("para", adf_text(c["content"][0].get("content"))))
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
    def plain(x):
        return [(x, None)]
    pn = []
    for n in nodes[:d + 1]:
        k = n[0]
        last = pn[-1] if pn else None
        if k == "code":
            if last and last["t"] == "tasks" and last["code"][-1] is None:
                last["code"][-1] = (n[1], n[2])
            else:
                pn.append({"t": "para", "lines": [plain("\x00")]})  # code outside the steps: drift
            continue
        if k == "tasks" and last and last["t"] == "tasks" and last["code"][-1] is not None:
            last["items"].extend(plain(x) for x in n[1])
            last["code"].extend([None] * len(n[1]))
            continue
        if k == "heading":
            pn.append({"t": "heading", "text": n[1]})
        elif k == "rule":
            pn.append({"t": "rule"})
        elif k == "para":
            pn.append({"t": "para", "lines": [plain(x) for x in n[1].split("\n")]})
        elif k == "tasks":
            pn.append({"t": k, "items": [plain(x) for x in n[1]], "code": [None] * len(n[1])})
        elif k == "bullets":
            pn.append({"t": k, "items": [plain(x) for x in n[1]]})
        elif k == "table":
            pn.append({"t": "table", "head": [plain(c) for c in n[1][0]], "rows": [[plain(c) for c in r] for r in n[1][1:]]})
        elif k == "details":
            pn.append({"t": "details", "lines": n[2]})
        else:
            pn.append({"t": "para", "lines": [plain("\x00")]})  # a node Groundwork never writes in the owned section: drift
    return render_md(pn)


class _H(HTMLParser):
    """Connector HTML -> the same node list as from_adf."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes, self.stack, self.buf = [], [], None
        self.list = None
        self.table = None
        self.details = None
        self.marks = []
        self.pre = None
        self.panel = None

    def _open(self):
        self.buf = ""

    def _close(self):
        s, self.buf = (self.buf or "").replace("\u200c", ""), None
        return s

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.pre is not None:
            if tag == "code":
                self.pre["lang"] = (a.get("class") or "").removeprefix("language-")
            return
        if tag == "pre":
            self.pre = {"lang": "", "text": ""}
        elif tag == "div" and a.get("data-type") == "panel-warning":
            self.panel = True
        elif tag == "details":
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
        if self.pre is not None:
            if tag == "pre":
                self.nodes.append(("code", self.pre["lang"], self.pre["text"]))
                self.pre = None
            return
        if tag == "div" and self.panel:
            self.panel = None
            return
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
        if self.pre is not None:
            self.pre["text"] += d
            return
        if self.buf is not None:
            self.buf += d


def from_html(h):
    p = _H()
    p.feed(h)
    p.close()
    return assemble(p.nodes)


_UNESC = re.compile(r"\\([!-/:-@\[-`{-~])")


def _unesc(l):
    l = re.sub(r"\[([^\]]+)\]\(\1\)", r"\1", l)  # a link whose text is its address
    return "".join(p if p.startswith("`") else _UNESC.sub(r"\1", p) for p in re.split(r"(`[^`]*`)", l))


def from_connector_markdown(md):
    """The connector's Markdown read-back. A 1.0.0-form body is paragraphs and a task list with the
    markers as text. A new-form body comes back with headings as '#### ', bullets as '* ', hard
    breaks as two trailing spaces, and the Groundwork details expand flattened: its title is dropped
    and its lines come back as paragraphs (verify)."""
    md = md.replace("\r\n", "\n").replace("\u200c", "")
    if START not in md:
        return _connector_new(md)
    lines = []
    for b in md.split("\n\n"):
        if b.strip() == "":
            lines.append("")
            continue
        rows = b.split("\n")
        if all(TASK.match(x) for x in rows):
            lines += ["- [ ] " + _unesc(x[6:]) for x in rows]
        else:
            lines += [_unesc(x.rstrip()) for x in rows]
    try:
        a, z = lines.index(START), lines.index(END)
    except ValueError:
        return ""
    return "\n".join(lines[a:z + 1])


def _connector_new(md):
    blocks, cur, fence = [], [], None
    for l in md.strip("\n").split("\n"):
        if fence is not None:
            if l.rstrip() == "```":
                blocks.append(fence)
                fence = None
            else:
                fence[2].append(l)
        elif l.startswith("```"):
            if cur:
                blocks.append(cur)
                cur = []
            fence = ("code", l[3:].strip(), [])
        elif l.strip() == "":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(l)
    if cur:
        blocks.append(cur)
    nodes = []
    for b in blocks:
        if isinstance(b, tuple):
            nodes.append(("code", b[1], "\n".join(b[2])))
            continue
        rows = b
        if len(rows) == 1 and rows[0].startswith("#### "):
            nodes.append(("heading", _unesc(rows[0][5:].strip())))
        elif len(rows) == 1 and rows[0].strip() in ("---", "\\---", "***"):
            nodes.append(("rule", None))
        elif all(TASK.match(x) for x in rows):
            nodes.append(("tasks", [_unesc(x[6:].rstrip()) for x in rows]))
        elif all(x.startswith(("* ", "- ")) for x in rows):
            nodes.append(("bullets", [_unesc(x[2:].rstrip()) for x in rows]))
        elif len(rows) > 1 and all(x.startswith("|") for x in rows) and re.fullmatch(r"\|( *:?-+:? *\|)+", rows[1].strip()):
            nodes.append(("table", [[_unesc(c.strip()) for c in r.strip()[1:-1].split("|")] for r in [rows[0]] + rows[2:]]))
        else:
            nodes.append(("para", "\n".join(_unesc(x.rstrip()) for x in rows)))
    k = next((i for i, n in enumerate(nodes) if n[0] == "para" and KEY_LINE.match(n[1])), None)
    if k is None:
        return ""
    start = k
    while start > 0 and nodes[start - 1][0] == "para" and "\n" not in nodes[start - 1][1] and DETAIL_LINE.match(nodes[start - 1][1]):
        start -= 1
    end = k + 1
    while end < len(nodes) and (nodes[end][0] == "rule" or (nodes[end][0] == "para" and nodes[end][1].startswith("Groundwork "))):
        end += 1
    lines = ["---" if n[0] == "rule" else n[1] for n in nodes[start:end]]
    return assemble(nodes[:start] + [("details", DETAILS, lines)])


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
