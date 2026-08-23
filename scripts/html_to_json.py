#!/usr/bin/env python3
"""
Converts index.html into a nested JSON tree (resume.json), preserving
element order and nesting. Uses stdlib html.parser only, no dependencies.

Scope: everything inside <div id="layout-content">. HTML comments are
never captured by html.parser's default tree-building path here, so any
comment-based directives in the source (e.g. crawler hints) are excluded
from the output automatically.

Usage:
    python3 html_to_json.py [input.html] [output.json]
"""

import json
import sys
from html.parser import HTMLParser

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

ROOT_ID = "layout-content"


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "attrs": {}, "children": []}
        self.stack = [self.root]
        self.capturing = False
        self.depth = 0

    def _current(self):
        return self.stack[-1]

    def _node_id(self, attrs_dict):
        return attrs_dict.get("id")

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        node = {"tag": tag, "attrs": attrs_dict, "children": []}

        if self.capturing:
            self._current()["children"].append(node)
            if tag not in VOID_TAGS:
                self.stack.append(node)
                self.depth += 1
        elif self._node_id(attrs_dict) == ROOT_ID:
            self.capturing = True
            self.root = node
            self.stack = [node]
            self.depth = 0

    def handle_startendtag(self, tag, attrs):
        attrs_dict = dict(attrs)
        node = {"tag": tag, "attrs": attrs_dict, "children": []}
        if self.capturing:
            self._current()["children"].append(node)

    def handle_endtag(self, tag):
        """
        Close the nearest matching open tag on the stack (implicit-close
        recovery, like a real HTML parser does for tag soup). A stray
        closing tag with no matching opener on the stack is ignored
        rather than corrupting or truncating capture -- source HTML here
        is hand-edited and not guaranteed to be well-formed.
        """
        if not self.capturing or tag in VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                closed_root = i == 0
                del self.stack[i:]  # drop tag itself and any unclosed descendants
                self.depth = len(self.stack) - 1
                if closed_root:
                    self.capturing = False
                return
        # no matching opener found on the stack -> ignore stray end tag

    def handle_data(self, data):
        if not self.capturing:
            return
        text = data.strip()
        if text:
            self._current()["children"].append({"tag": "#text", "text": text})

    # Comments are intentionally not handled -> excluded from tree.


def strip_empty_children(node):
    if not isinstance(node, dict) or "children" not in node:
        return node
    node["children"] = [strip_empty_children(c) for c in node["children"]]
    return node


def convert(html_path, json_path):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    parser = TreeBuilder()
    parser.feed(html)

    tree = strip_empty_children(parser.root)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)

    print(f"Wrote {json_path}")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    dst = sys.argv[2] if len(sys.argv) > 2 else "resume.json"
    convert(src, dst)
