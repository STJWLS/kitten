# -*- coding: utf-8 -*-
"""平台内核 · HTTP 服务（标准库，仅绑定回环）。

路由：
    GET  /                         工作台根壳（树 + 宿主）
    GET  /static/<path>            根壳资源（sdk.js / project.css）
    GET  /legacy/<path>            旧页面托管（零改动 + 资源版本号 + embed 去壳）
    GET  /p/<id>/<path>            子项目原生视图（custom: web/；auto: 内核生成）
    GET  /api/tree                 整棵项目树
    GET  /api/session              当前会话
    POST /api/login /logout        身份
    GET  /api/p/<id>               项目 manifest + rev
    GET  /api/p/<id>/state         统一读（ETag / 304 / gzip）
    POST /api/p/<id>/action        统一写（rev 乐观并发）
    GET  /api/state | POST /api/save     旧协议兼容（store.json 语义）
    GET  /api/health | /api/mailstatus | POST /api/mailtest
    GET  /api/metrics              引擎指标（缓存命中/写放大/304 次数）
    /mock/api/*                    Mock 后端反代（127.0.0.1:8768）
"""

import base64
import gzip
import hashlib
import io
import json
import math
import mimetypes
import os
import secrets
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import compat
from . import notifications as notification_store
from . import messages as message_store
from .auth import Auth
from .engine import DataEngine
from .mock_gateway import MockGateway
from .protocol import PROTOCOL, ProjectError, fail, ok
from .registry import Registry
from .services import mail as mail_service
from .services import reminders

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

PID_RE = re.compile(r"^/api/p/([a-zA-Z0-9_-]+)(?:/(state|action))?$")
VIEW_RE = re.compile(r"^/p/([a-zA-Z0-9_-]+)(/.*)?$")
ASSET_RE = re.compile(r'(src|href)="((?:\.\./)?assets/[^"?]+\.(?:js|css|png))"')

EMBED_CSS = ("<style id=\"kp-embed\">"
             "header{display:none!important}"
             "body{padding-top:0!important}"
             "</style>")

# 旧页面用 localStorage 里的 emf_login_v1 做登录门禁；内核把自己的会话桥接过去，
# 这样"根登录一次，所有子项目页面都认得你"，而不是各自再弹一次登录。
PERF_PATCH = ("<script id=\"kp-perf\">(function(){try{"
    "var d=document.documentElement,low=false,inFrame=window.parent&&window.parent!==window;"
    "if(inFrame){function syncPerf(){try{var p=window.parent.document.documentElement.getAttribute('data-perf');"
    "if(p){d.setAttribute('data-perf',p);window.__KP_PERF__=window.__KP_PERF__||{};window.__KP_PERF__.tier=p;}}catch(e){}}"
    "syncPerf();try{new MutationObserver(syncPerf).observe(window.parent.document.documentElement,{attributes:true,attributeFilter:['data-perf']});}catch(e){}return;}"
    "try{low=matchMedia('(prefers-reduced-motion: reduce)').matches;}catch(e){}"
    "var c=navigator.connection||{};"
    "if(c.saveData||/(^|-)2g$/.test(c.effectiveType||''))low=true;"
    "if((navigator.hardwareConcurrency||8)<=4)low=true;"
    "if((navigator.deviceMemory||8)<=4)low=true;"
    "d.setAttribute('data-perf',low?'low':'high');"
    "window.__KP_PERF__={tier:low?'low':'high',fps:0};"
    "function markLow(){d.setAttribute('data-perf','low');window.__KP_PERF__.tier='low';}"
    "if(!low&&window.requestAnimationFrame){var frames=0,start=0,checks=0,lowStreak=0;"
    "function tick(t){if(document.hidden){start=0;requestAnimationFrame(tick);return;}"
    "if(!start)start=t;frames++;"
    "if(t-start>=1000){var fps=frames*1000/(t-start);frames=0;start=t;checks++;"
    "window.__KP_PERF__.fps=Math.round(fps);"
    "lowStreak=0;if(checks>=4)return;}"
    "requestAnimationFrame(tick);}requestAnimationFrame(tick);}"
    "try{matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',function(e){if(e.matches)markLow();});}catch(e){}"
    "}catch(e){}})();</script>")

AUTH_PATCH = ("<script id=\"kp-auth\">(function(){try{"
             "var t=sessionStorage.getItem(\"kp_token\")||localStorage.getItem(\"kp_token\");"
             "if(!t)return;var f=window.fetch;"
             "window.fetch=function(u,o){o=o||{};var h=new Headers(o.headers||{});"
             "h.set(\"Authorization\",\"Bearer \"+t);"
             "if(window.__KP_MODULE__)h.set(\"X-KP-Module\",window.__KP_MODULE__);"
             "o.headers=h;return f.call(this,u,o);};"
             "}catch(e){}})();</script>")

BRIDGE_TPL = ("<script id=\"kp-bridge\">(function(){try{var s=%s;if(!s||!s.user)return;"
              "localStorage.setItem(\"emf_login_v1\",JSON.stringify({user:s.user}));"
              "localStorage.setItem(\"emf_current_user\",s.user);"
              "var m={};try{m=JSON.parse(localStorage.getItem(\"emf_unlocked_v1\")||\"{}\")}catch(e){}"
              "m[s.user]=true;localStorage.setItem(\"emf_unlocked_v1\",JSON.stringify(m));"
              "sessionStorage.setItem(\"emf_slogin_v1\",JSON.stringify({user:s.user}));"
              "}catch(e){}})();</script>")

TZ = timezone(timedelta(hours=8))


class _Redirect(Exception):
    def __init__(self, location):
        super().__init__(location)
        self.location = location


