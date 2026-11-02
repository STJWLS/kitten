# -*- coding: utf-8 -*-
"""课程看板 = JsonDocProject 的业务子类（一级继承）。

演示两类覆盖：
  1) merge   —— 不用整份覆盖，而是按 key 求并集：旧浏览器快照不会删掉服务端条目
  2) 自定义动作 —— toggle_done 不在基类动作集里，只属于本项目
"""

from kernel.project import JsonDocProject
from kernel.protocol import ProjectError


class Project(JsonDocProject):
    base = "json-doc"

    def default_state(self):
        return {"items": [], "term": "Fall 2026", "note": "由平台内核托管"}

    def item_key(self, item):
        return str(item.get("key") or item.get("id") or "")

    def merge(self, old, incoming, payload):
        by_key = {}
        for it in old.get("items") or []:
            if self.item_key(it):
                by_key[self.item_key(it)] = it
        for it in incoming.get("items") or []:
            if self.item_key(it):
                by_key[self.item_key(it)] = it
        merged = dict(incoming)
        merged["items"] = list(by_key.values())
        return merged

    def on_action(self, action, payload, data):
        if action == "toggle_done":
            key = str(payload.get("key") or "")
            items = [dict(i) for i in data.get("items") or []]
            for it in items:
                if self.item_key(it) == key:
                    it["done"] = not bool(it.get("done"))
                    merged = dict(data)
                    merged["items"] = items
                    return merged
            raise ProjectError("not_found", "没有 key=%r 的条目" % key)
        return None
