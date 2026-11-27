# -*- coding: utf-8 -*-
"""Mock 项目的 module-local API。

Mock 的实际 ASGI 应用仍由 platform 配置的 mock_gateway 托管；本文件只负责
把 /mock/api/* 的入口声明收回到 module，避免 kernel/server.py 继续堆专用路由。
"""
PREFIXES = ["/mock/api/"]


def handle(handler, method, path, parsed):
    if not path.startswith("/mock/api/"):
        return False
    handler._serve_mock(method)
    return True
