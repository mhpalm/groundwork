# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Jira tracker body format: the core's owned Markdown to real Jira formatting and back."""
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "harness"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "groundwork-tracker-jira", "scripts"))
from common import GOLDEN, fresh  # noqa: E402
import jira_body as jb  # noqa: E402
import render_proposal as rp  # noqa: E402
from check_hashes import owned_hash  # noqa: E402


def golden_bodies():
    names = sorted(os.path.basename(os.path.dirname(os.path.dirname(p)))
                   for p in glob.glob(os.path.join(GOLDEN, "*", "expected", "plan.json")))
    for g in names:
        plan, overlay, _e = fresh(g)
        for t in plan["tasks"]:
            yield g, t["id"], rp.task_body(plan, overlay, t)
        yield g, "epic", rp.epic_description(plan, overlay)
        yield g, "epic-frozen", rp.epic_description(plan, overlay, released=[p["id"] for p in plan["phases"]])


def connector_markdown(body):
    """What the Atlassian connector hands back for a new-form body, as observed on a live site:
    headings as '#### ', bullets as '* ', hard breaks as two trailing spaces, '~ [ ]' escaped outside
    code, links as [u](u), and the details expand flattened to one paragraph per line, title dropped."""
    def md(parts):
        out = []
        for t, m in parts:
            if m == "code":
                out.append(f"`{t}`")
            elif m == "link":
                out.append(f"[{t}]({t})")
            else:
                e = t.replace("~", "\\~").replace("[", "\\[").replace("]", "\\]")
                out.append(f"**{e}**" if m == "strong" else e)
        return "".join(out)
    blocks = []
    for n in jb.parse(body):
        t = n["t"]
        if t == "heading":
            blocks.append("#### " + n["text"])
        elif t == "rule":
            blocks.append("---")
        elif t == "para":
            blocks.append("  \n".join(md(l) for l in n["lines"]))
        elif t == "bullets":
            blocks.append("\n".join("* " + md(i) for i in n["items"]))
        elif t == "tasks":
            blocks.append("\n".join("- [ ] " + md(i) for i in n["items"]))
        elif t == "table":
            rows = [n["head"]] + n["rows"]
            lines = ["| " + " | ".join(md(c) for c in r) + " |" for r in rows]
            blocks.append("\n".join(lines[:1] + ["|" + " --- |" * len(n["head"])] + lines[1:]))
        elif t == "details":
            blocks.extend("---" if l == "---" else md(jb.inline(l)) for l in n["lines"])
    return "\n\n".join(blocks) + "\n"


def kinds(doc):
    return [c["type"] for c in doc["content"]]


class RoundTrip(unittest.TestCase):
    def test_every_golden_body_round_trips_exactly(self):
        n = 0
        for g, tid, body in golden_bodies():
            n += 1
            with self.subTest(golden=g, item=tid):
                self.assertTrue(jb.exact(body))
                self.assertEqual(jb.from_adf(jb.to_adf(body)), body)
                self.assertEqual(jb.from_html(jb.to_html(body)), body)
                self.assertEqual(jb.read(json.dumps(jb.to_adf(body))), body)
                self.assertEqual(jb.read(jb.to_html(body)), body)
        self.assertGreater(n, 50)

    def test_connector_markdown_read_back(self):
        n = 0
        for g, tid, body in golden_bodies():
            if not jb.exact(body):
                continue
            n += 1
            with self.subTest(golden=g, item=tid):
                self.assertEqual(jb.read(connector_markdown(body)), body)
        self.assertGreater(n, 50)

    def test_owned_hash_survives(self):
        _g, _t, body = next(golden_bodies())
        f = {"title": "t", "role_key": "developer", "phase": "P0", "key": "k"}
        self.assertEqual(owned_hash(dict(f, body_owned=body)), owned_hash(dict(f, body_owned=jb.from_adf(jb.to_adf(body)))))


