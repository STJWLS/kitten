# -*- coding: utf-8 -*-
"""KittenPuppy4Ever 平台内核 · 统一协议 kp/1。

根（工作台壳）与每个子项目之间只通过这一种信封通信，任何项目都不得
自定义顶层响应结构：

成功：
    {"ok": true,  "protocol": "kp/1", ...项目字段...}
失败：
    {"ok": false, "protocol": "kp/1", "error": {"code": "...", "message": "..."}}

标准错误码（子项目只能从这组里选，便于根统一提示/重试/埋点）：
    bad_request / not_found / unauthorized / forbidden / conflict
    unsupported_action / unsupported_project / internal
"""

PROTOCOL = "kp/1"


class ProjectError(Exception):
    """项目内部抛出的协议级错误；server 负责翻译成统一信封。"""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def ok(**fields):
    body = {"ok": True, "protocol": PROTOCOL}
    body.update(fields)
    return body


def fail(code: str, message: str, status: int = 400):
    return {"ok": False, "protocol": PROTOCOL,
            "error": {"code": code, "message": message}}, status