class Handler(BaseHTTPRequestHandler):
    server_version = "KittenPlatform/1.1"
    protocol_version = "HTTP/1.1"      # 持久连接：省掉每请求一次 TCP 建连

    # ---------------- 基础设施 ----------------
    def _send(self, body: bytes, status=200, content_type="application/json; charset=utf-8",
              cache="no-store", etag=None, extra=None, gzip_ok=False):
        accept_enc = (self.headers.get("Accept-Encoding") or "").lower()
        headers = {
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            # 允许被 GitHub Pages 入口 iframe 承载（地址栏保持 github.io），
            # 同时只放行本站与 stjwls.github.io，其它站点不能嵌。
            "Content-Security-Policy": "frame-ancestors 'self' https://stjwls.github.io",
            "Permissions-Policy": "microphone=(self), camera=(self)",
        }
        headers.update(extra or {})
        if gzip_ok and "gzip" in accept_enc and len(body) >= 1024:
            body = gzip.compress(body, 6)
            self.send_response(status)
            self.send_header("Content-Encoding", "gzip")
        else:
            self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if etag:
            self.send_header("ETag", etag)
        if gzip_ok:
            self.send_header("Vary", "Accept-Encoding")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, status=200, etag=None, extra=None, cache="no-store"):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        if etag and self._if_none_match(etag):
            self.server.engine.metrics["etag_304"] += 1
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.end_headers()
            return
        self._send(raw, status, "application/json; charset=utf-8", cache=cache,
                   etag=etag, extra=extra, gzip_ok=True)

    def _if_none_match(self, etag):
        inm = (self.headers.get("If-None-Match") or "").strip()
        return bool(inm) and (inm == etag or etag in inm)

    def _error(self, code, message, status=400):
        body, status = fail(code, message, status)
        self._json(body, status)

    def _not_found(self, message="not found"):
        self._error("not_found", message, 404)

    def log_message(self, *args):
        pass

    def handle(self):
        # 浏览器/尾部 keep-alive 连接断开是常态，不必每次打 traceback
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    # ---------------- 会话 ----------------
    @property
    def auth(self):
        return self.server.auth

    @property
    def registry(self):
        return self.server.registry

    @property
    def engine(self):
        return self.server.engine

    def _session_user(self):
        authz = (self.headers.get("Authorization") or "").strip()
        if authz.lower().startswith("bearer "):
            user = self.auth.read(authz[7:].strip())
            if user:
                return user
        raw = ""
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "kp_session":
                raw = v.strip()
        user = self.auth.read(raw) if raw else None
        if not user and self.auth.dev_mode:
            user = self.server.dev_user
        return user

    # ---------------- 日程管理（跨用户） ----------------
    def _sched_file(self):
        return os.path.join(self.server.root, "data", "schedule_events.json")

    def _sched_events_dir(self):
        return os.path.join(self.server.root, "data", "schedule", "events")

    def _sched_role_dir(self, user, role):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(user or ""))[:60] or "user"
        d = os.path.join(self.server.root, "data", "schedule", "users", safe, role)
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _sched_link_file(src, dst):
        try:
            if os.path.lexists(dst): os.unlink(dst)
            try: os.symlink(src, dst)
            except Exception:
                try: os.link(src, dst)
                except Exception: shutil.copyfile(src, dst)
        except Exception:
            pass

    def _sched_event_roles(self, ev):
        owner = str(ev.get("creator") or "")
        roles = {}
        if owner:
            roles.setdefault(owner, set()).add("owned")
        for u in ev.get("participants") or []:
            if str(u): roles.setdefault(str(u), set()).add("participated")
        for u in ev.get("mentions") or []:
            if str(u): roles.setdefault(str(u), set()).add("mentioned")
        return roles

    def _sched_sync_roles(self, events):
        root = self._sched_events_dir()
        users_root = os.path.join(self.server.root, "data", "schedule", "users")
        os.makedirs(users_root, exist_ok=True)
        wanted = {}
        for ev in events:
            eid = str(ev.get("id") or "")
            if not eid: continue
            for user, roles in self._sched_event_roles(ev).items():
                for role in roles:
                    wanted.setdefault((user, role), set()).add(eid)
        for (user, role), ids in wanted.items():
            d = self._sched_role_dir(user, role)
            for name in os.listdir(d):
                if name.endswith(".json") and name[:-5] not in ids:
                    try: os.unlink(os.path.join(d, name))
                    except Exception: pass
            for eid in ids:
                self._sched_link_file(os.path.join(root, eid + ".json"), os.path.join(d, eid + ".json"))
        # remove roles no longer wanted
        try:
            for user in os.listdir(users_root):
                for role in ("owned", "participated", "mentioned"):
                    d = os.path.join(users_root, user, role)
                    if not os.path.isdir(d): continue
                    ids = wanted.get((user, role), set())
                    for name in os.listdir(d):
                        if name.endswith(".json") and name[:-5] not in ids:
                            try: os.unlink(os.path.join(d, name))
                            except Exception: pass
        except Exception:
            pass

    def _sched_load(self):
        root = self._sched_events_dir()
        events = []
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                if not name.endswith(".json"): continue
                try:
                    with open(os.path.join(root, name), encoding="utf-8") as f:
                        ev = json.load(f)
                    if isinstance(ev, dict) and ev.get("id"): events.append(ev)
                except Exception: pass
        # one-time migration from legacy events file
        if not events and os.path.isfile(self._sched_file()):
            try:
                with open(self._sched_file(), encoding="utf-8") as f: old = json.load(f)
                if isinstance(old, dict) and isinstance(old.get("events"), list):
                    events = [e for e in old["events"] if isinstance(e, dict) and e.get("id")]
                    if events: self._sched_save({"events": events})
            except Exception: pass
        return {"events": events}

    def _sched_save(self, data):
        root = self._sched_events_dir(); os.makedirs(root, exist_ok=True)
        events = [e for e in (data.get("events") or []) if isinstance(e, dict) and e.get("id")]
        keep = set()
        for ev in events:
            eid = str(ev["id"]); keep.add(eid)
            path = os.path.join(root, eid + ".json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(ev, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)  # symlinks follow; hardlinks are recreated below
        for name in os.listdir(root):
            if name.endswith(".json") and name[:-5] not in keep:
                try: os.unlink(os.path.join(root, name))
                except Exception: pass
        self._sched_sync_roles(events)

    def _sched_people(self):
        out = []
        for name in sorted(self.auth.users):
            rec = self.auth.users.get(name) or {}
            out.append({"user": name, "emoji": rec.get("emoji") or "👤",
                        "role": rec.get("role") or "user"})
        return out

    @staticmethod
    def _sched_dt(date_s, minute):
        from datetime import datetime, timedelta
        return datetime.strptime(date_s, "%Y-%m-%d") + timedelta(minutes=int(minute))

    def _sched_interval(self, ev):
        start = self._sched_dt(str(ev.get("date") or ""), ev.get("startMin") or 0)
        end_date = str(ev.get("endDate") or ev.get("date") or "")
        end = self._sched_dt(end_date, ev.get("endMin") or 0)
        if end <= start:
            end = start
        return start, end

    def _sched_visible(self, user, ev):
        if str(ev.get("creator") or "") == user:
            return True
        if user in (ev.get("mentions") or []):
            return True
        return user in (ev.get("participants") or [])

    @staticmethod
    def _sched_event_can(user, ev, action="read"):
        owner = str(ev.get("creator") or "")
        if owner == user:
            return True
        if action == "read":
            return user in (ev.get("mentions") or []) or user in (ev.get("participants") or [])
        if user in (ev.get("participants") or []):
            return action in ("read", "write")
        return False

    @staticmethod
    def _sched_item_can(user, item, action="read"):
        owner = str(item.get("owner") or "")
        if owner == user:
            return True
        if action == "read":
            return user in (item.get("participants") or []) or user in (item.get("mentions") or [])
        if user in (item.get("participants") or []):
            return action == "write"
        return False

    def _sched_conflict(self, data, ev, user):
        """返回 conflict event 或 None；只检查参与者，提到不算占用。"""
        start, end = self._sched_interval(ev)
        for other in data.get("events") or []:
            if str(other.get("id")) == str(ev.get("id")):
                continue
            if user not in (other.get("participants") or []):
                continue
            os_, oe = self._sched_interval(other)
            if start < oe and os_ < end:
                return other
        return None

    def _sched_seed_courses(self):
        """把静态课程展开成普通日程事件（tag=课程），供调试窗口统一查看。"""
        from datetime import datetime, timedelta
        try:
            proj = self.registry.get("schedule")
            spec = proj.manifest() if proj else {}
            path = os.path.join(spec.get("dir") or "", "web", "schedule.json")
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            base = d.get("meta", {}).get("termStart") or "2026-09-07"
            slots = d.get("slots") or []
            data = self._sched_load()
            ids = {str(e.get("id")) for e in data.get("events") or []}
            deleted = set(data.get("deleted_course_ids") or [])
            added = 0
            for c in d.get("courses") or []:
                for ent in c.get("schedule") or []:
                    try:
                        s0 = slots[ent["slot"] - 1]
                        s1 = slots[ent["slot"] - 1 + (ent.get("span") or 1) - 1]
                    except Exception:
                        continue
                    for wk in ent.get("weeks") or []:
                        day = datetime.strptime(base, "%Y-%m-%d") + timedelta(days=(int(wk)-1)*7 + int(ent.get("day") or 0))
                        ds = day.strftime("%Y-%m-%d")
                        eid = "course-%s-%s-%s" % (c.get("code"), ds, s0.get("start"))
                        if eid in ids or eid in deleted:
                            continue
                        data.setdefault("events", []).append({
                            "id": eid,
                            "title": "%s · %s" % (c.get("code") or "", c.get("cn") or c.get("name") or ""),
                            "date": ds, "endDate": ds,
                            "startMin": s0.get("start") or 0, "endMin": s1.get("end") or 0,
                            "tag": "课程", "place": ent.get("venue") or "", "placeCode": "",
                            "note": ent.get("note") or "",
                            "reminders": [],
                            "creator": c.get("owner") or "kitten",
                            "mentions": list(c.get("mentions") or []),
                            "participants": list(c.get("participants") or [c.get("owner") or "kitten"]),
                            "source": "course",
                            "created_at": time.time(), "updated_at": time.time(),
                        })
                        ids.add(eid); added += 1
            if added:
                with SCHEDULE_LOCK:
                    self._sched_save(data)
        except Exception:
            traceback.print_exc()

    def _sched_admin_courses(self):
        try:
            proj = self.registry.get("schedule")
            spec = proj.manifest() if proj else {}
            path = os.path.join(spec.get("dir") or "", "web", "schedule.json")
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return {"slots": d.get("slots") or [], "courses": d.get("courses") or []}
        except Exception:
            return {"slots": [], "courses": []}

    def _sched_static_data(self):
        try:
            proj = self.registry.get("schedule")
            spec = proj.manifest() if proj else {}
            path = os.path.join(spec.get("dir") or "", "web", "schedule.json")
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _sched_custom_courses_file(self):
        return os.path.join(self.server.root, "data", "schedule_courses.json")

    def _sched_custom_courses(self):
        try:
            with open(self._sched_custom_courses_file(), encoding="utf-8") as f:
                d = json.load(f)
            return {"courses": d.get("courses") or [], "exams": d.get("exams") or []}
        except Exception:
            return {"courses": [], "exams": []}

    def _sched_store_file(self):
        return os.path.join(self.server.root, "data", "schedule_store.json")

    def _sched_store_load(self):
        try:
            with open(self._sched_store_file(), encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and int(d.get("version") or 0) >= 2:
                return d
        except Exception:
            pass
        return None

    @staticmethod
    def _sched_item_id(prefix, text):
        import hashlib as _h
        return prefix + "-" + _h.sha1(str(text).encode("utf-8")).hexdigest()[:12]

    def _sched_store_seed(self):
        static = self._sched_static_data()
        users = sorted(self.auth.users.keys())
        custom = {}
        courses, seen, exam_list = [], set(), []
        for c in (static.get("courses") or []):
            if not isinstance(c, dict): continue
            code = str(c.get("code") or "")
            if not code or code in seen: continue
            seen.add(code); item = dict(c)
            item.setdefault("source", "seed")
            item["owner"] = item.get("owner") or (users[0] if users else "kitten")
            item["participants"] = item.get("participants") or [item["owner"]]
            item["mentions"] = item.get("mentions") or [item["owner"]]
            item["schedule"] = item.get("schedule") or []
            for ex in (item.pop("exams", None) or []):
                if isinstance(ex, dict): ex = dict(ex, course=code)
                else: continue
                exam_list.append(ex)
            courses.append(item)
        for c in (custom.get("courses") or []):
            if not isinstance(c, dict): continue
            code = str(c.get("code") or "")
            if not code or code in seen: continue
            seen.add(code); item = dict(c)
            item.setdefault("source", "ai")
            item["owner"] = item.get("owner") or (users[0] if users else "kitten")
            item["participants"] = item.get("participants") or [item["owner"]]
            item["mentions"] = item.get("mentions") or [item["owner"]]
            for ex in (item.pop("exams", None) or []):
                if isinstance(ex, dict): ex = dict(ex, course=code)
                else: continue
                exam_list.append(ex)
            courses.append(item)
        exams, eseen = [], set()
        for ex in list(static.get("exams") or []) + list(custom.get("exams") or []) + exam_list:
            if not isinstance(ex, dict): continue
            key = (ex.get("course"), ex.get("date"), ex.get("time"), ex.get("week"))
            if key in eseen: continue
            eseen.add(key); item = dict(ex)
            item["id"] = item.get("id") or self._sched_item_id("exam", "%s|%s|%s" % key)
            course = next((c for c in courses if str(c.get("code") or "") == str(item.get("course") or "")), None)
            owner = str((course or {}).get("owner") or (users[0] if users else "kitten"))
            item["owner"] = item.get("owner") or owner
            item["participants"] = item.get("participants") or [item["owner"]]
            item["mentions"] = item.get("mentions") or [item["owner"]]
            exams.append(item)
        holidays = []
        for h in (static.get("holidays") or []):
            if not isinstance(h, dict): continue
            item = dict(h)
            item["id"] = item.get("id") or self._sched_item_id("hol", "%s|%s" % (item.get("name"), item.get("dates")))
            holidays.append(item)
        specials = []
        course_by_code = {str(c.get("code") or ""): c for c in courses}
        for sp in (static.get("specials") or []):
            if not isinstance(sp, dict): continue
            item = dict(sp)
            code = str(item.get("code") or "")
            course = course_by_code.get(code)
            if not item.get("title"):
                if course: item["title"] = course.get("cn") or course.get("name") or code
                else: item["title"] = str(item.get("note") or code or "特殊安排")[:120]
            item["tag"] = item.get("tag") or code or "安排"
            item["course"] = item.get("course") or (code if course else "")
            item["owner"] = item.get("owner") or str((course or {}).get("owner") or (users[0] if users else "kitten"))
            item["participants"] = item.get("participants") or [item["owner"]]
            item["mentions"] = item.get("mentions") or [item["owner"]]
            item["id"] = item.get("id") or self._sched_item_id("sp", "%s|%s|%s|%s" % (code, item.get("weeks"), item.get("day"), item.get("start")))
            specials.append(item)
        store = {"version": 2, "meta": static.get("meta") or {}, "slots": static.get("slots") or [],
                 "courses": courses, "specials": specials,
                 "exams": exams, "holidays": holidays,
                 "venues": static.get("venues") or []}
        with SCHEDULE_COURSES_LOCK:
            self._sched_store_save(store)
        return store

    def _sched_shared_file(self):
        return os.path.join(self.server.root, "data", "schedule", "shared.json")

    def _sched_items_root(self):
        return os.path.join(self.server.root, "data", "schedule", "items")

    def _sched_item_filename(self, kind, item):
        if kind == "course":
            owner = str(item.get("owner") or "")
            code = str(item.get("code") or "")
            return "course-" + hashlib.sha1((owner + "|" + code).encode("utf-8")).hexdigest()[:16] + ".json"
        return kind + "-" + re.sub(r"[^A-Za-z0-9_.-]", "_", str(item.get("id") or ""))[:80] + ".json"

    def _sched_items_load(self, kind):
        d = os.path.join(self._sched_items_root(), kind + "s")
        out = []
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if not name.endswith(".json"): continue
                try:
                    with open(os.path.join(d, name), encoding="utf-8") as f:
                        item = json.load(f)
                    if isinstance(item, dict): out.append(item)
                except Exception: pass
        return out

    def _sched_items_save(self, kind, items):
        d = os.path.join(self._sched_items_root(), kind + "s"); os.makedirs(d, exist_ok=True)
        keep = set()
        canonical = {}
        for item in items:
            if not isinstance(item, dict): continue
            fn = self._sched_item_filename(kind, item); keep.add(fn)
            path = os.path.join(d, fn); canonical[fn] = path
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        for name in os.listdir(d):
            if name.endswith(".json") and name not in keep:
                try: os.unlink(os.path.join(d, name))
                except Exception: pass
        return canonical

    def _sched_item_roles(self, item):
        owner = str(item.get("owner") or "")
        roles = {}
        if owner: roles.setdefault(owner, set()).add("owned")
        for u in item.get("participants") or []:
            if str(u): roles.setdefault(str(u), set()).add("participated")
        for u in item.get("mentions") or []:
            if str(u): roles.setdefault(str(u), set()).add("mentioned")
        return roles

    def _sched_sync_item_roles(self, canonical):
        users_root = os.path.join(self.server.root, "data", "schedule", "users")
        os.makedirs(users_root, exist_ok=True)
        wanted = {}
        for fn, path in canonical.items():
            # fn prefix identifies kind; reload item from path
            try:
                with open(path, encoding="utf-8") as f: item = json.load(f)
            except Exception: continue
            for user, roles in self._sched_item_roles(item).items():
                for role in roles:
                    wanted.setdefault((user, role), {})[fn] = path
        for (user, role), files in wanted.items():
            d = self._sched_role_dir(user, role)
            prefix = None
            for fn in files:
                prefix = fn.split("-", 1)[0]
                break
            for name in os.listdir(d):
                if name.endswith(".json") and (name.startswith("course-") or name.startswith("exam-") or name.startswith("special-")):
                    # only remove files of this kind when this user has none
                    kindprefix = name.split("-", 1)[0]
                    if kindprefix == prefix and name not in files:
                        try: os.unlink(os.path.join(d, name))
                        except Exception: pass
            for fn, path in files.items():
                self._sched_link_file(path, os.path.join(d, fn))
        # cleanup item files in role dirs that no longer have any wanted event for that kind
        for user in os.listdir(users_root):
            for role in ("owned", "participated", "mentioned"):
                d = os.path.join(users_root, user, role)
                if not os.path.isdir(d): continue
                for name in os.listdir(d):
                    if not name.endswith(".json"): continue
                    kindprefix = name.split("-", 1)[0]
                    if kindprefix in ("course", "exam", "special"):
                        if name not in wanted.get((user, role), {}):
                            try: os.unlink(os.path.join(d, name))
                            except Exception: pass

    def _sched_store_save(self, d):
        shared_path = self._sched_shared_file(); os.makedirs(os.path.dirname(shared_path), exist_ok=True)
        shared = {"version": 2, "meta": d.get("meta") or {}, "slots": d.get("slots") or [],
                  "holidays": d.get("holidays") or [], "venues": d.get("venues") or []}
        tmp = shared_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(shared, f, ensure_ascii=False, indent=1)
        os.replace(tmp, shared_path)
        canonical = {}
        for kind, key in (("course", "courses"), ("exam", "exams"), ("special", "specials")):
            canonical.update(self._sched_items_save(kind, d.get(key) or []))
        self._sched_sync_item_roles(canonical)

    def _sched_store_normalize(self, d):
        if not isinstance(d, dict): return d
        changed = False
        courses = [c for c in (d.get("courses") or []) if isinstance(c, dict)]
        for c in courses:
            owner = str(c.get("owner") or "kitten")
            parts = [str(x) for x in (c.get("participants") or [owner]) if str(x) in self.auth.users]
            if owner not in parts: parts = [owner] + parts
            ments = [str(x) for x in (c.get("mentions") or [owner]) if str(x) in self.auth.users]
            if c.get("owner") != owner or c.get("participants") != parts or c.get("mentions") != ments:
                c["owner"] = owner; c["participants"] = parts; c["mentions"] = ments; changed = True
        d["courses"] = courses
        course_by_code = {str(c.get("code") or ""): c for c in courses}
        exams = [e for e in (d.get("exams") or []) if isinstance(e, dict)]
        keyed = {(e.get("course"), e.get("date"), e.get("time"), e.get("week")) for e in exams}
        for c in (d.get("courses") or []):
            if not isinstance(c, dict): continue
            for ex in (c.pop("exams", None) or []):
                if not isinstance(ex, dict): continue
                ex = dict(ex, course=c.get("code") or ex.get("course"))
                key = (ex.get("course"), ex.get("date"), ex.get("time"), ex.get("week"))
                if key in keyed: continue
                keyed.add(key); exams.append(ex); changed = True
        for e in exams:
            if not e.get("id"):
                e["id"] = self._sched_item_id("exam", "%s|%s|%s|%s" % (e.get("course"), e.get("date"), e.get("time"), e.get("week")))
                changed = True
            course = course_by_code.get(str(e.get("course") or ""))
            owner = str(e.get("owner") or (course or {}).get("owner") or "kitten")
            parts = [str(x) for x in (e.get("participants") or [owner]) if str(x) in self.auth.users]
            if owner not in parts: parts = [owner] + parts
            ments = [str(x) for x in (e.get("mentions") or [owner]) if str(x) in self.auth.users]
            if e.get("owner") != owner or e.get("participants") != parts or e.get("mentions") != ments:
                e["owner"] = owner; e["participants"] = parts; e["mentions"] = ments; changed = True
        holidays = [h for h in (d.get("holidays") or []) if isinstance(h, dict)]
        for h in holidays:
            if not h.get("id"):
                h["id"] = self._sched_item_id("hol", "%s|%s" % (h.get("name"), h.get("dates")))
                changed = True
        specials = [sp for sp in (d.get("specials") or []) if isinstance(sp, dict)]
        for sp in specials:
            if not sp.get("id"):
                sp["id"] = self._sched_item_id("sp", "%s|%s|%s|%s" % (sp.get("code"), sp.get("weeks"), sp.get("day"), sp.get("start")))
                changed = True
            code = str(sp.get("code") or ""); course = course_by_code.get(code)
            if not sp.get("title"):
                sp["title"] = (course.get("cn") or course.get("name") or sp.get("note") or code or "特殊安排") if course else (sp.get("note") or code or "特殊安排")
                changed = True
            if not sp.get("tag"):
                sp["tag"] = code or "安排"; changed = True
            if not sp.get("course"):
                sp["course"] = code if course else ""; changed = True
            owner = str(sp.get("owner") or (course or {}).get("owner") or "kitten")
            parts = [str(x) for x in (sp.get("participants") or [owner]) if str(x) in self.auth.users]
            if owner not in parts: parts = [owner] + parts
            ments = [str(x) for x in (sp.get("mentions") or [owner]) if str(x) in self.auth.users]
            if sp.get("owner") != owner or sp.get("participants") != parts or sp.get("mentions") != ments:
                sp["owner"] = owner; sp["participants"] = parts; sp["mentions"] = ments; changed = True
        d["exams"] = exams; d["holidays"] = holidays; d["specials"] = specials
        if changed:
            with SCHEDULE_COURSES_LOCK:
                self._sched_store_save(d)
        return d

    def _sched_store(self):
        shared_path = self._sched_shared_file()
        items_root = self._sched_items_root()
        if not os.path.isfile(shared_path) and not os.path.isdir(items_root):
            legacy = self._sched_store_load() or self._sched_store_seed()
            self._sched_store_save(legacy)
        try:
            with open(shared_path, encoding="utf-8") as f: shared = json.load(f)
        except Exception:
            shared = {"version": 2, "meta": {}, "slots": [], "holidays": [], "venues": []}
        d = dict(shared)
        d["courses"] = self._sched_items_load("course")
        d["exams"] = self._sched_items_load("exam")
        d["specials"] = self._sched_items_load("special")
        return self._sched_store_normalize(d)

    def _sched_courses_store(self):
        d = self._sched_custom_courses()
        if d.get("seeded"):
            return d
        static = self._sched_static_data()
        users = sorted(self.auth.users.keys())
        merged, seen = [], set()
        for c in (static.get("courses") or []) + (d.get("courses") or []):
            if not isinstance(c, dict): continue
            code = str(c.get("code") or "")
            if not code or code in seen: continue
            seen.add(code)
            item = dict(c)
            item["owner"] = item.get("owner") or (users[0] if users else "")
            item["participants"] = item.get("participants") or list(users)
            item["mentions"] = item.get("mentions") or list(users)
            merged.append(item)
        exams, eseen = [], set()
        for e in (static.get("exams") or []) + (d.get("exams") or []):
            if not isinstance(e, dict): continue
            key = (e.get("course"), e.get("date"), e.get("time"))
            if key in eseen: continue
            eseen.add(key); exams.append(dict(e))
        out = {"courses": merged, "exams": exams, "seeded": True}
        with SCHEDULE_COURSES_LOCK:
            self._sched_custom_courses_save(out)
        return out

    def _sched_custom_courses_save(self, d):
        path = self._sched_custom_courses_file(); os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"courses": d.get("courses") or [], "exams": d.get("exams") or [], "seeded": bool(d.get("seeded"))}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def _sched_course_payload(self, args, old=None, user=""):
        store = self._sched_store()
        slots = store.get("slots") or []
        total_weeks = int((store.get("meta") or {}).get("totalWeeks") or 18)
        base = dict(old or {})
        old_code = str(base.get("code") or "")
        code = str(args.get("code") or old_code).strip()[:40]
        if not code: raise ProjectError("bad_request", "缺少课程代码 code", 400)
        name = str(args.get("name") or base.get("name") or code).strip()[:120]
        cn = str(args.get("cn") or base.get("cn") or name).strip()[:120]
        module = str(args.get("module") or base.get("module") or "M1").strip()[:20]
        try: credit = int(args.get("credit", base.get("credit", 0)) or 0)
        except Exception: raise ProjectError("bad_request", "学分必须是数字", 400)
        if credit < 0 or credit > 30: raise ProjectError("bad_request", "学分不合法", 400)
        prof = str(args.get("prof") or base.get("prof") or "")[:80]
        prof_en = str(args.get("prof_en") or base.get("prof_en") or "")[:80]
        venues = str(args.get("venues") or base.get("venues") or "")[:200]
        color = str(args.get("color") or base.get("color") or "")[:30]
        raw_sched = args.get("schedule") if "schedule" in args else base.get("schedule")
        sched = []
        for ent in (raw_sched or [])[:40]:
            if not isinstance(ent, dict): continue
            day = int(ent.get("day") or 0)
            if day < 0 or day > 6: continue
            weeks = []
            for w in (ent.get("weeks") or []):
                try:
                    wi = int(w)
                    if 1 <= wi <= total_weeks and wi not in weeks: weeks.append(wi)
                except Exception: pass
            if not weeks: continue
            slot = None
            try:
                if ent.get("slot") not in (None, ""): slot = int(ent.get("slot"))
            except Exception: slot = None
            start = ent.get("start"); end = ent.get("end")
            if slot is not None:
                span = int(ent.get("span") or 1)
                if not slots or slot < 1 or slot > len(slots) or span < 1 or slot + span - 1 > len(slots): continue
                item = {"weeks": weeks, "day": day, "slot": slot, "span": span}
            else:
                try:
                    start = int(start); end = int(end)
                except Exception: continue
                if not (0 <= start < end <= 1440): continue
                item = {"weeks": weeks, "day": day, "start": start, "end": end}
            item["venue"] = str(ent.get("venue") or "")[:120]
            item["note"] = str(ent.get("note") or "")[:240]
            sched.append(item)
        if not sched and not old:
            raise ProjectError("bad_request", "至少需要一个有效上课时间段 schedule", 400)
        owner = str(base.get("owner") or user)
        participants = args.get("participants") if "participants" in args else base.get("participants") or [owner]
        mentions = args.get("mentions") if "mentions" in args else base.get("mentions") or [owner]
        return {"code": code, "name": name, "cn": cn, "module": module, "credit": credit,
                "prof": prof, "prof_en": prof_en, "venues": venues, "color": color,
                "schedule": sched, "owner": owner,
                "participants": [str(x) for x in participants if str(x) in self.auth.users][:20],
                "mentions": [str(x) for x in mentions if str(x) in self.auth.users][:20],
                "custom": True}

    def _sched_payload(self, body, old=None):
        import re as _re
        old = old or {}
        def pick(key, default=""):
            return body[key] if key in body else old.get(key, default)
        def names(key):
            vals = pick(key, old.get(key) or [])
            if not isinstance(vals, list):
                vals = []
            return [str(x) for x in vals if str(x) in self.auth.users]
        title = str(pick("title", "") or "").strip()[:120]
        if not title:
            raise ProjectError("bad_request", "请填写日程标题", 400)
        date = str(pick("date", "") or "").strip()
        end_date = str(pick("endDate", date) or date).strip()
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", date) or not _re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
            raise ProjectError("bad_request", "日期格式不正确", 400)
        try:
            start = max(0, min(1440, int(pick("startMin", 0) or 0)))
            end = max(0, min(1440, int(pick("endMin", 0) or 0)))
        except Exception:
            raise ProjectError("bad_request", "时间格式不正确", 400)
        if (end_date, end) <= (date, start):
            raise ProjectError("bad_request", "结束时间必须晚于开始时间", 400)
        return {
            "id": str(old.get("id")) if old else (str(body.get("id") or "") or "s%d" % int(time.time() * 1000)),
            "title": title, "date": date, "endDate": end_date,
            "startMin": start, "endMin": end,
            "tag": str(pick("tag", "个人") or "个人")[:20],
            "place": str(pick("place", "") or "")[:200],
            "placeCode": str(pick("placeCode", "") or "")[:80],
            "note": str(pick("note", "") or "")[:2000],
            "reminders": pick("reminders", []) if isinstance(pick("reminders", []), list) else [],
            "mentions": names("mentions"), "participants": names("participants"),
        }

    # ---------------- LLM 服务配置 ----------------
    def _llm_file(self):
        return os.path.join(self.server.root, "data", "llm.json")

    def _llm_key_file(self):
        return os.path.join(self.server.root, "data", "llm_key.bin")

    def _llm_fernet(self):
        from cryptography.fernet import Fernet
        kp = self._llm_key_file()
        os.makedirs(os.path.dirname(kp), exist_ok=True)
        try:
            with open(kp, "rb") as f:
                key = f.read().strip()
        except Exception:
            key = Fernet.generate_key()
            tmp = kp + ".tmp"
            with open(tmp, "wb") as f:
                f.write(key)
            try:
                os.chmod(tmp, 0o600)
            except Exception:
                pass
            os.replace(tmp, kp)
        return Fernet(key)

    def _llm_load(self):
        try:
            with open(self._llm_file(), "rb") as f:
                raw = f.read()
        except Exception:
            return {"global": {}, "users": {}}
        try:
            if raw[:1] == b"{":
                d = json.loads(raw.decode("utf-8"))
            else:
                d = json.loads(self._llm_fernet().decrypt(raw).decode("utf-8"))
            return d if isinstance(d, dict) else {"global": {}, "users": {}}
        except Exception:
            return {"global": {}, "users": {}}

    def _llm_save(self, data):
        os.makedirs(os.path.dirname(self._llm_file()), exist_ok=True)
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        enc = self._llm_fernet().encrypt(raw)
        tmp = self._llm_file() + ".tmp"
        with open(tmp, "wb") as f:
            f.write(enc)
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, self._llm_file())

    @staticmethod
    def _llm_mask(key):
        key = str(key or "")
        return "" if not key else (key[:4] + "…" + key[-4:] if len(key) > 8 else "已设置")

    @staticmethod
    def _llm_detect(base_url, key=""):
        u = str(base_url or "").lower()
        if "3786" in u or "dsh" in u:
            return "dsh"
        table = [
            ("deepseek", "deepseek"), ("openai.com", "openai"), ("anthropic", "anthropic"),
            ("openrouter", "openrouter"), ("moonshot", "moonshot"), ("bigmodel", "zhipu"),
            ("dashscope", "qwen"), ("aliyuncs", "qwen"), ("groq", "groq"), ("mistral", "mistral"),
            ("11434", "ollama"), ("localhost", "local"),
        ]
        for needle, name in table:
            if needle in u:
                return name
        return "custom"

    def _llm_clean(self, body):
        base = str(body.get("base_url") or "").strip()[:500]
        key = str(body.get("api_key") or "").strip()[:500]
        provider = str(body.get("provider") or "").strip()[:40] or self._llm_detect(base, key)
        return {"provider": provider, "base_url": base, "api_key": key,
                "model": str(body.get("model") or "").strip()[:120],
                "enabled": bool(body.get("enabled", bool(base)))}

    def _llm_effective(self, user, provider_id=None):
        cfg = self._llm_load()
        me = (cfg.get("users") or {}).get(user) or {}
        g = cfg.get("global") or {}
        if me.get("mode") == "override" and me.get("base_url"):
            return dict(me, source="override")
        if g.get("enabled", True):
            p = None
            if provider_id:
                p = next((x for x in self._llm_providers(g) if x.get("id") == provider_id), None)
            p = p or self._llm_active_provider(g)
            if p and p.get("base_url"):
                return {"provider": p.get("provider"), "base_url": p.get("base_url"),
                        "api_key": (p.get("keys") or [""])[0], "model": p.get("model") or "",
                        "context_window": p.get("context_window") or 0,
                        "provider_id": p.get("id"), "effort": g.get("effort") or "medium",
                        "source": "server"}
            if g.get("base_url"):
                return dict(g, source="server")
        return None

    def _llm_public(self, cfg, source=None):
        cfg = cfg or {}
        return {"source": source, "provider": cfg.get("provider") or "",
                "base_url": cfg.get("base_url") or "", "model": cfg.get("model") or "",
                "context_window": cfg.get("context_window") or 0,
                "effort": cfg.get("effort") or "medium",
                "provider_id": cfg.get("provider_id") or "",
                "has_key": bool(cfg.get("api_key")), "key_masked": self._llm_mask(cfg.get("api_key")),
                "configured": bool(cfg.get("base_url"))}

    @staticmethod
    def _llm_keys(value):
        out = []
        for k in value or []:
            if isinstance(k, dict):
                k = k.get("key") or k.get("value") or ""
            k = str(k or "").strip()
            if k and k not in out:
                out.append(k[:500])
        return out

    def _llm_providers(self, g):
        g = g or {}
        ps = g.get("providers")
        if isinstance(ps, list) and ps:
            out = []
            for idx, p in enumerate(ps):
                if not isinstance(p, dict):
                    continue
                base = str(p.get("base_url") or "").strip()[:500]
                provider = str(p.get("provider") or "").strip()[:40] or self._llm_detect(base)
                pid = str(p.get("id") or provider or ("p%d" % idx)).strip()[:60]
                out.append({
                    "id": pid, "name": str(p.get("name") or pid)[:80],
                    "provider": provider, "base_url": base,
                    "model": str(p.get("model") or "").strip()[:120],
                    "context_window": int(p.get("context_window") or 0),
                    "keys": self._llm_keys(p.get("keys")),
                    "enabled": bool(p.get("enabled", True)),
                })
            if out:
                return out
        if g.get("base_url"):
            base = str(g.get("base_url") or "").strip()[:500]
            return [{"id": "default", "name": g.get("provider") or self._llm_detect(base),
                     "provider": g.get("provider") or self._llm_detect(base),
                     "base_url": base, "model": str(g.get("model") or "")[:120],
                     "context_window": int(g.get("context_window") or 0),
                     "keys": self._llm_keys([g.get("api_key")]), "enabled": True}]
        return []

    def _llm_active_provider(self, g):
        ps = self._llm_providers(g)
        if not ps:
            return None
        aid = (g or {}).get("active_provider")
        for p in ps:
            if p["id"] == aid:
                return p
        return ps[0]

    def _llm_provider_public(self, p, active=False):
        p = p or {}
        return {"id": p.get("id") or "", "name": p.get("name") or p.get("id") or "",
                "provider": p.get("provider") or "", "base_url": p.get("base_url") or "",
                "model": p.get("model") or "", "context_window": p.get("context_window") or 0,
                "has_key": bool(p.get("keys")), "key_masks": [self._llm_mask(k) for k in p.get("keys") or []],
                "active": bool(active), "enabled": bool(p.get("enabled", True))}

    def _llm_http(self, url, headers=None, payload=None, timeout=25):
        import urllib.request as _ur
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = _ur.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
        try:
            with _ur.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                try:
                    return r.status, json.loads(raw)
                except Exception:
                    return r.status, raw[:2000]
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw[:1000]
        except Exception as e:
            return 0, str(e)

    # ---------------- AI 会话（按用户独立，加密） ----------------
    def _ai_sessions_root(self):
        return os.path.join(self.server.root, "data", "ai_sessions")

    def _ai_sessions_dir(self, user):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", user)[:60] or "user"
        d = os.path.join(self._ai_sessions_root(), safe)
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _ai_session_id(value=""):
        v = str(value or "").strip()
        if re.match(r"^[A-Za-z0-9_-]{4,64}$", v):
            return v
        return "s-%d-%s" % (int(time.time() * 1000), secrets.token_hex(4))

    @staticmethod
    def _legacy_work_to_events(work):
        events = []
        for i, w in enumerate((work or [])[:80]):
            if not isinstance(w, dict): continue
            typ = str(w.get("type") or "thought")
            text = str(w.get("text") or "")
            if typ == "answer":
                events.append({"type": "user_answer", "text": text})
            elif typ == "tool":
                title = str(w.get("title") or "工具")
                tool = title.split("·", 1)[1].strip() if "·" in title else title
                cid = "legacy-%d" % i
                events.append({"type": "tool_call", "tool": tool, "callId": cid, "input": {}})
                events.append({"type": "tool_result", "callId": cid, "status": str(w.get("status") or "完成"), "result": text})
            else:
                events.append({"type": "thinking", "text": text})
        return events

    @staticmethod
    def _ai_session_public(session, full=False):
        s = session or {}
        base = {"id": s.get("id"), "title": s.get("title") or "新对话",
                "module": s.get("module") or "", "created": s.get("created") or "",
                "updated": s.get("updated") or "", "message_count": len(s.get("messages") or []),
                "usage": s.get("usage") or {}, "context_window": s.get("context_window") or 0,
                "dsh_session_id": s.get("dsh_session_id") or "",
                "dsh_model": s.get("dsh_model") or "", "dsh_effort": s.get("dsh_effort") or "",
                "needs_response": bool(s.get("needs_response")),
                "unread": bool(s.get("unread")),
                "archived": bool(s.get("archived")), "pinned": bool(s.get("pinned"))}
        if full:
            msgs = []
            for m in (s.get("messages") or []):
                if not isinstance(m, dict): continue
                mm = dict(m)
                if "content" not in mm: mm["content"] = mm.get("text") or ""
                legacy_work = mm.pop("work", None)
                if not mm.get("events") and legacy_work:
                    mm["events"] = Handler._legacy_work_to_events(legacy_work)
                msgs.append(mm)
            base["messages"] = msgs
        return base

    def _ai_session_load(self, user, sid):
        path = os.path.join(self._ai_sessions_dir(user), self._ai_session_id(sid) + ".enc")
        try:
            with open(path, "rb") as f:
                raw = self._llm_fernet().decrypt(f.read()).decode("utf-8")
            d = json.loads(raw)
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    def _ai_session_save(self, user, session):
        sid = self._ai_session_id((session or {}).get("id"))
        now = datetime.now(TZ).isoformat(timespec="seconds")
        old = self._ai_session_load(user, sid) or {}
        messages = []
        for m in (session.get("messages") or [])[:500]:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "user")
            if role not in ("user", "assistant", "system", "answer"):
                role = "user"
            raw_events = m.get("events") or []
            if not raw_events and m.get("work"):
                raw_events = Handler._legacy_work_to_events(m.get("work"))
            events = []
            for ev in raw_events[:600]:
                if not isinstance(ev, dict): continue
                clean = {}
                for k, v in ev.items():
                    if isinstance(v, str): clean[str(k)] = v[:8000]
                    elif isinstance(v, (int, float, bool)) or v is None: clean[str(k)] = v
                    elif isinstance(v, (dict, list)):
                        try: clean[str(k)] = json.loads(json.dumps(v, ensure_ascii=False)[:8000])
                        except Exception: pass
                if clean: events.append(clean)
            messages.append({"role": role, "content": str(m.get("content") or m.get("text") or "")[:120000],
                             "time": m.get("time") or now,
                             "files": m.get("files") if isinstance(m.get("files"), list) else [],
                             "stopped": bool(m.get("stopped")), "events": events})
        data = {"id": sid, "title": str(session.get("title") or old.get("title") or "新对话")[:120],
                "module": str(session.get("module") or old.get("module") or "")[:40],
                "created": old.get("created") or session.get("created") or now,
                "updated": now, "messages": messages,
                "usage": session.get("usage") if isinstance(session.get("usage"), dict) else (old.get("usage") or {}),
                "context_window": int(session.get("context_window") or old.get("context_window") or 0),
                "dsh_session_id": str(session.get("dsh_session_id") or old.get("dsh_session_id") or "")[:80],
                "dsh_model": str(session.get("dsh_model") or old.get("dsh_model") or "")[:120],
                "dsh_effort": str(session.get("dsh_effort") or old.get("dsh_effort") or "")[:20],
                "needs_response": bool(session.get("needs_response", old.get("needs_response"))),
                "unread": bool(session.get("unread", old.get("unread"))),
                "archived": bool(session.get("archived", old.get("archived"))),
                "pinned": bool(session.get("pinned", old.get("pinned")))}
        path = os.path.join(self._ai_sessions_dir(user), sid + ".enc")
        enc = self._llm_fernet().encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(enc)
        os.replace(tmp, path)
        return data

    def _ai_session_delete(self, user, sid):
        sid = self._ai_session_id(sid)
        d = self._ai_session_load(user, sid)
        if not d:
            return False
        if not d.get("archived"):
            raise ProjectError("forbidden", "只能删除已归档的会话", 403)
        try:
            os.remove(os.path.join(self._ai_sessions_dir(user), sid + ".enc"))
            return True
        except Exception:
            return False

    def _ai_session_flags(self, user, sid, archived=None, pinned=None):
        d = self._ai_session_load(user, self._ai_session_id(sid))
        if not d:
            raise ProjectError("not_found", "会话不存在", 404)
        if archived is not None:
            d["archived"] = bool(archived)
            if d["archived"]:
                d["pinned"] = False
        if pinned is not None:
            d["pinned"] = bool(pinned)
            if d["pinned"]:
                d["archived"] = False
        d["updated"] = d.get("updated") or datetime.now(TZ).isoformat(timespec="seconds")
        return self._ai_session_save(user, d)

    def _ai_session_list(self, user, full=False):
        out = []
        running_ids = set()
        try:
            with DSH_RUNS_LOCK:
                for r in DSH_RUNS.values():
                    if r.get("user") == user and r.get("session_id"):
                        running_ids.add(str(r.get("session_id")))
        except Exception:
            pass
        try:
            for name in os.listdir(self._ai_sessions_dir(user)):
                if not name.endswith(".enc"):
                    continue
                d = self._ai_session_load(user, name[:-4])
                if d:
                    pub = self._ai_session_public(d, full=full)
                    pub["running"] = pub.get("id") in running_ids
                    out.append(pub)
        except Exception:
            pass
        out.sort(key=lambda x: ((0 if x.get("pinned") else 1), -(datetime.fromisoformat(x.get("updated")).timestamp() if x.get("updated") else 0)))
        return out

    # ---------------- DSH Bridge ----------------
    def _dsh_config(self):
        try:
            with open(os.path.join(self.server.root, "config", "dsh.json"), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {"enabled": False}
        except Exception:
            return {"enabled": False}

    def _dsh_status(self):
        c = self._dsh_config()
        return {"enabled": bool(c.get("enabled")), "profile": c.get("profile") or "headless",
                "command": c.get("command") or "dsh", "cwd": c.get("cwd") or self.server.root,
                "models": c.get("models") or ["deepseek-flash", "deepseek-chat"],
                "efforts": c.get("efforts") or [{"id": "low", "name": "低"}, {"id": "medium", "name": "中"}, {"id": "high", "name": "高"}],
                "model": c.get("model") or "deepseek-flash", "effort": c.get("effort") or "high",
                "context_window": int(c.get("context_window") or 1000000),
                "model_contexts": c.get("model_contexts") or {}}

    def _ai_backend_data(self, user):
        """Build a read-only, user-scoped backend data snapshot for the DSH sandbox."""
        out = {"generated_at": datetime.now(TZ).isoformat(timespec="seconds"), "user": user}
        try:
            store = self._sched_store()
            def mine(x):
                return (str(x.get("owner") or "") == user or user in (x.get("participants") or []) or user in (x.get("mentions") or []))
            out["schedule"] = {
                "meta": store.get("meta") or {}, "slots": store.get("slots") or [],
                "courses": [c for c in (store.get("courses") or []) if isinstance(c, dict) and mine(c)],
                "exams": [e for e in (store.get("exams") or []) if isinstance(e, dict) and mine(e)],
                "holidays": store.get("holidays") or [],
                "specials": [sp for sp in (store.get("specials") or []) if isinstance(sp, dict) and mine(sp)],
                "venues": store.get("venues") or [],
                "events": [e for e in (self._sched_load().get("events") or []) if self._sched_visible(user, e)],
            }
        except Exception as e:
            out["schedule"] = {"error": str(e)[:200]}
        out["projects"] = {}
        for pid, proj in (self.registry.projects or {}).items():
            if not proj or not self._can_access(user, pid):
                continue
            if pid in ("schedule",):
                continue
            try:
                rev, data = proj.state()
                text = json.dumps(data or {}, ensure_ascii=False)
                out["projects"][pid] = {"rev": rev, "data": (data or {}) if len(text) <= 120000 else {"keys": list((data or {}).keys())[:40], "note": "项目状态过大，请使用专属工具"}}
            except Exception as e:
                out["projects"][pid] = {"error": str(e)[:160]}
        out["users"] = [{"user": u, "role": (self.auth.users.get(u) or {}).get("role")} for u in sorted(self.auth.users.keys())]
        return out

    def _write_ai_sandbox_links(self, sandbox, user):
        backend = os.path.join(sandbox, "backend")
        os.makedirs(backend, exist_ok=True)
        try:
            old_snapshot = os.path.join(sandbox, "kp_backend_data.json")
            if os.path.isfile(old_snapshot): os.unlink(old_snapshot)
        except Exception:
            pass
        for role in ("owned", "participated", "mentioned"):
            target = self._sched_role_dir(user, role)
            link = os.path.join(backend, role)
            try:
                if os.path.islink(link) or os.path.isfile(link): os.unlink(link)
                elif os.path.isdir(link):
                    try: os.rmdir(link)
                    except Exception: pass
                if not os.path.exists(link):
                    try: os.symlink(target, link, target_is_directory=True)
                    except Exception:
                        try:
                            subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, timeout=10)
                        except Exception:
                            shutil.copytree(target, link, dirs_exist_ok=True)
            except Exception:
                pass
        # shared schedule data (holidays/meta/slots/venues) as a real file link
        shared = self._sched_shared_file()
        if os.path.isfile(shared):
            self._sched_link_file(shared, os.path.join(backend, "shared.json"))
        # project state docs (read-only links)
        pd = os.path.join(backend, "projects"); os.makedirs(pd, exist_ok=True)
        for pid, proj in (self.registry.projects or {}).items():
            if not proj or not self._can_access(user, pid): continue
            src = getattr(proj, "data_path", None)
            if src and os.path.isfile(src):
                self._sched_link_file(src, os.path.join(pd, pid + ".json"))

    def _write_ai_backend_data(self, sandbox, user):
        path = os.path.join(sandbox, "kp_backend_data.json")
        data = self._ai_backend_data(user)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return path

    def _dsh_stream(self, user, body):
        self._dsh_ensure_plugin()
        c = self._dsh_config()
        if not c.get("enabled"):
            raise ProjectError("bad_request", "DSH Bridge 未启用", 400)
        module = str(body.get("module") or "")[:40]
        text = str(body.get("text") or "").strip()
        if not text:
            raise ProjectError("bad_request", "消息为空", 400)
        if module:
            proj = self.registry.get(module)
            if not proj or not self._can_access(user, module):
                raise ProjectError("forbidden", "当前模块不可访问：" + module, 403)
        psid = str(body.get("platform_session_id") or "")
        session = self._ai_session_load(user, psid) if psid else None
        dsh_id = str(body.get("dsh_session_id") or (session or {}).get("dsh_session_id") or "")
        transcript = ""
        if session and not dsh_id:
            msgs = (session.get("messages") or [])[-20:]
            if msgs:
                transcript = "\n\n".join(("用户回答：" if m.get("role") == "answer" else "用户：" if m.get("role") == "user" else "AI：") + str(m.get("content") or "") for m in msgs)
        file_notes = self._dsh_file_notes(user, body.get("files") or [])
        proj = self.registry.get(module) if module else None
        title = (proj.manifest().get("title") if proj else module) or "工作台"
        prompt = ("工作目录是隔离沙箱；平台原始 data/ 和 projects/ 目录不可直接访问，但沙盒内 backend/ 是真实数据的只读链接：\n"
                  "backend/owned、backend/participated、backend/mentioned 是当前用户的事件/课程/考试/special 角色目录；\n"
                  "backend/shared.json 是共享的节假日/meta/slots/venues；backend/projects/<id>.json 是项目状态。\n"
                  "需要数据时直接读取这些真实文件，不要假设没有数据；所有写操作仍必须通过平台桥完成，不要直接改这些文件。\n\n"
                  "当前时间：%s\n当前用户：%s\n当前模块：%s（%s）\n" % (datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), user, title, module or "无"))
        prompt += ("\n工作方式：先调用 workspace_overview 或 schedule_agenda 了解真实数据，再行动；"
                   "不要只给抽象建议。工具调用会真实读写平台，回答时必须说明实际执行结果；"
                   "信息不足时先查工具，不要猜。跨模块数据可以先用通用读取工具。\n")
        snapshot = self._ai_context_snapshot(user, module)
        if snapshot:
            prompt += "\n" + snapshot + "\n"
        if transcript:
            prompt += "\n之前的对话：\n" + transcript + "\n"
        if file_notes:
            prompt += "\n" + "\n\n".join(file_notes) + "\n"
        prompt += "\n用户消息：\n" + text

        eff = self._llm_effective(user)
        env = os.environ.copy()
        if eff and eff.get("api_key"):
            env[c.get("env_key") or "DEEPSEEK_API_KEY"] = eff["api_key"]
        token = secrets.token_hex(18)
        with DSH_TOKENS_LOCK:
            DSH_TOKENS[token] = {"user": user, "module": module, "expires": time.time() + 600, "ui": []}
        sandbox = os.path.join(self.server.root, c.get("sandbox_root") or "data/dsh_workspace", re.sub(r"[^A-Za-z0-9_.-]", "_", user)[:60] or "user")
        os.makedirs(sandbox, exist_ok=True)
        try: self._write_ai_sandbox_links(sandbox, user)
        except Exception: pass
        script = os.path.join(sandbox, "dsh_tool.py")
        try:
            shutil.copyfile(os.path.join(self.server.root, "tools", "dsh_tool.py"), script)
        except Exception:
            script = os.path.join(self.server.root, "tools", "dsh_tool.py")
        ticket = os.path.join(sandbox, ".bridge_ticket")
        with open(ticket, "w", encoding="utf-8") as f: f.write(token)
        env["KP_BRIDGE_URL"] = "http://127.0.0.1:%d" % int(self.server.server_address[1])
        env["KP_BRIDGE_MODULE"] = module or ""
        env["KP_BRIDGE_TICKET"] = ticket
        self._dsh_sync_skills(user, sandbox)
        skill_prompt = self._dsh_skill_prompt(user)
        if skill_prompt:
            prompt = prompt + "\n\n" + skill_prompt
        image_notes = self._dsh_image_notes(user, body.get("files") or [], sandbox)
        if image_notes:
            prompt += "\n" + "\n".join(image_notes) + "\n"
        model = str(body.get("model") or c.get("model") or "deepseek-flash")[:120]
        effort = str(body.get("effort") or c.get("effort") or "high")[:20]
        patch = os.path.join(sandbox, "model_patch.yml")
        with open(patch, "w", encoding="utf-8") as f:
            f.write("- id: agent-default-model\n  config:\n    provider: deepseek-official\n    model: %s\n    reasoningEffort: %s\n- id: user-questions\n  disabled: true\n- insert:\n    - id: kittenpuppy-stream-delta\n      name: '@kittenpuppy/dsh-stream-delta'\n- id: compaction-basic\n  config:\n    thresholdRatio: 0.9\n    retainRatio: 0.2\n" % (model, effort))
        prompt = "DSH 模型：%s · effort：%s\n\n%s" % (model, effort, prompt)
        prompt += "\n\n如果你需要用户回答或选择，请在最终回复末尾单独输出一行：\n"
        prompt += 'ASK_USER {"question":"向用户提出的问题","multiple":false,"options":["选项1","选项2"]}\n'
        prompt += "multiple 为 true 表示多选，false 表示单选；不要自行假设用户的选择。\n"
        tool_prompt = self._dsh_tool_prompt(module, script)
        if tool_prompt: prompt += "\n\n" + tool_prompt
        argv = [c.get("command") or "dsh", "--profile", c.get("profile") or "headless", "--patch", patch, "--json"]
        if dsh_id: argv += ["--session-id", dsh_id]
        argv += ["-"]
        run_id = secrets.token_hex(12)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        def sse(obj):
            try:
                self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass
        sse({"type": "run", "run_id": run_id})
        proc = None
        try:
            proc = subprocess.Popen(argv, cwd=sandbox, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", shell=True)
            timer = threading.Timer(int(c.get("timeout") or 240), lambda: proc.kill())
            timer.daemon = True; timer.start()
            with DSH_RUNS_LOCK:
                DSH_RUNS[run_id] = {"user": user, "proc": proc, "started": time.time(), "session_id": psid}
            proc.stdin.write(prompt); proc.stdin.close()
            session_id, texts, final_text, usage = "", [], "", {}
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("{"): continue
                try: ev = json.loads(line)
                except Exception: continue
                t = ev.get("type")
                if t == "session": session_id = str(ev.get("sessionId") or session_id)
                elif t == "text": texts.append(str(ev.get("text") or ""))
                elif t == "final" and ev.get("text") is not None: final_text = str(ev.get("text"))
                elif t == "status" and isinstance(ev.get("usage"), dict): usage = ev["usage"]
                sse(ev)
            reply = final_text or "".join(texts)
            with DSH_TOKENS_LOCK:
                ui_events = (DSH_TOKENS.pop(token, {}) or {}).get("ui") or []
            sse({"type": "done", "reply": reply, "dsh_session_id": session_id, "ui_events": ui_events,
                 "model": model, "effort": effort, "context_window": int(c.get("context_window") or 1000000),
                 "usage": {"prompt_tokens": int(usage.get("inputTokens") or 0),
                           "completion_tokens": int(usage.get("outputTokens") or 0),
                           "total_tokens": int(usage.get("totalTokens") or 0)}})
        except Exception as e:
            sse({"type": "error", "message": str(e)[:500]})
        finally:
            try:
                if proc and proc.poll() is None: proc.kill()
            except Exception: pass
            try: timer.cancel()
            except Exception: pass
            try: os.remove(ticket)
            except Exception: pass
            try: os.remove(patch)
            except Exception: pass
            try: shutil.rmtree(os.path.join(sandbox, "attachments"), ignore_errors=True)
            except Exception: pass
            with DSH_TOKENS_LOCK:
                DSH_TOKENS.pop(token, None)
            with DSH_RUNS_LOCK:
                DSH_RUNS.pop(run_id, None)

    def _mineru_config(self):
        try:
            path = os.path.join(self.server.root, "data", "mineru.json.enc")
            with open(path, "rb") as f:
                raw = self._llm_fernet().decrypt(f.read())
            d = json.loads(raw.decode("utf-8"))
        except Exception:
            d = {}
        if os.environ.get("MINERU_TOKEN"):
            d["token"] = os.environ["MINERU_TOKEN"]
        return d if isinstance(d, dict) else {}

    def _mineru_public(self):
        cfg = self._mineru_config()
        tok = str(cfg.get("token") or "")
        masked = (tok[:4] + "…" + tok[-4:]) if len(tok) >= 8 else ("已配置" if tok else "")
        now = datetime.now(TZ)
        expires = cfg.get("expires_at") or ""
        days_left = None
        if expires:
            try:
                dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                if dt.tzinfo is None: dt = dt.replace(tzinfo=TZ)
                days_left = (dt - now).days
            except Exception:
                days_left = None
        return {"configured": bool(tok), "token_masked": masked,
                "base_url": cfg.get("base_url") or "https://mineru.net/api/v4",
                "model_version": cfg.get("model_version") or "vlm",
                "created_at": cfg.get("created_at") or "",
                "expires_at": expires, "days_left": days_left}

    def _mineru_save(self, token=None, clear=False):
        cfg = self._mineru_config()
        old_token = str(cfg.get("token") or "")
        if clear:
            cfg.pop("token", None)
            cfg.pop("created_at", None); cfg.pop("expires_at", None)
        elif token is not None:
            tok = str(token).strip()
            if tok and (tok != old_token or not cfg.get("expires_at")):
                now = datetime.now(TZ)
                cfg.setdefault("created_at", now.isoformat(timespec="seconds"))
                cfg["expires_at"] = (now + timedelta(days=90)).isoformat(timespec="seconds")
            cfg["token"] = tok
        cfg.setdefault("base_url", "https://mineru.net/api/v4")
        cfg.setdefault("model_version", "vlm")
        cfg.setdefault("timeout", 240)
        path = os.path.join(self.server.root, "data", "mineru.json.enc")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        enc = self._llm_fernet().encrypt(json.dumps(cfg, ensure_ascii=False).encode("utf-8"))
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(enc)
        os.replace(tmp, path)
        return cfg

    def _mineru_check(self, token=None):
        cfg = self._mineru_config()
        tok = str(token or cfg.get("token") or "").strip()
        if not tok:
            return {"valid": False, "message": "未配置 MinerU Token"}
        import requests
        try:
            r = requests.get("https://mineru.net/api/v4/application/status",
                             headers={"Authorization": "Bearer " + tok}, timeout=30)
            text = r.text[:300]
            invalid = r.status_code == 401 or "A0202" in text or "A0211" in text
            valid = not invalid and r.status_code < 500
            msg = "Token 有效" if valid else "Token 无效或已过期"
        except Exception as e:
            return {"valid": False, "message": "检查失败：" + str(e)[:120]}
        pub = self._mineru_public()
        if token and token != str(cfg.get("token") or ""):
            pub = {"configured": True, "days_left": 90, "expires_at": (datetime.now(TZ) + timedelta(days=90)).isoformat(timespec="seconds")}
        return {"valid": valid, "message": msg, "expires_at": pub.get("expires_at") or "",
                "days_left": pub.get("days_left"), "checked_at": datetime.now(TZ).isoformat(timespec="seconds")}

    def _mineru_parse_pdf(self, name, raw):
        cfg = self._mineru_config()
        token = str(cfg.get("token") or "").strip()
        if not token or len(raw) > 200 * 1024 * 1024:
            return ""
        import urllib.request as _ur
        import zipfile
        base = str(cfg.get("base_url") or "https://mineru.net/api/v4").rstrip("/")
        model = str(cfg.get("model_version") or "vlm")
        timeout = int(cfg.get("timeout") or 240)
        sha = hashlib.sha256(raw).hexdigest()
        cache_dir = os.path.join(self.server.root, "data", "mineru_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache = os.path.join(cache_dir, sha + ".md")
        try:
            if os.path.isfile(cache):
                with open(cache, encoding="utf-8") as f:
                    return f.read()[:120000]
        except Exception:
            pass
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        def post_json(url, obj):
            req = _ur.Request(url, data=json.dumps(obj, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
            with _ur.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        def get_json(url):
            req = _ur.Request(url, headers={"Authorization": "Bearer " + token}, method="GET")
            with _ur.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        envelope = lambda r: r.get("data") if isinstance(r, dict) and r.get("code") == 0 else None
        data_id = "kp-" + sha[:20]
        try:
            batch = post_json(base + "/file-urls/batch", {
                "files": [{"name": name, "data_id": data_id}],
                "model_version": model, "is_ocr": True,
                "enable_formula": True, "enable_table": True})
            bd = envelope(batch)
            if not bd: return ""
            batch_id = str(bd.get("batch_id") or "")
            urls = bd.get("file_urls") or []
            if not batch_id or not urls: return ""
            import requests
            put = requests.put(urls[0], data=raw, timeout=timeout)
            put.raise_for_status()
            deadline = time.time() + timeout
            result = None
            while time.time() < deadline:
                time.sleep(3)
                res = get_json(base + "/extract-results/batch/" + quote(batch_id))
                rd = envelope(res)
                if not rd: continue
                items = rd.get("extract_result") or []
                if items:
                    item = items[0]
                    state = str(item.get("state") or "")
                    if state == "done":
                        result = item; break
                    if state == "failed":
                        return ""
            if not result: return ""
            zip_url = str(result.get("full_zip_url") or "")
            if not zip_url: return ""
            req = _ur.Request(zip_url, headers={"Authorization": "Bearer " + token})
            with _ur.urlopen(req, timeout=timeout) as r:
                zdata = r.read()
            with zipfile.ZipFile(io.BytesIO(zdata)) as z:
                names = [n for n in z.namelist() if n.lower().endswith(".md")]
                if not names: return ""
                names.sort(key=lambda n: (0 if n.lower().endswith("full.md") else 1, len(n)))
                text = z.read(names[0]).decode("utf-8", "replace")
            with open(cache, "w", encoding="utf-8") as f:
                f.write(text)
            return text[:120000]
        except Exception:
            return ""

    @staticmethod
    def _mineru_note(name, text):
        return "PDF 附件《%s》MinerU 解析内容：\n%s" % (name, text[:20000])

    def _ai_file_note(self, item, raw):
        name = str(item.get("name") or "file")
        mime = str(item.get("mime") or "")
        ext = os.path.splitext(name)[1].lower()
        text_ext = (".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".xml", ".log", ".tex")
        try:
            if mime.startswith("image/"):
                return "图片附件《%s》已上传（%s，%d 字节）；当前 DSH headless 文本桥不解析图像内容。" % (name, mime, len(raw))
            if ext == ".pdf" or mime == "application/pdf":
                mined = self._mineru_parse_pdf(name, raw)
                if mined:
                    return self._mineru_note(name, mined)
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(raw))
                pages = []
                for page in reader.pages[:30]:
                    pages.append(page.extract_text() or "")
                return "PDF 附件《%s》内容：\n%s" % (name, ("\n".join(pages))[:20000])
            if ext == ".docx" or "wordprocessingml" in mime:
                import docx
                d = docx.Document(io.BytesIO(raw))
                return "Word 附件《%s》内容：\n%s" % (name, ("\n".join(p.text for p in d.paragraphs if p.text))[:20000])
            if ext in (".xlsx", ".xlsm") or "spreadsheetml" in mime:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                rows = []
                for ws in wb.worksheets:
                    rows.append("[%s]" % ws.title)
                    for row in ws.iter_rows(max_row=200, values_only=True):
                        vals = [str(v) for v in row if v is not None]
                        if vals: rows.append(" | ".join(vals))
                return "表格附件《%s》内容：\n%s" % (name, ("\n".join(rows))[:20000])
            if mime.startswith("text/") or ext in text_ext:
                return "附件《%s》内容：\n%s" % (name, raw.decode("utf-8", "replace")[:20000])
            return "附件《%s》为二进制文件（%s，%d 字节），未解析内容。" % (name, mime or "未知类型", len(raw))
        except Exception as e:
            return "附件《%s》解析失败（%s），原始大小 %d 字节。" % (name, str(e)[:120], len(raw))

    def _dsh_image_notes(self, user, ids, sandbox):
        notes = []
        img_ext = (".png", ".jpg", ".jpeg", ".webp", ".gif")
        for fid in (ids or [])[:6]:
            item = next((x for x in self._files_index().get("files") or [] if x.get("id") == str(fid) and x.get("owner") == user), None)
            if not item: continue
            ext = os.path.splitext(item.get("name") or "")[1].lower()
            if not (str(item.get("mime") or "").startswith("image/") or ext in img_ext): continue
            try:
                with open(os.path.join(self._files_root(), item.get("stored") or ""), "rb") as ff:
                    raw = self._files_fernet().decrypt(ff.read())
                adir = os.path.join(sandbox, "attachments"); os.makedirs(adir, exist_ok=True)
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", item.get("name") or ("image" + ext))[:100]
                pth = os.path.join(adir, safe)
                with open(pth, "wb") as out: out.write(raw)
                notes.append("图片附件《%s》已解密到沙箱路径：%s。请使用 read_image 工具读取并理解图片内容。" % (item.get("name"), pth))
            except Exception:
                pass
        return notes

    def _dsh_file_notes(self, user, ids):
        notes = []
        for fid in (ids or [])[:6]:
            item = next((x for x in self._files_index().get("files") or [] if x.get("id") == str(fid) and x.get("owner") == user), None)
            if not item: continue
            try:
                with open(os.path.join(self._files_root(), item.get("stored") or ""), "rb") as ff:
                    raw = self._files_fernet().decrypt(ff.read())
                notes.append(self._ai_file_note(item, raw))
            except Exception:
                pass
        return notes

    def _dsh_tool_prompt(self, module, script=None):
        defs = self._ai_tool_defs(module)
        if not defs:
            return ""
        script = script or os.path.join(self.server.root, "tools", "dsh_tool.py")
        py = getattr(self.server, "python_exe", None) or sys.executable
        lines = ["你可以调用平台模块桥来完成当前模块的事务（这是唯一允许的模块写操作方式，不要直接修改 data 文件）：",
                 '"%s" "%s" --tool <工具名> --args-json "<JSON参数>"' % (py, script),
                 "工具返回 JSON；根据结果继续回答。可用工具："]
        for d in defs:
            lines.append("- %s：%s 参数=%s" % (d["name"], d["description"], json.dumps(d["parameters"], ensure_ascii=False)))
        if module == "schedule":
            lines.append("地点流程：先用 map_place_search 搜索（尽量带中心 lat/lng，返回距离最近的匹配）；"
                         "再用 schedule_place_create 建地点；用 schedule_create/schedule_update 的 place + placeCode 绑定；"
                         "解绑先 place=''、placeCode=''；删除地点前必须先解绑，否则会被拒绝。")
        return "\n".join(lines)

    def _dsh_ensure_plugin(self):
        try:
            src = os.path.join(self.server.root, "dsh_plugins", "stream-delta")
            home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
            dst = os.path.join(home, "profiles", "headless", "node_modules", "@kittenpuppy", "dsh-stream-delta")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            for f in ("package.json", "index.js"):
                a, b = os.path.join(src, f), os.path.join(dst, f)
                if not os.path.isfile(b) or os.path.getmtime(a) > os.path.getmtime(b):
                    shutil.copyfile(a, b)
        except Exception:
            pass

    def _dsh_run(self, user, module, prompt, dsh_session_id="", model="", effort=""):
        self._dsh_ensure_plugin()
        c = self._dsh_config()
        if not c.get("enabled"):
            raise ProjectError("bad_request", "DSH Bridge 未启用", 400)
        eff = self._llm_effective(user)
        key = (eff or {}).get("api_key") or ""
        env = os.environ.copy()
        env_key = c.get("env_key") or "DEEPSEEK_API_KEY"
        if key:
            env[env_key] = key
        cmd = str(c.get("command") or "dsh")
        profile = str(c.get("profile") or "headless")
        token = secrets.token_hex(18)
        sandbox_root = str(c.get("sandbox_root") or "")
        if sandbox_root:
            safe_user = re.sub(r"[^A-Za-z0-9_.-]", "_", user)[:60] or "user"
            cwd = os.path.join(self.server.root, sandbox_root, safe_user)
            os.makedirs(cwd, exist_ok=True)
        else:
            cwd = str(c.get("cwd") or self.server.root)
        try: self._write_ai_sandbox_links(cwd, user)
        except Exception: pass
        self._dsh_sync_skills(user, cwd)
        skill_prompt = self._dsh_skill_prompt(user)
        if skill_prompt:
            prompt = prompt + "\n\n" + skill_prompt
        now = time.time()
        with DSH_TOKENS_LOCK:
            DSH_TOKENS[token] = {"user": user, "module": module, "expires": now + 600, "ui": []}
        bridge_url = "http://127.0.0.1:%d" % int(self.server.server_address[1])
        env["KP_BRIDGE_URL"] = bridge_url
        env["KP_BRIDGE_MODULE"] = module or ""
        real_script = os.path.join(self.server.root, "tools", "dsh_tool.py")
        if sandbox_root:
            script_path = os.path.join(cwd, "dsh_tool.py")
            try:
                shutil.copyfile(real_script, script_path)
            except Exception:
                script_path = real_script
            ticket_file = os.path.join(cwd, ".bridge_ticket")
        else:
            script_path = real_script
            ticket_dir = os.path.join(self.server.root, "data", "dsh_bridge")
            os.makedirs(ticket_dir, exist_ok=True)
            ticket_file = os.path.join(ticket_dir, token + ".txt")
        with open(ticket_file, "w", encoding="utf-8") as tf:
            tf.write(token)
        try:
            os.chmod(ticket_file, 0o600)
        except Exception:
            pass
        env["KP_BRIDGE_TICKET"] = ticket_file
        prompt = ("工作目录是隔离沙箱；不要直接读取或修改平台 data/ 或 projects/ 下的文件。\n"
                  "所有当前模块的写操作必须通过下面的平台桥命令完成。\n\n" + prompt)
        prompt += "\n\n如果你需要用户回答或选择，请在最终回复末尾单独输出一行：\n"
        prompt += 'ASK_USER {"question":"向用户提出的问题","multiple":false,"options":["选项1","选项2"]}\n'
        prompt += "multiple 为 true 表示多选，false 表示单选；不要自行假设用户的选择。\n"
        tool_prompt = self._dsh_tool_prompt(module, script_path)
        if tool_prompt:
            prompt = prompt + "\n\n" + tool_prompt
        chosen_model = str(model or c.get("model") or "deepseek-flash")[:120]
        chosen_effort = str(effort or c.get("effort") or "medium")[:20]
        patch_file = os.path.join(cwd, "model_patch.yml")
        try:
            with open(patch_file, "w", encoding="utf-8") as pf:
                pf.write("- id: agent-default-model\n  config:\n    provider: deepseek-official\n    model: %s\n    reasoningEffort: %s\n- id: user-questions\n  disabled: true\n- insert:\n    - id: kittenpuppy-stream-delta\n      name: '@kittenpuppy/dsh-stream-delta'\n- id: compaction-basic\n  config:\n    thresholdRatio: 0.9\n    retainRatio: 0.2\n" % (chosen_model, chosen_effort))
        except Exception:
            patch_file = ""
        prompt = "DSH 模型：%s · effort：%s\n\n%s" % (chosen_model, chosen_effort, prompt)
        argv = [cmd, "--profile", profile]
        if patch_file:
            argv += ["--patch", patch_file]
        argv += ["--json"]
        if dsh_session_id:
            argv += ["--session-id", dsh_session_id]
        argv += ["-"]
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", shell=True)
            out, err = proc.communicate(prompt, timeout=int(c.get("timeout") or 240))
        except subprocess.TimeoutExpired:
            try: proc.kill()
            except Exception: pass
            raise ProjectError("upstream_error", "DSH 执行超时", 504)
        except Exception as e:
            raise ProjectError("upstream_error", "DSH 启动失败：%s" % e, 502)
        events, session_id, texts, final_text = [], "", [], ""
        usage = {}
        for line in (out or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            events.append(ev)
            if ev.get("type") == "session" and ev.get("sessionId"):
                session_id = str(ev.get("sessionId"))
            elif ev.get("type") == "text" and ev.get("text"):
                texts.append(str(ev.get("text")))
            elif ev.get("type") == "final" and ev.get("text") is not None:
                final_text = str(ev.get("text"))
            elif ev.get("type") == "status" and isinstance(ev.get("usage"), dict):
                usage = ev.get("usage")
        reply = final_text or "".join(texts)
        with DSH_TOKENS_LOCK:
            ui_events = (DSH_TOKENS.pop(token, {}) or {}).get("ui") or []
        try:
            os.remove(ticket_file)
        except Exception:
            pass
        if proc.returncode != 0 and not reply:
            msg = (err or out or "").strip().splitlines()[-3:]
            raise ProjectError("upstream_error", "DSH 执行失败：" + " ".join(msg)[:500], 502)
        try:
            os.remove(patch_file)
        except Exception:
            pass
        return {"reply": reply, "dsh_session_id": session_id, "events": events[-200:],
                "model": chosen_model, "effort": chosen_effort,
                "context_window": int(c.get("context_window") or 128000),
                "usage": {"prompt_tokens": int(usage.get("inputTokens") or 0),
                          "completion_tokens": int(usage.get("outputTokens") or 0),
                          "total_tokens": int(usage.get("totalTokens") or 0),
                          "context_window": 0},
                "ui_events": ui_events, "module": module}

    # ---------------- Platform Skill 管理 ----------------
    def _ai_skill_roots(self):
        roots = self._dsh_config().get("skill_roots") or []
        if not roots:
            roots = [os.path.join(self.server.root, "skills"),
                     os.path.join(os.path.expanduser("~"), ".agents", "skills"),
                     os.path.join(os.path.expanduser("~"), ".dsh", "skills")]
        out = []
        for r in roots:
            r = str(r)
            if r and os.path.isdir(r) and r not in out:
                out.append(r)
        return out

    @staticmethod
    def _ai_skill_meta(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read(12000)
        except Exception:
            return None
        name = os.path.basename(os.path.dirname(path)) if os.path.basename(path) == "SKILL.md" else os.path.splitext(os.path.basename(path))[0]
        desc = ""
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" not in line: continue
                k, v = line.split(":", 1)
                k, v = k.strip().lower(), v.strip().strip('"').strip("'")
                if k == "name" and v: name = v
                elif k == "description" and v: desc = v
        return {"name": name, "description": desc or name, "path": path,
                "source": os.path.basename(os.path.dirname(path)) or "local"}

    def _ai_skill_catalog(self, user=None):
        entries = {}
        for root in self._ai_skill_roots():
            try:
                children = sorted(os.listdir(root))
            except Exception:
                continue
            for child in children:
                if child.startswith("."): continue
                p = os.path.join(root, child)
                target = os.path.join(p, "SKILL.md") if os.path.isdir(p) else (p if p.lower().endswith(".md") else None)
                if not target or not os.path.isfile(target): continue
                meta = self._ai_skill_meta(target)
                if not meta: continue
                meta["source"] = os.path.basename(root)
                entries.setdefault(meta["name"], meta)
        enabled = set(self._ai_skills_enabled(user)) if user else set()
        out = []
        for name, meta in entries.items():
            item = dict(meta); item["enabled"] = name in enabled
            out.append(item)
        out.sort(key=lambda x: x["name"].lower())
        return out

    def _ai_skills_file(self):
        return os.path.join(self.server.root, "data", "ai_skills.json")

    def _ai_skills_load(self):
        try:
            with open(self._ai_skills_file(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {"users": {}}
        except Exception:
            return {"users": {}}

    def _ai_skills_enabled(self, user):
        d = self._ai_skills_load()
        vals = (d.get("users") or {}).get(user) or []
        return [str(x) for x in vals if isinstance(x, str)]

    def _ai_skill_toggle(self, user, name, enabled):
        d = self._ai_skills_load()
        users = d.setdefault("users", {})
        vals = set(users.get(user) or [])
        if enabled: vals.add(name)
        else: vals.discard(name)
        users[user] = sorted(vals)
        tmp = self._ai_skills_file() + ".tmp"
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._ai_skills_file())
        return users[user]

    def _dsh_sync_skills(self, user, sandbox):
        dest = os.path.join(sandbox, ".agents", "skills")
        try:
            if os.path.isdir(dest): shutil.rmtree(dest)
            os.makedirs(dest, exist_ok=True)
            by_name = {x["name"]: x for x in self._ai_skill_catalog(user)}
            for name in self._ai_skills_enabled(user):
                meta = by_name.get(name)
                if not meta: continue
                src = meta["path"]
                base = name if re.match(r"^[A-Za-z0-9_.-]+$", name) else re.sub(r"[^A-Za-z0-9_.-]", "_", name)
                if os.path.basename(src) == "SKILL.md":
                    shutil.copytree(os.path.dirname(src), os.path.join(dest, base))
                else:
                    shutil.copyfile(src, os.path.join(dest, base + ".md"))
        except Exception:
            pass

    def _dsh_skill_prompt(self, user):
        enabled = self._ai_skills_enabled(user)
        if not enabled:
            return ""
        cat = {x["name"]: x for x in self._ai_skill_catalog(user)}
        lines = ["已启用的 skills："]
        for n in enabled:
            meta = cat.get(n) or {}
            lines.append("- %s：%s" % (n, meta.get("description") or ""))
        lines.append("需要时使用 skill 工具加载对应 skill；不要假设未启用的 skill 可用。")
        return "\n".join(lines)

    def _ai_context_snapshot(self, user, module=""):
        try:
            store = self._sched_store()
            def mine(x):
                return (str(x.get("owner") or "") == user or user in (x.get("participants") or []) or user in (x.get("mentions") or []))
            courses = [c for c in (store.get("courses") or []) if isinstance(c, dict) and mine(c)]
            exams = [e for e in (store.get("exams") or []) if isinstance(e, dict) and mine(e)]
            events = [e for e in (self._sched_load().get("events") or []) if self._sched_visible(user, e)]
            today = datetime.now(TZ).date(); end = today + timedelta(days=14)
            upcoming = []
            for e in events:
                try: d = datetime.strptime(str(e.get("date")), "%Y-%m-%d").date()
                except Exception: continue
                if today <= d <= end: upcoming.append(e)
            upcoming.sort(key=lambda e: (e.get("date") or "", e.get("startMin") or 0))
            lines = ["【自动数据快照（每次请求注入，不需要用户重复提供）】",
                     "日程：未来14天 %d 条；课程：%d 门；考试：%d 场；节假日：%d 个。" % (len(upcoming), len(courses), len(exams), len(store.get("holidays") or []))]
            if upcoming:
                lines.append("近期日程：" + "；".join("%s %s %s" % (e.get("date"), e.get("title") or "", (e.get("place") or "")) for e in upcoming[:8]))
            if courses:
                lines.append("课程：" + "、".join("%s(%s)" % (c.get("code"), c.get("cn") or c.get("name") or "") for c in courses[:16]))
            if exams:
                lines.append("考试：" + "、".join("%s %s %s" % (e.get("course"), e.get("date"), e.get("time") or "") for e in exams[:10]))
            try:
                rev, pad = self.registry.get("scratchpad").state(); pads = (pad or {}).get("items") or []
                lines.append("临时便签：%d 条。" % len(pads))
            except Exception: pass
            try:
                rev, wp = self.registry.get("wishpool").state(); wishes = (wp or {}).get("wishes") or (wp or {}).get("items") or []
                lines.append("许愿池：%d 个愿望，待处理 %d 个。" % (len(wishes), len([w for w in wishes if w.get("status") == "pending"])))
            except Exception: pass
            return "\n".join(lines)
        except Exception:
            return ""

    # ---------------- AI 模块工具 ----------------    # ---------------- AI 模块工具 ----------------
    AI_TOOL_DEFS = {
        "scratchpad": [
            {"name": "scratchpad_append", "description": "在临时便签中新增一条便签",
             "parameters": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}},
            {"name": "scratchpad_list", "description": "读取当前便签列表",
             "parameters": {"type": "object", "properties": {}}},
        ],
        "schedule": [
            {"name": "schedule_create", "description": "新增一条个人日程；时间用 HH:MM",
             "parameters": {"type": "object", "properties": {
                 "title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
                 "start": {"type": "string", "description": "HH:MM"}, "end": {"type": "string", "description": "HH:MM"},
                 "place": {"type": "string"}, "placeCode": {"type": "string"}, "note": {"type": "string"}}, "required": ["title", "date", "start", "end"]}},
            {"name": "schedule_list", "description": "读取当前用户可见的日程",
             "parameters": {"type": "object", "properties": {"date": {"type": "string"}}}},
            {"name": "schedule_update", "description": "更新日程；id 必填，其余字段可只传要改的；时间用 HH:MM",
             "parameters": {"type": "object", "properties": {
                 "id": {"type": "string"},
                 "title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
                 "endDate": {"type": "string", "description": "YYYY-MM-DD"},
                 "start": {"type": "string", "description": "HH:MM"}, "end": {"type": "string", "description": "HH:MM"},
                 "startMin": {"type": "integer"}, "endMin": {"type": "integer"},
                 "tag": {"type": "string"}, "place": {"type": "string"}, "placeCode": {"type": "string"},
                 "note": {"type": "string"}, "reminders": {"type": "array"},
                 "mentions": {"type": "array", "items": {"type": "string"}},
                 "participants": {"type": "array", "items": {"type": "string"}}}, "required": ["id"]}},
            {"name": "schedule_delete", "description": "删除自己创建的日程",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
            {"name": "map_place_search", "description": "在高德地图搜索地点，返回距离指定中心最近的候选（坐标为 WGS84）",
             "parameters": {"type": "object", "properties": {
                 "keywords": {"type": "string"}, "city": {"type": "string"},
                 "lat": {"type": "number"}, "lng": {"type": "number"}, "limit": {"type": "integer"}},
                 "required": ["keywords"]}},
            {"name": "schedule_place_list", "description": "读取日程地点列表",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "schedule_place_create", "description": "新增一个日程地点",
             "parameters": {"type": "object", "properties": {
                 "name": {"type": "string"}, "short": {"type": "string"},
                 "address": {"type": "string"}, "note": {"type": "string"},
                 "lat": {"type": "number"}, "lng": {"type": "number"},
                 "code": {"type": "string"}}, "required": ["name"]}},
            {"name": "schedule_place_update", "description": "修改一个地点；传 id/code/name 定位，可改所有字段",
             "parameters": {"type": "object", "properties": {
                 "id": {"type": "string"}, "code": {"type": "string"}, "name": {"type": "string"},
                 "short": {"type": "string"}, "address": {"type": "string"},
                 "note": {"type": "string"}, "lat": {"type": "number"}, "lng": {"type": "number"}},
                 "required": []}},
            {"name": "schedule_place_delete", "description": "删除一个地点，并清理日程中的引用",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "code": {"type": "string"}, "name": {"type": "string"}}, "required": []}},
            {"name": "schedule_course_list", "description": "读取现有课程（静态课程 + AI 自定义课程）",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "schedule_course_create", "description": "新增一门课程（自定义课程，会进入课程表与周日程）",
             "parameters": {"type": "object", "properties": {
                 "code": {"type": "string", "description": "课程代码，如 NEW101"},
                 "name": {"type": "string"}, "cn": {"type": "string"},
                 "module": {"type": "string", "description": "M1/M2/跨模块"},
                 "credit": {"type": "integer"}, "prof": {"type": "string"}, "prof_en": {"type": "string"},
                 "venues": {"type": "string"}, "color": {"type": "string"},
                 "schedule": {"type": "array", "description": "上课时间：[{weeks:[1,2],day:0-6,slot:1-11,span:1,venue:'',note:''}]"},
                 "exams": {"type": "array", "description": "可选考试：[{date:'YYYY-MM-DD',time:'HH:MM',week:1,venue:''}]"},
                 "participants": {"type": "array", "items": {"type": "string"}},
                 "mentions": {"type": "array", "items": {"type": "string"}}},
                 "required": ["code", "name", "schedule"]}},
            {"name": "schedule_course_update", "description": "修改 AI 创建的自定义课程；code 定位且不可改",
             "parameters": {"type": "object", "properties": {
                 "code": {"type": "string"}, "name": {"type": "string"}, "cn": {"type": "string"},
                 "module": {"type": "string"}, "credit": {"type": "integer"},
                 "prof": {"type": "string"}, "prof_en": {"type": "string"},
                 "venues": {"type": "string"}, "color": {"type": "string"},
                 "schedule": {"type": "array"}, "exams": {"type": "array"},
                 "participants": {"type": "array"}, "mentions": {"type": "array"}}, "required": ["code"]}},
            {"name": "schedule_course_delete", "description": "删除任意课程及其考试/特殊安排",
             "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
            {"name": "schedule_course_refresh", "description": "刷新 AI 抽屉之外的全部模块内容（不重载 AI 抽屉/页面）",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "schedule_refresh", "description": "刷新 AI 抽屉之外的全部模块内容（不重载 AI 抽屉/页面）",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "schedule_exam_list", "description": "读取考试列表",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "schedule_exam_create", "description": "新增考试",
             "parameters": {"type": "object", "properties": {
                 "course": {"type": "string"}, "cn": {"type": "string"}, "date": {"type": "string"},
                 "time": {"type": "string"}, "week": {"type": "integer"}, "venue": {"type": "string"},
                 "participants": {"type": "array"}, "mentions": {"type": "array"}},
                 "required": ["course", "date"]}},
            {"name": "schedule_exam_update", "description": "修改考试，按 id 或 course+date 定位",
             "parameters": {"type": "object", "properties": {
                 "id": {"type": "string"}, "course": {"type": "string"}, "cn": {"type": "string"},
                 "date": {"type": "string"}, "time": {"type": "string"}, "week": {"type": "integer"}, "venue": {"type": "string"},
                 "participants": {"type": "array"}, "mentions": {"type": "array"}}}},
            {"name": "schedule_exam_delete", "description": "删除考试，按 id 或 course+date 定位",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "course": {"type": "string"}, "date": {"type": "string"}}}},
            {"name": "schedule_holiday_list", "description": "读取节假日列表",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "schedule_holiday_create", "description": "新增节假日",
             "parameters": {"type": "object", "properties": {
                 "name": {"type": "string"}, "en": {"type": "string"},
                 "weeks": {"type": "array"}, "days": {"type": "array"}, "dates": {"type": "array"}},
                 "required": ["name"]}},
            {"name": "schedule_holiday_update", "description": "修改节假日，按 id 或 name 定位",
             "parameters": {"type": "object", "properties": {
                 "id": {"type": "string"}, "name": {"type": "string"}, "en": {"type": "string"},
                 "weeks": {"type": "array"}, "days": {"type": "array"}, "dates": {"type": "array"}}}},
            {"name": "schedule_holiday_delete", "description": "删除节假日，按 id 或 name 定位",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}}},
            {"name": "schedule_special_list", "description": "读取特殊安排（不对齐课节的课程/考试/CARE 等）",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "schedule_special_create", "description": "新增特殊安排（不一定是课程相关）",
             "parameters": {"type": "object", "properties": {
                 "title": {"type": "string"}, "tag": {"type": "string"}, "code": {"type": "string"}, "course": {"type": "string"},
                 "weeks": {"type": "array"}, "day": {"type": "integer"},
                 "start": {"type": "integer"}, "end": {"type": "integer"},
                 "venue": {"type": "string"}, "note": {"type": "string"}, "isExam": {"type": "boolean"},
                 "participants": {"type": "array"}, "mentions": {"type": "array"}},
                 "required": ["title", "weeks", "day", "start", "end"]}},
            {"name": "schedule_special_update", "description": "修改特殊安排，按 id 或 code+weeks/day/start 定位",
             "parameters": {"type": "object", "properties": {
                 "id": {"type": "string"}, "code": {"type": "string"}, "title": {"type": "string"},
                 "weeks": {"type": "array"}, "day": {"type": "integer"}, "start": {"type": "integer"}, "end": {"type": "integer"},
                 "venue": {"type": "string"}, "note": {"type": "string"}, "isExam": {"type": "boolean"},
                 "participants": {"type": "array"}, "mentions": {"type": "array"}}}},
            {"name": "schedule_special_delete", "description": "删除特殊安排，按 id 定位或 code+weeks/day/start",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "code": {"type": "string"}, "weeks": {"type": "array"}, "day": {"type": "integer"}, "start": {"type": "integer"}}}},
        ],
        "wishpool": [
            {"name": "wishpool_list", "description": "读取许愿池愿望列表",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "wishpool_create", "description": "新增一个愿望",
             "parameters": {"type": "object", "properties": {
                 "title": {"type": "string"}, "coins": {"type": "integer"}, "dueDate": {"type": "string"}}, "required": ["title"]}},
            {"name": "wishpool_approve", "description": "通过一个愿望（需要维护权限）",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
            {"name": "wishpool_reject", "description": "拒绝一个愿望（需要维护权限）",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        ],
    }

    AI_UNIVERSAL_TOOL_DEFS = [
        {"name": "workspace_overview", "description": "读取当前用户/当前模块的全局概览：日程、课程、考试、便签、许愿池",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "schedule_list", "description": "跨模块读取个人日程",
         "parameters": {"type": "object", "properties": {"date": {"type": "string"}}}},
        {"name": "schedule_create", "description": "跨模块新增个人日程；时间用 HH:MM",
         "parameters": {"type": "object", "properties": {
             "title": {"type": "string"}, "date": {"type": "string"}, "start": {"type": "string"},
             "end": {"type": "string"}, "place": {"type": "string"}, "note": {"type": "string"}},
             "required": ["title", "date", "start", "end"]}},
        {"name": "schedule_update", "description": "跨模块更新日程，id 必填",
         "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "title": {"type": "string"},
             "date": {"type": "string"}, "endDate": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
             "startMin": {"type": "integer"}, "endMin": {"type": "integer"}, "tag": {"type": "string"},
             "place": {"type": "string"}, "note": {"type": "string"}, "reminders": {"type": "array"},
             "mentions": {"type": "array"}, "participants": {"type": "array"}}, "required": ["id"]}},
        {"name": "schedule_delete", "description": "跨模块删除自己创建的日程",
         "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        {"name": "wishpool_list", "description": "跨模块读取许愿池",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "wishpool_create", "description": "跨模块新增愿望",
         "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "coins": {"type": "integer"}, "dueDate": {"type": "string"}}, "required": ["title"]}},
        {"name": "wishpool_approve", "description": "跨模块通过愿望（需维护权限）",
         "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        {"name": "wishpool_reject", "description": "跨模块拒绝愿望（需维护权限）",
         "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        {"name": "schedule_agenda", "description": "读取未来一段时间的日程与课程安排",
         "parameters": {"type": "object", "properties": {"days": {"type": "integer", "description": "默认 14 天"}}}},
        {"name": "map_place_list", "description": "读取地点列表（日程/地图通用）",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "module_state", "description": "读取当前模块的数据概览（只读）",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "scratchpad_list", "description": "读取临时便签列表",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "scratchpad_append", "description": "在临时便签中新增一条便签",
         "parameters": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}},
    ]

    def _ai_tool_defs(self, module):
        base = list(self.AI_TOOL_DEFS.get(module or "", []))
        names = {d.get("name") for d in base}
        for d in self.AI_UNIVERSAL_TOOL_DEFS:
            if d.get("name") not in names:
                base.append(d)
        return base

    @staticmethod
    def _ai_hm_to_min(text):
        import re as _re
        m = _re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text or ""))
        if not m:
            raise ProjectError("bad_request", "时间格式应为 HH:MM", 400)
        return max(0, min(1439, int(m.group(1)) * 60 + int(m.group(2))))

    @staticmethod
    def _gcj_to_wgs(lng, lat):
        # GCJ-02 -> WGS84 approximation (same family as coord.js)
        if not (-180 <= lng <= 180 and -90 <= lat <= 90): return lng, lat
        x_pi = math.pi * 3000.0 / 180.0
        a, ee = 6378245.0, 0.00669342162296594323
        def transform_lat(x, y):
            ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
            ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
            ret += (20.0*math.sin(y*math.pi) + 40.0*math.sin(y/3.0*math.pi)) * 2.0/3.0
            ret += (160.0*math.sin(y/12.0*math.pi) + 320*math.sin(y*math.pi/30.0)) * 2.0/3.0
            return ret
        def transform_lng(x, y):
            ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
            ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
            ret += (20.0*math.sin(x*math.pi) + 40.0*math.sin(x/3.0*math.pi)) * 2.0/3.0
            ret += (150.0*math.sin(x/12.0*math.pi) + 300.0*math.sin(x/30.0*math.pi)) * 2.0/3.0
            return ret
        dlat = transform_lat(lng - 105.0, lat - 35.0)
        dlng = transform_lng(lng - 105.0, lat - 35.0)
        radlat = lat / 180.0 * math.pi
        magic = math.sin(radlat); magic = 1 - ee*magic*magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
        return lng - dlng, lat - dlat

    @staticmethod
    def _haversine_m(lat1, lng1, lat2, lng2):
        if None in (lat1, lng1, lat2, lng2): return None
        r = 6371000.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2-lat1); dl = math.radians(lng2-lng1)
        a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return 2*r*math.asin(math.sqrt(a))

    def _amap_key(self):
        try:
            with open(os.path.join(self.server.root, "projects", "schedule", "web", "schedule.json"), encoding="utf-8") as f:
                data = json.load(f)
                return str((data.get("meta") or {}).get("amapKey") or data.get("amapKey") or "")
        except Exception:
            return ""

    def _ai_tool_execute(self, user, module, name, args, dry_run=False):
        args = args if isinstance(args, dict) else {}
        allowed = [t.get("name") for t in self._ai_tool_defs(module)]
        if name not in allowed:
            raise ProjectError("forbidden", "工具不属于当前模块：" + str(name), 403)
        if name == "workspace_overview":
            store = self._sched_store()
            def mine(x):
                return (str(x.get("owner") or "") == user or user in (x.get("participants") or []) or user in (x.get("mentions") or []))
            courses = [c for c in (store.get("courses") or []) if isinstance(c, dict) and mine(c)]
            exams = [e for e in (store.get("exams") or []) if isinstance(e, dict) and mine(e)]
            events = [e for e in (self._sched_load().get("events") or []) if self._sched_visible(user, e)]
            today = datetime.now(TZ).strftime("%Y-%m-%d")
            upcoming = sorted([e for e in events if str(e.get("date") or "") >= today], key=lambda e: (e.get("date") or "", e.get("startMin") or 0))[:8]
            pad_items = []
            try:
                rev, pad = self.registry.get("scratchpad").state(); pad_items = (pad or {}).get("items") or []
            except Exception: pass
            wishes = []
            try:
                rev, wp = self.registry.get("wishpool").state(); wishes = (wp or {}).get("items") or []
            except Exception: pass
            return {"user": user, "module": module, "today": today,
                    "courses": [{"code": c.get("code"), "cn": c.get("cn"), "schedule": c.get("schedule") or []} for c in courses[:40]],
                    "exams": [{"course": e.get("course"), "cn": e.get("cn"), "date": e.get("date"), "time": e.get("time")} for e in exams[:40]],
                    "holidays": store.get("holidays") or [], "upcoming_events": upcoming,
                    "scratchpad_count": len(pad_items), "wishpool_pending": len([w for w in wishes if w.get("status") == "pending"])}
        if name == "schedule_agenda":
            try: days = max(1, min(90, int(args.get("days") or 14)))
            except Exception: days = 14
            today = datetime.now(TZ).date(); end = today + timedelta(days=days)
            events = []
            for e in self._sched_load().get("events") or []:
                if not self._sched_visible(user, e): continue
                try: d = datetime.strptime(str(e.get("date")), "%Y-%m-%d").date()
                except Exception: continue
                if today <= d <= end: events.append({"title": e.get("title"), "date": e.get("date"), "startMin": e.get("startMin"), "endMin": e.get("endMin"), "place": e.get("place") or "", "tag": e.get("tag") or ""})
            events.sort(key=lambda x: (x.get("date") or "", x.get("startMin") or 0))
            store = self._sched_store()
            courses = [{"code": c.get("code"), "cn": c.get("cn"), "schedule": c.get("schedule") or []}
                       for c in (store.get("courses") or []) if isinstance(c, dict)
                       and (str(c.get("owner") or "") == user or user in (c.get("participants") or []) or user in (c.get("mentions") or []))]
            return {"from": str(today), "to": str(end), "events": events[:60], "courses": courses[:40]}
        if name == "module_state":
            proj = self.registry.get(module) if module else None
            if not proj or not self._can_access(user, module):
                raise ProjectError("forbidden", "当前模块不可访问", 403)
            try:
                rev, data = proj.state(); data = data if isinstance(data, dict) else {}
                summary = {}
                for k, v in data.items():
                    if isinstance(v, list): summary[k] = {"count": len(v), "sample": v[:3]}
                    elif isinstance(v, dict): summary[k] = v if len(json.dumps(v, ensure_ascii=False)) < 2500 else {"keys": list(v.keys())[:30]}
                    else: summary[k] = v
                return {"module": module, "rev": rev, "summary": summary}
            except Exception as e:
                return {"module": module, "error": str(e)[:200]}
        if name == "map_place_list":
            return {"places": [{"code": v.get("code"), "name": v.get("name"), "short": v.get("short"), "address": v.get("address") or "", "lat": v.get("lat"), "lng": v.get("lng")}
                               for v in (self._sched_store().get("venues") or []) if isinstance(v, dict)]}
        if name in ("wishpool_list", "wishpool_create", "wishpool_approve", "wishpool_reject"):
            proj = self.registry.get("wishpool")
            if not proj or not self._can_access(user, "wishpool"):
                raise ProjectError("forbidden", "没有许愿池访问权限", 403)
            rev, data, audit = proj._load(); data = dict(data or {}); audit = list(audit or [])
            wishes = data.get("wishes") if isinstance(data.get("wishes"), list) else (data.get("items") or [])
            if name == "wishpool_list":
                return {"items": wishes, "stats": data.get("stats") or {}, "rev": rev}
            if not self._can_maintain(user, "wishpool"):
                raise ProjectError("forbidden", "没有许愿池维护权限", 403)
            now_iso = datetime.now(TZ).isoformat(timespec="seconds")
            if name == "wishpool_create":
                title = str(args.get("title") or "").strip()[:200]
                if not title: raise ProjectError("bad_request", "愿望标题为空", 400)
                try: coins = max(0, min(999999, int(args.get("coins") or 0)))
                except Exception: coins = 0
                wid = "w" + now_iso.replace("-", "").replace(":", "").replace("+", "p")
                wish = {"id": wid, "title": title, "coins": coins, "status": "pending",
                        "creator": user, "dueDate": str(args.get("dueDate") or "")[:20],
                        "createdAt": now_iso, "history": [{"at": now_iso, "by": user, "act": "提交", "note": "AI 创建"}]}
                if dry_run: return {"dry_run": True, "wish": wish}
                wishes = list(wishes) + [wish]; data["wishes"] = wishes
                with proj._lock:
                    proj._save(rev + 1, data, audit)
                return {"created": wish, "rev": rev + 1, "ui": {"module": "wishpool", "actions": [{"type": "reload_host"}]}}
            wid = str(args.get("id") or "")
            if not wid: raise ProjectError("bad_request", "缺少愿望 id", 400)
            target = next((w for w in wishes if str(w.get("id")) == wid), None)
            if not target: raise ProjectError("not_found", "愿望不存在", 404)
            new_status = "approved" if name == "wishpool_approve" else "rejected"
            target = dict(target); target["status"] = new_status
            target["history"] = list(target.get("history") or []) + [{"at": now_iso, "by": user, "act": "通过" if name == "wishpool_approve" else "拒绝", "note": "AI 操作"}]
            data["wishes"] = [target if w is next((x for x in wishes if str(x.get("id")) == wid), None) else w for w in wishes]
            if dry_run: return {"dry_run": True, "wish": target}
            with proj._lock:
                proj._save(rev + 1, data, audit)
            return {"updated": target, "rev": rev + 1, "ui": {"module": "wishpool", "actions": [{"type": "reload_host"}]}}
        if name == "scratchpad_list":
            proj = self.registry.get("scratchpad")
            if not proj or not self._can_access(user, "scratchpad"):
                raise ProjectError("forbidden", "没有便签访问权限", 403)
            rev, data = proj.state()
            return {"items": (data or {}).get("items") or [], "rev": rev}
        if name == "scratchpad_append":
            title = str(args.get("title") or "").strip()[:500]
            if not title:
                raise ProjectError("bad_request", "便签内容为空", 400)
            item = {"title": title, "at": datetime.now(TZ).isoformat(timespec="seconds")}
            if dry_run:
                return {"dry_run": True, "item": item}
            proj = self.registry.get("scratchpad")
            if not proj or not self._can_maintain(user, "scratchpad"):
                raise ProjectError("forbidden", "没有便签维护权限", 403)
            rev, data = proj.dispatch("append", {"item": item}, role=user, write_allowed=True)
            return {"added": item, "rev": rev,
                    "ui": {"module": "scratchpad", "actions": [
                        {"type": "focus", "selector": "#new-text"},
                        {"type": "refresh", "selector": "#list"}]}}
        if name == "schedule_list":
            data = self._sched_load()
            rows = []
            for ev in data.get("events") or []:
                if not self._sched_visible(user, ev):
                    continue
                if args.get("date") and str(ev.get("date")) != str(args.get("date")):
                    continue
                rows.append({"id": ev.get("id"), "title": ev.get("title"), "date": ev.get("date"),
                             "startMin": ev.get("startMin"), "endMin": ev.get("endMin"),
                             "place": ev.get("place") or "", "tag": ev.get("tag") or ""})
            return {"events": rows[:80]}
        if name == "schedule_create":
            title = str(args.get("title") or "").strip()[:120]
            date = str(args.get("date") or "").strip()
            if not title or not date:
                raise ProjectError("bad_request", "缺少日程标题或日期", 400)
            body = {"title": title, "date": date, "endDate": date,
                    "startMin": self._ai_hm_to_min(args.get("start")),
                    "endMin": self._ai_hm_to_min(args.get("end")),
                    "tag": str(args.get("tag") or "个人")[:20],
                    "place": str(args.get("place") or "")[:200],
                    "placeCode": str(args.get("placeCode") or "")[:80],
                    "note": str(args.get("note") or "")[:2000],
                    "participants": [user], "mentions": []}
            payload = self._sched_payload(body)
            payload["creator"] = user
            payload["created_at"] = time.time()
            payload["updated_at"] = time.time()
            if dry_run:
                return {"dry_run": True, "event": payload}
            data = self._sched_load()
            conflict = self._sched_conflict(data, payload, user)
            if conflict:
                return {"conflict": conflict.get("title"), "event": payload}
            data.setdefault("events", []).append(payload)
            with SCHEDULE_LOCK:
                self._sched_save(data)
            return {"created": {"id": payload.get("id"), "title": payload.get("title"),
                                "date": payload.get("date"), "startMin": payload.get("startMin"),
                                "endMin": payload.get("endMin")},
                    "ui": {"module": "schedule", "actions": [
                        {"type": "click", "selector": "#gridwrap"},
                        {"type": "refresh", "selector": "#mylist"}]}}
        if name == "schedule_update":
            eid = str(args.get("id") or "").strip()
            if not eid:
                raise ProjectError("bad_request", "缺少日程 id", 400)
            data = self._sched_load()
            old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None)
            if not old:
                raise ProjectError("not_found", "日程不存在", 404)
            if not self._sched_event_can(user, old, "write"):
                raise ProjectError("forbidden", "只有创建者或参与者可以修改日程", 403)
            body = dict(old)
            for k in ("title", "date", "endDate", "tag", "place", "placeCode", "note", "reminders", "mentions", "participants"):
                if k in args:
                    body[k] = args.get(k)
            if "start" in args and str(args.get("start") or "").strip():
                body["startMin"] = self._ai_hm_to_min(args.get("start"))
            elif "startMin" in args:
                body["startMin"] = args.get("startMin")
            if "end" in args and str(args.get("end") or "").strip():
                body["endMin"] = self._ai_hm_to_min(args.get("end"))
            elif "endMin" in args:
                body["endMin"] = args.get("endMin")
            ev = self._sched_payload(body, old)
            ev["creator"] = str(old.get("creator") or user)
            ev["source"] = old.get("source") or ""
            ev["created_at"] = old.get("created_at") or time.time()
            ev["updated_at"] = time.time()
            if dry_run:
                return {"dry_run": True, "event": ev}
            for participant in ev.get("participants") or []:
                conflict = self._sched_conflict(data, ev, participant)
                if conflict:
                    return {"conflict": conflict.get("title"), "event": ev}
            data["events"] = [ev if str(e.get("id")) == eid else e for e in data.get("events") or []]
            with SCHEDULE_LOCK:
                self._sched_save(data)
            return {"updated": {"id": ev.get("id"), "title": ev.get("title"), "date": ev.get("date"),
                                "startMin": ev.get("startMin"), "endMin": ev.get("endMin")},
                    "ui": {"module": "schedule", "actions": [
                        {"type": "click", "selector": "#gridwrap"},
                        {"type": "refresh", "selector": "#mylist"}]}}
        if name == "schedule_delete":
            eid = str(args.get("id") or "").strip()
            if not eid:
                raise ProjectError("bad_request", "缺少日程 id", 400)
            data = self._sched_load()
            old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None)
            if not old:
                raise ProjectError("not_found", "日程不存在", 404)
            if not self._sched_event_can(user, old, "delete"):
                raise ProjectError("forbidden", "只有创建者可以删除日程", 403)
            if dry_run:
                return {"dry_run": True, "deleted": eid}
            data["events"] = [e for e in data.get("events") or [] if str(e.get("id")) != eid]
            with SCHEDULE_LOCK:
                self._sched_save(data)
            return {"deleted": eid, "ui": {"module": "schedule", "actions": [
                {"type": "click", "selector": "#gridwrap"},
                {"type": "refresh", "selector": "#mylist"}]}}
        if name == "schedule_refresh":
            return {"refreshed": True, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
        if name in ("schedule_special_list", "schedule_special_create", "schedule_special_update", "schedule_special_delete"):
            store = self._sched_store()
            all_specials = [sp for sp in (store.get("specials") or []) if isinstance(sp, dict)]
            def special_is_mine(sp):
                return str(sp.get("owner") or "") == user or user in (sp.get("participants") or []) or user in (sp.get("mentions") or [])
            specials = [sp for sp in all_specials if special_is_mine(sp)]
            if name == "schedule_special_list":
                return {"specials": specials}
            def sp_find(args):
                sid = str(args.get("id") or "")
                if sid: return next((sp for sp in specials if str(sp.get("id")) == sid), None)
                title = str(args.get("title") or "")
                if title: return next((sp for sp in specials if str(sp.get("title")) == title), None)
                code = str(args.get("code") or "")
                weeks = args.get("weeks"); day = args.get("day"); start = args.get("start")
                return next((sp for sp in specials if (not code or str(sp.get("code")) == code) and (weeks is None or sp.get("weeks") == weeks)
                             and (day is None or int(sp.get("day") or 0) == int(day))
                             and (start is None or int(sp.get("start") or 0) == int(start))), None)
            if name == "schedule_special_create":
                title = str(args.get("title") or "").strip()[:120]
                code = str(args.get("code") or "").strip()[:40]
                sp = {"id": self._sched_item_id("sp", "%s|%s|%s|%s" % (title, args.get("weeks"), args.get("day"), time.time())),
                      "code": code, "course": str(args.get("course") or "")[:40],
                      "title": title, "tag": str(args.get("tag") or (code or "安排"))[:40],
                      "weeks": [int(x) for x in (args.get("weeks") or []) if str(x).lstrip("-").isdigit()][:20],
                      "day": int(args.get("day") or 0),
                      "start": int(args.get("start") or 0), "end": int(args.get("end") or 0),
                      "venue": str(args.get("venue") or "")[:120], "note": str(args.get("note") or "")[:240],
                      "isExam": bool(args.get("isExam") or False),
                      "owner": user,
                      "participants": [str(x) for x in (args.get("participants") or [user]) if str(x) in self.auth.users],
                      "mentions": [str(x) for x in (args.get("mentions") or [user]) if str(x) in self.auth.users]}
                if not sp["title"] or not sp["weeks"]: raise ProjectError("bad_request", "缺少 title/weeks", 400)
                if not (0 <= sp["day"] <= 6) or not (0 <= sp["start"] < sp["end"] <= 1440): raise ProjectError("bad_request", "day/start/end 不合法", 400)
                if dry_run: return {"dry_run": True, "special": sp}
                all_specials.append(sp); store["specials"] = all_specials
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"created": sp, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            old = sp_find(args)
            if not old: raise ProjectError("not_found", "特殊安排不存在", 404)
            if name == "schedule_special_update" and not self._sched_item_can(user, old, "write"):
                raise ProjectError("forbidden", "只有 special owner 或参与者可以修改", 403)
            if name == "schedule_special_delete" and not self._sched_item_can(user, old, "delete"):
                raise ProjectError("forbidden", "只有 special owner 可以删除", 403)
            if name == "schedule_special_update":
                for k in ("code", "course", "title", "tag", "venue", "note"):
                    if k in args: old[k] = str(args.get(k) or "")[: (240 if k == "note" else 120)]
                for k in ("weeks",):
                    if k in args: old[k] = [int(x) for x in (args.get(k) or []) if str(x).lstrip("-").isdigit()][:20]
                for k in ("day", "start", "end"):
                    if k in args: old[k] = int(args.get(k) or 0)
                if "isExam" in args: old["isExam"] = bool(args.get("isExam"))
                if "participants" in args: old["participants"] = [str(x) for x in (args.get("participants") or []) if str(x) in self.auth.users]
                if "mentions" in args: old["mentions"] = [str(x) for x in (args.get("mentions") or []) if str(x) in self.auth.users]
                old["owner"] = str(old.get("owner") or user)
                if old["owner"] not in (old.get("participants") or []): old["participants"] = [old["owner"]] + list(old.get("participants") or [])
                if not (0 <= int(old.get("day") or 0) <= 6) or not (0 <= int(old.get("start") or 0) < int(old.get("end") or 0) <= 1440):
                    raise ProjectError("bad_request", "day/start/end 不合法", 400)
                if dry_run: return {"dry_run": True, "special": old}
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"updated": old, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_special_delete":
                if dry_run: return {"dry_run": True, "deleted": old.get("id")}
                store["specials"] = [sp for sp in all_specials if sp is not old]
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"deleted": old.get("id"), "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
        if name in ("schedule_exam_list", "schedule_exam_create", "schedule_exam_update", "schedule_exam_delete",
                    "schedule_holiday_list", "schedule_holiday_create", "schedule_holiday_update", "schedule_holiday_delete"):
            store = self._sched_store()
            def exam_is_mine(e):
                return str(e.get("owner") or "") == user or user in (e.get("participants") or []) or user in (e.get("mentions") or [])
            mine_exams = [e for e in (store.get("exams") or []) if isinstance(e, dict) and exam_is_mine(e)]
            if name == "schedule_exam_list":
                return {"exams": mine_exams}
            if name == "schedule_holiday_list":
                return {"holidays": store.get("holidays") or []}
            def exam_find(args):
                eid = str(args.get("id") or "")
                if eid:
                    return next((e for e in mine_exams if str(e.get("id")) == eid), None)
                course = str(args.get("course") or ""); date = str(args.get("date") or "")
                return next((e for e in mine_exams if str(e.get("course")) == course and str(e.get("date")) == date), None)
            def holiday_find(args):
                hid = str(args.get("id") or "")
                if hid: return next((h for h in (store.get("holidays") or []) if str(h.get("id")) == hid), None)
                name = str(args.get("name") or "")
                return next((h for h in (store.get("holidays") or []) if str(h.get("name")) == name), None)
            if name == "schedule_exam_create":
                ex = {"id": self._sched_item_id("exam", "%s|%s|%s" % (args.get("course"), args.get("date"), time.time())),
                      "course": str(args.get("course") or "").strip()[:40],
                      "cn": str(args.get("cn") or "")[:120], "date": str(args.get("date") or "")[:20],
                      "time": str(args.get("time") or "")[:40], "week": int(args.get("week") or 0),
                      "venue": str(args.get("venue") or "")[:120],
                      "owner": user,
                      "participants": [str(x) for x in (args.get("participants") or [user]) if str(x) in self.auth.users],
                      "mentions": [str(x) for x in (args.get("mentions") or [user]) if str(x) in self.auth.users]}
                if not ex["course"] or not ex["date"]: raise ProjectError("bad_request", "缺少 course/date", 400)
                if dry_run: return {"dry_run": True, "exam": ex}
                store.setdefault("exams", []).append(ex)
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"created": ex, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_exam_update":
                old = exam_find(args)
                if not old: raise ProjectError("not_found", "考试不存在", 404)
                if not self._sched_item_can(user, old, "write"):
                    raise ProjectError("forbidden", "只有考试 owner 或参与者可以修改", 403)
                for k in ("course", "cn", "date", "time", "venue"):
                    if k in args: old[k] = str(args.get(k) or "")[: (120 if k in ("cn", "venue") else 40)]
                if "week" in args: old["week"] = int(args.get("week") or 0)
                if "participants" in args: old["participants"] = [str(x) for x in (args.get("participants") or []) if str(x) in self.auth.users]
                if "mentions" in args: old["mentions"] = [str(x) for x in (args.get("mentions") or []) if str(x) in self.auth.users]
                old["owner"] = str(old.get("owner") or user)
                if old["owner"] not in (old.get("participants") or []): old["participants"] = [old["owner"]] + list(old.get("participants") or [])
                if dry_run: return {"dry_run": True, "exam": old}
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"updated": old, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_exam_delete":
                old = exam_find(args)
                if not old: raise ProjectError("not_found", "考试不存在", 404)
                if not self._sched_item_can(user, old, "delete"):
                    raise ProjectError("forbidden", "只有考试 owner 可以删除", 403)
                if dry_run: return {"dry_run": True, "deleted": old.get("id")}
                store["exams"] = [e for e in (store.get("exams") or []) if e is not old]
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"deleted": old.get("id"), "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_holiday_create":
                h = {"id": self._sched_item_id("hol", "%s|%s" % (args.get("name"), time.time())),
                     "name": str(args.get("name") or "").strip()[:80], "en": str(args.get("en") or "")[:120],
                     "weeks": [int(x) for x in (args.get("weeks") or []) if str(x).lstrip("-").isdigit()][:20],
                     "days": [int(x) for x in (args.get("days") or []) if str(x).lstrip("-").isdigit()][:20],
                     "dates": [str(x)[:20] for x in (args.get("dates") or [])][:20]}
                if not h["name"]: raise ProjectError("bad_request", "缺少节假日名称", 400)
                if dry_run: return {"dry_run": True, "holiday": h}
                store.setdefault("holidays", []).append(h)
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"created": h, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_holiday_update":
                old = holiday_find(args)
                if not old: raise ProjectError("not_found", "节假日不存在", 404)
                for k in ("name", "en"):
                    if k in args: old[k] = str(args.get(k) or "")[:120]
                for k in ("weeks", "days"):
                    if k in args: old[k] = [int(x) for x in (args.get(k) or []) if str(x).lstrip("-").isdigit()][:20]
                if "dates" in args: old["dates"] = [str(x)[:20] for x in (args.get("dates") or [])][:20]
                if dry_run: return {"dry_run": True, "holiday": old}
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"updated": old, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_holiday_delete":
                old = holiday_find(args)
                if not old: raise ProjectError("not_found", "节假日不存在", 404)
                if dry_run: return {"dry_run": True, "deleted": old.get("id")}
                store["holidays"] = [h for h in (store.get("holidays") or []) if h is not old]
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"deleted": old.get("id"), "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
        if name in ("schedule_course_list", "schedule_course_create", "schedule_course_update", "schedule_course_delete", "schedule_course_refresh"):
            store = self._sched_store()
            all_courses = [c for c in (store.get("courses") or []) if isinstance(c, dict)]
            def course_is_mine(c):
                return str(c.get("owner") or "") == user or user in (c.get("participants") or []) or user in (c.get("mentions") or [])
            courses = [c for c in all_courses if course_is_mine(c)]
            if name in ("schedule_course_list", "schedule_course_refresh"):
                rows = [{k: c.get(k) for k in ("code", "name", "cn", "module", "credit", "prof", "venues", "schedule", "source", "owner")}
                        for c in courses[:200]]
                if name == "schedule_course_refresh":
                    return {"refreshed": True, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
                return {"courses": rows}
            code = str(args.get("code") or "").strip()[:40]
            if not code:
                raise ProjectError("bad_request", "缺少课程 code", 400)
            if name == "schedule_course_create":
                if any(str(c.get("code") or "") == code for c in courses):
                    raise ProjectError("conflict", "课程代码已存在：" + code, 409)
                course = self._sched_course_payload(args, user=user)
                course["owner"] = user
                pl = [str(x) for x in (args.get("participants") or course.get("participants") or [user]) if str(x) in self.auth.users]
                if user not in pl: pl = [user] + pl
                course["participants"] = pl
                course["mentions"] = [str(x) for x in (args.get("mentions") or course.get("mentions") or [user]) if str(x) in self.auth.users]
                course["source"] = "ai"
                course["updated_at"] = time.time()
                if dry_run: return {"dry_run": True, "course": course}
                all_courses.append(course)
                store["courses"] = all_courses
                for ex in (args.get("exams") or [])[:20]:
                    if isinstance(ex, dict):
                        store.setdefault("exams", []).append({"id": self._sched_item_id("exam", "%s|%s|%s" % (code, ex.get("date"), time.time())),
                                                               "course": code, "cn": course.get("cn") or course.get("name"),
                                                               "date": str(ex.get("date") or "")[:20], "time": str(ex.get("time") or "")[:20],
                                                               "week": int(ex.get("week") or 0), "venue": str(ex.get("venue") or "")[:120],
                                                               "owner": user, "participants": [user], "mentions": [user]})
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"created": {k: course.get(k) for k in ("code", "name", "cn", "credit", "schedule")},
                        "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            old = next((c for c in courses if str(c.get("code") or "") == code), None)
            if not old: raise ProjectError("not_found", "课程不存在", 404)
            if name == "schedule_course_update" and not self._sched_item_can(user, old, "write"):
                raise ProjectError("forbidden", "只有课程 owner 或参与者可以修改", 403)
            if name == "schedule_course_delete" and not self._sched_item_can(user, old, "delete"):
                raise ProjectError("forbidden", "只有课程 owner 可以删除", 403)
            if name == "schedule_course_update":
                course = self._sched_course_payload(args, old, user=user)
                course["code"] = code
                course["owner"] = str(old.get("owner") or user)
                pl = [str(x) for x in (args.get("participants", old.get("participants") or [course["owner"]])) if str(x) in self.auth.users]
                if course["owner"] not in pl: pl = [course["owner"]] + pl
                course["participants"] = pl
                course["mentions"] = [str(x) for x in (args.get("mentions", old.get("mentions") or [course["owner"]])) if str(x) in self.auth.users]
                course["source"] = old.get("source") or "seed"
                course["updated_at"] = time.time()
                if dry_run: return {"dry_run": True, "course": course}
                store["courses"] = [course if c is old else c for c in all_courses]
                if "exams" in args:
                    store["exams"] = [e for e in (store.get("exams") or []) if not (e.get("course") == code and str(e.get("owner") or user) == user)]
                    for ex in (args.get("exams") or [])[:20]:
                        if isinstance(ex, dict):
                            store["exams"].append({"id": self._sched_item_id("exam", "%s|%s|%s" % (code, ex.get("date"), time.time())),
                                                   "course": code, "cn": course.get("cn") or course.get("name"),
                                                   "date": str(ex.get("date") or "")[:20], "time": str(ex.get("time") or "")[:20],
                                                   "week": int(ex.get("week") or 0), "venue": str(ex.get("venue") or "")[:120],
                                                   "owner": user, "participants": [user], "mentions": [user]})
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"updated": {k: course.get(k) for k in ("code", "name", "cn", "credit", "schedule")},
                        "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_course_delete":
                if dry_run: return {"dry_run": True, "deleted": code}
                store["courses"] = [c for c in all_courses if c is not old]
                store["exams"] = [e for e in (store.get("exams") or []) if not (e.get("course") == code and str(e.get("owner") or user) == user)]
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"deleted": code, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
        if name == "map_place_search":
            keywords = str(args.get("keywords") or "").strip()[:120]
            if not keywords: raise ProjectError("bad_request", "缺少搜索关键词", 400)
            try: limit = max(1, min(20, int(args.get("limit") or 8)))
            except Exception: limit = 8
            city = str(args.get("city") or "上海")[:40]
            key = self._amap_key()
            if not key: raise ProjectError("bad_request", "未配置高德地图 API key", 400)
            url = ("https://restapi.amap.com/v3/place/text?key=" + quote(key) + "&keywords=" + quote(keywords) +
                   "&city=" + quote(city) + "&offset=" + str(limit) + "&page=1&extensions=all")
            try:
                with urllib.request.urlopen(url, timeout=12) as r:
                    payload = json.loads(r.read().decode("utf-8"))
            except Exception as e:
                raise ProjectError("upstream", "地图搜索失败：" + str(e)[:200], 502)
            if str(payload.get("status")) != "1":
                raise ProjectError("upstream", "地图搜索失败：" + str(payload.get("info") or "unknown"), 502)
            center_lat = args.get("lat"); center_lng = args.get("lng")
            try: center_lat = float(center_lat) if center_lat not in (None, "") else None
            except Exception: center_lat = None
            try: center_lng = float(center_lng) if center_lng not in (None, "") else None
            except Exception: center_lng = None
            matches = []
            for item in (payload.get("pois") or [])[:limit]:
                loc = str(item.get("location") or "")
                try:
                    glng, glat = [float(x) for x in loc.split(",")[:2]]
                    lng, lat = self._gcj_to_wgs(glng, glat)
                except Exception:
                    lng = lat = None
                dist = self._haversine_m(center_lat, center_lng, lat, lng) if center_lat is not None and center_lng is not None else None
                addr = item.get("address")
                if isinstance(addr, list): addr = "".join(str(x) for x in addr)
                matches.append({"name": str(item.get("name") or "")[:120], "address": str(addr or "")[:300],
                                "lat": lat, "lng": lng, "distance_m": round(dist) if dist is not None else None,
                                "adcode": str(item.get("adcode") or ""), "type": str(item.get("type") or "")[:120]})
            if center_lat is not None and center_lng is not None:
                matches.sort(key=lambda x: (x.get("distance_m") is None, x.get("distance_m") or 0))
            return {"query": keywords, "city": city, "matches": matches}
        if name in ("schedule_place_list", "schedule_place_create", "schedule_place_update", "schedule_place_delete"):
            store = self._sched_store()
            venues = [v for v in (store.get("venues") or []) if isinstance(v, dict)]
            if name == "schedule_place_list":
                return {"places": [{"code": v.get("code"), "name": v.get("name"), "short": v.get("short"),
                                    "address": v.get("address") or "", "note": v.get("note") or "",
                                    "lat": v.get("lat"), "lng": v.get("lng")} for v in venues[:200]]}
            def find_place(args):
                for key in ("id", "code", "name"):
                    val = str(args.get(key) or "").strip()
                    if not val: continue
                    for v in venues:
                        if key == "name" and str(v.get("name") or "") == val: return v
                        if key != "name" and str(v.get(key) or "") == val: return v
                return None
            def as_num(v):
                if v is None or v == "": return None
                try: return float(v)
                except Exception: raise ProjectError("bad_request", "经纬度必须是数字", 400)
            if name == "schedule_place_create":
                pname = str(args.get("name") or "").strip()[:120]
                if not pname: raise ProjectError("bad_request", "缺少地点名称", 400)
                if any(str(v.get("name") or "") == pname for v in venues):
                    raise ProjectError("conflict", "地点已存在：" + pname, 409)
                lat, lng = as_num(args.get("lat")), as_num(args.get("lng"))
                code = str(args.get("code") or "").strip()[:60] or ("v%d" % int(time.time() * 1000))
                if any(str(v.get("code") or "") == code for v in venues):
                    raise ProjectError("conflict", "地点 code 已存在：" + code, 409)
                place = {"code": code, "name": pname, "short": str(args.get("short") or pname)[:120],
                         "address": str(args.get("address") or "")[:300], "note": str(args.get("note") or "")[:500],
                         "lat": lat, "lng": lng, "custom": True}
                if dry_run: return {"dry_run": True, "place": place}
                venues.append(place); store["venues"] = venues
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                return {"created": place, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_place_update":
                old = find_place(args)
                if not old: raise ProjectError("not_found", "地点不存在", 404)
                old_name = str(old.get("name") or "")
                new_name = str(args.get("name") or old_name).strip()[:120]
                if new_name != old_name and any(str(v.get("name") or "") == new_name for v in venues if v is not old):
                    raise ProjectError("conflict", "地点名称已存在：" + new_name, 409)
                for k in ("name", "short", "address", "note"):
                    if k in args: old[k] = str(args.get(k) or "")[: (500 if k == "note" else 300)]
                if "name" in args:
                    old["name"] = new_name
                    if "short" not in args: old["short"] = new_name
                for k in ("lat", "lng"):
                    if k in args: old[k] = as_num(args.get(k))
                if dry_run: return {"dry_run": True, "place": old}
                store["venues"] = venues
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                data = self._sched_load(); changed = False
                for e in data.get("events") or []:
                    if str(e.get("place") or "") == old_name or str(e.get("placeCode") or "") == str(old.get("code") or ""):
                        e["place"] = new_name; e["placeCode"] = str(old.get("code") or ""); changed = True
                if changed:
                    with SCHEDULE_LOCK: self._sched_save(data)
                return {"updated": old, "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
            if name == "schedule_place_delete":
                old = find_place(args)
                if not old: raise ProjectError("not_found", "地点不存在", 404)
                old_name, old_code = str(old.get("name") or ""), str(old.get("code") or "")
                bound = []
                for ev in (self._sched_load().get("events") or []):
                    if str(ev.get("placeCode") or "") == old_code or (old_name and str(ev.get("place") or "") == old_name):
                        bound.append(ev)
                if bound:
                    raise ProjectError("conflict", "地点仍被 %d 条日程绑定，请先解绑：%s" % (
                        len(bound), "、".join(str(e.get("title") or e.get("id")) for e in bound[:5])), 409)
                if dry_run: return {"dry_run": True, "deleted": old_code}
                store["venues"] = [v for v in venues if v is not old]
                with SCHEDULE_COURSES_LOCK: self._sched_store_save(store)
                data = self._sched_load(); changed = False
                for e in data.get("events") or []:
                    if str(e.get("place") or "") == old_name or str(e.get("placeCode") or "") == old_code:
                        e["place"] = ""; e["placeCode"] = ""; changed = True
                if changed:
                    with SCHEDULE_LOCK: self._sched_save(data)
                return {"deleted": old.get("code"), "ui": {"module": "schedule", "actions": [{"type": "reload_host"}]}}
        raise ProjectError("bad_request", "未知工具：" + str(name), 400)

    def _ai_tool_prompt(self, module, user):
        defs = self._ai_tool_defs(module)
        if not defs:
            return ""
        proj = self.registry.get(module) if module else None
        title = (proj.manifest().get("title") if proj else module) or module
        lines = ["当前模块：%s（%s）。你正在这个模块内协助用户。" % (title, module),
                 "通用工具（workspace_overview / schedule_agenda / map_place_list / scratchpad_*）在所有模块可用；写操作使用当前模块专属工具。",
                 "优先查询真实数据再行动，不要只用常识回答。", "你可以使用以下工具："]
        for d in defs:
            lines.append("- %s: %s 参数=%s" % (d["name"], d["description"], json.dumps(d["parameters"], ensure_ascii=False)))
        lines.append("需要调用工具时，只输出一行 JSON，例如：")
        lines.append('{"tool":"工具名","args":{...}}')
        lines.append("工具执行后你会收到结果，再给出最终回答；不需要工具时正常回答。")
        return "\n".join(lines)

    # ---------------- 用户加密文件 ----------------    # ---------------- 用户加密文件 ----------------
    def _files_root(self):
        return os.path.join(self.server.root, "data", "files")

    def _files_key_path(self):
        return os.path.join(self._files_root(), "upload_key.bin")

    def _files_index_path(self):
        return os.path.join(self._files_root(), "index.json")

    def _files_fernet(self):
        from cryptography.fernet import Fernet
        root = self._files_root()
        os.makedirs(root, exist_ok=True)
        kp = self._files_key_path()
        try:
            with open(kp, "rb") as f:
                key = f.read().strip()
        except Exception:
            key = Fernet.generate_key()
            tmp = kp + ".tmp"
            with open(tmp, "wb") as f:
                f.write(key)
            try:
                os.chmod(tmp, 0o600)
            except Exception:
                pass
            os.replace(tmp, kp)
        return Fernet(key)

    def _files_index(self):
        try:
            with open(self._files_index_path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) and isinstance(d.get("files"), list) else {"files": []}
        except Exception:
            return {"files": []}

    def _files_save_index(self, data):
        os.makedirs(self._files_root(), exist_ok=True)
        tmp = self._files_index_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._files_index_path())

    @staticmethod
    def _files_public(item):
        return {"id": item.get("id"), "name": item.get("name"), "mime": item.get("mime") or "application/octet-stream",
                "size": int(item.get("size") or 0), "sha256": item.get("sha256") or "",
                "created": item.get("created") or "", "owner": item.get("owner")}

    def _bug_file(self):
        return os.path.join(self.server.root, "data", "bugreports.json")

    def _bug_log(self):
        return os.path.join(self.server.root, "data", "bugreports.jsonl")

    def _bug_load(self):
        try:
            with open(self._bug_file(), encoding="utf-8-sig") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _bug_append_log(self, rec):
        with BUG_LOCK:
            try:
                os.makedirs(os.path.dirname(self._bug_log()), exist_ok=True)
                with open(self._bug_log(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                traceback.print_exc()

    def _bug_save(self, bugs):
        with BUG_LOCK:
            path = self._bug_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(bugs, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)

    def _bug_list(self, user):
        bugs = self._bug_load()
        vals = list(bugs.values())
        if not self.auth.is_admin(user):
            vals = [b for b in vals if b.get("user") == user]
        vals.sort(key=lambda b: b.get("updated", 0), reverse=True)
        return vals

    def _birthday_file(self):
        return os.path.join(self.server.root, "data", "birthdays.json")

    def _load_birthdays(self):
        try:
            with open(self._birthday_file(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save_birthday(self, user, value):
        with THEME_LOCK:
            d = self._load_birthdays()
            if value:
                d[user] = value
            else:
                d.pop(user, None)
            path = self._birthday_file(); os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        return d.get(user, "")

    def _birthday_parts(self, user):
        val = str(self._load_birthdays().get(user) or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            try:
                d = datetime.strptime(val, "%Y-%m-%d").date()
                return d.year, d.strftime("%m-%d"), val
            except ValueError:
                return None, "", ""
        if re.match(r"^\d{2}-\d{2}$", val):
            return None, val, val
        return None, "", ""

    def _birthday_today(self, user):
        year, md, val = self._birthday_parts(user)
        today = datetime.now(TZ)
        return val if md and md == today.strftime("%m-%d") else ""

    def _birthday_age(self, user):
        year, md, val = self._birthday_parts(user)
        if not year:
            return None
        today = datetime.now(TZ)
        if md != today.strftime("%m-%d"):
            return None
        return max(0, today.year - year)

    def _theme_file(self):
        return os.path.join(self.server.root, "data", "themes.json")

    def _load_themes(self):
        try:
            with open(self._theme_file(), encoding="utf-8-sig") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _birthday_asset_library(self):
        base = os.path.join(self.server.root, "static", "birthday")
        library = {}
        for cat in ("cake", "balloon", "confetti", "star"):
            files = []
            d = os.path.join(base, "library", cat)
            if os.path.isdir(d):
                names = [n for n in os.listdir(d) if n.lower().endswith("_styled.png")]
                if not names:
                    names = [n for n in os.listdir(d) if n.lower().endswith("_cut.png")]
                if not names:
                    names = [n for n in os.listdir(d) if n.lower().endswith(".png")]
                files = sorted(["/static/birthday/library/%s/%s" % (cat, n) for n in names])
            if not files:
                fallback = os.path.join(base, cat + ".png")
                if os.path.isfile(fallback): files = ["/static/birthday/%s.png" % cat]
            library[cat] = files
        return library

    def _birthday_palette(self, user):
        day = self._birthday_today(user)
        if not day:
            return None
        themes = self._load_themes()
        t = themes.get(user) or {}
        color = _hex_color(t.get("color")) if isinstance(t, dict) else None
        if not color:
            color = (DEFAULT_THEME.get(user) or {}).get("color") or "#9bd1ec"
        colormap = t.get("colormap") if isinstance(t, dict) else "monochrome"
        if colormap not in COLORMAPS:
            colormap = "monochrome"
        pal = build_palette(color, colormap)
        # monochrome base + a few coordinated accent hues derived from the
        # user's own theme colour (not a fixed birthday theme)
        h, sat, light = _rgb_hsl(_hex_rgb(color))
        def shift(deg, sat_mul=1.0, light_mul=1.0):
            return _rgb_hex(_hsl_rgb(h + deg, max(0.08, min(1.0, sat * sat_mul)),
                                    max(0.12, min(0.90, light * light_mul))))
        colors = [color, shift(28, 0.95, 1.06), shift(-38, 0.9, 0.96),
                  shift(118, 0.82, 1.04), shift(194, 0.88, 0.98)]
        pal["birthday"] = {"active": True, "id": "birthday", "name": "生日限定",
                           "emoji": "🎂", "date": day,
                           "greeting": "%s，生日快乐" % user,
                           "age": self._birthday_age(user),
                           "colors": colors,
                           "assets": self._birthday_asset_library(),
                           "locked": True}
        pal["locked"] = True
        return pal

    def _theme_for(self, user):
        if not user:
            return None
        bday = self._birthday_palette(user)
        if bday:
            return bday
        themes = self._load_themes()
        t = themes.get(user) or {}
        color = _hex_color(t.get("color")) if isinstance(t, dict) else None
        colormap = t.get("colormap") if isinstance(t, dict) else None
        if not color:
            color = (DEFAULT_THEME.get(user) or {}).get("color") or "#9bd1ec"
        if colormap not in COLORMAPS:
            colormap = "monochrome"
        return build_palette(color, colormap)

    def _save_theme(self, user, color, colormap="monochrome"):
        if colormap not in COLORMAPS:
            colormap = "monochrome"
        pal = build_palette(color, colormap)
        with THEME_LOCK:
            themes = self._load_themes()
            themes[user] = {"color": color, "colormap": colormap, "deep": pal["deep"]}
            path = self._theme_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(themes, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        return build_palette(color, colormap)

    # ---------------- 活跃事件（使用统计） ----------------
    def _activity_path(self):
        return os.path.join(self.server.root, "data", "activity.json")

    def _activity_load(self):
        try:
            with open(self._activity_path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {"events": []}
        except Exception:
            return {"events": []}

    def _activity_record(self, user, kind, module=""):
        if not user:
            return
        module = str(module or "")[:80]
        event = {"ts": int(time.time()), "user": str(user), "kind": str(kind)[:16], "module": module}
        with ACTIVITY_LOCK:
            d = self._activity_load()
            events = d.get("events") if isinstance(d.get("events"), list) else []
            events.append(event)
            # Bound storage; keep the newest 30000 events (plenty for a year).
            if len(events) > 30000:
                events = events[-30000:]
            d["events"] = events
            path = self._activity_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, path)

    def _activity_stats(self, user_filter="", days=365):
        try:
            days = max(7, min(730, int(days)))
        except Exception:
            days = 365
        now = datetime.now(TZ)
        start = (now.date() - timedelta(days=days - 1))
        day_map = {}
        for i in range(days):
            day_map[(start + timedelta(days=i)).isoformat()] = 0
        hours = [0] * 24
        modules = {m["id"]: {"id": m["id"], "title": m.get("title") or m["id"], "icon": m.get("icon") or "", "opens": 0, "uses": 0} for m in self._modules()}
        users = {}
        events = (self._activity_load().get("events") or [])
        for e in events:
            try:
                ts = int(e.get("ts") or 0)
                dt = datetime.fromtimestamp(ts, TZ)
            except Exception:
                continue
            if dt.date() < start:
                continue
            u = str(e.get("user") or "")
            if not u or (user_filter and u != user_filter):
                continue
            key = dt.date().isoformat()
            if key in day_map:
                day_map[key] += 1
            hours[dt.hour] += 1
            urec = users.setdefault(u, {"user": u, "total": 0, "opens": 0, "uses": 0})
            urec["total"] += 1
            kind = str(e.get("kind") or "")
            if kind == "open":
                urec["opens"] += 1
            elif kind == "use":
                urec["uses"] += 1
            mid = str(e.get("module") or "")
            if mid in modules and kind in ("open", "use"):
                field = "opens" if kind == "open" else "uses"
                modules[mid][field] += 1
                bu = modules[mid].setdefault("by_user", {})
                rec = bu.setdefault(u, {"opens": 0, "uses": 0})
                rec[field] += 1
        day_list = [{"date": k, "count": v} for k, v in sorted(day_map.items())]
        total = sum(day_map.values())
        active_days = sum(1 for v in day_map.values() if v)
        return {
            "scope": user_filter or "all",
            "days": day_list,
            "hours": hours,
            "modules": list(modules.values()),
            "users": sorted(users.values(), key=lambda x: x["total"], reverse=True),
            "totals": {"events": total, "active_days": active_days, "opens": sum(m["opens"] for m in modules.values()), "uses": sum(m["uses"] for m in modules.values())},
        }

    def _modules(self):
        out = []
        for pid, proj in self.registry.projects.items():
            spec = proj.manifest()
            out.append({"id": pid, "title": spec.get("title") or pid,
                        "icon": spec.get("icon") or "", "path": spec.get("path") or ""})
        out.sort(key=lambda x: ((x.get("path") or "").count("/"), x["id"]))
        return out

    def _tree_for(self, user):
        tree = self.registry.tree()

        def walk(node):
            if node.get("id") != "root" and not self._can_access(user, node.get("id")):
                return None
            n = dict(node)
            kids = [walk(c) for c in (node.get("children") or [])]
            n["children"] = [k for k in kids if k]
            return n

        root = walk(tree.get("root") or {"id": "root", "children": []})
        return {"root": root, "errors": tree.get("errors") or []}

    def _admin_guard(self):
        user = self._require_user()
        if not self.auth.is_admin(user):
            raise ProjectError("forbidden", "需要管理员权限", 403)
        return user

    def _is_secure_ctx(self):
        """经 cloudflared 进来时服务端看到的是 http，但浏览器是 https —— 用 CF 头判断。"""
        if (self.headers.get("X-Forwarded-Proto") or "").lower().startswith("https"):
            return True
        if self.headers.get("CF-Connecting-IP"):
            return True
        visitor = self.headers.get("CF-Visitor") or ""
        return "https" in visitor

    def _record(self, user):
        try:
            self.auth.record_activity(user)
        except Exception:
            pass

    def _can_access(self, user, pid):
        if not user or not self.auth.can_access(user, pid):
            return False
        proj = self.registry.get(pid)
        roles = (proj.manifest().get("roles") if proj else None) or []
        if roles and self.auth.role_of(user) not in roles:
            return False
        return True

    def _can_maintain(self, user, pid):
        return bool(user) and self.auth.can_maintain(user, pid)

    def _require_user(self):
        user = self._session_user()
        if not user:
            raise ProjectError("unauthorized", "请先登录工作台", 401)
        self._record(user)
        return user

    # ---------------- HTTP ----------------
    def do_OPTIONS(self):
        self._json(ok())

    def do_GET(self):
        self.server.request_count += 1
        try:
            self._route_get()
        except _Redirect as r:
            self.send_response(302)
            self.send_header("Location", r.location)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except ProjectError as e:
            self._error(e.code, e.message, e.status)
        except Exception:
            traceback.print_exc()
            self._error("internal", "内核异常，见服务端日志", 500)

    def do_POST(self):
        self.server.request_count += 1
        try:
            self._route_post()
        except ProjectError as e:
            self._error(e.code, e.message, e.status)
        except Exception:
            traceback.print_exc()
            self._error("internal", "内核异常，见服务端日志", 500)

    def do_DELETE(self):
        self.server.request_count += 1
        try:
            self._route_admin_post(urlparse(self.path).path)
        except ProjectError as e:
            self._error(e.code, e.message, e.status)
        except Exception:
            traceback.print_exc()
            self._error("internal", "内核异常，见服务端日志", 500)

    def _client_key(self):
        """登录限流用的客户端标识。

        经 cloudflared 隧道进来时，服务端看到的 remote 永远是 127.0.0.1，
        所以优先用 Cloudflare 注入的真实访客 IP；本机直连（测试工具）用 local: 前缀，
        两者分开计数，避免"一个人被锁 = 全家人被锁"。
        """
        cf = (self.headers.get("CF-Connecting-IP") or "").strip()
        if cf:
            return "cf:" + cf
        xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if xff:
            return "xff:" + xff
        ip = self.client_address[0] if self.client_address else "?"
        return "local:" + ip

    # ---------------- GET ----------------
    def _route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if os.environ.get("KP_DEBUG"):
            print("[GET] %r ua=%r ref=%r" % (self.path, (self.headers.get("User-Agent") or "")[:50],
                                             (self.headers.get("Referer") or "")[:60]))

        if path in ("/", "/index.html"):
            return self._serve_file(os.path.join(self.server.static_dir, "landing.html"))

        if path in ("/home", "/home/"):
            return self._serve_file(os.path.join(self.server.static_dir, "index.html"))

        if path.rstrip("/") == "/courtyard":
            # 造院升级为游戏中心的第一个子游戏；旧 URL 保留并跳到新路径。
            target = "/games/courtyard/"
            if parsed.query:
                target += "?" + parsed.query
            raise _Redirect(target)

        if path.rstrip("/") in self.server.canonical_paths:
            # 旧版 URL 结构：/dashboard/ · /dashboard/map/ · /wishpool/ · /mock/
            # 统一返回同一个壳，由前端按地址栏路径决定渲染"工作台"还是某个看板。
            return self._serve_file(os.path.join(self.server.static_dir, "index.html"))
        if path in ("/login", "/login/"):
            return self._serve_file(os.path.join(self.server.static_dir, "login.html"))
        if path.startswith("/static/"):
            return self._serve_static(self.server.static_dir, path[len("/static/"):])

        if path == "/api/health":
            return self._json(ok(projects=len(self.registry.projects),
                                 errors=self.registry.errors,
                                 reminder_alive=bool(self.server.reminder_thread
                                                     and self.server.reminder_thread.is_alive()),
                                 engine="kp-engine/1.1"))

        if path == "/api/metrics":
            user = self._require_user()
            if self.auth.profile(user).get("role") != "主要维护者" and user != "puppy":
                raise ProjectError("forbidden", "仅维护者可见指标", 403)
            return self._json(ok(engine=self.engine.stats(),
                                 protocol=PROTOCOL,
                                 requests=getattr(self.server, "request_count", 0)))

        # ---- 旧协议兼容 ----
        if path == "/api/state":
            user = self._require_user()
            module = (self.headers.get("X-KP-Module") or "").strip()
            if module:
                if not self._can_access(user, module):
                    raise ProjectError("forbidden", "没有 %s 的访问权限" % module, 403)
            elif not self.auth.is_admin(user):
                raise ProjectError("forbidden", "缺少模块标识", 403)
            state = compat.read_state(self.engine)
            etag = 'W/"store-%d"' % self.engine.state_version()
            return self._json(state, etag=etag)

        if path == "/api/mailstatus":
            return self._json(mail_service.mail_status(self.server.root))

        if path == "/api/bootstrap":
            user = self._require_user()
            return self._json(ok(
                session=self.auth.profile(user),
                tree=self._tree_for(user),
                theme=self._theme_for(user),
                dev_mode=self.auth.dev_mode,
            ))

        if path == "/api/bugreports":
            user = self._require_user()
            vals = self._bug_list(user)
            return self._json(ok(reports=vals, stats={
                "total": len(vals),
                "open": sum(1 for b in vals if b.get("status") == "open"),
            }))

        m = re.match(r"^/api/bugreports/([^/]+)/comments$", path)
        if m:
            user = self._require_user()
            bugs = self._bug_load()
            rec = bugs.get(unquote(m.group(1)))
            if not rec:
                raise ProjectError("not_found", "反馈不存在", 404)
            if rec.get("user") != user and not self.auth.is_admin(user):
                raise ProjectError("forbidden", "不能查看别人的反馈", 403)
            return self._json(ok(comments=rec.get("comments") or []))

        if path == "/api/admin/activity":
            self._admin_guard()
            q = parse_qs(parsed.query)
            user_filter = str((q.get("user") or [""])[0] or "")
            days = (q.get("days") or ["365"])[0]
            return self._json(ok(activity=self._activity_stats(user_filter, days)))

        if path == "/api/admin/users":
            viewer = self._admin_guard()
            data = self.auth.usage_summary(viewer)
            return self._json(ok(modules=self._modules(), **data))

        if path == "/api/bugreport":
            user = self._require_user()
            body = self._read_json()
            now = time.time()
            bid = str(body.get("id") or "").strip()
            bugs = self._bug_load()
            old = bugs.get(bid) if bid else None
            if old and old.get("user") != user and not self.auth.is_admin(user):
                raise ProjectError("forbidden", "不能修改别人的反馈", 403)
            if not bid:
                bid = "bug-%d-%04x" % (int(now), secrets.randbelow(0x10000))
            rec = {
                "id": bid,
                "user": old.get("user") if old else user,
                "page": str(body.get("page") or "")[:300],
                "title": str(body.get("title") or "")[:120],
                "detail": str(body.get("detail") or "")[:8000],
                "severity": str(body.get("severity") or "normal")[:20],
                "status": (old.get("status") if old else "open"),
                "created": old.get("created") if old else now,
                "updated": now,
                "comments": list(old.get("comments") or []) if old else [],
            }
            if body.get("draft"):
                if not old:
                    rec["status"] = "draft"
            else:
                rec["status"] = "open" if (not old or old.get("status") == "draft") else old.get("status")
            bugs[bid] = rec
            self._bug_save(bugs)
            self._bug_append_log(rec)
            return self._json(ok(report=rec))

        m = re.match(r"^/api/bugreports/([^/]+)/status$", path)
        if m:
            user = self._require_user()
            if not self.auth.is_admin(user):
                raise ProjectError("forbidden", "需要管理员权限", 403)
            body = self._read_json()
            status = str(body.get("status") or "")
            if status not in ("open", "doing", "fixed", "closed"):
                raise ProjectError("bad_request", "状态不合法", 400)
            bugs = self._bug_load()
            bid = unquote(m.group(1))
            rec = bugs.get(bid)
            if not rec:
                raise ProjectError("not_found", "反馈不存在", 404)
            rec["status"] = status
            rec["updated"] = time.time()
            self._bug_save(bugs)
            self._bug_append_log(rec)
            return self._json(ok(report=rec))

        if path.startswith("/api/admin/"):
            return self._route_admin_post(path)

        if path == "/api/public-theme":
            q = parse_qs(parsed.query or "")
            name = (q.get("user") or [""])[0].strip()
            if not name or name not in self.auth.users:
                raise ProjectError("not_found", "用户不存在", 404)
            return self._json(ok(user=name, theme=self._theme_for(name)))

        if path == "/api/schedule/admin/events":
            user = self._require_user()
            if not self.auth.is_super(user):
                raise ProjectError("forbidden", "仅 superadmin 可查看日程调试", 403)
            self._sched_seed_courses()
            data = self._sched_load()
            events = list(data.get("events") or [])
            events.sort(key=lambda e: (e.get("date") or "", e.get("startMin") or 0))
            return self._json(ok(events=events, users=self._sched_people(), me=user))

        if path == "/api/schedule/courses":
            user = self._require_user()
            if not self._can_access(user, "schedule"):
                raise ProjectError("forbidden", "没有日程访问权限", 403)
            store = self._sched_store()
            def mine(x):
                if not isinstance(x, dict): return False
                if str(x.get("owner") or "") == user: return True
                return user in (x.get("participants") or []) or user in (x.get("mentions") or [])
            courses = [c for c in (store.get("courses") or []) if mine(c)]
            specials = [sp for sp in (store.get("specials") or []) if mine(sp)]
            exams = [e for e in (store.get("exams") or []) if mine(e)]
            return self._json(ok(version=store.get("version") or 2, meta=store.get("meta") or {},
                                 slots=store.get("slots") or [], courses=courses,
                                 specials=specials, exams=exams,
                                 holidays=store.get("holidays") or [], venues=store.get("venues") or []))

        if path == "/api/schedule/venues":
            user = self._require_user()
            if not self._can_access(user, "schedule"):
                raise ProjectError("forbidden", "没有日程访问权限", 403)
            store = self._sched_store()
            if self.command == "POST":
                body = self._read_json()
                incoming = body.get("venues")
                if not isinstance(incoming, list):
                    raise ProjectError("bad_request", "venues 必须是数组", 400)
                merged = []
                for v in incoming[:300]:
                    if not isinstance(v, dict): continue
                    code = str(v.get("code") or "").strip()[:60]
                    name = str(v.get("name") or "").strip()[:120]
                    if not code or not name: continue
                    merged.append({"code": code, "name": name, "short": str(v.get("short") or name)[:120],
                                   "address": str(v.get("address") or "")[:300], "note": str(v.get("note") or "")[:500],
                                   "lat": v.get("lat"), "lng": v.get("lng"), "custom": bool(v.get("custom"))})
                with SCHEDULE_COURSES_LOCK:
                    store["venues"] = merged
                    self._sched_store_save(store)
                return self._json(ok(venues=merged))
            return self._json(ok(venues=store.get("venues") or []))

        if path == "/api/schedule/events":
            user = self._require_user()
            data = self._sched_load()
            events = [e for e in (data.get("events") or []) if self._sched_visible(user, e)]
            events.sort(key=lambda e: (e.get("date") or "", e.get("startMin") or 0))
            return self._json(ok(events=events, users=self._sched_people(), me=user))

        if path == "/api/schedule/participants":
            user = self._require_user()
            q = parse_qs(parsed.query or "")
            date = (q.get("date") or [""])[0]
            try:
                start = int((q.get("startMin") or ["0"])[0])
                end = int((q.get("endMin") or ["0"])[0])
            except Exception:
                raise ProjectError("bad_request", "时间格式不正确", 400)
            if not date or end <= start:
                raise ProjectError("bad_request", "时间段不正确", 400)
            q0 = self._sched_dt(date, start)
            q1 = self._sched_dt(date, end)
            exclude = (q.get("exclude") or [""])[0]
            data = self._sched_load()
            out = []
            for person in self._sched_people():
                busy = None
                for ev in data.get("events") or []:
                    if exclude and str(ev.get("id")) == exclude:
                        continue
                    if person["user"] not in (ev.get("participants") or []):
                        continue
                    e0, e1 = self._sched_interval(ev)
                    if q0 < e1 and e0 < q1:
                        busy = ev
                        break
                out.append({"user": person["user"], "emoji": person["emoji"],
                            "role": person["role"], "available": busy is None,
                            "busy_title": (busy or {}).get("title", ""),
                            "busy_id": (busy or {}).get("id", "")})
            return self._json(ok(users=out, me=user))

        if path == "/api/ai/skills":
            user = self._require_user()
            return self._json(ok(skills=self._ai_skill_catalog(user), enabled=self._ai_skills_enabled(user),
                                 roots=self._ai_skill_roots()))

        if path == "/api/ai/dsh/status":
            user = self._require_user()
            return self._json(ok(dsh=self._dsh_status()))

        if path == "/api/ai/tools":
            user = self._require_user()
            q = parse_qs(urlparse(self.path).query)
            module = str((q.get("module") or [""])[0])[:40]
            return self._json(ok(module=module, tools=self._ai_tool_defs(module)))

        if path == "/api/ai/sessions":
            user = self._require_user()
            return self._json(ok(sessions=self._ai_session_list(user)))

        if path == "/api/ai/sessions/backup":
            user = self._require_user()
            sessions = self._ai_session_list(user, full=True)
            return self._json(ok(version=1, exported=datetime.now(TZ).isoformat(timespec="seconds"),
                                 user=user, sessions=sessions))

        sm = re.match(r"^/api/ai/sessions/([A-Za-z0-9_-]{4,64})$", path)
        if sm:
            user = self._require_user()
            d = self._ai_session_load(user, sm.group(1))
            if not d:
                raise ProjectError("not_found", "会话不存在", 404)
            return self._json(ok(session=self._ai_session_public(d, full=True)))

        if path == "/api/files":
            user = self._require_user()
            idx = self._files_index()
            files = [self._files_public(x) for x in idx.get("files") or [] if x.get("owner") == user]
            files.sort(key=lambda x: x.get("created") or "", reverse=True)
            return self._json(ok(files=files))

        fm = re.match(r"^/api/files/([^/]+)$", path)
        if fm:
            user = self._require_user()
            fid = fm.group(1)
            idx = self._files_index()
            item = next((x for x in idx.get("files") or [] if x.get("id") == fid and x.get("owner") == user), None)
            if not item:
                raise ProjectError("not_found", "文件不存在", 404)
            path_enc = os.path.join(self._files_root(), item.get("stored") or "")
            try:
                with open(path_enc, "rb") as f:
                    token = f.read()
                data = self._files_fernet().decrypt(token)
            except Exception:
                raise ProjectError("internal", "文件解密失败", 500)
            name = item.get("name") or "file"
            ascii_name = re.sub(r'[^A-Za-z0-9._-]', "_", name)[:80] or "file"
            disp = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (ascii_name, quote(name))
            return self._send(data, 200, item.get("mime") or "application/octet-stream", cache="no-store",
                              extra={"Content-Disposition": disp})

        if path == "/api/llm/models":
            user = self._require_user()
            q = parse_qs(urlparse(self.path).query)
            body = {k: (v[0] if v else "") for k, v in q.items()}
            cfg = self._llm_load()
            g = cfg.get("global") or {}
            provider_id = str(body.get("provider_id") or body.get("provider") or "")
            p = next((x for x in self._llm_providers(g) if x.get("id") == provider_id), None) if provider_id else None
            if p:
                base, key, provider = p.get("base_url") or "", (p.get("keys") or [""])[0], p.get("provider") or ""
            else:
                eff = self._llm_effective(user)
                if not eff:
                    raise ProjectError("bad_request", "尚未配置 AI 服务", 400)
                base, key, provider = eff.get("base_url") or "", eff.get("api_key") or "", eff.get("provider") or ""
            base = str(base).strip().rstrip("/")
            if not base:
                raise ProjectError("bad_request", "Base URL 为空", 400)
            headers = {"Authorization": "Bearer " + key} if key else {}
            if provider == "dsh":
                url = base + "/api/models"
            elif base.endswith("/models"):
                url = base
            else:
                url = base + "/models"
            status, data = self._llm_http(url, headers)
            if status == 0 and provider == "dsh":
                status, data = self._llm_http(base + "/v1/models", headers)
            ids = []
            if isinstance(data, dict):
                items = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
                for it in items or []:
                    if isinstance(it, str):
                        ids.append(it)
                    elif isinstance(it, dict):
                        mid = it.get("id") or it.get("name") or it.get("model")
                        if mid:
                            ids.append(str(mid))
            seen = []
            for x in ids:
                if x not in seen:
                    seen.append(x)
            return self._json(ok(models=seen, provider=provider, provider_id=(p or {}).get("id") or "",
                                 status=status, context_window=(p or {}).get("context_window") or 0))

        if path == "/api/llm/status":
            user = self._require_user()
            cfg = self._llm_load()
            g = cfg.get("global") or {}
            me = (cfg.get("users") or {}).get(user) or {"mode": "server"}
            eff = self._llm_effective(user)
            ps = self._llm_providers(g)
            active = self._llm_active_provider(g)
            return self._json(ok(
                server=self._llm_public(g, "server"),
                me={"mode": me.get("mode") or "server", **self._llm_public(me, me.get("mode") or "server")},
                effective=self._llm_public(eff, eff.get("source") if eff else None),
                providers=[self._llm_provider_public(p, p.get("id") == (active or {}).get("id")) for p in ps],
                message=("未配置服务端 AI，请联系管理员" if not ps else ""),
            ))

        if path == "/api/llm/admin":
            user = self._require_user()
            if not self.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可查看全局 AI 配置", 403)
            cfg = self._llm_load()
            g = cfg.get("global") or {}
            active = self._llm_active_provider(g)
            return self._json(ok(global_=self._llm_public(g, "server"),
                                 providers=[self._llm_provider_public(p, p.get("id") == (active or {}).get("id")) for p in self._llm_providers(g)],
                                 mineru=self._mineru_public(),
                                 kinds=["deepseek", "openai", "anthropic", "openrouter", "moonshot",
                                        "zhipu", "qwen", "groq", "mistral", "ollama", "dsh", "local", "custom"]))

        if path == "/api/birthday/public":
            # Unauthenticated landing pages only learn that today is somebody's
            # birthday; no usernames or dates are exposed.
            active = any(self._birthday_today(u) for u in self.auth.users)
            return self._json(ok(active=bool(active)))

        if path == "/api/birthday":
            user = self._require_user()
            return self._json(ok(birthday=self._load_birthdays().get(user, ""), today=self._birthday_today(user), age=self._birthday_age(user)))

        if path == "/api/theme":
            user = self._require_user()
            return self._json(ok(theme=self._theme_for(user)))

        if path == "/api/users/public":
            user = self._require_user()
            users = []
            for u in sorted(self.auth.users):
                rec = self.auth.users.get(u) or {}
                if not rec.get("active", True):
                    continue
                pal = self._theme_for(u) or {}
                users.append({"user": u, "emoji": rec.get("emoji") or "👤",
                              "color": pal.get("color") or "#9bd1ec",
                              "deep": pal.get("deep") or pal.get("color") or "#9bd1ec"})
            return self._json(ok(users=users))

        if path == "/api/tree":
            user = self._require_user()
            return self._json(ok(session=self.auth.profile(user), **self._tree_for(user)))

        if path == "/api/session":
            user = self._session_user()
            if not user:
                return self._json(ok(session=None, dev_mode=self.auth.dev_mode))
            return self._json(ok(session=self.auth.profile(user), dev_mode=self.auth.dev_mode))

        if path.startswith("/mock/api/"):
            return self._serve_mock("GET")

        # ---- 新协议 ----
        m = PID_RE.match(path)
        if m:
            pid, verb = m.group(1), m.group(2)
            user = self._require_user()
            project = self.registry.get(pid)
            if not project:
                raise ProjectError("unsupported_project", "没有这个项目：%s" % pid, 404)
            if not self._can_access(user, pid):
                raise ProjectError("forbidden", "没有 %s 的访问权限" % pid, 403)
            if verb in ("state", None):
                rev, data = project.state(user)
                manifest = project.manifest()
                etag = 'W/"%s-%d"' % (pid, rev)
                return self._json(ok(
                    project=pid, rev=rev, data=data,
                    manifest={k: manifest.get(k) for k in
                              ("id", "title", "icon", "base", "desc", "capabilities", "acl", "view", "ui")},
                ), etag=etag)
            raise ProjectError("not_found", "未知的 API 动词", 404)

        if path == "/api/messages/threads":
            user = self._require_user()
            data = message_store.threads(user, sorted(self.auth.users.keys()))
            data["unread"] = message_store.unread(user)
            return self._json(ok(**data))

        if path == "/api/messages/thread":
            user = self._require_user()
            peer = str((parse_qs(parsed.query).get("peer") or [""])[0])
            if peer not in self.auth.users or peer == user:
                raise ProjectError("bad_request", "收件人不存在", 400)
            return self._json(ok(peer=peer, messages=message_store.conversation(user, peer)))

        if path == "/api/messages/export":
            user = self._require_user()
            q = parse_qs(parsed.query)
            fmt = str((q.get("format") or ["json"])[0]).lower()
            if fmt not in ("json", "csv", "txt"):
                fmt = "json"
            notes = notification_store.list_for(user, 1000)
            dms = message_store.all_for(user, 20000)
            exported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if fmt == "json":
                payload = json.dumps({"user": user, "exported_at": exported_at, "notifications": notes, "direct_messages": dms}, ensure_ascii=False, indent=1).encode("utf-8")
            elif fmt == "csv":
                import csv as _csv
                out = io.StringIO()
                w = _csv.writer(out)
                w.writerow(["type", "module", "kind", "from", "to", "title", "body", "created", "read"])
                for it in notes:
                    w.writerow(["notification", it.get("module", ""), it.get("kind", ""), "", user, it.get("title", ""), it.get("body", ""), it.get("created", ""), "1" if it.get("read") else "0"])
                for it in dms:
                    w.writerow(["direct", "dm", "", it.get("from", ""), it.get("to", ""), "", it.get("body", ""), it.get("created", ""), "1" if it.get("read") else "0"])
                payload = out.getvalue().encode("utf-8")
            else:
                lines = ["messages export for %s (%s)" % (user, exported_at), ""]
                for it in notes:
                    lines.append("[notification/%s] %s — %s" % (it.get("module", ""), it.get("title", ""), it.get("body", "")))
                for it in dms:
                    lines.append("[direct] %s → %s: %s" % (it.get("from", ""), it.get("to", ""), it.get("body", "")))
                payload = ("\n".join(lines) + "\n").encode("utf-8")
            compress = str((q.get("gzip") or ["1"])[0]).lower() not in ("0", "false", "no")
            if compress:
                payload = gzip.compress(payload, mtime=0)
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            ext = fmt + (".gz" if compress else "")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream" if compress else ("text/csv; charset=utf-8" if fmt == "csv" else "text/plain; charset=utf-8" if fmt == "txt" else "application/json; charset=utf-8"))
            self.send_header("Content-Disposition", 'attachment; filename="messages-%s-%s.%s"' % (user, stamp, ext))
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/notifications":
            user = self._require_user()
            q = parse_qs(parsed.query)
            try:
                limit = int((q.get("limit") or ["200"])[0])
            except Exception:
                limit = 200
            data = notification_store.summary(user)
            note_items = data["items"][:max(1, min(500, limit))]
            return self._json(ok(items=note_items, unread=data["unread"], modules=data["modules"], server_time=time.time()))

        # ---- 旧页面托管 ----
        if path.startswith("/legacy/"):
            return self._serve_legacy(path[len("/legacy/"):], parsed.query)

        m = VIEW_RE.match(path)
        if m:
            return self._serve_view(m.group(1), m.group(2) or "/")

        self._not_found()

    # ---------------- POST ----------------
    def _route_post(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/messages/send":
            user = self._require_user()
            body = self._read_json()
            to = str(body.get("to") or "").strip()
            text = str(body.get("body") or "").strip()
            if to not in self.auth.users or to == user:
                raise ProjectError("bad_request", "收件人不存在", 400)
            if not text:
                raise ProjectError("bad_request", "消息不能为空", 400)
            item = message_store.send(user, to, text)
            return self._json(ok(message=item))

        if path == "/api/messages/read":
            user = self._require_user()
            body = self._read_json()
            changed = message_store.mark_read(user, str(body.get("peer") or ""), bool(body.get("all")))
            return self._json(ok(changed=changed, unread=message_store.unread(user)))

        if path == "/api/notifications/read":
            user = self._require_user()
            body = self._read_json()
            result = notification_store.mark_read(
                user,
                ids=body.get("ids") if isinstance(body.get("ids"), list) else [],
                module=str(body.get("module") or ""),
                mark_all=bool(body.get("all")),
            )
            return self._json(ok(**result))

        if path == "/api/activity":
            user = self._require_user()
            try:
                body = self._read_json()
            except Exception:
                body = {}
            kind = str((body or {}).get("kind") or "heartbeat")[:16]
            module = str((body or {}).get("module") or "")[:80]
            self._activity_record(user, kind, module)
            return self._json(ok(recorded=True))

        if path == "/api/ai/dsh/stream":
            user = self._require_user()
            body = self._read_json()
            self._dsh_stream(user, body)
            return

        if path == "/api/ai/skills/toggle":
            user = self._require_user()
            body = self._read_json()
            name = str(body.get("name") or "").strip()[:120]
            if not name:
                raise ProjectError("bad_request", "缺少 skill 名称", 400)
            enabled = self._ai_skill_toggle(user, name, bool(body.get("enabled")))
            return self._json(ok(enabled=enabled))

        if path == "/api/ai/skills/import":
            user = self._require_user()
            body = self._read_json()
            name = str(body.get("name") or "").strip()[:80]
            desc = str(body.get("description") or "").strip()[:500]
            content = str(body.get("content") or "").strip()
            if not name or not content:
                raise ProjectError("bad_request", "需要 name 与 content", 400)
            slug = re.sub(r"[^A-Za-z0-9_.-]", "-", name).strip("-") or ("skill-" + secrets.token_hex(3))
            d = os.path.join(self.server.root, "skills", slug)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: %s\ndescription: %s\n---\n\n%s\n" % (name, desc or name, content))
            self._ai_skill_toggle(user, name, True)
            return self._json(ok(skill={"name": name, "path": os.path.join(d, "SKILL.md")}))

        if path == "/api/ai/dsh/stop":
            user = self._require_user()
            body = self._read_json()
            rid = str(body.get("run_id") or "").strip()
            stopped = False
            with DSH_RUNS_LOCK:
                run = DSH_RUNS.get(rid)
                if run and run.get("user") == user:
                    try:
                        run["proc"].kill(); stopped = True
                    except Exception:
                        pass
                    run["stopped"] = True
            return self._json(ok(stopped=stopped))

        if path == "/api/ai/dsh/chat":
            user = self._require_user()
            body = self._read_json()
            module = str(body.get("module") or "")[:40]
            text = str(body.get("text") or "").strip()
            if not text:
                raise ProjectError("bad_request", "消息为空", 400)
            if module:
                proj = self.registry.get(module)
                if not proj or not self._can_access(user, module):
                    raise ProjectError("forbidden", "当前模块不可访问：" + module, 403)
            psid = str(body.get("platform_session_id") or "")
            session = self._ai_session_load(user, psid) if psid else None
            dsh_id = str(body.get("dsh_session_id") or (session or {}).get("dsh_session_id") or "")
            transcript = ""
            if session and not dsh_id:
                msgs = (session.get("messages") or [])[-20:]
                if msgs:
                    transcript = "\n\n".join(("用户回答：" if m.get("role") == "answer" else "用户：" if m.get("role") == "user" else "AI：") + str(m.get("content") or "") for m in msgs)
            file_notes = self._dsh_file_notes(user, body.get("files") or [])
            proj = self.registry.get(module) if module else None
            module_title = (proj.manifest().get("title") if proj else module) or "工作台"
            prompt = "你是 KittenPuppy4Ever 工作台内的 AI 助手。\n"
            prompt += "当前用户：%s\n当前模块：%s（%s）\n" % (user, module_title, module or "无")
            prompt += "请在该模块上下文中帮助用户；需要操作模块时使用可用工具，并说明实际执行结果。\n"
            if transcript:
                prompt += "\n之前的对话：\n" + transcript + "\n"
            if file_notes:
                prompt += "\n" + "\n\n".join(file_notes) + "\n"
            prompt += "\n用户消息：\n" + text
            result = self._dsh_run(user, module, prompt, dsh_id,
                                   model=str(body.get("model") or "")[:120],
                                   effort=str(body.get("effort") or "")[:20])
            new_dsh = result.get("dsh_session_id") or dsh_id
            if session and new_dsh and session.get("dsh_session_id") != new_dsh:
                session["dsh_session_id"] = new_dsh
                try: self._ai_session_save(user, session)
                except Exception: pass
            ui = None
            if module == "scratchpad":
                ui = {"module": module, "actions": [{"type": "focus", "selector": "#new-text"},
                                                    {"type": "refresh", "selector": "#list"}]}
            elif module == "schedule":
                ui = {"module": module, "actions": [{"type": "click", "selector": "#gridwrap"},
                                                    {"type": "refresh", "selector": "#mylist"}]}
            return self._json(ok(reply=result.get("reply") or "", dsh_session_id=new_dsh,
                                 usage=result.get("usage") or {}, events=result.get("events") or [],
                                 module=module, ui=ui, ui_events=result.get("ui_events") or [],
                                 model=result.get("model") or "", effort=result.get("effort") or "",
                                 context_window=result.get("context_window") or 0))

        if path == "/api/dsh/tool":
            token = (self.headers.get("X-KP-Bridge") or "").strip()
            with DSH_TOKENS_LOCK:
                rec = DSH_TOKENS.get(token)
                if not rec or rec.get("expires", 0) < time.time():
                    raise ProjectError("unauthorized", "DSH Bridge token 无效或已过期", 401)
                user, module = rec.get("user"), rec.get("module")
            body = self._read_json()
            mod = str(body.get("module") or module or "")[:40]
            if mod != (module or ""):
                raise ProjectError("forbidden", "Bridge token 不允许跨模块", 403)
            tool = str(body.get("tool") or "")[:80]
            result = self._ai_tool_execute(user, mod, tool, body.get("args") or {}, dry_run=bool(body.get("dry_run")))
            ui = result.get("ui") if isinstance(result, dict) else None
            if ui:
                with DSH_TOKENS_LOCK:
                    if token in DSH_TOKENS:
                        DSH_TOKENS[token].setdefault("ui", []).append(ui)
            return self._json(ok(result=result, module=mod, tool=tool))

        if path == "/api/ai/tools/execute":
            user = self._require_user()
            body = self._read_json()
            module = str(body.get("module") or "")[:40]
            name = str(body.get("tool") or "")[:80]
            result = self._ai_tool_execute(user, module, name, body.get("args") or {}, dry_run=bool(body.get("dry_run")))
            return self._json(ok(dry_run=bool(body.get("dry_run")), result=result))

        if path == "/api/ai/sessions/save":
            user = self._require_user()
            body = self._read_json()
            session = body.get("session") if isinstance(body.get("session"), dict) else body
            sid = self._ai_session_id(session.get("id"))
            session["id"] = sid
            if body.get("dry_run"):
                # Validate/shape in memory, do not write any server state.
                preview = {"id": sid, "title": str(session.get("title") or "新对话")[:120],
                           "module": str(session.get("module") or "")[:40],
                           "messages": session.get("messages") or [], "usage": session.get("usage") or {},
                           "context_window": session.get("context_window") or 0}
                return self._json(ok(dry_run=True, session=self._ai_session_public(preview, full=True)))
            data = self._ai_session_save(user, session)
            return self._json(ok(session=self._ai_session_public(data, full=True)))

        if path == "/api/ai/sessions/flags":
            user = self._require_user()
            body = self._read_json()
            d = self._ai_session_flags(user, body.get("id"),
                                       body.get("archived") if "archived" in body else None,
                                       body.get("pinned") if "pinned" in body else None)
            return self._json(ok(session=self._ai_session_public(d, full=False)))

        if path == "/api/ai/sessions/delete":
            user = self._require_user()
            body = self._read_json()
            okdel = self._ai_session_delete(user, body.get("id"))
            return self._json(ok(deleted=bool(okdel)))

        if path == "/api/ai/sessions/import":
            user = self._require_user()
            body = self._read_json()
            mode = str(body.get("mode") or "new")
            if mode not in ("overwrite", "new"):
                raise ProjectError("bad_request", "导入模式不合法", 400)
            items = body.get("sessions") if isinstance(body.get("sessions"), list) else ([body.get("session")] if isinstance(body.get("session"), dict) else [])
            items = [x for x in items if isinstance(x, dict)]
            if not items:
                raise ProjectError("bad_request", "导入内容为空", 400)
            if body.get("dry_run"):
                return self._json(ok(dry_run=True, imported=len(items), mode=mode,
                                     sessions=[self._ai_session_public(x, full=True) for x in items[:20]]))
            saved = []
            for item in items[:500]:
                item = dict(item)
                if mode == "overwrite" and item.get("id"):
                    item["id"] = self._ai_session_id(item["id"])
                else:
                    item["id"] = self._ai_session_id("")
                saved.append(self._ai_session_public(self._ai_session_save(user, item), full=True))
            return self._json(ok(imported=len(saved), mode=mode, sessions=saved))

        if path == "/api/files/upload":
            user = self._require_user()
            body = self._read_json()
            name = os.path.basename(str(body.get("name") or "file")).strip()[:180] or "file"
            mime = str(body.get("mime") or "application/octet-stream")[:120]
            raw = str(body.get("data") or "")
            if "," in raw and raw.lstrip().startswith("data:"):
                raw = raw.split(",", 1)[1]
            try:
                data = base64.b64decode(raw, validate=True)
            except Exception:
                raise ProjectError("bad_request", "文件内容不是合法 base64", 400)
            if not data:
                raise ProjectError("bad_request", "文件为空", 400)
            if len(data) > 16 * 1024 * 1024:
                raise ProjectError("bad_request", "文件不能超过 16MB", 413)
            if body.get("dry_run"):
                token = self._files_fernet().encrypt(data)
                dec = self._files_fernet().decrypt(token)
                return self._json(ok(dry_run=True, file={"name": name, "mime": mime, "size": len(data),
                                                         "sha256": hashlib.sha256(data).hexdigest(),
                                                         "encrypted": len(token) > 0, "roundtrip": dec == data}))
            fid = secrets.token_hex(12)
            safe_user = re.sub(r"[^A-Za-z0-9_.-]", "_", user)[:60] or "user"
            rel = os.path.join(safe_user, fid + ".bin")
            full = os.path.join(self._files_root(), rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            token = self._files_fernet().encrypt(data)
            with open(full, "wb") as f:
                f.write(token)
            item = {"id": fid, "owner": user, "name": name, "mime": mime,
                    "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "created": datetime.now(TZ).isoformat(timespec="seconds"),
                    "stored": rel, "enc": "fernet"}
            with FILES_LOCK:
                idx = self._files_index()
                idx.setdefault("files", []).append(item)
                self._files_save_index(idx)
            return self._json(ok(file=self._files_public(item)))

        if path == "/api/files/delete":
            user = self._require_user()
            body = self._read_json()
            fid = str(body.get("id") or "")
            with FILES_LOCK:
                idx = self._files_index()
                item = next((x for x in idx.get("files") or [] if x.get("id") == fid and x.get("owner") == user), None)
                if not item:
                    raise ProjectError("not_found", "文件不存在", 404)
                idx["files"] = [x for x in idx.get("files") or [] if not (x.get("id") == fid and x.get("owner") == user)]
                self._files_save_index(idx)
            try:
                os.remove(os.path.join(self._files_root(), item.get("stored") or ""))
            except Exception:
                pass
            return self._json(ok(deleted=fid))

        m = re.match(r"^/api/bugreports/([^/]+)/comments$", path)
        if m:
            user = self._require_user()
            body = self._read_json()
            text = str(body.get("text") or "").strip()
            if not text:
                raise ProjectError("bad_request", "回复内容不能为空", 400)
            bugs = self._bug_load()
            bid = unquote(m.group(1))
            rec = bugs.get(bid)
            if not rec:
                raise ProjectError("not_found", "反馈不存在", 404)
            if rec.get("user") != user and not self.auth.is_admin(user):
                raise ProjectError("forbidden", "不能回复别人的反馈", 403)
            comments = list(rec.get("comments") or [])
            comments.append({"id": "c-%d-%04x" % (int(time.time()), secrets.randbelow(0x10000)),
                             "user": user, "text": text[:4000], "created": time.time()})
            rec["comments"] = comments
            rec["updated"] = time.time()
            bugs[bid] = rec
            self._bug_save(bugs)
            self._bug_append_log(rec)
            return self._json(ok(comments=comments))

        if path == "/api/bugreport":
            user = self._require_user()
            body = self._read_json()
            now = time.time()
            bid = str(body.get("id") or "").strip()
            bugs = self._bug_load()
            old = bugs.get(bid) if bid else None
            if old and old.get("user") != user and not self.auth.is_admin(user):
                raise ProjectError("forbidden", "不能修改别人的反馈", 403)
            if not bid:
                bid = "bug-%d-%04x" % (int(now), secrets.randbelow(0x10000))
            rec = {
                "id": bid,
                "user": old.get("user") if old else user,
                "page": str(body.get("page") or "")[:300],
                "title": str(body.get("title") or "")[:120],
                "detail": str(body.get("detail") or "")[:8000],
                "severity": str(body.get("severity") or "normal")[:20],
                "status": (old.get("status") if old else "open"),
                "created": old.get("created") if old else now,
                "updated": now,
                "comments": list(old.get("comments") or []) if old else [],
            }
            if body.get("draft"):
                if not old:
                    rec["status"] = "draft"
            else:
                rec["status"] = "open" if (not old or old.get("status") == "draft") else old.get("status")
            bugs[bid] = rec
            self._bug_save(bugs)
            self._bug_append_log(rec)
            return self._json(ok(report=rec))

        m = re.match(r"^/api/bugreports/([^/]+)/status$", path)
        if m:
            user = self._require_user()
            if not self.auth.is_admin(user):
                raise ProjectError("forbidden", "需要管理员权限", 403)
            body = self._read_json()
            status = str(body.get("status") or "")
            if status not in ("open", "doing", "fixed", "closed"):
                raise ProjectError("bad_request", "状态不合法", 400)
            bugs = self._bug_load()
            bid = unquote(m.group(1))
            rec = bugs.get(bid)
            if not rec:
                raise ProjectError("not_found", "反馈不存在", 404)
            rec["status"] = status
            rec["updated"] = time.time()
            self._bug_save(bugs)
            self._bug_append_log(rec)
            return self._json(ok(report=rec))

        if path.startswith("/api/admin/"):
            return self._route_admin_post(path)

        if path == "/api/birthday":
            user = self._require_user()
            body = self._read_json()
            val = str(body.get("birthday") or "").strip()
            if val and not re.match(r"^\d{2}-\d{2}$", val) and not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                raise ProjectError("bad_request", "生日格式应为 MM-DD 或 YYYY-MM-DD", 400)
            if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    raise ProjectError("bad_request", "生日日期不合法", 400)
            return self._json(ok(birthday=self._save_birthday(user, val)))

        if path == "/api/theme":
            user = self._require_user()
            if self._birthday_today(user):
                return self._json(ok(theme=self._birthday_palette(user), saved=False, locked=True), status=200)
            body = self._read_json()
            color = _hex_color((body or {}).get("color"))
            if not color:
                raise ProjectError("bad_request", "主题色必须是 #rrggbb", 400)
            colormap = str((body or {}).get("colormap") or "monochrome")
            if colormap not in COLORMAPS:
                raise ProjectError("bad_request", "未知的色彩模板", 400)
            return self._json(ok(theme=self._save_theme(user, color, colormap)))

        if path == "/api/register":
            body = self._read_json()
            user = str(body.get("user") or "").strip()
            password = str(body.get("password") or "")
            if not user or len(password) < 6:
                raise ProjectError("bad_request", "用户名必填，口令至少 6 位", 400)
            good, msg = self.auth.create_user(user, password, "user")
            if not good:
                raise ProjectError("bad_request", msg, 400)
            rec = self.auth.users[user]
            rec["emoji"] = "👤"
            rec["modules"] = {pid: True for pid in self.registry.projects}
            self.auth.save_users()
            self._save_theme(user, "#ec9fbe", "pinkfdu")
            return self._json(ok(session=self.auth.profile(user)))

        if path == "/api/schedule/admin/events":
            user = self._require_user()
            if not self.auth.is_super(user):
                raise ProjectError("forbidden", "仅 superadmin 可修改日程调试", 403)
            body = self._read_json()
            data = self._sched_load()
            eid = str(body.get("id") or "")
            old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None) if eid else None
            ev = self._sched_payload(body, old)
            creator = str(body.get("creator") or (old.get("creator") if old else user))
            ev["creator"] = creator if creator in self.auth.users else user
            ev["mentions"] = list(body.get("mentions") or (old.get("mentions") if old else [])) or [ev["creator"]]
            now = time.time()
            ev["updated_at"] = now
            ev["created_at"] = (old or {}).get("created_at") or now
            for participant in ev.get("participants") or []:
                conflict = self._sched_conflict(data, ev, participant)
                if conflict:
                    raise ProjectError("conflict", "%s 在该时段已有日程「%s」" % (participant, conflict.get("title") or ""), 409)
            if old:
                data["events"] = [ev if str(e.get("id")) == eid else e for e in data.get("events") or []]
            else:
                data.setdefault("events", []).append(ev)
            with SCHEDULE_LOCK:
                self._sched_save(data)
            return self._json(ok(event=ev))

        if path == "/api/schedule/admin/events/delete":
            user = self._require_user()
            if not self.auth.is_super(user):
                raise ProjectError("forbidden", "仅 superadmin 可删除日程", 403)
            body = self._read_json()
            eid = str(body.get("id") or "")
            data = self._sched_load()
            old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None)
            if old and old.get("source") == "course":
                data.setdefault("deleted_course_ids", []).append(eid)
            data["events"] = [e for e in data.get("events") or [] if str(e.get("id")) != eid]
            with SCHEDULE_LOCK:
                self._sched_save(data)
            return self._json(ok(deleted=eid))

        if path == "/api/schedule/events":
            user = self._require_user()
            body = self._read_json()
            data = self._sched_load()
            eid = str(body.get("id") or "")
            old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None) if eid else None
            if old and not self._sched_event_can(user, old, "write"):
                raise ProjectError("forbidden", "只有创建者或参与者可以修改日程", 403)
            ev = self._sched_payload(body, old)
            ev["creator"] = str(old.get("creator")) if old else user
            if not ev.get("mentions"):
                ev["mentions"] = [user]
            now = time.time()
            ev["updated_at"] = now
            if old:
                ev["created_at"] = old.get("created_at") or now
            else:
                ev["created_at"] = now
            for participant in ev.get("participants") or []:
                conflict = self._sched_conflict(data, ev, participant)
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
            with SCHEDULE_LOCK:
                self._sched_save(data)
            return self._json(ok(event=ev))

        if path == "/api/schedule/events/delete":
            user = self._require_user()
            body = self._read_json()
            eid = str(body.get("id") or "")
            data = self._sched_load()
            old = next((e for e in data.get("events") or [] if str(e.get("id")) == eid), None)
            if not old:
                raise ProjectError("not_found", "日程不存在", 404)
            if not self._sched_event_can(user, old, "delete"):
                raise ProjectError("forbidden", "只有创建者可以删除日程", 403)
            data["events"] = [e for e in data.get("events") or [] if str(e.get("id")) != eid]
            with SCHEDULE_LOCK:
                self._sched_save(data)
            return self._json(ok(deleted=eid))

        if path == "/api/llm/admin/mineru":
            user = self._require_user()
            if not self.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可设置 MinerU", 403)
            body = self._read_json()
            self._mineru_save(token=body.get("token"), clear=bool(body.get("clear")))
            return self._json(ok(mineru=self._mineru_public()))

        if path == "/api/llm/admin/mineru/check":
            user = self._require_user()
            if not self.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可检查 MinerU", 403)
            body = self._read_json()
            return self._json(ok(check=self._mineru_check(body.get("token"))))

        if path == "/api/llm/admin":
            user = self._require_user()
            if not self.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可设置全局 AI", 403)
            body = self._read_json()
            cfg = self._llm_load()
            old_g = cfg.get("global") or {}
            old_ps = {p.get("id"): p for p in self._llm_providers(old_g)}
            if isinstance(body.get("providers"), list):
                out, first = [], None
                for idx, p in enumerate(body.get("providers") or []):
                    if not isinstance(p, dict):
                        continue
                    base = str(p.get("base_url") or "").strip()[:500]
                    if not base:
                        continue
                    provider = str(p.get("provider") or "").strip()[:40] or self._llm_detect(base)
                    pid = str(p.get("id") or provider or ("p%d" % idx)).strip()[:60]
                    oldp = old_ps.get(pid) or {}
                    keys = self._llm_keys(oldp.get("keys"))
                    text = p.get("keys_text")
                    if text is not None:
                        text = str(text).strip()
                        if text in ("__CLEAR__", "CLEAR"):
                            keys = []
                        elif text:
                            keys = self._llm_keys(text.splitlines())
                    elif isinstance(p.get("keys"), list):
                        keys = self._llm_keys(p.get("keys"))
                    item = {"id": pid, "name": str(p.get("name") or pid)[:80],
                            "provider": provider, "base_url": base,
                            "model": str(p.get("model") or "").strip()[:120],
                            "context_window": int(p.get("context_window") or 0),
                            "keys": keys, "enabled": bool(p.get("enabled", True))}
                    out.append(item)
                    if p.get("active"):
                        first = item
                if not out:
                    raise ProjectError("bad_request", "至少配置一个可用的服务商", 400)
                first = first or out[0]
                clean = {"provider": first["provider"], "base_url": first["base_url"],
                         "api_key": (first["keys"] or [""])[0], "model": first["model"],
                         "context_window": first["context_window"],
                         "enabled": first["enabled"]}
                cfg["global"] = {**clean, "providers": out, "active_provider": first["id"],
                                 "effort": str(body.get("effort") or old_g.get("effort") or "medium")[:20]}
            else:
                clean = self._llm_clean(body)
                if body.get("api_key") is None and old_g.get("api_key"):
                    clean["api_key"] = old_g["api_key"]
                if str(body.get("api_key") or "").strip() in ("__CLEAR__", "CLEAR"):
                    clean["api_key"] = ""
                cfg["global"] = clean
            self._llm_save(cfg)
            g = cfg.get("global") or {}
            active = self._llm_active_provider(g)
            return self._json(ok(global_=self._llm_public(g, "server"),
                                 providers=[self._llm_provider_public(p, p.get("id") == (active or {}).get("id")) for p in self._llm_providers(g)]))

        if path == "/api/llm/me":
            user = self._require_user()
            body = self._read_json()
            cfg = self._llm_load()
            users = cfg.setdefault("users", {})
            cur = users.get(user) or {}
            mode = str(body.get("mode") or cur.get("mode") or "server")
            if mode not in ("server", "override"):
                raise ProjectError("bad_request", "模式不合法", 400)
            clean = self._llm_clean(body)
            if not body.get("api_key") and cur.get("api_key"):
                clean["api_key"] = cur["api_key"]
            if str(body.get("api_key") or "").strip() in ("__CLEAR__", "CLEAR"):
                clean["api_key"] = ""
            clean["mode"] = mode
            if mode == "server":
                g = cfg.get("global") or {}
                if not (g.get("base_url") and g.get("enabled", True)):
                    raise ProjectError("bad_request", "服务端尚未配置 AI，请联系管理员", 400)
            users[user] = clean
            self._llm_save(cfg)
            return self._json(ok(me={"mode": mode, **self._llm_public(clean, mode)}))

        if path == "/api/llm/test":
            user = self._require_user()
            body = self._read_json()
            cfg = self._llm_effective(user)
            if body.get("scope") == "global":
                if not self.auth.is_admin(user):
                    raise ProjectError("forbidden", "仅管理员可测试全局配置", 403)
                cfg = self._llm_load().get("global") or {}
            if not cfg or not cfg.get("base_url"):
                raise ProjectError("bad_request", "尚未配置 AI 服务", 400)
            base = cfg["base_url"].rstrip("/")
            provider = cfg.get("provider") or self._llm_detect(base)
            if provider == "dsh":
                status, data = self._llm_http(base + "/api/health", {"Authorization": "Bearer " + (cfg.get("api_key") or "")})
                return self._json(ok(reachable=status in (200, 401), status=status,
                                     message=("本机 DSH 可达" if status in (200, 401) else "本机 DSH 不可达"),
                                     data=data))
            url = base if base.endswith("/models") else base + "/models"
            headers = {"Authorization": "Bearer " + cfg.get("api_key", "")} if cfg.get("api_key") else {}
            status, data = self._llm_http(url, headers)
            return self._json(ok(reachable=200 <= status < 300, status=status, provider=provider, data=data))

        if path == "/api/llm/models":
            user = self._require_user()
            body = {}
            if self.command == "POST":
                body = self._read_json()
            else:
                q = parse_qs(urlparse(self.path).query)
                body = {k: (v[0] if v else "") for k, v in q.items()}
            cfg = self._llm_load()
            g = cfg.get("global") or {}
            provider_id = str(body.get("provider_id") or body.get("provider") or "")
            p = next((x for x in self._llm_providers(g) if x.get("id") == provider_id), None) if provider_id else None
            if p:
                base, key, provider = p.get("base_url") or "", (p.get("keys") or [""])[0], p.get("provider") or ""
            else:
                eff = self._llm_effective(user)
                if not eff:
                    raise ProjectError("bad_request", "尚未配置 AI 服务", 400)
                base, key, provider = eff.get("base_url") or "", eff.get("api_key") or "", eff.get("provider") or ""
            base = str(body.get("base_url") or base).strip().rstrip("/")
            key = str(body.get("api_key") or key)
            provider = str(body.get("provider") or provider or self._llm_detect(base))
            if not base:
                raise ProjectError("bad_request", "Base URL 为空", 400)
            headers = {"Authorization": "Bearer " + key} if key else {}
            if provider == "dsh":
                url = base + "/api/models"
            elif base.endswith("/models"):
                url = base
            else:
                url = base + "/models"
            status, data = self._llm_http(url, headers)
            if status == 0 and provider == "dsh":
                status, data = self._llm_http(base + "/v1/models", headers)
            ids = []
            if isinstance(data, dict):
                items = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
                for it in items or []:
                    if isinstance(it, str):
                        ids.append(it)
                    elif isinstance(it, dict):
                        mid = it.get("id") or it.get("name") or it.get("model")
                        if mid:
                            ids.append(str(mid))
            seen = []
            for x in ids:
                if x not in seen:
                    seen.append(x)
            return self._json(ok(models=seen, provider=provider, provider_id=(p or {}).get("id") or "",
                                 status=status, context_window=(p or {}).get("context_window") or 0))

        if path == "/api/llm/chat":
            user = self._require_user()
            body = self._read_json()
            provider_id = str(body.get("provider_id") or "")
            cfg = self._llm_effective(user, provider_id or None)
            if not cfg or not cfg.get("base_url"):
                raise ProjectError("bad_request", "未配置 AI 服务，请联系管理员", 400)
            messages = body.get("messages") or []
            if not isinstance(messages, list) or not messages:
                raise ProjectError("bad_request", "messages 不能为空", 400)
            module = str(body.get("module") or "")[:40]
            if module:
                proj = self.registry.get(module)
                if not proj or not self._can_access(user, module):
                    raise ProjectError("forbidden", "当前模块不可访问：" + module, 403)
            dry_run = bool(body.get("dry_run"))
            file_notes = self._dsh_file_notes(user, body.get("files") or [])
            if file_notes:
                messages = [{"role": "system", "content": "用户上传了以下文件：\n\n" + "\n\n".join(file_notes)}] + messages
            tool_prompt = self._ai_tool_prompt(module, user) if module else ""
            if tool_prompt:
                messages = [{"role": "system", "content": tool_prompt}] + messages
            model = str(body.get("model") or cfg.get("model") or "deepseek-chat")[:160]
            effort = str(body.get("effort") or cfg.get("effort") or "medium")[:20]
            base = cfg["base_url"].rstrip("/")
            if base.endswith("/chat/completions"):
                url = base
            elif base.endswith("/v1"):
                url = base + "/chat/completions"
            else:
                url = base + "/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            if cfg.get("api_key"):
                headers["Authorization"] = "Bearer " + cfg["api_key"]
            tool_results = []
            reply = ""
            data = {}
            for round_no in range(3):
                payload = {"model": model, "messages": messages, "stream": False}
                if effort and effort != "medium":
                    payload["reasoning_effort"] = effort
                status, data = self._llm_http(url, headers, payload, timeout=int(body.get("timeout") or 60))
                if not (200 <= status < 300):
                    raise ProjectError("upstream_error", "AI 服务返回 %s：%s" % (status, str(data)[:300]), 502)
                try:
                    reply = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                except Exception:
                    reply = ""
                parsed = None
                txt = str(reply or "").strip()
                if txt.startswith("```"):
                    txt = re.sub(r"^```[a-zA-Z]*\s*", "", txt)
                    txt = re.sub(r"\s*```$", "", txt)
                try:
                    cand = json.loads(txt)
                    if isinstance(cand, dict) and cand.get("tool"):
                        parsed = cand
                except Exception:
                    parsed = None
                if not parsed or round_no >= 2:
                    break
                name = str(parsed.get("tool") or "")
                args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
                try:
                    result = self._ai_tool_execute(user, module, name, args, dry_run=dry_run)
                except Exception as e:
                    result = {"error": str(getattr(e, "message", e))}
                tool_results.append({"tool": name, "args": args, "result": result})
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "system", "content": "工具 %s 执行结果：%s" % (name, json.dumps(result, ensure_ascii=False)[:4000])})
            usage = (data.get("usage") if isinstance(data, dict) else None) or {}
            def rough_tokens(text):
                return max(1, int(len(text or "") / 3))
            pt = usage.get("prompt_tokens") or sum(rough_tokens(m.get("content") if isinstance(m, dict) else "") for m in messages)
            ct = usage.get("completion_tokens") or rough_tokens(reply)
            total = usage.get("total_tokens") or (pt + ct)
            return self._json(ok(reply=reply, raw=data, provider=cfg.get("provider"), model=model,
                                 effort=effort, tool_results=tool_results,
                                 usage={"prompt_tokens": int(pt), "completion_tokens": int(ct),
                                        "total_tokens": int(total),
                                        "context_window": int(cfg.get("context_window") or 0)}))

        if path == "/api/login":
            key = self._client_key()
            now = time.time()
            fails = [t for t in self.server.login_fails.get(key, []) if now - t < 600]
            if len(fails) >= 10:
                raise ProjectError(
                    "forbidden", "登录失败次数过多，请 10 分钟后再试", 429)
            body = self._read_json()
            user = str(body.get("user") or "").strip()
            password = str(body.get("password") or "")
            if not user or not password:
                raise ProjectError("bad_request", "需要 user 与 password")
            if not self.auth.verify(user, password):
                fails.append(now)
                self.server.login_fails[key] = fails
                raise ProjectError("unauthorized", "口令不正确", 401)
            self.server.login_fails.pop(key, None)
            self.auth.record_activity(user)
            token = self.auth.issue(user)
            self._json(ok(session=self.auth.profile(user), token=token),
                       extra={"Set-Cookie": self.auth.cookie_header(
                           token, secure=self._is_secure_ctx())})
            return

        if path == "/api/logout":
            self._json(ok(), extra={"Set-Cookie": self.auth.clear_cookie(
                secure=self._is_secure_ctx())})
            return

        # ---- 旧协议兼容 ----
        if path == "/api/save":
            user = self._require_user()
            module = (self.headers.get("X-KP-Module") or "").strip()
            if module:
                if not self._can_maintain(user, module):
                    raise ProjectError("forbidden", "没有 %s 的维护权限" % module, 403)
            elif not self.auth.is_admin(user):
                raise ProjectError("forbidden", "缺少模块标识", 403)
            body = self._read_json()
            result = compat.save_state(self.engine, body, role=user)
            out = {"ok": True}
            out.update(result)
            return self._json(out)

        if path == "/api/mailtest":
            now = datetime.now(TZ).replace(tzinfo=None)
            item = {"title": "邮件提醒测试", "venue": "FISF310",
                    "note": "这是一封来自 EMF 课表看板的测试邮件",
                    "date": now.date().isoformat(),
                    "start": now + timedelta(minutes=60), "end": now + timedelta(minutes=120)}
            okv, msg = mail_service.send_mail(
                self.server.root,
                reminders._mail_subject(item, 60), reminders._mail_body(item, 60))
            return self._json({"ok": okv, "msg": msg})

        if path.startswith("/mock/api/"):
            return self._serve_mock("POST")

        m = PID_RE.match(path)
        if not m or m.group(2) != "action":
            self._not_found()
            return
        pid = m.group(1)
        user = self._require_user()
        project = self.registry.get(pid)
        if not project:
            raise ProjectError("unsupported_project", "没有这个项目：%s" % pid, 404)
        if not self._can_access(user, pid):
            raise ProjectError("forbidden", "没有 %s 的访问权限" % pid, 403)
        if not self._can_maintain(user, pid):
            raise ProjectError("forbidden", "没有 %s 的维护权限" % pid, 403)
        body = self._read_json()
        action = str(body.get("action") or "").strip()
        if not action:
            raise ProjectError("bad_request", "缺少 action")
        rev = body.get("rev")
        payload = dict(body.get("payload") or {})
        payload["_kp_user"] = user
        payload["_kp_users"] = sorted(self.auth.users)
        payload["_kp_user_colors"] = {
            u: ((self._theme_for(u) or {}).get("color") or "#9bd1ec")
            for u in self.auth.users
        }
        new_rev, data = project.dispatch(action, payload, rev=rev, role=user, write_allowed=True)
        try:
            self._activity_record(user, "use", pid)
        except Exception:
            pass
        self._json(ok(project=pid, action=action, rev=new_rev, data=project.present(data, user)))

    # ---------------- 用户管理 ----------------
    def _route_admin_post(self, path):
        viewer = self._admin_guard()
        superadmin = self.auth.is_super(viewer)
        body = self._read_json()
        if path == "/api/bugreports":
            user = self._require_user()
            vals = self._bug_list(user)
            return self._json(ok(reports=vals, stats={
                "total": len(vals),
                "open": sum(1 for b in vals if b.get("status") == "open"),
            }))

        if path == "/api/admin/users":
            name = str(body.get("user") or "").strip()
            password = str(body.get("password") or "")
            role = str(body.get("role") or "user")
            if not superadmin and role != "user":
                raise ProjectError("forbidden", "管理员只能创建普通成员", 403)
            if role not in ("user", "admin"):
                raise ProjectError("bad_request", "角色只能是 user/admin", 400)
            if len(password) < 6:
                raise ProjectError("bad_request", "口令至少 6 位", 400)
            good, msg = self.auth.create_user(name, password, role)
            if not good:
                raise ProjectError("bad_request", msg, 400)
            default_color = "#8fb3e8" if role == "admin" else "#ec9fbe"
            self._save_theme(name, default_color, "pinkfdu")
            return self._json(ok(users=self.auth.usage_summary(viewer)["users"]))

        m = re.match(r"^/api/admin/users/([^/]+)/(module|maintain|role|password)$", path)
        if m:
            target, op = unquote(m.group(1)), m.group(2)
            if target not in self.auth.users:
                raise ProjectError("not_found", "用户不存在", 404)
            target_role = self.auth.role_of(target)
            if not superadmin and target_role != "user":
                raise ProjectError("forbidden", "管理员只能管理普通成员", 403)
            if target == viewer and op in ("role", "maintain"):
                raise ProjectError("bad_request", "不能修改自己的管理权限", 400)
            if op == "module":
                mid = str(body.get("module") or "")
                if not self.registry.get(mid):
                    raise ProjectError("bad_request", "模块不存在", 400)
                self.auth.set_module(target, mid, bool(body.get("allow")), "modules")
            elif op == "maintain":
                if not superadmin:
                    raise ProjectError("forbidden", "只有超级管理员可以设置维护权限", 403)
                if target_role != "admin":
                    raise ProjectError("bad_request", "维护权限只对管理员有意义", 400)
                mid = str(body.get("module") or "")
                if not self.registry.get(mid):
                    raise ProjectError("bad_request", "模块不存在", 400)
                self.auth.set_module(target, mid, bool(body.get("allow")), "maintain")
            elif op == "role":
                if not superadmin:
                    raise ProjectError("forbidden", "只有超级管理员可以改角色", 403)
                role = str(body.get("role") or "")
                if role not in ("user", "admin"):
                    raise ProjectError("bad_request", "角色只能是 user/admin", 400)
                self.auth.set_role(target, role)
            elif op == "password":
                password = str(body.get("password") or "")
                if len(password) < 6:
                    raise ProjectError("bad_request", "口令至少 6 位", 400)
                self.auth.reset_password(target, password)
            return self._json(ok(users=self.auth.usage_summary(viewer)["users"]))

        m = re.match(r"^/api/admin/users/([^/]+)$", path)
        if m and self.command == "DELETE":
            target = unquote(m.group(1))
            if target == viewer:
                raise ProjectError("bad_request", "不能删除自己", 400)
            target_role = self.auth.role_of(target)
            if not superadmin and target_role != "user":
                raise ProjectError("forbidden", "管理员只能删除普通成员", 403)
            good, msg = self.auth.delete_user(target)
            if not good:
                raise ProjectError("forbidden", msg, 403)
            return self._json(ok(users=self.auth.usage_summary(viewer)["users"]))

        raise ProjectError("not_found", "未知的管理接口", 404)

    # ---------------- 工具 ----------------
    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n <= 0:
            return {}
        if n > 32 * 1024 * 1024:
            raise ProjectError("bad_request", "请求体过大", 413)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            raise ProjectError("bad_request", "请求体不是合法 JSON")
        if not isinstance(body, dict):
            raise ProjectError("bad_request", "请求体必须是 JSON 对象")
        return body

    def _serve_static(self, root, rel, pid=None):
        rel = unquote(rel).replace("\\", "/").lstrip("/")
        full = os.path.normpath(os.path.join(root, rel))
        if not (full == root or full.startswith(root + os.sep)):
            raise ProjectError("forbidden", "非法路径", 403)
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        ext = os.path.splitext(full)[1].lower()
        # 只有 AI 的本地 vendor 资源做长缓存；项目 JS/CSS 必须可重新验证，
        # 否则 reload_host 会继续使用旧版本脚本，出现“刷新了但视图没变”。
        rel_norm = rel.replace("\\", "/")
        vendor_asset = "vendor" in rel_norm.split("/")
        birthday_asset = rel_norm.startswith("birthday/")
        self._serve_file(full, cache=("public, max-age=31536000, immutable" if vendor_asset else
                                      "public, max-age=86400" if birthday_asset else "no-cache"),
                         gzip_ok=ext in (".html", ".js", ".css", ".json", ".svg"), pid=pid)

    def _serve_file(self, full, cache="no-cache", gzip_ok=False, pid=None):
        if not os.path.isfile(full):
            self._not_found()
            return
        ext = os.path.splitext(full)[1].lower()
        try:
            with open(full, "rb") as f:
                body = f.read()
        except Exception:
            self._not_found()
            return
        if ext == ".html":
            text = body.decode("utf-8", "replace")
            text = self._inject_shell(text, pid)
            if pid:
                text = self._version_local_assets(text, os.path.dirname(full))
            body = text.encode("utf-8")
        mtime = int(os.path.getmtime(full))
        self._send(body, 200, MIME.get(ext, "application/octet-stream"), cache=cache,
                   etag=None if ext in (".html",) else 'W/"%d"' % mtime,
                   gzip_ok=gzip_ok or ext in (".html", ".js", ".css", ".json"))

    # ---------------- 旧页面托管 ----------------
    def _serve_legacy(self, rel, query):
        web_root = self.server.web_root
        rel = unquote(rel).replace("\\", "/")
        if rel in ("", "/"):
            rel = "index.html"
        full = os.path.normpath(os.path.join(web_root, rel))
        if not (full == web_root or full.startswith(web_root + os.sep)):
            raise ProjectError("forbidden", "非法路径", 403)
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self._not_found("旧页面不存在：%s" % rel)
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            body = f.read()
        if ext == ".html":
            text = body.decode("utf-8", "replace")
            text = self._rewrite_assets(text, os.path.dirname(full))
            # 旧页面按目录映射 module，供 /api/state 做权限校验
            parts = [p for p in rel.split("/") if p]
            module = "schedule"
            if parts and parts[0] in ("map", "wishpool", "mock", "courtyard"):
                module = parts[0]
            text = text.replace("<head>", "<head>" + PERF_PATCH + AUTH_PATCH + "<script>window.__KP_MODULE__=%s;</script>" % json.dumps(module), 1)
            if "embed=1" in (query or ""):
                user = self._session_user()
                patch = AUTH_PATCH
                if user:
                    patch += BRIDGE_TPL % json.dumps({"user": user}, ensure_ascii=False)
                text = text.replace("<head>", "<head>" + patch, 1)
                text = text.replace("</head>", EMBED_CSS + "</head>", 1)
            body = text.encode("utf-8")
        mtime = int(os.path.getmtime(full))
        is_asset = ext in (".js", ".css", ".png", ".svg", ".ico", ".json")
        self._send(body, 200, MIME.get(ext, "application/octet-stream"),
                   cache=("public, max-age=31536000, immutable" if is_asset else "no-cache"),
                   etag=None if ext == ".html" else 'W/"%d"' % mtime,
                   gzip_ok=ext in (".html", ".js", ".css", ".json"))

    @staticmethod
    def _rewrite_assets(text, html_dir):
        def repl(m):
            attr, path = m.group(1), m.group(2)
            full = os.path.normpath(os.path.join(html_dir, path.replace("/", os.sep)))
            try:
                return '%s="%s?v=%d"' % (attr, path, int(os.path.getmtime(full)))
            except Exception:
                return m.group(0)
        return ASSET_RE.sub(repl, text)

    # ---------------- 原生视图 ----------------
    def _theme_tags(self, pid=None):
        user = self._session_user() or ""
        cls = "user-kitten" if user == "kitten" else ("user-puppy" if user == "puppy" else "")
        theme = self._theme_for(user)
        style = ""
        if pid:
            try:
                spec = self.registry.get(pid).manifest()
                accent = ((spec.get("ui") or {}).get("theme") or {}).get("accent")
                if accent:
                    style += "<style id=\"kp-accent\">:root{--accent:%s}</style>" % accent
            except Exception:
                pass
        if theme:
            style += ("<style id=\"kp-user-theme\">"
                      "body,body.user-kitten,body.user-puppy{"
                      "--pink:%s;--pink-deep:%s;--accent:%s;--accent-weak:%s;--mint:%s;"
                      "--p-accent:%s;--bg:%s;--card:%s;--line:%s;--ink:%s;%s}</style>") % (
                theme["soft"], theme["deep"], theme["accent"], theme["soft"], theme["mint"],
                theme["deep"], theme["bg"], theme["card"], theme["line"], theme["ink"],
                "".join("--%s:%s;" % (t["name"], t["color"]) for t in theme.get("tone") or []) +
                "".join("--kp-ramp-%d:%s;" % (i, c) for i, c in enumerate(theme.get("ramp") or [])))
        return cls, style, theme

    def _version_local_assets(self, text, base_dir):
        def repl(m):
            attr, path, tail = m.group(1), m.group(2), m.group(3)
            if path.startswith(("http:", "https:", "//", "data:")):
                return m.group(0)
            local = path.lstrip("/") if not path.startswith("/") else path.lstrip("/")
            full = os.path.normpath(os.path.join(self.server.root if path.startswith("/") else base_dir, local))
            try:
                if os.path.isfile(full):
                    return attr + path + "?v=" + str(int(os.path.getmtime(full))) + tail
            except Exception:
                pass
            return m.group(0)
        return re.sub(r'((?:src|href)=\")([^\"?#]+\.(?:js|css))(\")', repl, text)

    def _inject_shell(self, text, pid=None):
        cls, style, theme = self._theme_tags(pid)
        if cls:
            if re.search(r"<body[^>]*class=\"", text):
                text = re.sub(r"<body([^>]*class=\")([^\"]*)", lambda m: m.group(1) + m.group(2) + " " + cls, text, count=1)
            else:
                text = re.sub(r"<body([^>]*)>", lambda m: "<body" + m.group(1) + ' class="' + cls + '">', text, count=1)
        if style:
            text = text.replace("</head>", style + "</head>", 1)
        if theme:
            text = text.replace("<head>", "<head><script>window.__KP_THEME__=%s;</script>" % json.dumps(theme, ensure_ascii=False), 1)
        if pid:
            text = text.replace("<head>", "<head><script>window.__KP_MODULE__=%s;</script>" % json.dumps(pid), 1)
        return text.replace("<head>", "<head>" + PERF_PATCH + AUTH_PATCH, 1)

    def _serve_view(self, pid, rest):
        project = self.registry.get(pid)
        if not project:
            self._not_found("没有这个项目")
            return
        # 页面本身不挡：iframe 里第三方 cookie 可能丢失，页面由 JS 用 token 拉数据；
        # 真正的数据接口（/api/p/<id>/state）仍然鉴权。
        spec = project.manifest()
        view = spec.get("view") or {"kind": "auto"}
        if view.get("kind") == "custom":
            root = os.path.normpath(os.path.join(spec["dir"], view.get("dir") or "web"))
            self._serve_static(root, rest, pid)
        elif view.get("kind") == "legacy":
            # 原生路由落到旧页面：直接 302 到对应 /legacy/ URL（资源相对路径才不会断）
            url = view.get("url") or "/legacy/"
            raise _Redirect(url.rstrip("/") + "/" + rest.lstrip("/"))
        else:
            self._serve_auto_view(spec)

    def _serve_auto_view(self, spec):
        pid = spec["id"]
        title = spec.get("title") or pid
        url = "/api/p/%s" % pid
        html = AUTO_VIEW_HTML.replace("__PID__", pid).replace("__TITLE__", title) \
            .replace("__URL__", url)
        html = self._inject_shell(html, pid)
        self._send(html.encode("utf-8"), 200, "text/html; charset=utf-8", gzip_ok=True)

    # ---------------- Mock（进程内 ASGI，不再用 8768） ----------------
    def _serve_mock(self, method):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n > 30 * 1024 * 1024:
            raise ProjectError("bad_request", "音频过大", 413)
        body = self.rfile.read(n) if (method == "POST" and n > 0) else b""
        try:
            status, hdrs, data = self.server.mock_gateway.handle(
                method, self.path, dict(self.headers.items()), body)
        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "error": "Mock 后端不可用：%s" % e}, 503)
            return
        ctype = "application/json; charset=utf-8"
        for k, v in hdrs:
            if k.decode("latin-1").lower() == "content-type":
                ctype = v.decode("latin-1")
        self._send(data, status, ctype, cache="no-store", gzip_ok=False)


THEME_LOCK = threading.Lock()
ACTIVITY_LOCK = threading.Lock()
BUG_LOCK = threading.Lock()
SCHEDULE_LOCK = threading.Lock()
SCHEDULE_COURSES_LOCK = threading.Lock()
FILES_LOCK = threading.Lock()
DSH_TOKENS = {}
DSH_RUNS = {}
DSH_TOKENS_LOCK = threading.Lock()
DSH_RUNS_LOCK = threading.Lock()
DEFAULT_THEME = {
    "kitten": {"color": "#ec9fbe", "deep": "#b25e83"},
    "puppy": {"color": "#8fb3e8", "deep": "#2a5fb8"},
}


def _hex_color(v):
    if not isinstance(v, str):
        return None
    v = v.strip()
    if len(v) == 7 and v[0] == "#":
        try:
            int(v[1:], 16)
            return v.lower()
        except ValueError:
            return None
    return None


COLORMAPS = {
    "monochrome": None,
    "pinkfdu": ["#ec9fbe", "#d97fab", "#b96fa9", "#8f6fb8", "#5b7fc7", "#003da5"],
    "viridis": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    "plasma": ["#0d0887", "#7e03a8", "#cc4778", "#f89540", "#f0f921"],
    "inferno": ["#000004", "#420a68", "#932667", "#dd513a", "#fca50a", "#fcffa4"],
    "magma": ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"],
    "cividis": ["#002051", "#2d3e6b", "#57647d", "#8a8f8b", "#c6b98e", "#fde737"],
    "turbo": ["#30123b", "#4145ab", "#4675ed", "#39a2fc", "#1bcfd4", "#24eca6", "#61fc6c", "#a4fc3b", "#d1e834", "#f3c63a", "#fe9b2d", "#f36315", "#d93806", "#b11901", "#7a0402"],
}


def _hex_rgb(h):
    n = int(h[1:], 16)
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255)


def _rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _rgb_hsl(rgb):
    r, g, b = [c / 255.0 for c in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60.0, s, l


def _hsl_rgb(h, s, l):
    h = h % 360
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2
    if h < 60: rgb = (c, x, 0)
    elif h < 120: rgb = (x, c, 0)
    elif h < 180: rgb = (0, c, x)
    elif h < 240: rgb = (0, x, c)
    elif h < 300: rgb = (x, 0, c)
    else: rgb = (c, 0, x)
    return tuple(int(round((v + m) * 255)) for v in rgb)


def _mix(a, b, t):
    ra, rb = _hex_rgb(a), _hex_rgb(b)
    return _rgb_hex(tuple(ra[i] * (1 - t) + rb[i] * t for i in range(3)))


def _luma(h):
    r, g, b = _hex_rgb(h)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _sample_cmap(name, t):
    stops = COLORMAPS.get(name)
    if not stops:
        return "#b25e83"
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(len(stops) - 2, int(t))
    return _mix(stops[i], stops[i + 1], t - i)


def _interp_stops(stops, t):
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(len(stops) - 2, int(t))
    return _mix(stops[i], stops[i + 1], t - i)


def build_ramp(levels, colormap, n=64):
    """连续色卡：monochrome 在 6 级之间插值；固定 colormap 直接沿 stops 取样。"""
    if colormap == "monochrome":
        stops = levels
    else:
        stops = COLORMAPS.get(colormap) or levels
    return [_interp_stops(stops, i / float(max(1, n - 1))) for i in range(n)]


def build_palette(color, colormap="monochrome"):
    """由用户主题色 + colormap 计算 6 级层级色，并映射到界面语义变量。"""
    color = _hex_color(color) or "#ec9fbe"
    if colormap not in COLORMAPS:
        colormap = "monochrome"
    h, s, l = _rgb_hsl(_hex_rgb(color))
    levels = []
    if colormap == "monochrome":
        # 同一色相：主题色 = L4；向浅/深拉满剩余空间，让 6 级区分更明显
        base_l = max(0.08, min(0.92, l))
        for frac in (0.94, 0.70, 0.40):
            ll = base_l + (1.0 - base_l) * frac
            ss = min(1.0, max(0.05, s * (1.0 - 0.50 * frac)))
            levels.append(_rgb_hex(_hsl_rgb(h, ss, ll)))
        levels.append(color)
        for frac in (0.30, 0.56):
            ll = max(0.06, base_l * (1.0 - frac))
            ss = min(1.0, max(0.05, s * 1.12))
            levels.append(_rgb_hex(_hsl_rgb(h, ss, ll)))
    else:
        for t in (0.04, 0.22, 0.40, 0.58, 0.76, 0.95):
            levels.append(_sample_cmap(colormap, t))
    # 语义映射：bg/card 浅、line/soft 中、accent 深、deep 最深
    tone = [{"name": "tone-%d" % (i + 1), "label": "L%d" % (i + 1), "color": c}
            for i, c in enumerate(levels)]
    accent = levels[4]
    if _luma(accent) > 0.55:
        accent = _rgb_hex(tuple(c * 0.66 for c in _hex_rgb(accent)))
    soft = levels[3]
    mint = levels[2]
    deep = levels[5]
    # 页面底比卡片更深：页面 = tone-2，卡片 = tone-1（卡片更浅）
    bg = levels[1]
    card = levels[0]
    line = levels[2]
    ink = _mix("#2a2420", levels[5], 0.18)
    return {"color": color, "colormap": colormap, "accent": accent, "deep": deep,
            "soft": soft, "pink": soft, "mint": mint,
            "bg": bg, "card": card, "line": line, "ink": ink,
            "tone": tone, "ramp": build_ramp(levels, colormap)}


def _darken(hexcolor, amount=0.28):
    n = int(hexcolor[1:], 16)
    r, g, b = (n >> 16) & 255, (n >> 8) & 255, n & 255
    return "#%02x%02x%02x" % (
        max(0, int(r * (1 - amount))),
        max(0, int(g * (1 - amount))),
        max(0, int(b * (1 - amount))),
    )


class PlatformServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, root, dev_user="puppy"):
        self.root = root
        self.static_dir = os.path.join(root, "static")
        self.config = self._load_config(root)
        self.web_root = os.path.normpath(
            os.path.join(root, self.config.get("web_root") or "../emf-schedule"))
        self.auth = Auth(root)
        self.engine = DataEngine(root)
        self.registry = Registry(root, engine=self.engine)
        # 管理员默认对全部模块可维护；superadmin 可在用户管理里逐项关掉
        try:
            for _u, _rec in self.auth.users.items():
                if _rec.get("role") == "admin":
                    _maint = _rec.setdefault("maintain", {})
                    for _pid in self.registry.projects:
                        _maint.setdefault(_pid, True)
            # 新模块默认对所有用户开放（不覆盖管理员显式撤销的 false）
            for _rec in self.auth.users.values():
                _mods = _rec.setdefault("modules", {})
                _mods.setdefault("ai", True)
            self.auth.save_users()
        except Exception:
            traceback.print_exc()
        self.dev_user = dev_user
        self.request_count = 0
        self.login_fails = {}
        self.upstreams = self.config.get("upstreams") or [
            {"prefix": "/mock/api/", "target": "http://127.0.0.1:8768", "rewrite": "/api/"},
        ]
        mock_dir = self.config.get("mock_dir") or os.environ.get("KP_MOCK_DIR")
        if not mock_dir:
            candidates = [
                os.path.normpath(os.path.join(root, "..", "..", "..", "MockInterview")),
                r"D:\KittenLisaWork\MockInterview",
                os.path.join(os.path.expanduser("~"), "MockInterview"),
            ]
            for cand in candidates:
                if os.path.isfile(os.path.join(cand, "mock_web.py")):
                    mock_dir = cand
                    break
            else:
                mock_dir = candidates[0]
        self.mock_gateway = MockGateway(mock_dir)
        self.canonical_paths = {}
        for pid, proj in self.registry.projects.items():
            p = (proj.manifest() or {}).get("path")
            if p:
                self.canonical_paths[p.rstrip("/") or "/"] = pid
        super().__init__(addr, Handler)
        self.reminder_thread, self._reminder_stop = reminders.start(
            root, self.engine, self.registry.projects)

    @staticmethod
    def _load_config(root):
        try:
            with open(os.path.join(root, "config", "platform.json"), encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return {}

    def upstream_path(self, path):
        from urllib.parse import urlparse
        for entry in self.upstreams:
            prefix = entry.get("prefix") or ""
            if prefix and path.startswith(prefix):
                u = urlparse(entry.get("target") or "")
                rest = path[len(prefix):]
                upstream_path = (entry.get("rewrite") or "/") + rest
                return u.hostname, u.port or 80, upstream_path
        return None
