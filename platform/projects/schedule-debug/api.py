# -*- coding: utf-8 -*-
"""日程调试 module-local API（superadmin 专用）。"""
from kernel.protocol import ProjectError, ok
import time

PREFIXES = ["/api/schedule/admin/"]


def handle(handler, method, path, parsed):
    if method == "GET" and path == "/api/schedule/admin/events":
        user = handler._require_user()
        if not handler.auth.is_super(user):
            raise ProjectError("forbidden", "仅 superadmin 可查看日程调试", 403)
        handler._sched_seed_courses()
        data = handler._sched_load()
        events = list(data.get("events") or [])
        events.sort(key=lambda e: (e.get("date") or "", e.get("startMin") or 0))
        handler._json(ok(events=events, users=handler._sched_people(), me=user))
        return True

    if method == "POST" and path == "/api/schedule/admin/events":
        user = handler._require_user()
        if not handler.auth.is_super(user):
            raise ProjectError("forbidden", "仅 superadmin 可修改日程调试", 403)
        body = handler._read_json()
        data = handler._sched_load()
        eid = str(body.get("id") or "")
        old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None) if eid else None
        ev = handler._sched_payload(body, old)
        creator = str(body.get("creator") or (old.get("creator") if old else user))
        ev["creator"] = creator if creator in handler.auth.users else user
        ev["mentions"] = list(body.get("mentions") or (old.get("mentions") if old else [])) or [ev["creator"]]
        now = time.time()
        ev["updated_at"] = now
        ev["created_at"] = (old or {}).get("created_at") or now
        for participant in ev.get("participants") or []:
            conflict = handler._sched_conflict(data, ev, participant)
            if conflict:
                raise ProjectError("conflict", "%s 在该时段已有日程「%s」" % (participant, conflict.get("title") or ""), 409)
        if old:
            data["events"] = [ev if str(e.get("id")) == eid else e for e in data.get("events") or []]
        else:
            data.setdefault("events", []).append(ev)
        handler._sched_save_locked(data)
        handler._json(ok(event=ev))
        return True

    if method == "POST" and path == "/api/schedule/admin/events/delete":
        user = handler._require_user()
        if not handler.auth.is_super(user):
            raise ProjectError("forbidden", "仅 superadmin 可删除日程", 403)
        body = handler._read_json()
        eid = str(body.get("id") or "")
        data = handler._sched_load()
        old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None)
        if old and old.get("source") == "course":
            data.setdefault("deleted_course_ids", []).append(eid)
        data["events"] = [e for e in data.get("events") or [] if str(e.get("id")) != eid]
        handler._sched_save_locked(data)
        handler._json(ok(deleted=eid))
        return True

    return False
