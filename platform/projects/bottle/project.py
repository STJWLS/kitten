# -*- coding: utf-8 -*-
"""时光漂流瓶：所有瓶子公开可见，但内容只给写信人和收件人看。"""
import hashlib
import secrets
from datetime import datetime

from kernel.project import JsonDocProject, TZ, now_iso
from kernel.protocol import ProjectError
from kernel.notifications import notify

COLORS = ["#d98a9a", "#7fa6cf", "#8dbb9a", "#d6b47a", "#a799c9", "#d58f6e", "#7fb7b5", "#c59ab6"]


def _date_ok(v):
    try:
        datetime.strptime(str(v), "%Y-%m-%d")
        return True
    except Exception:
        return False


def _color_for(user):
    h = int(hashlib.sha1(str(user or "").encode("utf-8")).hexdigest()[:8], 16)
    return COLORS[h % len(COLORS)]


def _today():
    return datetime.now(TZ).date()


class Project(JsonDocProject):
    base = "json-doc"

    def default_state(self):
        return {"bottles": [], "layouts": {}}

    def item_key(self, item):
        return str(item.get("id") or "")

    def merge(self, old, incoming, payload):
        by = {self.item_key(x): x for x in (old.get("bottles") or []) if self.item_key(x)}
        for x in (incoming.get("bottles") or []):
            if self.item_key(x):
                by[self.item_key(x)] = x
        out = dict(incoming)
        out["bottles"] = list(by.values())
        layouts = dict(old.get("layouts") or {})
        layouts.update(incoming.get("layouts") or {})
        out["layouts"] = layouts
        return out

    def _find(self, data, bid):
        for b in data.get("bottles") or []:
            if self.item_key(b) == bid:
                return b
        return None

    def present(self, data, user=None):
        """收信人开启前看不到正文；写信人始终能看到自己写的。"""
        today = _today()
        out = []
        for b in data.get("bottles") or []:
            try:
                due = datetime.strptime(str(b.get("openAt")), "%Y-%m-%d").date() <= today
            except Exception:
                due = False
            is_from = bool(user) and user == b.get("from")
            is_to = bool(user) and user == b.get("to")
            opened = bool(b.get("opened"))
            item = {
                "id": b.get("id"), "from": b.get("from"), "to": b.get("to"),
                "openAt": b.get("openAt"), "createdAt": b.get("createdAt"),
                "opened": opened, "openedAt": b.get("openedAt"),
                "color": b.get("color") or _color_for(b.get("from")),
                "due": due, "isMine": is_from, "isRecipient": is_to,
                "canOpen": bool(is_to and due and not opened),
            }
            if is_from or (is_to and opened):
                item["message"] = b.get("message") or ""
            out.append(item)
        layout = {}
        if user:
            raw = (data.get("layouts") or {}).get(user) or {}
            if isinstance(raw, dict):
                for bid, pos in list(raw.items())[:2000]:
                    try:
                        x = float(pos.get("x")); y = float(pos.get("y"))
                    except Exception:
                        continue
                    if 0 <= x <= 1 and 0 <= y <= 1:
                        layout[str(bid)] = {"x": round(x, 5), "y": round(y, 5)}
        return {"bottles": out, "layout": layout}

    def on_action(self, action, payload, data):
        user = str(payload.get("_kp_user") or "")
        if not user:
            raise ProjectError("forbidden", "需要登录")
        if action == "create":
            to = str(payload.get("to") or "").strip()
            message = str(payload.get("message") or "").strip()
            open_at = str(payload.get("openAt") or "").strip()
            users = [str(x) for x in (payload.get("_kp_users") or [])]
            if not message:
                raise ProjectError("bad_request", "写点什么再封进瓶子吧")
            if to not in users:
                raise ProjectError("bad_request", "收件人不存在")
            if not _date_ok(open_at):
                raise ProjectError("bad_request", "开启日期格式应为 YYYY-MM-DD")
            if len(message) > 4000:
                raise ProjectError("bad_request", "太长了，最多 4000 字")
            theme_color = str((payload.get("_kp_user_colors") or {}).get(user) or "")
            item = {
                "id": "b" + now_iso().replace("-", "").replace(":", "").replace("+", "p") + secrets.token_hex(2),
                "from": user, "to": to, "message": message, "openAt": open_at,
                "createdAt": now_iso(), "opened": False, "openedAt": "",
                "color": theme_color if theme_color.startswith("#") else _color_for(user),
            }
            out = dict(data)
            out["bottles"] = list(data.get("bottles") or []) + [item]
            if to != user:
                try:
                    notify(to, "bottle", "bottle_received", "收到一个漂流瓶",
                           "%s 给你投了一个漂流瓶，开启日 %s" % (user, open_at),
                           "/bottle/", actor=user, meta={"bottleId": item["id"]})
                except Exception:
                    pass
            return out
        if action == "open":
            bid = str(payload.get("id") or "")
            b = self._find(data, bid)
            if not b:
                raise ProjectError("not_found", "没有这个漂流瓶")
            if b.get("to") != user:
                raise ProjectError("forbidden", "这不是给你的漂流瓶")
            try:
                due = datetime.strptime(str(b.get("openAt")), "%Y-%m-%d").date() <= _today()
            except Exception:
                due = False
            if not due:
                raise ProjectError("not_due", "还没到开启的日子")
            if b.get("opened"):
                raise ProjectError("bad_request", "这个瓶子已经打开过了")
            out = dict(data)
            out["bottles"] = [dict(x) for x in (data.get("bottles") or [])]
            for x in out["bottles"]:
                if self.item_key(x) == bid:
                    x["opened"] = True
                    x["openedAt"] = now_iso()
                    break
            return out
        if action in ("save_positions", "layout"):
            raw = payload.get("positions")
            if not isinstance(raw, dict):
                raise ProjectError("bad_request", "位置数据格式不对")
            valid_ids = {self.item_key(x) for x in (data.get("bottles") or [])}
            clean = {}
            for bid, pos in list(raw.items())[:2000]:
                if str(bid) not in valid_ids or not isinstance(pos, dict):
                    continue
                try:
                    x = float(pos.get("x")); y = float(pos.get("y"))
                except Exception:
                    continue
                if 0 <= x <= 1 and 0 <= y <= 1:
                    clean[str(bid)] = {"x": round(x, 5), "y": round(y, 5)}
            out = dict(data)
            layouts = dict(data.get("layouts") or {})
            layouts[user] = clean
            out["layouts"] = layouts
            return out
        return super().on_action(action, payload, data)
