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
