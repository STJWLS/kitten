# -*- coding: utf-8 -*-
"""日程 module-local API：courses / venues / events / participants。"""
from urllib.parse import parse_qs

from kernel import notifications as notification_store
from kernel.protocol import ProjectError, ok

PREFIXES = [
    "/api/schedule/courses",
    "/api/schedule/venues",
    "/api/schedule/events",
    "/api/schedule/participants",
]


def handle(handler, method, path, parsed):
    if method == "GET" and path == "/api/schedule/courses":
        user = handler._require_user()
        if not handler._can_access(user, "schedule"):
            raise ProjectError("forbidden", "没有日程访问权限", 403)
        store = handler._sched_store()

        def mine(x):
            if not isinstance(x, dict):
                return False
            if str(x.get("owner") or "") == user:
                return True
            return user in (x.get("participants") or []) or user in (x.get("mentions") or [])

        courses = [c for c in (store.get("courses") or []) if mine(c)]
        specials = [sp for sp in (store.get("specials") or []) if mine(sp)]
        exams = [e for e in (store.get("exams") or []) if mine(e)]
        handler._json(ok(version=store.get("version") or 2, meta=store.get("meta") or {},
                         slots=store.get("slots") or [], courses=courses,
                         specials=specials, exams=exams,
                         holidays=store.get("holidays") or [], venues=store.get("venues") or []))
        return True

    if path == "/api/schedule/venues":
        user = handler._require_user()
        if not handler._can_access(user, "schedule"):
            raise ProjectError("forbidden", "没有日程访问权限", 403)
        store = handler._sched_store()
        if method == "POST":
            body = handler._read_json()
            incoming = body.get("venues")
            if not isinstance(incoming, list):
                raise ProjectError("bad_request", "venues 必须是数组", 400)
            merged = []
            for v in incoming[:300]:
                if not isinstance(v, dict):
                    continue
                code = str(v.get("code") or "").strip()[:60]
                name = str(v.get("name") or "").strip()[:120]
                if not code or not name:
                    continue
                merged.append({"code": code, "name": name, "short": str(v.get("short") or name)[:120],
                               "address": str(v.get("address") or "")[:300], "note": str(v.get("note") or "")[:500],
                               "lat": v.get("lat"), "lng": v.get("lng"), "custom": bool(v.get("custom"))})
            store["venues"] = merged
            handler._sched_courses_save_locked(store)
            handler._json(ok(venues=merged))
            return True
        handler._json(ok(venues=store.get("venues") or []))
        return True

    if method == "GET" and path == "/api/schedule/events":
        user = handler._require_user()
        data = handler._sched_load()
        events = [e for e in (data.get("events") or []) if handler._sched_visible(user, e)]
        events.sort(key=lambda e: (e.get("date") or "", e.get("startMin") or 0))
        handler._json(ok(events=events, users=handler._sched_people(), me=user))
        return True

    if method == "GET" and path == "/api/schedule/participants":
        user = handler._require_user()
        q = parse_qs(parsed.query or "")
        date = (q.get("date") or [""])[0]
        try:
            start = int((q.get("startMin") or ["0"])[0])
            end = int((q.get("endMin") or ["0"])[0])
        except Exception:
            raise ProjectError("bad_request", "时间格式不正确", 400)
        if not date or end <= start:
            raise ProjectError("bad_request", "时间段不正确", 400)
        q0 = handler._sched_dt(date, start)
        q1 = handler._sched_dt(date, end)
        exclude = (q.get("exclude") or [""])[0]
        data = handler._sched_load()
        out = []
        for person in handler._sched_people():
            busy = None
            for ev in data.get("events") or []:
                if exclude and str(ev.get("id")) == exclude:
                    continue
                if person["user"] not in (ev.get("participants") or []):
                    continue
                e0, e1 = handler._sched_interval(ev)
                if q0 < e1 and e0 < q1:
                    busy = ev
                    break
            out.append({"user": person["user"], "emoji": person["emoji"],
                        "role": person["role"], "available": busy is None,
                        "busy_title": (busy or {}).get("title", ""),
                        "busy_id": (busy or {}).get("id", "")})
        handler._json(ok(users=out, me=user))
        return True

    if method == "POST" and path == "/api/schedule/events":
        user = handler._require_user()
        body = handler._read_json()
        data = handler._sched_load()
        eid = str(body.get("id") or "")
        old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None) if eid else None
        if old and not handler._sched_event_can(user, old, "write"):
            raise ProjectError("forbidden", "只有创建者或参与者可以修改日程", 403)
        ev = handler._sched_payload(body, old)
        ev["creator"] = str(old.get("creator")) if old else user
        if not ev.get("mentions"):
            ev["mentions"] = [user]
        import time
        now = time.time()
        ev["updated_at"] = now
        if old:
            ev["created_at"] = old.get("created_at") or now
        else:
            ev["created_at"] = now
        for participant in ev.get("participants") or []:
            conflict = handler._sched_conflict(data, ev, participant)
            if conflict:
                raise ProjectError(
                    "conflict",
                    "%s 在该时段已有日程「%s」，同一时段只能参与一个日程" % (
                        participant, conflict.get("title") or "未命名"),
                    409)
        try:
            old_mentions = set(old.get("mentions") or []) if old else set()
            old_parts = set(old.get("participants") or []) if old else set()
            for u in [str(x) for x in (ev.get("mentions") or [])]:
                if u and u != user and u not in old_mentions:
                    notification_store.notify(
                        u, "schedule", "schedule_mention", "日程里提到了你",
                        "%s 在日程「%s」中提到了你" % (user, ev.get("title") or ""),
                        "/schedule/", actor=user, meta={"eventId": ev.get("id")})
            for u in [str(x) for x in (ev.get("participants") or [])]:
                if u and u != user and u not in old_parts:
                    notification_store.notify(
                        u, "schedule", "schedule_participant", "你被加入了一个日程",
                        "%s 邀请你参与日程「%s」" % (user, ev.get("title") or ""),
                        "/schedule/", actor=user, meta={"eventId": ev.get("id")})
        except Exception:
            pass
        if old:
            data["events"] = [ev if str(e.get("id")) == eid else e for e in data.get("events") or []]
        else:
            data.setdefault("events", []).append(ev)
        handler._sched_save_locked(data)
        handler._json(ok(event=ev))
        return True

    if method == "POST" and path == "/api/schedule/events/delete":
        user = handler._require_user()
        body = handler._read_json()
        eid = str(body.get("id") or "")
        data = handler._sched_load()
        old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None)
        if not old:
            raise ProjectError("not_found", "日程不存在", 404)
        if not handler._sched_event_can(user, old, "delete"):
            raise ProjectError("forbidden", "只有创建者可以删除日程", 403)
        data["events"] = [e for e in data.get("events") or [] if str(e.get("id")) != eid]
        handler._sched_save_locked(data)
        handler._json(ok(deleted=eid))
        return True

    return False
