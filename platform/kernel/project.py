# -*- coding: utf-8 -*-
"""抽象项目（Abstract Project）与默认实现。

面向对象的类比（这是整套机制的核心）：

    AbstractProject   ← 抽象类：只规定协议（state / dispatch / merge / validate / acl）
    JsonDocProject    ← 具体基类：一份 JSON 文档 + rev 版本 + 默认 CRUD 动作
    CoinProject       ← 中间基类：在 JsonDocProject 之上加硬币账本（继承）
    wishpool.Project  ← 业务子类：继承 CoinProject，覆盖 merge、追加审批动作

一个子项目在磁盘上只需要：
    projects/<id>/project.json      声明式 manifest（可继承 bases/*.json）
    projects/<id>/project.py        可选：`Project = <AbstractProject 子类>`
    projects/<id>/web/              可选：视图（继承 static/project.css + sdk.js）

manifest 的 base 决定了"这个项目实例化自哪个抽象项目"，内核会校验
project.py 里的 Project 必须是该基类的**子类**（类似 Java 的 extends 检查）。
没有 project.py 时直接用基类实例化 —— 这就是"零代码创建标签页"。
"""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

from .protocol import ProjectError

TZ = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def _clip(obj, limit=400):
    """审计日志里截断过大的 payload，避免 doc.json 膨胀。"""
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "<unserializable>"
    return s if len(s) <= limit else s[:limit] + "…"


