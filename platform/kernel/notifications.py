# -*- coding: utf-8 -*-
"""Per-user in-site notifications (station mail).

The store is intentionally small and file based, like the rest of the platform.
A notification always belongs to one recipient and records the actor, module,
kind, title, body and optional link/meta.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone

_LOCK = threading.RLock()
_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "notifications.json")
_MAX_TOTAL = 3000
_MAX_PER_USER = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"items": []}
        items = data.get("items")
        if not isinstance(items, list):
            items = []
        return {"items": items}
    except Exception:
        return {"items": []}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _PATH)


def notify(user, module, kind, title, body="", link="", actor="", meta=None) -> dict | None:
    """Append one notification for *user*. Returns the stored item."""
    user = str(user or "").strip()
    if not user:
        return None
    item = {
        "id": "n" + str(int(time.time() * 1000)) + secrets.token_hex(3),
        "user": user,
        "actor": str(actor or "").strip(),
        "module": str(module or "system").strip() or "system",
        "kind": str(kind or "notice").strip() or "notice",
        "title": str(title or "").strip()[:160],
        "body": str(body or "").strip()[:500],
        "link": str(link or "").strip()[:300],
        "meta": meta if isinstance(meta, dict) else {},
        "created": _now_iso(),
        "read": False,
    }
    with _LOCK:
        data = _load()
        items = data["items"]
        items.insert(0, item)
        # Keep the file bounded; drop oldest items globally and per recipient.
        if len(items) > _MAX_TOTAL:
            items = items[:_MAX_TOTAL]
        seen = {}
        kept = []
        for it in items:
            u = str(it.get("user") or "")
            seen[u] = seen.get(u, 0) + 1
            if seen[u] <= _MAX_PER_USER:
                kept.append(it)
        data["items"] = kept
        _save(data)
    return item


def list_for(user, limit=200) -> list[dict]:
    user = str(user or "")
    limit = max(1, min(500, int(limit or 200)))
    with _LOCK:
        items = [it for it in _load()["items"] if str(it.get("user") or "") == user]
    items.sort(key=lambda x: str(x.get("created") or ""), reverse=True)
    return items[:limit]


def summary(user) -> dict:
    items = list_for(user, 500)
    modules = {}
    for it in items:
        mod = str(it.get("module") or "system")
        rec = modules.setdefault(mod, {"module": mod, "total": 0, "unread": 0})
        rec["total"] += 1
        if not it.get("read"):
            rec["unread"] += 1
    return {
        "items": items,
        "unread": sum(1 for it in items if not it.get("read")),
        "modules": sorted(modules.values(), key=lambda x: x["module"]),
    }


def mark_read(user, ids=None, module=None, mark_all=False) -> dict:
    user = str(user or "")
    ids = {str(x) for x in (ids or []) if str(x)} if isinstance(ids, (list, tuple, set)) else set()
    module = str(module or "").strip()
    changed = 0
    with _LOCK:
        data = _load()
        for it in data["items"]:
            if str(it.get("user") or "") != user or it.get("read"):
                continue
            if not mark_all:
                if ids and str(it.get("id") or "") not in ids:
                    continue
                if module and str(it.get("module") or "") != module:
                    continue
                if not ids and not module:
                    continue
            it["read"] = True
            changed += 1
        if changed:
            _save(data)
    return {"changed": changed, "unread": summary(user)["unread"]}
