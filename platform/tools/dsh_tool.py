# -*- coding: utf-8 -*-
"""DSH -> platform module tool bridge client.

Usage:
  python platform/tools/dsh_tool.py --tool schedule_create --args-json '{"title":"..."}'
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True)
    ap.add_argument("--args-json", default="{}")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    base = os.environ.get("KP_BRIDGE_URL") or "http://127.0.0.1:8772"
    token = os.environ.get("KP_BRIDGE_TOKEN") or ""
    if not token:
        ticket_file = os.environ.get("KP_BRIDGE_TICKET") or ""
        if ticket_file:
            try:
                token = open(ticket_file, encoding="utf-8").read().strip()
            except Exception:
                token = ""
    module = os.environ.get("KP_BRIDGE_MODULE") or ""
    try:
        payload = json.loads(args.args_json or "{}")
    except Exception as e:
        print(json.dumps({"ok": False, "error": "args-json 不是合法 JSON: %s" % e}, ensure_ascii=False))
        return 2
    body = json.dumps({"module": module, "tool": args.tool, "args": payload, "dry_run": args.dry_run}).encode("utf-8")
    req = urllib.request.Request(base + "/api/dsh/tool", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-KP-Bridge": token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(r.read().decode("utf-8", "replace"))
            return 0
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace"))
        return 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
