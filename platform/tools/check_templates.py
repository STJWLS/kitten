# -*- coding: utf-8 -*-
"""Validate the explicit module page-template tree and manifest bindings."""
from __future__ import annotations
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
TREE = os.path.join(PLATFORM, "static", "template-tree.json")
PROJECTS = os.path.join(PLATFORM, "projects")


def flatten(node, parent="", parent_props=None, out=None, errors=None):
    out = out if out is not None else {}
    errors = errors if errors is not None else []
    if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node.get("id").startswith("#"):
        errors.append("node missing #id under %s" % (parent or "root"))
        return out
    raw = node["id"].lstrip("#")
    full = ("%s.%s" % (parent, raw)) if parent else "#" + raw
    if full in out:
        errors.append("duplicate template path: %s" % full)
        return out
    props = {}
    if parent_props:
        props.update(parent_props)
    for k, v in (node.get("properties") or {}).items():
        if isinstance(v, list) and isinstance(props.get(k), list):
            props[k] = props[k] + [x for x in v if x not in props[k]]
        elif isinstance(v, dict) and isinstance(props.get(k), dict):
            merged = dict(props[k]); merged.update(v); props[k] = merged
        else:
            props[k] = v
    out[full] = {"id": full, "shortId": node["id"], "properties": props}
    for child in node.get("children") or []:
        flatten(child, full, props, out, errors)
    return out


def main() -> int:
    if not os.path.isfile(TREE):
        print("missing template tree: %s" % TREE, file=sys.stderr); return 2
    try:
        doc = json.load(open(TREE, encoding="utf-8"))
    except Exception as e:
        print("bad template tree JSON: %s" % e, file=sys.stderr); return 2
    nodes, errors = {}, []
    flatten(doc.get("root"), "", {}, nodes, errors)
    if "#module" not in nodes:
        errors.append("root must resolve to #module")
    if "#module.game" not in nodes:
        errors.append("missing #module.game")
    for path, node in nodes.items():
        if path != "#module" and "." not in path:
            errors.append("orphan/top-level template: %s" % path)
    # manifest bindings
    bindings = {}
    for name in sorted(os.listdir(PROJECTS)):
        p = os.path.join(PROJECTS, name, "project.json")
        if not os.path.isfile(p):
            continue
        try:
            m = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            errors.append("%s: bad project.json: %s" % (name, e)); continue
        tpl = ((m.get("ui") or {}).get("template")) or "#module"
        bindings[name] = tpl
        if tpl not in nodes:
            errors.append("%s: ui.template %r not in template tree" % (name, tpl))
    print("template tree: %s" % TREE)
    print("nodes: %s" % ", ".join(sorted(nodes)))
    for name, tpl in sorted(bindings.items()):
        print("  %-16s -> %s" % (name, tpl))
    if errors:
        print("ERROR")
        for e in errors:
            print("  -", e)
        return 1
    print("OK: %d templates, %d module bindings" % (len(nodes), len(bindings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
