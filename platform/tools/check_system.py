# -*- coding: utf-8 -*-
"""Whole-platform system gate.

Runs the format/template/contract checks and validates system-level invariants:
module-local API ownership, migrated routes no longer living in kernel/server.py,
declared data boundaries, and the architecture document.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
ALLOWED_DATA_KINDS = {"tree", "client", "static", "legacy-store", "project", "service", "proxy"}
MIGRATED_ROUTES = (
    "/api/ai/", "/api/llm/", "/api/files",
    "/api/schedule/courses", "/api/schedule/venues",
    "/api/schedule/events", "/api/schedule/participants",
    "/api/schedule/admin/", "/mock/api/",
)


def run(name, script):
    print("== %s ==" % name)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, os.path.join(HERE, script)], cwd=PLATFORM,
                       text=True, encoding="utf-8", errors="replace", capture_output=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    print("\n".join(out.strip().splitlines()[-8:]))
    return p.returncode == 0, out


def main() -> int:
    ok = True
    for name, script in (("module format", "check_modules.py"),
                         ("page templates", "check_templates.py"),
                         ("module contracts", "check_contracts.py")):
        good, _ = run(name, script)
        ok = ok and good

    print("== system invariants ==")
    # API ownership / route extraction
    sys.path.insert(0, PLATFORM)
    from kernel.registry import Registry
    reg = Registry(PLATFORM)
    if reg.errors:
        print("registry errors:", reg.errors)
        ok = False
    seen = []
    for item in reg.api_catalog():
        for prefix in item["prefixes"]:
            if not (prefix.startswith("/api/") or prefix.startswith("/mock/api/")):
                print("bad API prefix:", item, prefix); ok = False
            if any(prefix.startswith(old) or old.startswith(prefix) for old in seen):
                print("overlapping API prefix:", item, seen); ok = False
            seen.append(prefix)
    print("module APIs:", json.dumps(reg.api_catalog(), ensure_ascii=False))

    server_py = os.path.join(PLATFORM, "kernel", "server.py")
    src = open(server_py, encoding="utf-8").read()
    route_ok = True
    for route in MIGRATED_ROUTES:
        needle = 'if path == "%s' % route
        if needle in src:
            print("migrated route still hardcoded:", route); route_ok = False
    if not route_ok:
        ok = False
    print("migrated route scan: " + ("OK" if route_ok else "FAIL"))

    # data boundaries
    for pid in reg.order:
        spec = reg.get(pid).manifest()
        data = spec.get("data")
        if data is None:
            print("WARN data boundary undeclared:", pid)
            continue
        if not isinstance(data, dict) or data.get("kind") not in ALLOWED_DATA_KINDS:
            print("bad data boundary:", pid, data); ok = False

    if not os.path.isfile(os.path.join(PLATFORM, "SYSTEM.md")):
        print("missing SYSTEM.md")
        ok = False

    print("== RESULT ==", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