class AbstractProject:
    """抽象项目：定义每个标签页必须遵守的协议。不可直接实例化使用。"""

    base = "abstract"

    def __init__(self, spec: dict, ctx: dict):
        self.spec = spec
        self.ctx = ctx                     # {"role":..., "data_dir":..., "user":...}
        self.id = spec["id"]
        self.dir = spec["dir"]
        self._lock = threading.RLock()

    # ---------------- 元信息（会被 /api/tree 与 /api/p/<id> 暴露） ----------------
    def manifest(self):
        return self.spec

    def capabilities(self):
        return list(self.spec.get("capabilities") or [])

    def acl(self):
        return dict(self.spec.get("acl") or {})

    # ---------------- 持久化：一个项目一份 JSON，带 rev 与审计日志 ----------------
    @property
    def data_path(self):
        return os.path.join(self.ctx["data_dir"], "doc.json")

    def _load(self):
        engine = self.ctx.get("engine")
        if engine is not None:
            return engine.read(self.id)
        try:
            with open(self.data_path, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            doc = {}
        data = doc.get("data")
        if not isinstance(data, dict):
            data = self.default_state()
        return int(doc.get("_rev") or 0), data, list(doc.get("_audit") or [])

    def _save(self, rev, data, audit):
        engine = self.ctx.get("engine")
        if engine is not None:
            engine.write(self.id, data, rev=rev, audit=audit)
            return        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        tmp = self.data_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"_rev": rev, "data": data, "_audit": audit[-200:]},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.data_path)

    # ---------------- 协议入口 ----------------
    def state(self, user=None):
        """返回 (rev, data)。"""
        with self._lock:
            rev, data, _ = self._load()
            return rev, self.present(data, user)

    def present(self, data, user=None):
        """可选：返回给某个用户看的数据视图（敏感项目覆盖）。"""
        return data

    def dispatch(self, action: str, payload: dict, rev=None, role=None, write_allowed=None):
        """执行一个动作，返回 (new_rev, data)。

        统一约定：
          - 只读动作 "get" 不产生新版本
          - 写动作必须通过 acl.write 校验
          - 客户端带 rev 时做乐观并发（旧客户端写入 -> 409 conflict）
          - 任何写动作都会写一条审计记录（谁、何时、什么动作）
        """
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ProjectError("bad_request", "payload 必须是 JSON 对象")

        with self._lock:
            cur_rev, data, audit = self._load()

            if action in ("", "get"):
                return cur_rev, data

            if rev is not None:
                try:
                    rev_i = int(rev)
                except Exception:
                    raise ProjectError("bad_request", "rev 必须是整数")
                if rev_i != cur_rev:
                    raise ProjectError(
                        "conflict",
                        "版本冲突：服务器 rev=%d，客户端 rev=%d，请重新拉取" % (cur_rev, rev_i),
                        409)

            allowed = self.can_write(role) if write_allowed is None else bool(write_allowed)
            if not allowed:
                raise ProjectError("forbidden", "角色 %r 没有项目 %s 的维护权限" % (role, self.id), 403)

            # 1) 子类自定义动作优先  2) 回落到基类默认动作
            result = self.on_action(action, payload, data)
            if result is None:
                result = self.default_action(action, payload, data)
            if result is None:
                raise ProjectError(
                    "unsupported_action",
                    "项目 %s 不支持动作 %r（可用：%s）" % (
                        self.id, action, ", ".join(sorted(self.action_names()))))

            result = self.validate(result)
            new_rev = cur_rev + 1
            audit.append({
                "at": now_iso(), "rev": new_rev, "action": action,
                "role": role, "payload": _clip(payload),
            })
            self._save(new_rev, result, audit)
            return new_rev, result

    def _can_write(self, role):  # pragma: no cover - 兼容旧调用
        return self.can_write(role)

    def merge_list_field(self, field, items, limit=1000):
        """只把一个列表字段并集写回（提醒去重记录等系统写入用），不触碰其它字段。"""
        with self._lock:
            rev, data, audit = self._load()
            merged = list(data.get(field) or [])
            changed = False
            for it in items:
                if it not in merged:
                    merged.append(it)
                    changed = True
            if not changed:
                return rev
            merged = merged[-limit:]
            new = dict(data)
            new[field] = merged
            audit = list(audit)
            audit.append({"at": now_iso(), "rev": rev + 1,
                          "action": "merge_list:" + field, "role": "system", "payload": ""})
            new_rev = rev + 1
            self._save(new_rev, new, audit)
            return new_rev

    # ---------------- 子类可覆盖的钩子 ----------------
    def default_state(self) -> dict:
        return {}

    def validate(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ProjectError("bad_request", "项目状态必须是 JSON 对象")
        return data

    def merge(self, old: dict, incoming: dict, payload: dict) -> dict:
        """默认：整份覆盖。业务项目可覆盖成"按主键求并集"等策略。"""
        return incoming

    def on_action(self, action: str, payload: dict, data: dict):
        """子类自定义动作；返回新的 data，不处理则返回 None。"""
        return None

    def default_action(self, action: str, payload: dict, data: dict):
        """基类默认动作集；返回新的 data，不认识则返回 None。"""
        return None

    def action_names(self):
        names = set()
        name = type(self)
        while name is not object and name is not AbstractProject:
            names |= set(getattr(name, "ACTIONS", []) or [])
            name = name.__mro__[1]
        return names

    # ---------------- ACL ----------------
    def can_read(self, role):
        acl = self.acl()
        allowed = acl.get("read")
        return True if not allowed else role in allowed

    def can_write(self, role):
        acl = self.acl()
        allowed = acl.get("write")
        return True if not allowed else role in allowed


class JsonDocProject(AbstractProject):
    """默认实现：一份 JSON 文档 + 版本号 + 最小可用的 CRUD 动作。

    动作：
        get                 -> 读状态（不涨版本）
        set   {data}       -> 整份替换（merge 钩子介入）
        patch {patch}      -> 顶层浅合并
        append{item}       -> 往 items 追加一条（自动补 id）
        remove{id|key}     -> 从 items 删除
        reset              -> 回到 default_state()
    """

    base = "json-doc"
    ACTIONS = ["get", "set", "patch", "append", "remove", "reset"]

    def default_state(self):
        return {"items": []}

    def item_key(self, item):
        if isinstance(item, dict):
            return str(item.get("id") or item.get("key") or "")
        return ""

    def _items(self, data):
        items = data.get("items")
        return list(items) if isinstance(items, list) else []

    def default_action(self, action, payload, data):
        if action == "set":
            incoming = payload.get("data")
            if not isinstance(incoming, dict):
                raise ProjectError("bad_request", "set 需要 data 对象（可用 patch 做局部更新）")
            return self.merge(data, self.validate(incoming), payload)

        if action == "patch":
            patch = payload.get("patch")
            if not isinstance(patch, dict):
                raise ProjectError("bad_request", "patch 需要 patch 对象")
            merged = dict(data)
            merged.update(patch)
            return merged

        if action == "append":
            item = payload.get("item")
            if not isinstance(item, dict):
                raise ProjectError("bad_request", "append 需要 item 对象")
            item = dict(item)
            if not self.item_key(item):
                item["id"] = uuid.uuid4().hex[:10]
            items = self._items(data) + [item]
            merged = dict(data)
            merged["items"] = items
            return merged

        if action == "remove":
            key = str(payload.get("id") or payload.get("key") or "")
            if not key:
                raise ProjectError("bad_request", "remove 需要 id 或 key")
            before = self._items(data)
            after = [i for i in before if self.item_key(i) != key]
            if len(after) == len(before):
                raise ProjectError("not_found", "没有主键为 %r 的条目" % key)
            merged = dict(data)
            merged["items"] = after
            return merged

        if action == "reset":
            return self.default_state()

        return None
