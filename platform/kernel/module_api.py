# -*- coding: utf-8 -*-
"""Module-local HTTP API registry.

A project may ship ``projects/<id>/api.py`` with::

    PREFIXES = ["/api/ai/"]
    def handle(handler, method, path, parsed):
        ...

The platform HTTP handler asks the registry to match a path and delegates to the
module's handler before falling back to legacy/custom kernel routes. Handlers
receive the live HTTP handler so existing response/auth helpers remain usable
during the migration; new handlers should keep business logic in the module.
"""
from __future__ import annotations

from typing import Callable


class ModuleAPI:
    def __init__(self, pid: str, prefixes, handler: Callable):
        self.pid = pid
        self.prefixes = tuple(str(p) for p in (prefixes or []))
        self.handler = handler

    def matches(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.prefixes)

    def handle(self, handler, method: str, path: str, parsed):
        return bool(self.handler(handler, method, path, parsed))