class LooksLikeJira(unittest.TestCase):
    def setUp(self):
        plan, overlay, _e = fresh("G1")
        self.task = rp.task_body(plan, overlay, plan["tasks"][0])
        self.epic = rp.epic_description(plan, overlay)

    def test_task_uses_headings_lists_and_a_checklist(self):
        k = kinds(jb.to_adf(self.task))
        self.assertIn("heading", k)
        self.assertIn("bulletList", k)
        self.assertIn("taskList", k)
        self.assertEqual(k[-1], "expand")

    def test_epic_phase_table_is_a_table(self):
        doc = jb.to_adf(self.epic)
        self.assertIn("table", kinds(doc))
        self.assertNotIn("|", json.dumps([c for c in doc["content"] if c["type"] == "paragraph"]))

    def test_no_markers_no_blank_paragraphs_and_key_hidden(self):
        for body in (self.task, self.epic):
            doc = jb.to_adf(body)
            top = json.dumps([c for c in doc["content"] if c["type"] != "expand"])
            self.assertNotIn("groundwork:owned", top)
            self.assertNotIn("`gw:", top)
            self.assertNotIn('"gw:', top)
            for c in doc["content"]:
                if c["type"] == "paragraph":
                    self.assertTrue(c.get("content"))
            self.assertEqual(doc["content"][-1]["attrs"]["title"], jb.DETAILS)
            h = jb.to_html(body)
            self.assertNotIn("<p></p>", h)
            self.assertNotIn("&lt;!--", h)


    def test_field_and_link_lines_only_in_the_details(self):
        # Type, points, estimate and dependencies live in Jira fields and Blocks links, so the lines
        # repeating them move into the collapsed details instead of the visible description.
        plan, overlay, _e = fresh("G1")
        dep = next(t for t in plan["tasks"] if "**Depends on:**" in rp.task_body(plan, overlay, t))
        doc = jb.to_adf(rp.task_body(plan, overlay, dep))
        top = json.dumps([c for c in doc["content"] if c["type"] != "expand"])
        details = json.dumps(doc["content"][-1])
        for label in ("Type:", "Depends on:"):
            self.assertNotIn(label, top)
            self.assertIn(label, details)


class Drift(unittest.TestCase):
    def setUp(self):
        plan, overlay, _e = fresh("G1")
        self.body = rp.task_body(plan, overlay, plan["tasks"][0])
        self.doc = jb.to_adf(self.body)

    def test_ticking_a_step_is_not_drift(self):
        doc = json.loads(json.dumps(self.doc))
        tl = next(c for c in doc["content"] if c["type"] == "taskList")
        tl["content"][0]["attrs"]["state"] = "DONE"
        self.assertEqual(jb.from_adf(doc), self.body)

    def test_text_added_below_the_details_is_not_drift(self):
        doc = json.loads(json.dumps(self.doc))
        doc["content"].append({"type": "paragraph", "content": [{"type": "text", "text": "A note from a person"}]})
        self.assertEqual(jb.from_adf(doc), self.body)

    def test_editing_a_step_is_drift(self):
        doc = json.loads(json.dumps(self.doc))
        tl = next(c for c in doc["content"] if c["type"] == "taskList")
        tl["content"][0]["content"][0]["text"] += " (edited)"
        self.assertNotEqual(jb.from_adf(doc), self.body)

    def test_a_foreign_node_inside_the_owned_section_is_drift(self):
        doc = json.loads(json.dumps(self.doc))
        doc["content"].insert(1, {"type": "panel", "attrs": {"panelType": "info"}, "content": []})
        self.assertNotEqual(jb.from_adf(doc), self.body)

    def test_removing_the_details_expand_gives_no_owned_section(self):
        doc = json.loads(json.dumps(self.doc))
        doc["content"] = doc["content"][:-1]
        self.assertEqual(jb.from_adf(doc), "")


class Legacy(unittest.TestCase):
    """Bodies written by skill 1.0.0 (one paragraph per line, markers as text) still normalize."""

    def setUp(self):
        plan, overlay, _e = fresh("G1")
        self.body = rp.task_body(plan, overlay, plan["tasks"][0])

    def test_legacy_adf_and_html_read_back(self):
        self.assertEqual(jb.from_adf(jb.legacy_adf(self.body)), self.body)
        self.assertEqual(jb.from_html(jb.legacy_html(self.body)), self.body)

    def test_spacer_paragraphs_in_a_new_form_body_are_ignored(self):
        h = jb.to_html(self.body).replace("</ul>", "</ul><p>\u200c</p>")
        self.assertEqual(jb.from_html(h), self.body)

    def test_connector_markdown_read_back(self):
        # The connector's Markdown export of a 1.0.0 body: paragraphs split by blank lines,
        # spacer paragraphs as U+200C, '-', '~' and '[' escaped outside code spans.
        out = []
        for l in self.body.split("\n"):
            if l.startswith("- [ ] "):
                out.append(l)
                continue
            esc = l if l.startswith("`") else l.replace("-", "\\-").replace("~", "\\~").replace("[", "\\[")
            if l.startswith("<!--"):
                esc = l
            out.append("‌" if l == "" else esc)
        md = "\n\n".join(out)
        md = md.replace("\n\n- [ ] ", "\n- [ ] ")
        self.assertEqual(jb.from_connector_markdown(md), self.body)

    def test_fallback_when_round_trip_is_not_exact(self):
        odd = jb.START + "\nline one\n\n\n`gw:x:y`\n" + jb.END
        self.assertFalse(jb.exact(odd))
        doc = jb.to_adf(odd)
        self.assertEqual(doc["content"][0]["content"][0]["text"], jb.START)
        self.assertEqual(jb.from_adf(doc), odd)


if __name__ == "__main__":
    unittest.main()
