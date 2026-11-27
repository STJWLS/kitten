# -*- coding: utf-8 -*-
"""Read-only module protocol contract checks.

This complements check_modules.py (static manifest checks) by instantiating each
project from the registry and exercising a temp-dir copy of the base protocol.
It never writes into platform/data.
"""
from __future__ import annotations
import copy
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
sys.path.insert(0, PLATFORM)

from kernel.registry import Registry  # noqa: E402


def main() -> int:
    errors = []
    reg = Registry(PLATFORM)
    if reg.errors:
        errors.extend("registry: " + e for e in reg.errors)
    print("modules:", len(reg.projects))
    for pid in reg.order:
        p = reg.get(pid)
        try:
            rev, data = p.state("puppy")
            if not isinstance(rev, int) or not isinstance(data, dict):
                errors.append("%s: state() returned %r/%r" % (pid, type(rev), type(data)))
            names = set(p.action_names())
            if "get" not in names:
                errors.append("%s: action_names missing get" % pid)
            # Exercise base append/remove in a temp data dir. This does not touch
            # real data and is skipped for projects with a non-default protocol.
            with tempfile.TemporaryDirectory(prefix="kp-contract-") as td:
                cls = type(p)
                inst = cls(p.manifest(), {"role": "puppy", "data_dir": td, "engine": None})
                nrev, ndata = inst.dispatch("append", {"_kp_user": "puppy", "_kp_users": ["kitten", "puppy"], "item": {"id": "__contract__", "title": "contract"}}, role="puppy")
                items = ndata.get("items") if isinstance(ndata, dict) else None
                if not isinstance(items, list) or not any(str(x.get("id")) == "__contract__" for x in items if isinstance(x, dict)):
                    errors.append("%s: append did not persist item" % pid)
                rrev, rdata = inst.dispatch("remove", {"_kp_user": "puppy", "_kp_users": ["kitten", "puppy"], "id": "__contract__"}, role="puppy")
                items = rdata.get("items") if isinstance(rdata, dict) else None
                if any(str(x.get("id")) == "__contract__" for x in (items or []) if isinstance(x, dict)):
                    errors.append("%s: remove did not delete item" % pid)
            print("  PASS %-16s rev=%-4s actions=%s" % (pid, rev, ",".join(sorted(names))))
        except Exception as e:
            errors.append("%s: %s: %s" % (pid, type(e).__name__, e))
            print("  FAIL %-16s %s" % (pid, e))
    if errors:
        print("\nCONTRACT ERRORS (%d)" % len(errors))
        for e in errors:
            print("  -", e)
        return 1
    print("\nOK: %d module contracts" % len(reg.projects))
    return 0


if __name__ == "__main__":
    sys.exit(main())
