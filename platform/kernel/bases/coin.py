# -*- coding: utf-8 -*-
"""内核提供的中间基类：带硬币账本的项目（继承 JsonDocProject）。

这是"类继承"在项目体系里的落点：
    wishpool.Project 继承 CoinProject → 直接获得 items + coins + log 与
    grant/spend/transfer 动作，只覆盖自己关心的业务规则。
"""

from ..project import JsonDocProject, now_iso
from ..protocol import ProjectError


class CoinProject(JsonDocProject):
    base = "coin"
    ACTIONS = JsonDocProject.ACTIONS + ["grant", "spend"]

    def default_state(self):
        return {"items": [], "coins": 0, "log": []}

    def adjust(self, data, delta, reason, role=None):
        coins = int(data.get("coins") or 0) + int(delta)
        if coins < 0:
            raise ProjectError("bad_request", "余额不足：当前 %s，扣减 %s" % (
                data.get("coins", 0), -int(delta)))
        merged = dict(data)
        merged["coins"] = coins
        log = list(merged.get("log") or [])
        log.append({"at": now_iso(), "delta": int(delta), "reason": reason, "by": role})
        merged["log"] = log[-300:]
        return merged

    def default_action(self, action, payload, data):
        if action == "grant":
            try:
                delta = int(payload.get("amount") or 0)
            except Exception:
                raise ProjectError("bad_request", "amount 必须是整数")
            if delta <= 0:
                raise ProjectError("bad_request", "grant 的 amount 必须为正")
            return self.adjust(data, delta, payload.get("reason") or "grant")
        if action == "spend":
            try:
                delta = int(payload.get("amount") or 0)
            except Exception:
                raise ProjectError("bad_request", "amount 必须是整数")
            if delta <= 0:
                raise ProjectError("bad_request", "spend 的 amount 必须为正")
            return self.adjust(data, -delta, payload.get("reason") or "spend")
        return super().default_action(action, payload, data)
