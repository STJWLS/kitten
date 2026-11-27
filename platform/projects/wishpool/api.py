# -*- coding: utf-8 -*-
"""许愿池 module-local legacy-compatible API.

The current wishpool page still uses the old store.json shape but no longer
touches the platform-global /api/state or /api/save endpoints. This adapter keeps
the legacy UI working while scoping its data access to the wishpool module.
"""
from kernel import compat
from kernel.protocol import ProjectError

PREFIXES = ["/api/wishpool/"]


def handle(handler, method, path, parsed):
    if method == "GET" and path == "/api/wishpool/state":
        user = handler._require_user()
        if not handler._can_access(user, "wishpool"):
            raise ProjectError("forbidden", "没有许愿池访问权限", 403)
        state = compat.read_state(handler.engine)
        # 愿望/余额的权威数据来自项目 doc；兼容层只补充 schedule 投影与旧 t。
        project = handler.registry.get("wishpool")
        if project is not None:
            _rev, data = project.state(user)
            if isinstance(data, dict):
                for key in ("wishes", "coins", "wish_notified"):
                    if key in data:
                        state[key] = data[key]
        handler._json(state, etag='W/"store-%d"' % handler.engine.state_version())
        return True

    if method == "POST" and path == "/api/wishpool/save":
        user = handler._require_user()
        if not handler._can_access(user, "wishpool"):
            raise ProjectError("forbidden", "没有许愿池访问权限", 403)
        body = handler._read_json()
        result = compat.save_state(handler.engine, body, role=user)
        handler._json(result)
        return True

    return False
