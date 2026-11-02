# -*- coding: utf-8 -*-
"""猫猫许愿池 = CoinProject 的业务子类（二级继承）。

继承链：AbstractProject -> JsonDocProject -> CoinProject -> 本项目
  - 直接获得 items / coins / log 与 grant / spend（来自 CoinProject）
  - 覆盖 merge：愿望按 id 求并集（只增不删，客户端旧快照不会冲掉服务端愿望）
  - 追加业务动作：create_wish / approve / reject
"""

from kernel.bases.coin import CoinProject
from kernel.project import now_iso
from kernel.protocol import ProjectError
from kernel.notifications import notify


class Project(CoinProject):
    base = "coin"

    def default_state(self):
        return {"items": [], "coins": 0, "log": [],
                "stats": {"pending": 0, "approved": 0, "rejected": 0}}

    def item_key(self, item):
        return str(item.get("id") or "")

    def merge(self, old, incoming, payload):
        by_id = {}
        for it in old.get("items") or []:
            if self.item_key(it):
                by_id[self.item_key(it)] = it
        for it in incoming.get("items") or []:
            if self.item_key(it):
                by_id[self.item_key(it)] = it
        merged = dict(incoming)
        merged["items"] = list(by_id.values())
        return merged

    def _find(self, data, wid):
        for it in data.get("items") or []:
            if self.item_key(it) == wid:
                return it
        return None

    def _stat(self, data, status):
        stats = dict(data.get("stats") or {})
        stats["pending"] = len([i for i in data.get("items") or [] if i.get("status") == "pending"])
        stats["approved"] = len([i for i in data.get("items") or [] if i.get("status") == "approved"])
        stats["rejected"] = len([i for i in data.get("items") or [] if i.get("status") == "rejected"])
        return stats

    def on_action(self, action, payload, data):
        user = str(payload.get("_kp_user") or "")
        if action == "create_wish":
            title = str(payload.get("title") or "").strip()
            if not title:
                raise ProjectError("bad_request", "愿望需要一个标题")
            try:
                coins = int(payload.get("coins") or 0)
            except Exception:
                raise ProjectError("bad_request", "coins 必须是整数")
            if coins < 0:
                raise ProjectError("bad_request", "coins 不能为负")
            wid = "w" + now_iso().replace("-", "").replace(":", "").replace("+", "p")
            item = {
                "id": wid, "title": title, "coins": coins, "status": "pending",
                "dueDate": payload.get("dueDate") or "",
                "createdAt": now_iso(), "user": user,
            }
            merged = dict(data)
            merged["items"] = list(data.get("items") or []) + [item]
            merged["stats"] = self._stat(merged, "pending")
            for other in [str(x) for x in (payload.get("_kp_users") or [])]:
                if other and other != user:
                    try:
                        notify(other, "wishpool", "wish_created", "新的许愿",
                               "%s 许了一个愿望：%s" % (user, title), "/wishpool/", actor=user,
                               meta={"wishId": wid})
                    except Exception:
                        pass
            return merged

        if action in ("approve", "reject"):
            wid = str(payload.get("id") or "")
            if not self._find(data, wid):
                raise ProjectError("not_found", "没有 id=%r 的愿望" % wid)
            items = [dict(i) for i in data.get("items") or []]
            owner = ""
            for it in items:
                if it.get("id") == wid:
                    owner = str(it.get("user") or (it.get("owner") or ""))
                    it["status"] = "approved" if action == "approve" else "rejected"
                    it["decidedAt"] = now_iso()
                    if action == "approve" and int(it.get("coins") or 0) > 0:
                        # 审批通过时由 puppy 发放许愿币（复用 CoinProject 的账本）
                        data = self.adjust(data, -int(it["coins"]), "approve:" + wid)
                    break
            merged = dict(data)
            merged["items"] = items
            merged["stats"] = self._stat(merged, "pending")
            if owner and owner != user:
                try:
                    notify(owner, "wishpool", "wish_" + str(action), "愿望已" + ("通过" if action == "approve" else "驳回"),
                           "管理员处理了你的愿望：%s" % (next((i.get("title") for i in items if i.get("id") == wid), "")),
                           "/wishpool/", actor=user, meta={"wishId": wid})
                except Exception:
                    pass
            return merged

        return super().on_action(action, payload, data)
